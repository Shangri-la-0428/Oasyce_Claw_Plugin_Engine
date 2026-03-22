"""
Oasyce Chain RPC Client — connects Python SDK to the Cosmos chain.
Uses the chain's REST API (default localhost:1317).
Local fallback is opt-in and disabled by default for formal deployments.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import subprocess
from typing import Any, Callable, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# Default timeout for REST requests (seconds).
_DEFAULT_TIMEOUT = 10

# Paths to check for oasyced binary.
_OASYCED_SEARCH_PATHS = [
    os.path.expanduser("~/Desktop/oasyce-chain/build/oasyced"),
    "/usr/local/bin/oasyced",
]


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _find_oasyced() -> Optional[str]:
    """Find the oasyced binary."""
    # Check PATH first.
    found = shutil.which("oasyced")
    if found:
        return found
    # Check known locations.
    for path in _OASYCED_SEARCH_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


class ChainClientError(Exception):
    """Raised when a chain RPC call fails."""


class ChainClient:
    """Low-level RPC client that talks to the Oasyce Cosmos chain via REST.

    For transactions, delegates to the ``oasyced`` CLI binary for proper
    signing and broadcasting.  For queries, uses the REST API directly.
    """

    def __init__(
        self,
        rest_url: str = "http://localhost:1317",
        grpc_url: str = "localhost:9090",
        timeout: int = _DEFAULT_TIMEOUT,
        chain_id: str = "oasyce-local-1",
        keyring_backend: str = "test",
        default_from: Optional[str] = None,
        fees: str = "500uoas",
    ):
        self.rest_url = rest_url.rstrip("/")
        self.grpc_url = grpc_url
        self.timeout = timeout
        self.chain_id = chain_id
        self.keyring_backend = keyring_backend
        self.default_from = default_from
        self.fees = fees
        self._oasyced = _find_oasyced()

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Return True if the chain's REST API is reachable."""
        try:
            resp = requests.get(
                f"{self.rest_url}/cosmos/base/tendermint/v1beta1/node_info",
                timeout=self.timeout,
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Perform a GET request against the chain REST API."""
        url = f"{self.rest_url}{path}"
        try:
            resp = requests.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise ChainClientError(f"GET {path} failed: {exc}") from exc

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Perform a POST request against the chain REST API."""
        url = f"{self.rest_url}{path}"
        try:
            resp = requests.post(url, json=body, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise ChainClientError(f"POST {path} failed: {exc}") from exc

    # ------------------------------------------------------------------
    # CLI-based transaction execution
    # ------------------------------------------------------------------

    @property
    def has_cli(self) -> bool:
        """True if the oasyced CLI binary is available."""
        return self._oasyced is not None

    def _run_cli(
        self,
        args: List[str],
        from_key: Optional[str] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Run an oasyced CLI command and return the result.

        Adds standard flags: --keyring-backend, --chain-id, --fees, --yes, --output json.
        """
        if not self._oasyced:
            raise ChainClientError("oasyced binary not found")

        cmd = [self._oasyced] + args
        if from_key:
            cmd += ["--from", from_key]
        cmd += [
            "--keyring-backend",
            self.keyring_backend,
            "--chain-id",
            self.chain_id,
            "--fees",
            self.fees,
            "--yes",
            "--output",
            "json",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            # oasyced outputs YAML by default, JSON with --output json
            output = result.stdout.strip()
            if not output:
                output = result.stderr.strip()
            if not output:
                raise ChainClientError(
                    f"oasyced returned no output. Exit code: {result.returncode}"
                )

            try:
                return json.loads(output)
            except json.JSONDecodeError:
                # Some commands output YAML even with --output json
                # Parse the key fields we care about
                parsed: Dict[str, Any] = {"raw_output": output}
                for line in output.split("\n"):
                    if ": " in line:
                        key, _, val = line.partition(": ")
                        key = key.strip().strip('"')
                        val = val.strip().strip('"')
                        parsed[key] = val
                return parsed
        except subprocess.TimeoutExpired:
            raise ChainClientError("oasyced command timed out")
        except FileNotFoundError:
            raise ChainClientError(f"oasyced not found at {self._oasyced}")

    def _resolve_from_key(self, actor: str, from_key: Optional[str] = None) -> str:
        """Resolve the CLI signer without silently changing the business actor."""
        signer = from_key or actor or self.default_from
        if signer:
            return signer
        raise ChainClientError(
            "No signer configured. Pass from_key explicitly or configure default_from."
        )

    def _query_cli(
        self,
        args: List[str],
        timeout: int = 15,
    ) -> Dict[str, Any]:
        """Run an oasyced query command and return JSON result."""
        if not self._oasyced:
            raise ChainClientError("oasyced binary not found")

        cmd = [self._oasyced] + args + ["--output", "json"]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = result.stdout.strip()
            if not output:
                raise ChainClientError(f"Query failed: {result.stderr.strip()}")
            return json.loads(output)
        except json.JSONDecodeError:
            raise ChainClientError(f"Invalid JSON from query: {output[:200]}")
        except subprocess.TimeoutExpired:
            raise ChainClientError("oasyced query timed out")

    def _build_tx_body(self, type_url: str, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Build an unsigned Cosmos SDK transaction body.

        Returns the full ``/cosmos/tx/v1beta1/txs`` payload *without*
        auth_info or signatures — the caller (or a future signer module)
        must complete and broadcast it.

        TODO: Integrate with chain keyring for actual signing.
        """
        return {
            "tx": {
                "body": {
                    "messages": [
                        {
                            "@type": type_url,
                            **msg,
                        }
                    ],
                    "memo": "",
                    "timeout_height": "0",
                    "extension_options": [],
                    "non_critical_extension_options": [],
                },
                "auth_info": {
                    "signer_infos": [],
                    "fee": {
                        "amount": [],
                        "gas_limit": "200000",
                        "payer": "",
                        "granter": "",
                    },
                },
                "signatures": [],
            },
            "mode": "BROADCAST_MODE_SYNC",
        }

    def _broadcast_tx(self, type_url: str, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Build and broadcast an unsigned transaction.

        NOTE: This will be rejected by the chain until signing is
        implemented.  It is provided so callers can see the exact
        payload shape and integrate a signer later.
        """
        payload = self._build_tx_body(type_url, msg)
        return self._post("/cosmos/tx/v1beta1/txs", payload)

    # ==================================================================
    # Settlement module — /oasyce/settlement/v1
    # ==================================================================

    def create_escrow(
        self,
        creator: str,
        provider: str,
        amount_uoas: int,
        timeout_seconds: int = 3600,
        capability_id: str = "",
        asset_id: str = "",
        from_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new escrow."""
        if self.has_cli:
            args = ["tx", "settlement", "create-escrow", f"{amount_uoas}uoas"]
            if asset_id:
                args += ["--asset-id", asset_id]
            if capability_id:
                args += ["--capability-id", capability_id]
            return self._run_cli(args, from_key=self._resolve_from_key(creator, from_key))
        msg = {
            "creator": creator,
            "provider": provider,
            "amount": {"denom": "uoas", "amount": str(amount_uoas)},
        }
        if capability_id:
            msg["capability_id"] = capability_id
        if asset_id:
            msg["asset_id"] = asset_id
        return self._broadcast_tx("/oasyce.settlement.v1.MsgCreateEscrow", msg)

    def release_escrow(
        self,
        escrow_id: str,
        releaser: str,
        from_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Release escrowed funds to the provider."""
        if self.has_cli:
            return self._run_cli(
                ["tx", "settlement", "release-escrow", escrow_id],
                from_key=self._resolve_from_key(releaser, from_key),
            )
        msg = {"creator": releaser, "escrow_id": escrow_id}
        return self._broadcast_tx("/oasyce.settlement.v1.MsgReleaseEscrow", msg)

    def refund_escrow(
        self,
        escrow_id: str,
        refunder: str,
        from_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Refund escrowed funds to the consumer."""
        if self.has_cli:
            return self._run_cli(
                ["tx", "settlement", "refund-escrow", escrow_id],
                from_key=self._resolve_from_key(refunder, from_key),
            )
        msg = {"creator": refunder, "escrow_id": escrow_id}
        return self._broadcast_tx("/oasyce.settlement.v1.MsgRefundEscrow", msg)

    def get_escrow(self, escrow_id: str) -> Dict[str, Any]:
        """Query a single escrow by ID."""
        return self._get(f"/oasyce/settlement/v1/escrow/{escrow_id}")

    def get_escrows_by_creator(self, creator: str) -> Dict[str, Any]:
        """Query all escrows for a given creator address."""
        return self._get(f"/oasyce/settlement/v1/escrows/{creator}")

    def get_bonding_curve_price(self, asset_id: str) -> Dict[str, Any]:
        """Query the current bonding curve price for an asset."""
        return self._get(f"/oasyce/settlement/v1/bonding_curve/{asset_id}")

    # ==================================================================
    # Capability module — /oasyce/capability/v1
    # ==================================================================

    def register_capability(
        self,
        provider: str,
        name: str,
        description: str,
        endpoint_url: str,
        price_uoas: int,
        tags: Optional[List[str]] = None,
        rate_limit: int = 0,
        from_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Register a new capability."""
        if self.has_cli:
            args = [
                "tx",
                "oasyce_capability",
                "register",
                name,
                endpoint_url,
                f"{price_uoas}uoas",
            ]
            if description:
                args += ["--description", description]
            if tags:
                args += ["--tags", ",".join(tags)]
            if rate_limit:
                args += ["--rate-limit", str(rate_limit)]
            return self._run_cli(args, from_key=self._resolve_from_key(provider, from_key))
        msg = {
            "creator": provider,
            "name": name,
            "description": description,
            "endpoint_url": endpoint_url,
            "price_per_call": {"denom": "uoas", "amount": str(price_uoas)},
            "tags": tags or [],
            "rate_limit": str(rate_limit),
        }
        return self._broadcast_tx("/oasyce.capability.v1.MsgRegisterCapability", msg)

    def invoke_capability(
        self,
        consumer: str,
        capability_id: str,
        input_data: str,
        from_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Invoke a capability."""
        if self.has_cli:
            return self._run_cli(
                ["tx", "oasyce_capability", "invoke", capability_id, "--input", input_data],
                from_key=self._resolve_from_key(consumer, from_key),
            )
        msg = {
            "creator": consumer,
            "capability_id": capability_id,
            "input": base64.b64encode(input_data.encode()).decode(),
        }
        return self._broadcast_tx("/oasyce.capability.v1.MsgInvokeCapability", msg)

    def get_capability(self, capability_id: str) -> Dict[str, Any]:
        """Query a single capability by ID."""
        return self._get(f"/oasyce/capability/v1/capability/{capability_id}")

    def list_capabilities(
        self,
        tag: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List capabilities, optionally filtered by tag or provider."""
        if provider:
            return self._get(f"/oasyce/capability/v1/capabilities/provider/{provider}")
        params: Dict[str, str] = {}
        if tag:
            params["tag"] = tag
        return self._get("/oasyce/capability/v1/capabilities", params=params)

    def get_earnings(self, provider: str) -> Dict[str, Any]:
        """Query total earnings for a provider."""
        return self._get(f"/oasyce/capability/v1/earnings/{provider}")

    # ==================================================================
    # DataRights module — /oasyce/datarights/v1
    # ==================================================================

    def register_data_asset(
        self,
        owner: str,
        name: str,
        description: str,
        content_hash: str,
        rights_type: str = "original",
        tags: Optional[List[str]] = None,
        co_creators: Optional[List[Dict[str, Any]]] = None,
        from_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Register a new data asset."""
        if self.has_cli:
            args = ["tx", "datarights", "register", name, content_hash]
            if description:
                args += ["--description", description]
            if rights_type:
                args += ["--rights-type", rights_type]
            if tags:
                args += ["--tags", ",".join(tags)]
            return self._run_cli(args, from_key=self._resolve_from_key(owner, from_key))
        rights_map = {
            "original": 0,
            "co_creation": 1,
            "licensed": 2,
            "collection": 3,
        }
        msg = {
            "creator": owner,
            "name": name,
            "description": description,
            "content_hash": content_hash,
            "rights_type": rights_map.get(rights_type, 0),
            "tags": tags or [],
            "co_creators": co_creators or [],
        }
        return self._broadcast_tx("/oasyce.datarights.v1.MsgRegisterDataAsset", msg)

    def buy_shares(
        self,
        buyer: str,
        asset_id: str,
        amount_uoas: int,
        from_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Buy shares of a data asset."""
        if self.has_cli:
            return self._run_cli(
                ["tx", "datarights", "buy-shares", asset_id, f"{amount_uoas}uoas"],
                from_key=self._resolve_from_key(buyer, from_key),
            )
        msg = {
            "creator": buyer,
            "asset_id": asset_id,
            "amount": {"denom": "uoas", "amount": str(amount_uoas)},
        }
        return self._broadcast_tx("/oasyce.datarights.v1.MsgBuyShares", msg)

    def get_data_asset(self, asset_id: str) -> Dict[str, Any]:
        """Query a single data asset by ID."""
        return self._get(f"/oasyce/datarights/v1/data_asset/{asset_id}")

    def list_data_assets(
        self,
        tag: Optional[str] = None,
        owner: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List data assets."""
        params: Dict[str, str] = {}
        if tag:
            params["tag"] = tag
        if owner:
            params["owner"] = owner
        return self._get("/oasyce/datarights/v1/data_assets", params=params)

    def get_shareholders(self, asset_id: str) -> Dict[str, Any]:
        """Query shareholders for an asset."""
        return self._get(f"/oasyce/datarights/v1/shares/{asset_id}")

    def file_dispute(
        self,
        creator: str,
        asset_id: str,
        reason: str,
        evidence: str = "",
    ) -> Dict[str, Any]:
        """File a dispute against a data asset (unsigned tx)."""
        msg = {
            "creator": creator,
            "asset_id": asset_id,
            "reason": reason,
            "evidence": evidence,
        }
        return self._broadcast_tx("/oasyce.datarights.v1.MsgFileDispute", msg)

    def resolve_dispute(
        self,
        creator: str,
        dispute_id: str,
        resolution: str,
    ) -> Dict[str, Any]:
        """Resolve a dispute (arbitrator only, unsigned tx)."""
        msg = {
            "creator": creator,
            "dispute_id": dispute_id,
            "resolution": resolution,
        }
        return self._broadcast_tx("/oasyce.datarights.v1.MsgResolveDispute", msg)

    def get_dispute(self, dispute_id: str) -> Dict[str, Any]:
        """Query a single dispute by ID."""
        return self._get(f"/oasyce/datarights/v1/dispute/{dispute_id}")

    def list_disputes(self, asset_id: Optional[str] = None) -> Dict[str, Any]:
        """List disputes, optionally filtered by asset_id."""
        params: Dict[str, str] = {}
        if asset_id:
            params["asset_id"] = asset_id
        return self._get("/oasyce/datarights/v1/disputes", params=params)

    # ==================================================================
    # Reputation module — /oasyce/reputation/v1
    # ==================================================================

    def get_reputation(self, address: str) -> Dict[str, Any]:
        """Query reputation score for an address."""
        return self._get(f"/oasyce/reputation/v1/reputation/{address}")

    def submit_feedback(
        self,
        from_addr: str,
        invocation_id: str,
        rating: int,
        comment: str = "",
    ) -> Dict[str, Any]:
        """Submit feedback for a completed invocation (unsigned tx).

        Rating is 0-500 (0 = worst, 500 = best).
        """
        msg = {
            "creator": from_addr,
            "invocation_id": invocation_id,
            "rating": rating,
            "comment": comment,
        }
        return self._broadcast_tx("/oasyce.reputation.v1.MsgSubmitFeedback", msg)

    def report_misbehavior(
        self,
        reporter: str,
        target: str,
        evidence: str,
        description: str = "",
    ) -> Dict[str, Any]:
        """Report misbehavior by a participant (unsigned tx)."""
        msg = {
            "creator": reporter,
            "target": target,
            "evidence": evidence,
            "description": description,
        }
        return self._broadcast_tx("/oasyce.reputation.v1.MsgReportMisbehavior", msg)

    def get_feedback(self, invocation_id: str) -> Dict[str, Any]:
        """Query all feedback for a given invocation."""
        return self._get(f"/oasyce/reputation/v1/feedback/{invocation_id}")

    def get_leaderboard(self, limit: int = 100) -> Dict[str, Any]:
        """Query the reputation leaderboard."""
        return self._get("/oasyce/reputation/v1/leaderboard", params={"limit": str(limit)})

    # ==================================================================
    # Capability module — update/deactivate
    # ==================================================================

    def update_capability(
        self,
        creator: str,
        capability_id: str,
        endpoint_url: Optional[str] = None,
        price_uoas: Optional[int] = None,
        rate_limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Update a capability (unsigned tx)."""
        msg: Dict[str, Any] = {
            "creator": creator,
            "capability_id": capability_id,
        }
        if endpoint_url is not None:
            msg["endpoint_url"] = endpoint_url
        if price_uoas is not None:
            msg["price_per_call"] = {"denom": "uoas", "amount": str(price_uoas)}
        if rate_limit is not None:
            msg["rate_limit"] = str(rate_limit)
        return self._broadcast_tx("/oasyce.capability.v1.MsgUpdateCapability", msg)

    def deactivate_capability(
        self,
        creator: str,
        capability_id: str,
    ) -> Dict[str, Any]:
        """Deactivate a capability (unsigned tx)."""
        msg = {"creator": creator, "capability_id": capability_id}
        return self._broadcast_tx("/oasyce.capability.v1.MsgDeactivateCapability", msg)

    # ==================================================================
    # Bank / Account — standard Cosmos SDK endpoints
    # ==================================================================

    def get_balance(self, address: str) -> Dict[str, Any]:
        """Query all token balances for an address."""
        return self._get(f"/cosmos/bank/v1beta1/balances/{address}")

    def get_balance_by_denom(self, address: str, denom: str = "uoas") -> Dict[str, Any]:
        """Query a specific denom balance for an address."""
        return self._get(
            f"/cosmos/bank/v1beta1/balances/{address}/by_denom", params={"denom": denom}
        )

    def get_account(self, address: str) -> Dict[str, Any]:
        """Query account info (sequence, account number, etc.)."""
        return self._get(f"/cosmos/auth/v1beta1/accounts/{address}")


# ======================================================================
# OasyceClient — high-level wrapper with local-engine fallback
# ======================================================================


class OasyceClient:
    """Unified client that attempts chain RPC first.

    Local fallback is only used when explicitly enabled.

    Usage::

        client = OasyceClient()
        # Uses the chain and raises when unavailable unless fallback is enabled.
        caps = client.list_capabilities(tag="nlp")
    """

    def __init__(
        self,
        rest_url: str = "http://localhost:1317",
        grpc_url: str = "localhost:9090",
        timeout: int = _DEFAULT_TIMEOUT,
        allow_local_fallback: Optional[bool] = None,
    ):
        self._chain = ChainClient(rest_url=rest_url, grpc_url=grpc_url, timeout=timeout)
        self._local_engine: Optional[Any] = None
        self._chain_available: Optional[bool] = None
        self._allow_local_fallback = (
            _env_flag("OASYCE_ALLOW_LOCAL_FALLBACK")
            if allow_local_fallback is None
            else allow_local_fallback
        )

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    def _check_chain(self) -> bool:
        """Check (and cache) whether the chain is reachable."""
        if self._chain_available is None:
            self._chain_available = self._chain.is_connected()
        return self._chain_available

    def refresh_connection(self) -> bool:
        """Re-check chain availability (clears cached status)."""
        self._chain_available = None
        return self._check_chain()

    @property
    def is_chain_mode(self) -> bool:
        """True if currently using the on-chain backend."""
        return self._check_chain()

    @property
    def chain(self) -> ChainClient:
        """Direct access to the underlying ChainClient."""
        return self._chain

    @property
    def allow_local_fallback(self) -> bool:
        """True when local-engine fallback is explicitly enabled."""
        return self._allow_local_fallback

    # ------------------------------------------------------------------
    # Local engine (lazy-loaded)
    # ------------------------------------------------------------------

    def _get_local_engine(self) -> Any:
        """Lazily import and return the local Python engine.

        This avoids a hard dependency — if the local modules are not
        installed, we raise a clear error.
        """
        if self._local_engine is None:
            try:
                from oasyce.engines.core_engines import EngineManager  # type: ignore

                self._local_engine = EngineManager()
            except ImportError:
                logger.warning("Local engine not available — chain-only mode.")
                self._local_engine = _NullEngine()
        return self._local_engine

    def _fallback_disabled_error(self, operation: str) -> ChainClientError:
        return ChainClientError(
            f"Chain unavailable for {operation}; local fallback is disabled."
        )

    def _call_with_optional_fallback(
        self,
        operation: str,
        chain_call: Callable[[], Any],
        local_method: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if self._check_chain():
            try:
                return chain_call()
            except ChainClientError as exc:
                if not self._allow_local_fallback:
                    raise
                logger.warning(
                    "Chain query failed for %s, falling back to local engine: %s",
                    operation,
                    exc,
                )
        elif not self._allow_local_fallback:
            raise self._fallback_disabled_error(operation)

        engine = self._get_local_engine()
        return getattr(engine, local_method)(*args, **kwargs)

    # ------------------------------------------------------------------
    # Capability methods
    # ------------------------------------------------------------------

    def list_capabilities(
        self,
        tag: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List capabilities from chain or local engine."""
        return self._call_with_optional_fallback(
            "list_capabilities",
            lambda: self._chain.list_capabilities(tag=tag, provider=provider).get(
                "capabilities", []
            ),
            "list_capabilities",
            tag=tag,
            provider=provider,
        )

    def get_capability(self, capability_id: str) -> Dict[str, Any]:
        """Get a single capability."""
        return self._call_with_optional_fallback(
            "get_capability",
            lambda: self._chain.get_capability(capability_id).get("capability", {}),
            "get_capability",
            capability_id,
        )

    def get_earnings(self, provider: str) -> Dict[str, Any]:
        """Get earnings for a provider."""
        return self._call_with_optional_fallback(
            "get_earnings",
            lambda: self._chain.get_earnings(provider),
            "get_earnings",
            provider,
        )

    # ------------------------------------------------------------------
    # DataRights methods
    # ------------------------------------------------------------------

    def list_data_assets(
        self,
        tag: Optional[str] = None,
        owner: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List data assets from chain or local engine."""
        return self._call_with_optional_fallback(
            "list_data_assets",
            lambda: self._chain.list_data_assets(tag=tag, owner=owner).get("assets", []),
            "list_data_assets",
            tag=tag,
            owner=owner,
        )

    def get_data_asset(self, asset_id: str) -> Dict[str, Any]:
        """Get a single data asset."""
        return self._call_with_optional_fallback(
            "get_data_asset",
            lambda: self._chain.get_data_asset(asset_id).get("asset", {}),
            "get_data_asset",
            asset_id,
        )

    # ------------------------------------------------------------------
    # Settlement methods
    # ------------------------------------------------------------------

    def get_escrow(self, escrow_id: str) -> Dict[str, Any]:
        """Get a single escrow."""
        return self._call_with_optional_fallback(
            "get_escrow",
            lambda: self._chain.get_escrow(escrow_id).get("escrow", {}),
            "get_escrow",
            escrow_id,
        )

    def get_bonding_curve_price(self, asset_id: str) -> Dict[str, Any]:
        """Get bonding curve price for an asset."""
        return self._call_with_optional_fallback(
            "get_bonding_curve_price",
            lambda: self._chain.get_bonding_curve_price(asset_id),
            "get_bonding_curve_price",
            asset_id,
        )

    # ------------------------------------------------------------------
    # Reputation methods
    # ------------------------------------------------------------------

    def get_reputation(self, address: str) -> Dict[str, Any]:
        """Get reputation for an address."""
        return self._call_with_optional_fallback(
            "get_reputation",
            lambda: self._chain.get_reputation(address),
            "get_reputation",
            address,
        )

    # ------------------------------------------------------------------
    # DataRights tx methods
    # ------------------------------------------------------------------

    def register_data_asset(self, **kwargs: Any) -> Dict[str, Any]:
        """Register a data asset on chain."""
        return self._chain.register_data_asset(**kwargs)

    def buy_shares(self, **kwargs: Any) -> Dict[str, Any]:
        """Buy shares of a data asset on chain."""
        return self._chain.buy_shares(**kwargs)

    def file_dispute(self, **kwargs: Any) -> Dict[str, Any]:
        """File a dispute on chain."""
        return self._chain.file_dispute(**kwargs)

    def resolve_dispute(self, **kwargs: Any) -> Dict[str, Any]:
        """Resolve a dispute on chain."""
        return self._chain.resolve_dispute(**kwargs)

    def get_dispute(self, dispute_id: str) -> Dict[str, Any]:
        """Get a single dispute."""
        return self._call_with_optional_fallback(
            "get_dispute",
            lambda: self._chain.get_dispute(dispute_id).get("dispute", {}),
            "get_dispute",
            dispute_id,
        )

    def list_disputes(self, asset_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List disputes."""
        return self._call_with_optional_fallback(
            "list_disputes",
            lambda: self._chain.list_disputes(asset_id=asset_id).get("disputes", []),
            "list_disputes",
            asset_id=asset_id,
        )

    def get_shareholders(self, asset_id: str) -> List[Dict[str, Any]]:
        """Get shareholders for a data asset."""
        return self._call_with_optional_fallback(
            "get_shareholders",
            lambda: self._chain.get_shareholders(asset_id).get("shareholders", []),
            "get_shareholders",
            asset_id,
        )

    # ------------------------------------------------------------------
    # Settlement tx methods
    # ------------------------------------------------------------------

    def create_escrow(self, **kwargs: Any) -> Dict[str, Any]:
        """Create an escrow on chain."""
        return self._chain.create_escrow(**kwargs)

    def release_escrow(self, escrow_id: str, releaser: str) -> Dict[str, Any]:
        """Release escrowed funds on chain."""
        return self._chain.release_escrow(escrow_id, releaser)

    def refund_escrow(self, escrow_id: str, refunder: str) -> Dict[str, Any]:
        """Refund escrowed funds on chain."""
        return self._chain.refund_escrow(escrow_id, refunder)

    # ------------------------------------------------------------------
    # Capability tx methods
    # ------------------------------------------------------------------

    def register_capability(self, **kwargs: Any) -> Dict[str, Any]:
        """Register a capability on chain."""
        return self._chain.register_capability(**kwargs)

    def invoke_capability(self, **kwargs: Any) -> Dict[str, Any]:
        """Invoke a capability on chain."""
        return self._chain.invoke_capability(**kwargs)

    def update_capability(self, **kwargs: Any) -> Dict[str, Any]:
        """Update a capability on chain."""
        return self._chain.update_capability(**kwargs)

    def deactivate_capability(self, **kwargs: Any) -> Dict[str, Any]:
        """Deactivate a capability on chain."""
        return self._chain.deactivate_capability(**kwargs)

    # ------------------------------------------------------------------
    # Reputation tx methods
    # ------------------------------------------------------------------

    def submit_feedback(self, **kwargs: Any) -> Dict[str, Any]:
        """Submit feedback on chain."""
        return self._chain.submit_feedback(**kwargs)

    def report_misbehavior(self, **kwargs: Any) -> Dict[str, Any]:
        """Report misbehavior on chain."""
        return self._chain.report_misbehavior(**kwargs)

    def get_feedback(self, invocation_id: str) -> Dict[str, Any]:
        """Get feedback for an invocation."""
        return self._call_with_optional_fallback(
            "get_feedback",
            lambda: self._chain.get_feedback(invocation_id),
            "get_feedback",
            invocation_id,
        )

    def get_leaderboard(self, limit: int = 100) -> Dict[str, Any]:
        """Get reputation leaderboard."""
        return self._call_with_optional_fallback(
            "get_leaderboard",
            lambda: self._chain.get_leaderboard(limit=limit),
            "get_leaderboard",
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Bank / Account
    # ------------------------------------------------------------------

    def get_balance(self, address: str) -> Dict[str, Any]:
        """Get token balances for an address."""
        return self._call_with_optional_fallback(
            "get_balance",
            lambda: self._chain.get_balance(address),
            "get_balance",
            address,
        )

    def is_connected(self) -> bool:
        """Check if chain is reachable."""
        return self._check_chain()


class _NullEngine:
    """Stub engine returned when the local Python engine is not installed."""

    def __getattr__(self, name: str) -> Any:
        def _not_available(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            raise ChainClientError(
                f"Operation '{name}' unavailable: chain is down and local engine is not installed."
            )

        return _not_available
