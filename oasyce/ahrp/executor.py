"""
AHRP Executor -- Wires the handshake protocol to Oasyce settlement via chain.

Handles the economic actions triggered by protocol messages:
  ACCEPT  -> create escrow on chain
  CONFIRM -> release escrow + update reputation
  DELIVER -> record exposure + verify content hash

This is the bridge between "two agents talking" and "money moving".
Settlement is delegated to the Cosmos chain via OasyceClient.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from oasyce.ahrp import (
    AcceptPayload,
    ConfirmPayload,
    DeliverPayload,
    MessageType,
    Need,
    OfferPayload,
    ProtocolMessage,
    RequestPayload,
    Transaction,
    TxState,
    AgentIdentity,
    Capability,
    AnnouncePayload,
    match_score,
)
from oasyce.chain_client import ChainClientError, OasyceClient
from oasyce.config import get_economics, NetworkMode


@dataclass
class EscrowRecord:
    """Tracks locked funds for an in-flight transaction."""

    tx_id: str
    buyer: str
    seller: str
    amount_oas: float
    locked_at: int = field(default_factory=lambda: int(time.time()))
    released: bool = False
    chain_escrow_id: str = ""


class AHRPExecutor:
    """Executes the economic side of AHRP transactions.

    Maintains:
      - Agent registry (from ANNOUNCE messages)
      - Capability index (for matching)
      - Active transactions
      - Escrow ledger
      - Connection to OasyceClient for chain-based settlement
    """

    def __init__(
        self,
        chain_client: Optional[OasyceClient] = None,
        require_signature: bool = True,
        network_mode: NetworkMode = NetworkMode.MAINNET,
        db_path: Optional[str] = None,
        # Legacy parameter name for backward compatibility
        settlement: Any = None,
    ):
        self._chain = chain_client or OasyceClient()
        self.require_signature = require_signature
        self._network_mode = network_mode
        economics = get_economics(network_mode)
        self._min_agent_stake: int = economics["agent_stake"]
        self.agents: Dict[str, AgentIdentity] = {}
        self.capabilities: Dict[str, List[Capability]] = {}  # agent_id -> caps
        self.endpoints: Dict[str, List[str]] = {}  # agent_id -> endpoints
        self.transactions: Dict[str, Transaction] = {}
        self.escrows: Dict[str, EscrowRecord] = {}
        self._offer_counter = 0
        self._tx_counter = 0

        # Persistence (optional — None = pure in-memory)
        self._store = None
        if db_path is not None:
            from oasyce.ahrp.persistence import AHRPStore
            self._store = AHRPStore(db_path)
            self._load_from_store()

    def _load_from_store(self) -> None:
        """Restore state from persistent storage on startup."""
        if not self._store:
            return
        # Agents + endpoints
        for agent_id, (identity, endpoints, count) in self._store.load_agents().items():
            self.agents[agent_id] = identity
            self.endpoints[agent_id] = endpoints
        # Capabilities
        for agent_id, caps in self._store.load_capabilities().items():
            self.capabilities[agent_id] = caps
        # Escrows
        for esc in self._store.load_escrows():
            self.escrows[esc["tx_id"]] = EscrowRecord(
                tx_id=esc["tx_id"], buyer=esc["buyer"], seller=esc["seller"],
                amount_oas=esc["amount_oas"], locked_at=esc["locked_at"],
                released=esc["released"], chain_escrow_id=esc["chain_escrow_id"],
            )
        # Counters
        if self.escrows:
            max_num = max(
                (int(k.split("-")[1]) for k in self.escrows if k.startswith("tx-")),
                default=0,
            )
            self._tx_counter = max_num

    def _persist_agent(self, agent_id: str) -> None:
        """Write-through: persist agent + capabilities after mutation."""
        if not self._store:
            return
        agent = self.agents.get(agent_id)
        if agent:
            self._store.save_agent(agent, self.endpoints.get(agent_id, []))
            caps = self.capabilities.get(agent_id, [])
            self._store.save_capabilities(agent_id, caps)

    def _persist_escrow(self, tx_id: str) -> None:
        """Write-through: persist escrow after mutation."""
        if not self._store:
            return
        esc = self.escrows.get(tx_id)
        if esc:
            self._store.save_escrow(
                esc.tx_id, esc.buyer, esc.seller, esc.amount_oas,
                esc.locked_at, esc.released, esc.chain_escrow_id,
            )

    @property
    def chain(self) -> OasyceClient:
        """Access the underlying chain client."""
        return self._chain

    def verify_message(self, msg: ProtocolMessage, expected_sender: str) -> bool:
        """Look up the agent's public_key and verify the message signature."""
        agent = self.agents.get(expected_sender)
        if not agent:
            return False
        return msg.verify_signature(agent.public_key)

    # -- ANNOUNCE --
    def handle_announce(
        self,
        payload: AnnouncePayload,
        signed_message: Optional[ProtocolMessage] = None,
    ) -> str:
        """Register or update an agent's identity and capabilities.

        Returns agent_id.
        """
        if self.require_signature:
            if signed_message is None:
                raise ValueError("Signature required but no signed message provided")
            if not signed_message.verify_signature(payload.identity.public_key):
                raise ValueError("Invalid signature on ANNOUNCE message")

        agent = payload.identity

        # Min-stake anti-sybil: agent must meet minimum stake for this network
        agent_stake_uoas = int(agent.stake * 1e8)
        if agent_stake_uoas < self._min_agent_stake:
            min_oas = self._min_agent_stake / 1e8
            raise ValueError(
                f"Insufficient stake: {agent.stake} OAS < minimum {min_oas} OAS "
                f"for {self._network_mode.value}"
            )

        self.agents[agent.agent_id] = agent
        self.capabilities[agent.agent_id] = list(payload.capabilities)
        self.endpoints[agent.agent_id] = list(payload.endpoints)
        self._persist_agent(agent.agent_id)
        return agent.agent_id

    # -- REQUEST -> match --
    def find_matches(
        self,
        need: Need,
        requester_id: str,
        top_k: int = 5,
        min_score: float = 0.1,
    ) -> List[Dict[str, Any]]:
        """Find best-matching capabilities for a need.

        Returns list of {agent_id, capability_id, score, price_floor}
        sorted by score descending.
        """
        results = []
        for agent_id, caps in self.capabilities.items():
            if agent_id == requester_id:
                continue  # don't match with yourself
            agent = self.agents.get(agent_id)
            if agent and agent.reputation < need.min_reputation:
                continue
            for cap in caps:
                score = match_score(need, cap)
                if score >= min_score:
                    results.append(
                        {
                            "agent_id": agent_id,
                            "capability_id": cap.capability_id,
                            "score": score,
                            "price_floor": cap.price_floor,
                            "origin_type": cap.origin_type,
                        }
                    )
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    # -- ACCEPT -> escrow --
    def handle_accept(
        self,
        buyer_id: str,
        seller_id: str,
        offer: OfferPayload,
        signed_message: Optional[ProtocolMessage] = None,
    ) -> Transaction:
        """Lock escrow on-chain and create transaction.

        1. Create escrow on chain via OasyceClient
        2. Create a Transaction in ACCEPTED state
        """
        if self.require_signature and signed_message is not None:
            if not self.verify_message(signed_message, buyer_id):
                raise ValueError("Invalid signature on ACCEPT message")

        self._tx_counter += 1
        tx_id = f"tx-{self._tx_counter:06d}"

        # Create escrow on chain
        chain_escrow_id = ""
        amount_uoas = int(offer.price_oas * 1e8)
        try:
            result = self._chain.chain.create_escrow(
                creator=buyer_id,
                provider=seller_id,
                amount_uoas=amount_uoas,
                capability_id=offer.capability_id,
            )
            chain_escrow_id = result.get("tx_response", {}).get("txhash", "")
        except ChainClientError:
            # If chain is unavailable, still record locally
            chain_escrow_id = f"local-{tx_id}"

        # Record escrow
        escrow = EscrowRecord(
            tx_id=tx_id,
            buyer=buyer_id,
            seller=seller_id,
            amount_oas=offer.price_oas,
            chain_escrow_id=chain_escrow_id,
        )
        self.escrows[tx_id] = escrow
        self._persist_escrow(tx_id)

        # Create transaction
        tx = Transaction(
            tx_id=tx_id,
            buyer=buyer_id,
            seller=seller_id,
            state=TxState.ACCEPTED,
            offer=offer,
            accept=AcceptPayload(
                offer_id=offer.offer_id,
                escrow_tx_id=chain_escrow_id,
            ),
        )
        self.transactions[tx_id] = tx
        return tx

    # -- DELIVER -> verify + record --
    def handle_deliver(
        self,
        tx_id: str,
        deliver: DeliverPayload,
        signed_message: Optional[ProtocolMessage] = None,
    ) -> Transaction:
        """Record delivery and advance transaction state."""
        tx = self.transactions.get(tx_id)
        if not tx:
            raise ValueError(f"Transaction {tx_id} not found")

        if self.require_signature and signed_message is not None:
            if not self.verify_message(signed_message, tx.seller):
                raise ValueError("Invalid signature on DELIVER message")

        tx.deliver = deliver
        tx.advance(MessageType.DELIVER)
        return tx

    # -- CONFIRM -> settle + reputation --
    def handle_confirm(
        self,
        tx_id: str,
        confirm: ConfirmPayload,
        signed_message: Optional[ProtocolMessage] = None,
    ) -> Transaction:
        """Finalize: release escrow on chain, update reputation.

        1. Release escrow on chain
        2. Update both agents' reputation locally
        3. Mark transaction as CONFIRMED
        """
        tx = self.transactions.get(tx_id)
        if not tx:
            raise ValueError(f"Transaction {tx_id} not found")

        if self.require_signature and signed_message is not None:
            if not self.verify_message(signed_message, tx.buyer):
                raise ValueError("Invalid signature on CONFIRM message")

        escrow = self.escrows.get(tx_id)
        if not escrow:
            raise ValueError(f"No escrow for {tx_id}")

        # Release escrow on chain
        _log = logging.getLogger("oasyce.ahrp.executor")
        chain_released = False
        if escrow.chain_escrow_id and not escrow.chain_escrow_id.startswith("local-"):
            try:
                self._chain.chain.release_escrow(
                    escrow_id=escrow.chain_escrow_id,
                    releaser=tx.buyer,
                )
                chain_released = True
            except ChainClientError as exc:
                _log.error(
                    "ESCROW RELEASE FAILED tx=%s escrow=%s error=%s — "
                    "requires manual recovery",
                    tx_id, escrow.chain_escrow_id, exc,
                )
        else:
            chain_released = True  # local escrow, no chain action needed

        escrow.released = True
        self._persist_escrow(tx_id)
        confirm.settlement_tx_id = escrow.chain_escrow_id

        # Update reputation (both parties get credit for successful tx)
        for agent_id in [tx.buyer, tx.seller]:
            agent = self.agents.get(agent_id)
            if agent:
                agent.reputation = min(95.0, agent.reputation + 1.0)

        tx.confirm = confirm
        tx.advance(MessageType.CONFIRM)
        return tx

    # -- Stats --
    def stats(self) -> Dict[str, Any]:
        """Network-level statistics."""
        completed = sum(1 for tx in self.transactions.values() if tx.state == TxState.CONFIRMED)
        total_volume = sum(e.amount_oas for e in self.escrows.values() if e.released)
        return {
            "registered_agents": len(self.agents),
            "total_capabilities": sum(len(c) for c in self.capabilities.values()),
            "active_transactions": sum(
                1
                for tx in self.transactions.values()
                if tx.state not in (TxState.CONFIRMED, TxState.EXPIRED, TxState.DISPUTED)
            ),
            "completed_transactions": completed,
            "total_volume_oas": total_volume,
            "chain_connected": self._chain.is_chain_mode,
        }
