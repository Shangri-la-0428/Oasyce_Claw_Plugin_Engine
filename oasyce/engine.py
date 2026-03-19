from __future__ import annotations

from datetime import datetime, timezone

from oasyce.config import OasyceConfig, get_config
from oasyce.interfaces.verifier import VerifyResult
from oasyce.interfaces.pricing import QuoteResult
from oasyce.interfaces.settlement import SettleResult
from oasyce.models.capture_pack import CapturePack
from oasyce.models.asset import Asset
from oasyce.models.transaction import Transaction


class OasyceEngine:
    def __init__(self, config: OasyceConfig | None = None) -> None:
        self.cfg = config or get_config()

    def submit(self, pack: CapturePack, creator: str) -> tuple[VerifyResult, str | None]:
        """Verify a CapturePack; if valid, register as asset. Returns (result, asset_id|None)."""
        result = self.cfg.verifier.verify(pack)
        if not result.valid:
            return result, None

        asset = Asset(creator=creator, media_hash=pack.media_hash)
        asset_id = self.cfg.registry.register(asset)
        return result, asset_id

    def buy(self, asset_id: str, buyer: str) -> tuple[QuoteResult | None, SettleResult | None]:
        """Quote price for one unit, then settle the transaction."""
        asset = self.cfg.registry.get(asset_id)
        if asset is None:
            return None, None

        quote = self.cfg.pricing.quote(asset_id, asset.supply)

        tx = Transaction(
            asset_id=asset_id,
            buyer=buyer,
            amount_oas=quote.price_oas,
            tx_type="buy",
        )
        settle = self.cfg.settlement.settle(tx)

        if settle.success:
            asset.supply += 1
            self.cfg.registry.update_supply(asset_id, asset.supply)

        return quote, settle


def demo() -> None:
    """Run a full pipeline demonstration."""
    engine = OasyceEngine()

    now = datetime.now(timezone.utc).isoformat()
    pack = CapturePack(
        timestamp=now,
        gps_hash="a" * 64,
        device_signature="deadbeef",
        media_hash="b" * 64,
        source="camera",
    )

    print("=== Oasyce Core Demo ===\n")

    # Step 1: Submit & verify
    verify_result, asset_id = engine.submit(pack, creator="alice")
    print(f"1. Verify: valid={verify_result.valid}, asset_id={asset_id}")

    if asset_id is None:
        print("   Verification failed, aborting.")
        return

    # Step 2: Buy
    quote, settle = engine.buy(asset_id, buyer="bob")
    assert quote is not None and settle is not None
    print(f"2. Quote:  price={quote.price_oas} OAS (supply={quote.supply})")
    print(f"3. Settle: success={settle.success}, tx_id={settle.tx_id[:8]}...")
    if settle.split:
        s = settle.split
        print(
            f"   Split:  creator={s.creator:.2f}, burn={s.protocol_burn:.2f}, "
            f"validator={s.protocol_validator:.2f}, router={s.router:.2f}"
        )

    # Step 3: Second buy (price goes up on bonding curve)
    quote2, settle2 = engine.buy(asset_id, buyer="carol")
    assert quote2 is not None and settle2 is not None
    print(f"4. Second buy: price={quote2.price_oas} OAS (supply={quote2.supply})")

    print("\nDone.")


if __name__ == "__main__":
    demo()
