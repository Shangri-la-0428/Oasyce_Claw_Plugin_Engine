from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

from oasyce.services import public_beta_signer
from oasyce.services.public_beta_signer import (
    PublicBetaSignerError,
    ensure_public_beta_signer,
    inspect_public_beta_signer,
)
from oasyce import update_manager


def test_inspect_public_beta_signer_reports_ready():
    def fake_runner(args, **kwargs):
        assert args[:3] == ["keys", "show", "oasyce-agent"]
        return {"raw_output": "oasyce1ready"}

    responses = {
        "http://chain.example.test/cosmos/auth/v1beta1/accounts/oasyce1ready": {"account": {}},
        "http://chain.example.test/cosmos/bank/v1beta1/balances/oasyce1ready/by_denom?denom=uoas": {
            "balance": {"amount": "20000000"}
        },
    }

    result = inspect_public_beta_signer(
        signer_name="oasyce-agent",
        rest_url="http://chain.example.test",
        run_oasyced=fake_runner,
        http_get_json=lambda url, timeout=5: responses[url],
    )

    assert result["key_exists"] is True
    assert result["account_exists"] is True
    assert result["balance_uoas"] == 20_000_000
    assert result["ready"] is True


def test_ensure_public_beta_signer_creates_and_claims(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    state = {"created": False, "funded": False}

    def fake_runner(args, **kwargs):
        if args[:3] == ["keys", "show", "oasyce-agent"]:
            if not state["created"]:
                raise PublicBetaSignerError("key not found")
            return {"raw_output": "oasyce1created"}
        if args[:3] == ["keys", "add", "oasyce-agent"]:
            state["created"] = True
            return {"address": "oasyce1created"}
        raise AssertionError(f"unexpected args: {args}")

    def fake_http_get_json(url, timeout=5):
        if url.endswith("/cosmos/auth/v1beta1/accounts/oasyce1created"):
            if state["funded"]:
                return {"account": {}}
            raise RuntimeError("account not found")
        if url.endswith("/cosmos/bank/v1beta1/balances/oasyce1created/by_denom?denom=uoas"):
            if state["funded"]:
                return {"balance": {"amount": "20000000"}}
            return {"balance": {"amount": "0"}}
        raise AssertionError(f"unexpected url: {url}")

    def fake_faucet(url, params=None, timeout=5):
        assert params == {"address": "oasyce1created"}
        state["funded"] = True
        return SimpleNamespace(raise_for_status=lambda: None)

    result = ensure_public_beta_signer(
        signer_name="oasyce-agent",
        rest_url="http://chain.example.test",
        faucet_url="http://faucet.example.test",
        run_oasyced=fake_runner,
        http_get_json=fake_http_get_json,
        http_get=fake_faucet,
        wait_seconds=1,
    )

    persisted = update_manager.read_managed_install_state()
    assert result["created"] is True
    assert result["claimed_faucet"] is True
    assert result["ready"] is True
    assert persisted["chain_signer_name"] == "oasyce-agent"
    assert persisted["chain_signer_address"] == "oasyce1created"


def test_ensure_public_beta_signer_wraps_faucet_http_errors(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    def fake_runner(args, **kwargs):
        assert args[:3] == ["keys", "show", "oasyce-agent"]
        return {"raw_output": "oasyce1created"}

    def fake_http_get_json(url, timeout=5):
        if url.endswith("/cosmos/auth/v1beta1/accounts/oasyce1created"):
            raise RuntimeError("account not found")
        if url.endswith("/cosmos/bank/v1beta1/balances/oasyce1created/by_denom?denom=uoas"):
            return {"balance": {"amount": "0"}}
        raise AssertionError(f"unexpected url: {url}")

    def fake_faucet(url, params=None, timeout=5):
        response = SimpleNamespace(status_code=429)
        raise requests.HTTPError("429 Client Error", response=response)

    with pytest.raises(PublicBetaSignerError, match="Public beta faucet request failed"):
        ensure_public_beta_signer(
            signer_name="oasyce-agent",
            rest_url="http://chain.example.test",
            faucet_url="http://faucet.example.test",
            run_oasyced=fake_runner,
            http_get_json=fake_http_get_json,
            http_get=fake_faucet,
            wait_seconds=1,
        )
