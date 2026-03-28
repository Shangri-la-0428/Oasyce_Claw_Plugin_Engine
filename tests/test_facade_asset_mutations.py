from __future__ import annotations

import hashlib
from types import SimpleNamespace

from oasyce.services.facade import OasyceServiceFacade
from oasyce.storage.ledger import Ledger


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_reregister_asset_creates_new_version_and_updates_hash(tmp_path):
    file_path = tmp_path / "asset.txt"
    file_path.write_text("v1", encoding="utf-8")

    original_hash = _sha256_text("v1")
    ledger = Ledger(str(tmp_path / "ledger.db"))
    ledger.register_asset(
        "ASSET_RE1",
        "owner-1",
        original_hash,
        {
            "owner": "owner-1",
            "file_path": str(file_path),
            "file_hash": original_hash,
            "created_at": "2026-03-28T00:00:00+00:00",
        },
    )
    facade = OasyceServiceFacade(ledger=ledger, allow_local_fallback=True)

    file_path.write_text("v2", encoding="utf-8")

    result = facade.reregister_asset("ASSET_RE1", owner="owner-1")

    assert result.success is True
    assert result.data["changed"] is True
    assert result.data["version"] == 2
    assert result.data["file_hash"] == _sha256_text("v2")

    meta = ledger.get_asset_metadata("ASSET_RE1")
    assert meta["file_hash"] == _sha256_text("v2")
    assert meta["versions"][-1]["version"] == 2
    assert meta["versions"][-1]["file_hash"] == _sha256_text("v2")


def test_reregister_asset_returns_no_change_when_hash_matches(tmp_path):
    file_path = tmp_path / "asset.txt"
    file_path.write_text("same", encoding="utf-8")

    current_hash = _sha256_text("same")
    ledger = Ledger(str(tmp_path / "ledger.db"))
    ledger.register_asset(
        "ASSET_RE2",
        "owner-1",
        current_hash,
        {
            "owner": "owner-1",
            "file_path": str(file_path),
            "file_hash": current_hash,
            "created_at": "2026-03-28T00:00:00+00:00",
        },
    )
    facade = OasyceServiceFacade(ledger=ledger, allow_local_fallback=True)

    result = facade.reregister_asset("ASSET_RE2", owner="owner-1")

    assert result.success is True
    assert result.data == {
        "asset_id": "ASSET_RE2",
        "changed": False,
        "message": "no changes detected",
    }


def test_stake_node_updates_total_via_facade(tmp_path):
    ledger = Ledger(str(tmp_path / "ledger.db"))
    facade = OasyceServiceFacade(ledger=ledger, allow_local_fallback=True)

    result = facade.stake_node("validator-1", "staker-1", 25.0)

    assert result.success is True
    assert result.data == {"node_id": "validator-1", "total_stake": 25.0}

    stakes = ledger.get_stakes_summary()
    assert stakes == [{"validator_id": "validator-1", "total": 25.0}]


def test_buy_success_dispatches_buy_notifications(monkeypatch, tmp_path):
    ledger = Ledger(str(tmp_path / "ledger.db"))
    ledger.register_asset(
        "ASSET_BUY_NOTIFY",
        "owner-1",
        "hash-1",
        {"owner": "owner-1"},
    )
    facade = OasyceServiceFacade(ledger=ledger, allow_local_fallback=True)

    calls = []

    class _Notifications:
        def dispatch(self, asset_id, buyer, quote):
            calls.append((asset_id, buyer, quote))

    receipt = SimpleNamespace(
        status=SimpleNamespace(value="success"),
        receipt_id="rcpt-1",
        asset_id="ASSET_BUY_NOTIFY",
        buyer="buyer-1",
        amount_oas=10.0,
        quote=SimpleNamespace(
            equity_minted=2.0,
            spot_price_after=1.5,
            protocol_fee=0.1,
        ),
    )
    settlement_pool = SimpleNamespace(equity={"buyer-1": 2.0})
    settlement = SimpleNamespace(
        get_pool=lambda asset_id: settlement_pool,
        execute=lambda asset_id, buyer, amount: receipt,
    )

    monkeypatch.setattr(facade, "_get_settlement", lambda: settlement)
    monkeypatch.setattr(facade, "_get_buy_notifications", lambda: _Notifications())
    monkeypatch.setattr(facade, "get_equity_access_level", lambda asset_id, buyer: "L1")

    result = facade.buy("ASSET_BUY_NOTIFY", "buyer-1", 10.0)

    assert result.success is True
    assert result.data["equity_balance"] == 2.0
    assert calls == [
        (
            "ASSET_BUY_NOTIFY",
            "buyer-1",
            {
                "equity_minted": 2.0,
                "spot_price_after": 1.5,
                "protocol_fee": 0.1,
            },
        )
    ]
