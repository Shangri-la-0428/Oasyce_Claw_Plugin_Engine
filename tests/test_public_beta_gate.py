from __future__ import annotations

from pathlib import Path

from oasyce.services.public_beta_gate import (
    DEFAULT_PUBLIC_BETA_NODE_URL,
    run_public_beta_doctor,
    run_public_beta_smoke,
)


class _Mode:
    name = "TESTNET"


def test_run_public_beta_doctor_success(monkeypatch):
    responses = iter(
        [
            {"result": {"node_info": {"network": "oasyce-testnet-1"}}},
            {"chain_id": "oasyce-testnet-1"},
            {"params": {"airdrop_amount": {"amount": "1"}, "pow_difficulty": 16}},
        ]
    )

    report = run_public_beta_doctor(
        rest_url="http://chain.example.test",
        rpc_url="http://rpc.example.test",
        import_optional_module=lambda name: object(),
        wallet_exists=lambda: True,
        managed_install_reader=lambda: {"auto_update": True, "installed_via_bootstrap": True},
        network_mode_reader=lambda: _Mode(),
        security_reader=lambda mode: {"allow_local_fallback": False},
        which=lambda name: "/usr/local/bin/datavault",
        find_oasyced=lambda: "/usr/local/bin/oasyced",
        http_get_json=lambda url, timeout=5: next(responses),
        signer_inspector=lambda **kwargs: {
            "name": "oasyce-agent",
            "address": "oasyce1test",
            "key_exists": True,
            "balance_uoas": 2_000_000,
            "ready": True,
        },
    )

    assert report["scope"] == "public_beta"
    assert report["status"] == "ok"
    assert report["errors"] == 0
    names = {item["name"] for item in report["checks"]}
    assert "Network mode" in names
    assert "Public chain RPC" in names
    assert "Public chain health" in names
    assert report["rest_url"] == "http://chain.example.test"
    assert report["rpc_url"] == "http://rpc.example.test"


def test_run_public_beta_smoke_happy_path(tmp_path):
    calls: list[tuple[str, tuple, dict]] = []
    portfolio_attempts = {"count": 0}

    class FakeClient:
        def __init__(self, base_url: str):
            assert base_url == DEFAULT_PUBLIC_BETA_NODE_URL

        def status(self):
            calls.append(("status", (), {}))
            return {"ok": True}

        def register(
            self,
            file_path,
            owner,
            tags="",
            rights_type="original",
            price_model="auto",
            price=0,
            machine=False,
            trace_id=None,
        ):
            calls.append(
                (
                    "register",
                    (file_path, owner),
                    {
                        "tags": tags,
                        "rights_type": rights_type,
                        "price_model": price_model,
                        "price": price,
                        "machine": machine,
                        "trace_id": trace_id,
                    },
                )
            )
            assert Path(file_path).exists()
            return {
                "ok": True,
                "action": "register",
                "state": "success",
                "retryable": False,
                "trace_id": trace_id,
                "data": {"asset_id": "ASSET_SMOKE_1", "owner": owner},
            }

        def quote(self, asset_id, amount=10, machine=False, trace_id=None):
            calls.append(("quote", (asset_id, amount), {"machine": machine, "trace_id": trace_id}))
            return {
                "ok": True,
                "action": "quote",
                "state": "success",
                "retryable": False,
                "trace_id": trace_id,
                "data": {"asset_id": asset_id, "amount": amount},
            }

        def buy(
            self, asset_id, buyer, amount=10.0, machine=False, trace_id=None, idempotency_key=None
        ):
            calls.append(
                (
                    "buy",
                    (asset_id, buyer, amount),
                    {
                        "machine": machine,
                        "trace_id": trace_id,
                        "idempotency_key": idempotency_key,
                    },
                )
            )
            replay = sum(1 for name, *_ in calls if name == "buy") > 1
            return {
                "ok": True,
                "action": "buy",
                "state": "success",
                "retryable": False,
                "trace_id": trace_id,
                "idempotent_replay": replay,
                "data": {"asset_id": asset_id, "buyer": buyer},
            }

        def portfolio(self, buyer=None, machine=False, trace_id=None):
            calls.append(("portfolio", (buyer,), {"machine": machine, "trace_id": trace_id}))
            portfolio_attempts["count"] += 1
            return {
                "ok": True,
                "action": "portfolio",
                "state": "success",
                "retryable": False,
                "trace_id": trace_id,
                "data": {
                    "buyer": buyer,
                    "holdings": (
                        []
                        if portfolio_attempts["count"] == 1
                        else [{"asset_id": "ASSET_SMOKE_1", "shares": 1.0}]
                    ),
                },
            }

        def support_beta(self, limit=20, transactions_limit=20):
            calls.append(
                ("support_beta", (), {"limit": limit, "transactions_limit": transactions_limit})
            )
            return {
                "ok": True,
                "events": [
                    {"trace_id": "beta-smoke-123-register"},
                    {"trace_id": "beta-smoke-123-buy"},
                ],
                "transactions": [],
            }

    report = run_public_beta_smoke(
        doctor_runner=lambda **kwargs: {
            "scope": "public_beta",
            "status": "ok",
            "errors": 0,
            "warnings": 0,
            "checks": [],
        },
        signer_inspector=lambda **kwargs: {
            "name": "oasyce-agent",
            "address": "oasyce1smoke",
            "key_exists": True,
            "balance_uoas": 2_000_000,
            "ready": True,
        },
        client_cls=FakeClient,
        smoke_dir=tmp_path,
        trace_prefix="beta-smoke-123",
    )

    assert report["scope"] == "public_beta_smoke"
    assert report["status"] == "ok"
    assert report["errors"] == 0
    assert report["asset_id"] == "ASSET_SMOKE_1"
    assert report["created_asset"] is True
    names = [item["name"] for item in report["checks"]]
    assert names == [
        "Doctor gate",
        "Local node API",
        "Register",
        "Quote",
        "Buy",
        "Buy replay",
        "Portfolio",
        "Support trace",
    ]
    assert [name for name, *_ in calls] == [
        "status",
        "register",
        "quote",
        "buy",
        "buy",
        "portfolio",
        "portfolio",
        "support_beta",
    ]


def test_run_public_beta_smoke_blocks_on_doctor_failure(tmp_path):
    report = run_public_beta_smoke(
        doctor_runner=lambda **kwargs: {
            "scope": "public_beta",
            "status": "error",
            "errors": 2,
            "warnings": 0,
            "checks": [{"name": "Network mode", "status": "error", "detail": "Set env"}],
        },
        signer_inspector=lambda **kwargs: {
            "name": "oasyce-agent",
            "address": "oasyce1blocked",
            "key_exists": True,
            "balance_uoas": 2_000_000,
            "ready": True,
        },
        smoke_dir=tmp_path,
        trace_prefix="beta-smoke-blocked",
    )

    assert report["status"] == "error"
    assert report["errors"] >= 1
    assert report["checks"][0]["name"] == "Doctor gate"
