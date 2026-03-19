from __future__ import annotations

from oasyce.interfaces.settlement import ISettlement, SettleResult
from oasyce.models.transaction import Transaction, SettleSplit


class MockSettlement(ISettlement):
    def settle(self, tx: Transaction) -> SettleResult:
        if tx.amount_oas <= 0:
            return SettleResult(success=False, tx_id=tx.tx_id, reason="amount must be positive")

        amt = tx.amount_oas
        # 90% creator, 5% protocol (50% burn + 50% validator), 5% router
        creator = amt * 0.90
        protocol_burn = amt * 0.05 * 0.50  # 2.5%
        protocol_validator = amt * 0.05 * 0.50  # 2.5%
        router = amt * 0.05

        split = SettleSplit(
            creator=creator,
            protocol_burn=protocol_burn,
            protocol_validator=protocol_validator,
            router=router,
        )
        return SettleResult(success=True, tx_id=tx.tx_id, split=split)
