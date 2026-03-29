from __future__ import annotations

from pathlib import Path

import pytest

from oasyce.account_state import (
    AccountStateError,
    adopt_account,
    build_account_status,
    configure_bootstrap_account,
    read_device_authorization,
    read_account_state,
    revoke_device_authorization,
    resolve_canonical_account_address,
)


def test_build_account_status_uses_stored_account_state(tmp_path: Path):
    path = tmp_path / "account.json"
    configure_bootstrap_account(
        wallet_address="wallet-local",
        chain_signer={"name": "oasyce-agent", "address": "oasyce1same"},
        path=path,
    )

    status = build_account_status(
        path=path,
        wallet_get_address=lambda: "wallet-local",
        managed_state_reader=lambda: {
            "chain_signer_name": "oasyce-agent",
            "chain_signer_address": "oasyce1same",
            "auto_update": True,
        },
        signer_inspector=lambda **_: {
            "name": "oasyce-agent",
            "address": "oasyce1same",
            "ready": True,
        },
    )

    assert status["configured"] is True
    assert status["account_address"] == "oasyce1same"
    assert status["account_mode"] == "managed_local"
    assert status["wallet_matches_account"] is False
    assert status["signer_matches_account"] is True
    assert (
        resolve_canonical_account_address(
            path=path,
            wallet_get_address=lambda: "wallet-local",
            managed_state_reader=lambda: {
                "chain_signer_name": "oasyce-agent",
                "chain_signer_address": "oasyce1same",
            },
            signer_inspector=lambda **_: {
                "name": "oasyce-agent",
                "address": "oasyce1same",
                "ready": True,
            },
        )
        == "oasyce1same"
    )


def test_read_account_state_ignores_legacy_derived_fields(tmp_path: Path):
    path = tmp_path / "account.json"
    path.write_text(
        """
        {
          "version": 1,
          "account_address": "oasyce1legacy",
          "account_mode": "attached_readonly",
          "signer_name": "legacy-signer",
          "wallet_address": "wallet-old",
          "wallet_matches_account": true,
          "signer_matches_account": false
        }
        """
    )

    state = read_account_state(path)

    assert state["account_address"] == "oasyce1legacy"
    assert state["account_mode"] == "attached_readonly"
    assert state["signer_name"] == "legacy-signer"
    assert "wallet_address" not in state
    assert "wallet_matches_account" not in state


def test_adopt_account_readonly_without_local_signer(tmp_path: Path):
    path = tmp_path / "account.json"
    auth_path = tmp_path / "device_authorization.json"
    status = adopt_account(
        account_address="oasyce1shared",
        readonly=True,
        path=path,
        authorization_path=auth_path,
        wallet_get_address=lambda: "wallet-local",
        managed_state_reader=lambda: {},
        signer_inspector=lambda **_: {"name": "", "address": "", "ready": False},
        device_id_resolver=lambda: "device-A",
    )

    assert status["account_address"] == "oasyce1shared"
    assert status["account_mode"] == "attached_readonly"
    assert status["can_sign"] is False
    assert status["wallet_address"] == "wallet-local"
    assert status["device_id"] == "device-A"
    assert status["device_authorization_status"] == "readonly"
    assert status["account_origin"] == "joined_existing"


def test_adopt_account_persists_only_explicit_account_intent(tmp_path: Path):
    path = tmp_path / "account.json"
    auth_path = tmp_path / "device_authorization.json"
    adopt_account(
        account_address="oasyce1shared",
        readonly=True,
        path=path,
        authorization_path=auth_path,
        wallet_get_address=lambda: "wallet-local",
        managed_state_reader=lambda: {},
        signer_inspector=lambda **_: {"name": "", "address": "", "ready": False},
        device_id_resolver=lambda: "device-A",
    )

    raw = path.read_text()

    assert '"account_address": "oasyce1shared"' in raw
    assert '"account_mode": "attached_readonly"' in raw
    assert '"account_origin": "joined_existing"' in raw
    assert '"wallet_address"' not in raw
    assert '"wallet_matches_account"' not in raw
    assert '"signer_matches_account"' not in raw

    device_auth = read_device_authorization(auth_path)
    assert device_auth["device_id"] == "device-A"
    assert device_auth["account_address"] == "oasyce1shared"
    assert device_auth["authorization_status"] == "readonly"


def test_adopt_account_requires_matching_signer_for_write_access(tmp_path: Path):
    path = tmp_path / "account.json"
    with pytest.raises(AccountStateError):
        adopt_account(
            account_address="oasyce1wanted",
            signer_name="oasyce-agent",
            readonly=False,
            path=path,
            authorization_path=tmp_path / "device_authorization.json",
            wallet_get_address=lambda: "wallet-local",
            managed_state_reader=lambda: {
                "chain_signer_name": "oasyce-agent",
                "chain_signer_address": "oasyce1different",
            },
            signer_inspector=lambda **_: {
                "name": "oasyce-agent",
                "address": "oasyce1different",
                "ready": True,
            },
            device_id_resolver=lambda: "device-A",
        )


def test_adopt_account_signing_mode_uses_local_signer(tmp_path: Path):
    path = tmp_path / "account.json"
    auth_path = tmp_path / "device_authorization.json"
    status = adopt_account(
        signer_name="oasyce-agent",
        readonly=False,
        path=path,
        authorization_path=auth_path,
        wallet_get_address=lambda: "wallet-local",
        managed_state_reader=lambda: {
            "chain_signer_name": "oasyce-agent",
            "chain_signer_address": "oasyce1shared",
        },
        signer_inspector=lambda **_: {
            "name": "oasyce-agent",
            "address": "oasyce1shared",
            "ready": True,
        },
        device_id_resolver=lambda: "device-A",
    )

    assert status["account_address"] == "oasyce1shared"
    assert status["account_mode"] == "managed_local"
    assert status["can_sign"] is True
    assert status["device_authorization_status"] == "active"
    assert status["account_origin"] == "joined_existing"


def test_configure_bootstrap_account_clears_stale_attach_override(tmp_path: Path):
    path = tmp_path / "account.json"
    adopt_account(
        account_address="oasyce1shared",
        readonly=True,
        path=path,
        authorization_path=tmp_path / "device_authorization.json",
        wallet_get_address=lambda: "wallet-local",
        managed_state_reader=lambda: {},
        signer_inspector=lambda **_: {"name": "", "address": "", "ready": False},
        device_id_resolver=lambda: "device-A",
    )

    configure_bootstrap_account(
        wallet_address="wallet-local",
        chain_signer={"name": "oasyce-agent", "address": "oasyce1primary"},
        path=path,
        authorization_path=tmp_path / "device_authorization.json",
    )
    status = build_account_status(
        path=path,
        authorization_path=tmp_path / "device_authorization.json",
        wallet_get_address=lambda: "wallet-local",
        managed_state_reader=lambda: {
            "chain_signer_name": "oasyce-agent",
            "chain_signer_address": "oasyce1primary",
            "auto_update": True,
        },
        signer_inspector=lambda **_: {
            "name": "oasyce-agent",
            "address": "oasyce1primary",
            "ready": True,
        },
        device_id_resolver=lambda: "device-A",
    )

    assert status["account_address"] == "oasyce1primary"
    assert status["account_mode"] == "managed_local"
    assert status["can_sign"] is True
    assert status["account_origin"] == ""


def test_build_account_status_marks_expired_device_authorization(tmp_path: Path):
    path = tmp_path / "account.json"
    auth_path = tmp_path / "device_authorization.json"
    adopt_account(
        signer_name="oasyce-agent",
        readonly=False,
        path=path,
        authorization_path=auth_path,
        authorization_expires_at=1.0,
        wallet_get_address=lambda: "wallet-local",
        managed_state_reader=lambda: {
            "chain_signer_name": "oasyce-agent",
            "chain_signer_address": "oasyce1shared",
        },
        signer_inspector=lambda **_: {
            "name": "oasyce-agent",
            "address": "oasyce1shared",
            "ready": True,
        },
        device_id_resolver=lambda: "device-A",
    )

    status = build_account_status(
        path=path,
        authorization_path=auth_path,
        wallet_get_address=lambda: "wallet-local",
        managed_state_reader=lambda: {
            "chain_signer_name": "oasyce-agent",
            "chain_signer_address": "oasyce1shared",
        },
        signer_inspector=lambda **_: {
            "name": "oasyce-agent",
            "address": "oasyce1shared",
            "ready": True,
        },
        device_id_resolver=lambda: "device-A",
    )

    assert status["device_authorization_status"] == "expired"
    assert status["can_sign"] is False


def test_build_account_status_detects_copied_device_authorization(tmp_path: Path):
    path = tmp_path / "account.json"
    auth_path = tmp_path / "device_authorization.json"
    adopt_account(
        signer_name="oasyce-agent",
        readonly=False,
        path=path,
        authorization_path=auth_path,
        wallet_get_address=lambda: "wallet-local",
        managed_state_reader=lambda: {
            "chain_signer_name": "oasyce-agent",
            "chain_signer_address": "oasyce1shared",
        },
        signer_inspector=lambda **_: {
            "name": "oasyce-agent",
            "address": "oasyce1shared",
            "ready": True,
        },
        device_id_resolver=lambda: "device-A",
    )

    status = build_account_status(
        path=path,
        authorization_path=auth_path,
        wallet_get_address=lambda: "wallet-local",
        managed_state_reader=lambda: {
            "chain_signer_name": "oasyce-agent",
            "chain_signer_address": "oasyce1shared",
        },
        signer_inspector=lambda **_: {
            "name": "oasyce-agent",
            "address": "oasyce1shared",
            "ready": True,
        },
        device_id_resolver=lambda: "device-B",
    )

    assert status["device_matches_authorization"] is False
    assert status["can_sign"] is False


def test_revoke_device_authorization_disables_signing(tmp_path: Path):
    path = tmp_path / "account.json"
    auth_path = tmp_path / "device_authorization.json"
    adopt_account(
        signer_name="oasyce-agent",
        readonly=False,
        path=path,
        authorization_path=auth_path,
        wallet_get_address=lambda: "wallet-local",
        managed_state_reader=lambda: {
            "chain_signer_name": "oasyce-agent",
            "chain_signer_address": "oasyce1shared",
        },
        signer_inspector=lambda **_: {
            "name": "oasyce-agent",
            "address": "oasyce1shared",
            "ready": True,
        },
        device_id_resolver=lambda: "device-A",
    )

    status = revoke_device_authorization(
        path=path,
        authorization_path=auth_path,
        device_id_resolver=lambda: "device-A",
    )

    assert status["device_authorization_status"] == "revoked"
    assert status["can_sign"] is False
