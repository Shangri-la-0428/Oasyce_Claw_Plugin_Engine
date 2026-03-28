from __future__ import annotations

import importlib.util
from typing import Any, Callable, Dict, Optional

from oasyce import update_manager as _update_manager


def get_account_status_payload(
    *,
    status_reader: Optional[Callable[[], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if status_reader is None:
        from oasyce.account_state import build_account_status

        status_reader = build_account_status
    return status_reader()


def verify_account_payload(
    *,
    require_signing: bool = False,
    status_reader: Optional[Callable[[], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    status = get_account_status_payload(status_reader=status_reader)
    issues: list[str] = []
    warnings: list[str] = []

    if not status.get("configured"):
        issues.append("No canonical account is configured on this device.")
    if status.get("configured") and not status.get("account_address"):
        issues.append("Canonical account configuration is missing an account address.")
    if require_signing and not status.get("can_sign"):
        issues.append("This device cannot sign as the canonical account.")
    if status.get("signer_name") and not status.get("signer_matches_account"):
        issues.append("Local signer does not match the canonical account.")
    if status.get("wallet_present") and not status.get("wallet_matches_account"):
        warnings.append("Local wallet address differs from the canonical account.")

    return {
        "ok": not issues,
        "account_address": status.get("account_address", ""),
        "account_mode": status.get("account_mode", "unconfigured"),
        "can_sign": bool(status.get("can_sign")),
        "issues": issues,
        "warnings": warnings,
        "status": status,
    }


def adopt_account_payload(
    *,
    account_address: Optional[str] = None,
    signer_name: Optional[str] = None,
    readonly: bool = False,
    adopter: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if adopter is None:
        from oasyce.account_state import adopt_account

        adopter = adopt_account
    status = adopter(
        account_address=account_address,
        signer_name=signer_name,
        readonly=readonly,
    )
    return {"ok": True, **status}


def join_device_payload(
    *,
    account_address: str,
    signer_name: Optional[str] = None,
    readonly: bool = False,
    no_update: bool = False,
    check_package_updates: Callable[[], list[dict[str, Any]]],
    upgrade_managed_packages: Callable[[], Any],
    module_spec_finder: Callable[[str], Any] = importlib.util.find_spec,
    which: Callable[[str], Optional[str]],
    adopter: Optional[Callable[..., Dict[str, Any]]] = None,
    verifier: Optional[Callable[..., Dict[str, Any]]] = None,
    bootstrap_runner: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not str(account_address or "").strip():
        return {"ok": False, "error": "Pass --account to join an existing canonical account."}

    adopt_payload = adopt_account_payload(
        account_address=account_address,
        signer_name=signer_name,
        readonly=readonly,
        adopter=adopter,
    )

    if bootstrap_runner is None:
        bootstrap_runner = run_bootstrap
    bootstrap = bootstrap_runner(
        no_update=no_update,
        check_package_updates=check_package_updates,
        upgrade_managed_packages=upgrade_managed_packages,
        module_spec_finder=module_spec_finder,
        which=which,
    )
    if not bootstrap.get("ok"):
        return {
            "ok": False,
            "error": bootstrap.get("error", "bootstrap failed"),
            "adopt": adopt_payload,
            "bootstrap": bootstrap,
        }

    if verifier is None:
        verifier = verify_account_payload
    verify = verifier(require_signing=not readonly)

    status = verify.get("status") or {}
    environment_ready = bool(
        bootstrap.get("datavault_module")
        and bootstrap.get("datavault_cli")
        and status.get("configured")
    )
    write_ready = bool(environment_ready and status.get("can_sign"))
    device_ready = bool(environment_ready and (readonly or write_ready))

    return {
        "ok": bool(verify.get("ok") and device_ready),
        "action": "device_join",
        "readonly": bool(readonly),
        "account_address": str(account_address or "").strip(),
        "environment_ready": environment_ready,
        "write_ready": write_ready,
        "adopt": adopt_payload,
        "bootstrap": bootstrap,
        "verify": verify,
    }


def _prepare_bootstrap_environment(
    *,
    no_update: bool,
    check_package_updates: Callable[[], list[dict[str, Any]]],
    upgrade_managed_packages: Callable[[], Any],
    module_spec_finder: Callable[[str], Any],
    which: Callable[[str], Optional[str]],
) -> Dict[str, Any]:
    packages = check_package_updates()
    if not no_update and any(pkg["latest"] is None for pkg in packages):
        failed = ", ".join(pkg["name"] for pkg in packages if pkg["latest"] is None)
        return {"ok": False, "error": f"Failed to check PyPI for: {failed}"}

    updated = False
    if not no_update and any((not pkg["installed"]) or (not pkg["up_to_date"]) for pkg in packages):
        result = upgrade_managed_packages()
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr or "upgrade failed"}
        updated = True
        packages = check_package_updates()

    managed_state = _update_manager.enable_managed_install(auto_update=True)
    return {
        "ok": True,
        "updated": updated,
        "packages": packages,
        "datavault_module": module_spec_finder("datavault") is not None,
        "datavault_cli": which("datavault") is not None,
        "managed_state": managed_state,
    }


def _resolve_bootstrap_account(
    *,
    mode: Any,
    account_address: Optional[str],
    signer_name: Optional[str],
    readonly: bool,
) -> Dict[str, Any]:
    from oasyce.account_state import (
        AccountStateError,
        adopt_account,
        build_account_status,
        configure_bootstrap_account,
    )
    from oasyce.identity import Wallet
    from oasyce.services.public_beta_signer import (
        PublicBetaSignerError,
        ensure_public_beta_signer,
        public_beta_bootstrap_required,
    )

    explicit_account_attach = bool(account_address or signer_name or readonly)
    if explicit_account_attach:
        account = adopt_account(
            account_address=account_address,
            signer_name=signer_name,
            readonly=readonly,
        )
        return {
            "ok": True,
            "wallet_address": Wallet.get_address(),
            "wallet_created": False,
            "chain_signer": None,
            "account": account,
            "used_existing_account": True,
        }

    existing = build_account_status()
    if existing.get("configured"):
        return {
            "ok": True,
            "wallet_address": existing.get("wallet_address", ""),
            "wallet_created": False,
            "chain_signer": None,
            "account": existing,
            "used_existing_account": True,
        }

    wallet_address = Wallet.get_address()
    wallet_created = False
    if not wallet_address:
        wallet_address = Wallet.create().address
        wallet_created = True

    chain_signer = None
    if public_beta_bootstrap_required() and getattr(mode, "name", str(mode)) == "TESTNET":
        chain_signer = ensure_public_beta_signer()

    configure_bootstrap_account(wallet_address=wallet_address, chain_signer=chain_signer)
    return {
        "ok": True,
        "wallet_address": wallet_address,
        "wallet_created": wallet_created,
        "chain_signer": chain_signer,
        "account": build_account_status(),
        "used_existing_account": False,
    }


def run_bootstrap(
    *,
    no_update: bool = False,
    account_address: Optional[str] = None,
    signer_name: Optional[str] = None,
    readonly: bool = False,
    check_package_updates: Callable[[], list[dict[str, Any]]],
    upgrade_managed_packages: Callable[[], Any],
    module_spec_finder: Callable[[str], Any] = importlib.util.find_spec,
    which: Callable[[str], Optional[str]],
) -> Dict[str, Any]:
    from oasyce.account_state import AccountStateError
    from oasyce.config import NetworkMode, get_network_mode
    from oasyce.services.public_beta_signer import PublicBetaSignerError

    mode = get_network_mode()
    env = _prepare_bootstrap_environment(
        no_update=no_update,
        check_package_updates=check_package_updates,
        upgrade_managed_packages=upgrade_managed_packages,
        module_spec_finder=module_spec_finder,
        which=which,
    )
    if not env.get("ok"):
        return env

    try:
        account_resolution = _resolve_bootstrap_account(
            mode=mode,
            account_address=account_address,
            signer_name=signer_name,
            readonly=readonly,
        )
    except (AccountStateError, PublicBetaSignerError) as exc:
        return {
            "ok": False,
            "error": str(exc),
            "wallet_address": "",
            "wallet_created": False,
            "datavault_module": env.get("datavault_module", False),
            "datavault_cli": env.get("datavault_cli", False),
            "auto_update_enabled": env.get("managed_state", {}).get("auto_update", False),
        }

    wallet_address = str(account_resolution.get("wallet_address") or "")
    wallet_created = bool(account_resolution.get("wallet_created"))
    chain_signer = account_resolution.get("chain_signer")
    account = account_resolution.get("account") or {}
    used_existing_account = bool(account_resolution.get("used_existing_account"))

    ready = bool(env["datavault_module"] and env["datavault_cli"] and account.get("configured"))
    if mode == NetworkMode.TESTNET:
        ready = ready and bool(account.get("can_sign"))
    elif not used_existing_account:
        ready = ready and bool(wallet_address)

    payload: Dict[str, Any] = {
        "ok": True,
        "action": "bootstrap",
        "updated": env["updated"],
        "packages": env["packages"],
        "wallet_address": wallet_address,
        "wallet_created": wallet_created,
        "datavault_module": env["datavault_module"],
        "datavault_cli": env["datavault_cli"],
        "ready": ready,
        "auto_update_enabled": env["managed_state"].get("auto_update", False),
        "used_existing_account": used_existing_account,
        "account": {
            "account_address": account.get("account_address"),
            "account_mode": account.get("account_mode"),
            "signer_name": account.get("signer_name"),
            "signer_address": account.get("signer_address"),
            "wallet_address": account.get("wallet_address"),
            "can_sign": account.get("can_sign"),
        },
    }
    if chain_signer is not None:
        payload["chain_signer"] = {
            "name": chain_signer.get("name"),
            "address": chain_signer.get("address"),
            "created": chain_signer.get("created", False),
            "claimed_faucet": chain_signer.get("claimed_faucet", False),
            "ready": chain_signer.get("ready", False),
        }
    return payload
