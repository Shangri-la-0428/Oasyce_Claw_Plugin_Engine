from __future__ import annotations

from types import SimpleNamespace

from oasyce.bridge import core_bridge


def _signed_metadata() -> dict:
    return {
        "owner": "oasyce1owner",
        "file_hash": "b" * 64,
        "tags": ["beta-smoke"],
    }


def test_bridge_register_resolves_chain_asset_id(monkeypatch):
    monkeypatch.setattr(core_bridge, "_verify_pack", lambda pack: {"valid": True, "reason": None})

    fake_chain = SimpleNamespace(
        register_data_asset=lambda **kwargs: {"txhash": "TXHASH_1"},
        list_data_assets=lambda owner=None: {
            "data_assets": [
                {
                    "id": "DATA_real123",
                    "content_hash": "b" * 64,
                }
            ]
        },
    )
    fake_client = SimpleNamespace(chain=fake_chain, allow_local_fallback=False)
    monkeypatch.setattr(core_bridge, "_get_client", lambda: fake_client)

    result = core_bridge.bridge_register(_signed_metadata())

    assert result["valid"] is True
    assert result["core_asset_id"] == "DATA_real123"


def test_bridge_buy_surfaces_failed_tx_response(monkeypatch):
    fake_chain = SimpleNamespace(
        buy_shares=lambda **kwargs: {
            "tx_response": {
                "txhash": "TXHASH_2",
                "code": 13,
                "raw_log": "insufficient funds",
            }
        }
    )
    fake_client = SimpleNamespace(chain=fake_chain)
    monkeypatch.setattr(core_bridge, "_get_client", lambda: fake_client)

    result = core_bridge.bridge_buy("DATA_real123", buyer="oasyce1buyer", amount=1.0)

    assert "error" in result
    assert "insufficient funds" in result["error"]
