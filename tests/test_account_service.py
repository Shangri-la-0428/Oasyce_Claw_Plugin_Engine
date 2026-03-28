from __future__ import annotations

import types

from oasyce.services.account_service import (
    adopt_account_payload,
    get_account_status_payload,
    join_device_payload,
    run_bootstrap,
    verify_account_payload,
)


def test_get_account_status_payload_passthrough():
    payload = get_account_status_payload(
        status_reader=lambda: {
            "configured": True,
            "account_address": "oasyce1shared",
            "can_sign": True,
        }
    )

    assert payload["account_address"] == "oasyce1shared"
    assert payload["can_sign"] is True


def test_adopt_account_payload_wraps_status():
    payload = adopt_account_payload(
        account_address="oasyce1shared",
        readonly=True,
        adopter=lambda **_: {
            "configured": True,
            "account_address": "oasyce1shared",
            "account_mode": "attached_readonly",
            "can_sign": False,
        },
    )

    assert payload["ok"] is True
    assert payload["account_mode"] == "attached_readonly"


def test_run_bootstrap_returns_structured_upgrade_failure():
    payload = run_bootstrap(
        no_update=False,
        check_package_updates=lambda: [
            {
                "name": "oasyce",
                "current": "2.3.2",
                "latest": "2.4.0",
                "installed": True,
                "up_to_date": False,
            }
        ],
        upgrade_managed_packages=lambda: types.SimpleNamespace(
            returncode=1, stderr="network down"
        ),
        module_spec_finder=lambda name: object(),
        which=lambda name: "/usr/local/bin/datavault",
    )

    assert payload["ok"] is False
    assert payload["error"] == "network down"


def test_verify_account_payload_reports_signing_issue():
    payload = verify_account_payload(
        require_signing=True,
        status_reader=lambda: {
            "configured": True,
            "account_address": "oasyce1shared",
            "account_mode": "attached_readonly",
            "can_sign": False,
            "signer_name": "",
            "signer_matches_account": False,
            "wallet_present": True,
            "wallet_matches_account": True,
        },
    )

    assert payload["ok"] is False
    assert "cannot sign" in payload["issues"][0]


def test_verify_account_payload_reports_revoked_device_authorization():
    payload = verify_account_payload(
        require_signing=True,
        status_reader=lambda: {
            "configured": True,
            "account_address": "oasyce1shared",
            "account_mode": "attached_signing",
            "can_sign": False,
            "signer_name": "oasyce-agent",
            "signer_matches_account": True,
            "wallet_present": True,
            "wallet_matches_account": True,
            "device_authorization_status": "revoked",
            "authorization_matches_account": True,
            "device_matches_authorization": True,
        },
    )

    assert payload["ok"] is False
    assert any("revoked" in issue for issue in payload["issues"])


def test_verify_account_payload_reports_copied_device_authorization():
    payload = verify_account_payload(
        require_signing=True,
        status_reader=lambda: {
            "configured": True,
            "account_address": "oasyce1shared",
            "account_mode": "attached_signing",
            "can_sign": False,
            "signer_name": "oasyce-agent",
            "signer_matches_account": True,
            "wallet_present": True,
            "wallet_matches_account": True,
            "device_authorization_status": "active",
            "authorization_matches_account": True,
            "device_matches_authorization": False,
        },
    )

    assert payload["ok"] is False
    assert any("different device" in issue for issue in payload["issues"])


def test_run_bootstrap_reuses_existing_account_without_creating_wallet(monkeypatch):
    monkeypatch.setenv("OASYCE_NETWORK_MODE", "testnet")

    from oasyce.services import account_service

    wallet_calls = {"created": False}

    class FakeWallet:
        @staticmethod
        def get_address():
            return ""

        @staticmethod
        def create():
            wallet_calls["created"] = True
            return types.SimpleNamespace(address="wallet-new")

    monkeypatch.setattr("oasyce.identity.Wallet", FakeWallet)
    monkeypatch.setattr(
        account_service._update_manager,
        "enable_managed_install",
        lambda auto_update=True: {"auto_update": True, "installed_via_bootstrap": True},
    )
    monkeypatch.setattr(
        "oasyce.account_state.build_account_status",
        lambda: {
            "configured": True,
            "account_address": "oasyce1shared",
            "account_mode": "attached_readonly",
            "signer_name": "",
            "signer_address": "",
            "wallet_address": "",
            "can_sign": False,
        },
    )

    payload = run_bootstrap(
        no_update=True,
        check_package_updates=lambda: [],
        upgrade_managed_packages=lambda: types.SimpleNamespace(returncode=0, stderr=""),
        module_spec_finder=lambda name: object(),
        which=lambda name: "/usr/local/bin/datavault",
    )

    assert payload["ok"] is True
    assert payload["used_existing_account"] is True
    assert payload["wallet_created"] is False
    assert wallet_calls["created"] is False


def test_join_device_payload_readonly_success():
    payload = join_device_payload(
        account_address="oasyce1shared",
        readonly=True,
        no_update=True,
        check_package_updates=lambda: [],
        upgrade_managed_packages=lambda: types.SimpleNamespace(returncode=0, stderr=""),
        module_spec_finder=lambda name: object(),
        which=lambda name: "/usr/local/bin/datavault",
        adopter=lambda **_: {
            "configured": True,
            "account_address": "oasyce1shared",
            "account_mode": "attached_readonly",
            "can_sign": False,
        },
        bootstrap_runner=lambda **_: {
            "ok": True,
            "datavault_module": True,
            "datavault_cli": True,
            "account": {"account_address": "oasyce1shared"},
        },
        verifier=lambda **_: {
            "ok": True,
            "status": {
                "configured": True,
                "account_address": "oasyce1shared",
                "can_sign": False,
            },
            "issues": [],
            "warnings": [],
        },
    )

    assert payload["ok"] is True
    assert payload["readonly"] is True
    assert payload["write_ready"] is False


def test_join_device_payload_requires_account():
    payload = join_device_payload(
        account_address="",
        readonly=True,
        no_update=True,
        check_package_updates=lambda: [],
        upgrade_managed_packages=lambda: types.SimpleNamespace(returncode=0, stderr=""),
        which=lambda name: "/usr/local/bin/datavault",
    )

    assert payload["ok"] is False
    assert "Pass --account" in payload["error"]
