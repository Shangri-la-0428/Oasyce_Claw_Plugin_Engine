from __future__ import annotations

import base64
import json
import types
from pathlib import Path

from oasyce.services.account_service import (
    adopt_account_payload,
    export_device_bundle_data_payload,
    export_device_bundle_payload,
    get_account_status_payload,
    join_device_from_bundle_data_payload,
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
        upgrade_managed_packages=lambda: types.SimpleNamespace(returncode=1, stderr="network down"),
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


def test_export_device_bundle_payload_signing_bundle(tmp_path: Path):
    keyring_dir = tmp_path / "keyring-test"
    keyring_dir.mkdir()
    (keyring_dir / "oasyce-agent.info").write_bytes(b"signer-secret")

    payload = export_device_bundle_payload(
        output_path=str(tmp_path / "device.json"),
        readonly=False,
        status_reader=lambda: {
            "configured": True,
            "account_address": "oasyce1shared",
            "can_sign": True,
            "signer_name": "oasyce-agent",
        },
        keyring_dir=keyring_dir,
        clock=lambda: 123.0,
    )

    assert payload["ok"] is True
    bundle = json.loads((tmp_path / "device.json").read_text())
    assert bundle["bundle_mode"] == "signing"
    assert bundle["account_address"] == "oasyce1shared"
    assert base64.b64decode(bundle["signer_info_b64"]) == b"signer-secret"


def test_export_device_bundle_data_payload_returns_bundle_object(tmp_path: Path):
    keyring_dir = tmp_path / "keyring-test"
    keyring_dir.mkdir()
    (keyring_dir / "oasyce-agent.info").write_bytes(b"signer-secret")

    payload = export_device_bundle_data_payload(
        readonly=False,
        status_reader=lambda: {
            "configured": True,
            "account_address": "oasyce1shared",
            "can_sign": True,
            "signer_name": "oasyce-agent",
        },
        keyring_dir=keyring_dir,
        clock=lambda: 123.0,
    )

    assert payload["ok"] is True
    assert payload["bundle_mode"] == "signing"
    assert payload["bundle"]["account_address"] == "oasyce1shared"


def test_join_device_from_bundle_data_payload_imports_signer(tmp_path: Path):
    keyring_dir = tmp_path / "keyring-test"

    payload = join_device_from_bundle_data_payload(
        bundle={
            "kind": "oasyce_trusted_device_bundle",
            "version": 1,
            "account_address": "oasyce1shared",
            "bundle_mode": "signing",
            "signer_name": "oasyce-agent",
            "signer_info_b64": base64.b64encode(b"signer-secret").decode("ascii"),
        },
        keyring_dir=keyring_dir,
    )

    assert payload["ok"] is True
    assert payload["readonly"] is False
    assert (keyring_dir / "oasyce-agent.info").read_bytes() == b"signer-secret"


def test_join_device_payload_from_bundle(tmp_path: Path):
    bundle_path = tmp_path / "device.json"
    bundle_path.write_text(
        json.dumps(
            {
                "kind": "oasyce_trusted_device_bundle",
                "version": 1,
                "account_address": "oasyce1shared",
                "bundle_mode": "signing",
                "signer_name": "oasyce-agent",
                "signer_info_b64": base64.b64encode(b"signer-secret").decode("ascii"),
            }
        )
    )

    payload = join_device_payload(
        account_address="",
        bundle_path=str(bundle_path),
        readonly=False,
        no_update=True,
        check_package_updates=lambda: [],
        upgrade_managed_packages=lambda: types.SimpleNamespace(returncode=0, stderr=""),
        module_spec_finder=lambda name: object(),
        which=lambda name: "/usr/local/bin/datavault",
        bundle_joiner=lambda **_: {
            "ok": True,
            "account_address": "oasyce1shared",
            "signer_name": "oasyce-agent",
            "readonly": False,
            "bundle_mode": "signing",
        },
        adopter=lambda **_: {
            "configured": True,
            "account_address": "oasyce1shared",
            "account_mode": "attached_signing",
            "can_sign": True,
            "signer_name": "oasyce-agent",
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
                "can_sign": True,
            },
            "issues": [],
            "warnings": [],
        },
    )

    assert payload["ok"] is True
    assert payload["readonly"] is False
    assert payload["bundle"]["bundle_mode"] == "signing"


def test_join_device_payload_rejects_bundle_account_mismatch():
    payload = join_device_payload(
        account_address="oasyce1manual",
        bundle_path="/tmp/oasyce-device.json",
        readonly=False,
        no_update=True,
        check_package_updates=lambda: [],
        upgrade_managed_packages=lambda: types.SimpleNamespace(returncode=0, stderr=""),
        which=lambda name: "/usr/local/bin/datavault",
        bundle_joiner=lambda **_: {
            "ok": True,
            "account_address": "oasyce1bundle",
            "signer_name": "oasyce-agent",
            "readonly": False,
            "bundle_mode": "signing",
        },
    )

    assert payload["ok"] is False
    assert "Bundle account" in payload["error"]
