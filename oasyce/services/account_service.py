from __future__ import annotations

import base64
import importlib.util
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from oasyce import update_manager as _update_manager

_DEVICE_BUNDLE_KIND = "oasyce_trusted_device_bundle"
_DEVICE_BUNDLE_VERSION = "1"


def _default_keyring_dir() -> Path:
    return Path.home() / ".oasyced" / "keyring-test"


def _looks_like_thronglets_connection(payload: Dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    thronglets_keys = {
        "owner_account",
        "primary_device_identity",
        "signed_by_device",
        "ttl_hours",
        "expires_at",
    }
    return len(thronglets_keys.intersection(payload.keys())) >= 2


def _validate_device_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(bundle, dict):
        raise RuntimeError("Bundle payload must be a JSON object.")
    if bundle.get("kind") != _DEVICE_BUNDLE_KIND:
        if _looks_like_thronglets_connection(bundle):
            raise RuntimeError(
                "This file is a Thronglets connection file, not an Oasyce device file. "
                "Use the Thronglets join/import flow instead of `oas device join`."
            )
        raise RuntimeError("Bundle is not an Oasyce trusted-device bundle.")
    schema_version = bundle.get("schema_version")
    version = bundle.get("version")
    if schema_version is None and version is None:
        raise RuntimeError("Bundle is missing schema_version.")
    if schema_version is not None and str(schema_version) != _DEVICE_BUNDLE_VERSION:
        raise RuntimeError(
            f"Unsupported bundle schema_version: {schema_version!r}."
        )
    if version is not None and str(version) != _DEVICE_BUNDLE_VERSION:
        raise RuntimeError(f"Unsupported bundle version: {version!r}.")
    return bundle


def _read_device_bundle(bundle_path: str) -> Dict[str, Any]:
    target = Path(bundle_path).expanduser()
    try:
        payload = json.loads(target.read_text())
    except FileNotFoundError as exc:
        raise RuntimeError(f"Bundle not found: {target}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read device bundle: {target}") from exc

    return _validate_device_bundle(payload)


def _write_signer_info_file(
    *,
    signer_name: str,
    signer_info_b64: str,
    keyring_dir: Optional[Path] = None,
) -> str:
    if not signer_name:
        raise RuntimeError("Bundle is missing signer_name.")
    try:
        signer_bytes = base64.b64decode(signer_info_b64.encode("ascii"))
    except Exception as exc:
        raise RuntimeError("Bundle signer payload is invalid.") from exc

    target_dir = keyring_dir or _default_keyring_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{signer_name}.info"
    if target.exists():
        existing = target.read_bytes()
        if existing != signer_bytes:
            raise RuntimeError(
                f"Local signer file already exists with different contents: {target}"
            )
    else:
        target.write_bytes(signer_bytes)
        target.chmod(0o600)
    return str(target)


def _build_device_bundle(
    *,
    readonly: bool = False,
    status_reader: Optional[Callable[[], Dict[str, Any]]] = None,
    keyring_dir: Optional[Path] = None,
    clock: Callable[[], float] = time.time,
) -> Dict[str, Any]:
    status = get_account_status_payload(status_reader=status_reader)
    account_address = str(status.get("account_address") or "").strip()
    if not account_address:
        raise RuntimeError("No canonical account is configured on this device.")

    bundle_mode = "readonly"
    signer_name = ""
    signer_info_b64 = ""
    if not readonly and status.get("can_sign"):
        signer_name = str(status.get("signer_name") or "").strip()
        if not signer_name:
            raise RuntimeError("This device can sign, but no local signer name is configured.")
        signer_info_path = (keyring_dir or _default_keyring_dir()) / f"{signer_name}.info"
        try:
            signer_bytes = signer_info_path.read_bytes()
        except OSError as exc:
            raise RuntimeError(f"Could not read signer info for bundle export: {exc}") from exc
        signer_info_b64 = base64.b64encode(signer_bytes).decode("ascii")
        bundle_mode = "signing"

    return {
        "kind": _DEVICE_BUNDLE_KIND,
        "schema_version": _DEVICE_BUNDLE_VERSION,
        "version": _DEVICE_BUNDLE_VERSION,
        "created_at": float(clock()),
        "account_address": account_address,
        "bundle_mode": bundle_mode,
        "signer_name": signer_name,
        "signer_info_b64": signer_info_b64,
    }


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
    auth_status = str(status.get("device_authorization_status") or "").strip()
    if auth_status == "revoked":
        issues.append("This device authorization has been revoked.")
    elif auth_status == "expired":
        issues.append("This device authorization has expired.")
    if status.get("configured") and not status.get("authorization_matches_account", True):
        issues.append("Trusted device authorization belongs to a different canonical account.")
    if status.get("configured") and not status.get("device_matches_authorization", True):
        issues.append("Trusted device authorization belongs to a different device.")
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
    authorization_expires_at: Optional[float] = None,
    adopter: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if adopter is None:
        from oasyce.account_state import adopt_account

        adopter = adopt_account
    status = adopter(
        account_address=account_address,
        signer_name=signer_name,
        readonly=readonly,
        authorization_expires_at=authorization_expires_at,
    )
    return {"ok": True, **status}


def revoke_device_payload(
    *,
    revoker: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if revoker is None:
        from oasyce.account_state import revoke_device_authorization

        revoker = revoke_device_authorization
    status = revoker()
    return {"ok": True, **status}


def export_device_bundle_payload(
    *,
    output_path: str,
    readonly: bool = False,
    status_reader: Optional[Callable[[], Dict[str, Any]]] = None,
    keyring_dir: Optional[Path] = None,
    clock: Callable[[], float] = time.time,
) -> Dict[str, Any]:
    if not str(output_path or "").strip():
        return {"ok": False, "error": "Pass --output to write the trusted-device bundle."}
    try:
        bundle = _build_device_bundle(
            readonly=readonly,
            status_reader=status_reader,
            keyring_dir=keyring_dir,
            clock=clock,
        )
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}

    target = Path(output_path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(bundle, indent=2, sort_keys=True))
    target.chmod(0o600)
    return {
        "ok": True,
        "output_path": str(target),
        "account_address": bundle["account_address"],
        "bundle_mode": bundle["bundle_mode"],
        "signer_name": bundle["signer_name"],
    }


def export_device_bundle_data_payload(
    *,
    readonly: bool = False,
    status_reader: Optional[Callable[[], Dict[str, Any]]] = None,
    keyring_dir: Optional[Path] = None,
    clock: Callable[[], float] = time.time,
) -> Dict[str, Any]:
    try:
        bundle = _build_device_bundle(
            readonly=readonly,
            status_reader=status_reader,
            keyring_dir=keyring_dir,
            clock=clock,
        )
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "bundle": bundle,
        "account_address": bundle["account_address"],
        "bundle_mode": bundle["bundle_mode"],
        "signer_name": bundle["signer_name"],
    }


def join_device_from_bundle_data_payload(
    *,
    bundle: Dict[str, Any],
    keyring_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    payload = _validate_device_bundle(bundle)
    signer_name = str(payload.get("signer_name") or "").strip()
    bundle_mode = str(payload.get("bundle_mode") or "readonly").strip() or "readonly"
    if signer_name:
        _write_signer_info_file(
            signer_name=signer_name,
            signer_info_b64=str(payload.get("signer_info_b64") or ""),
            keyring_dir=keyring_dir,
        )
    return {
        "ok": True,
        "account_address": str(payload.get("account_address") or "").strip(),
        "signer_name": signer_name,
        "readonly": bundle_mode != "signing",
        "bundle_mode": bundle_mode,
    }


def join_device_from_bundle_payload(
    *,
    bundle_path: str,
    keyring_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    return join_device_from_bundle_data_payload(
        bundle=_read_device_bundle(bundle_path), keyring_dir=keyring_dir
    )


def join_device_payload(
    *,
    account_address: str,
    signer_name: Optional[str] = None,
    readonly: bool = False,
    bundle_path: Optional[str] = None,
    bundle: Optional[Dict[str, Any]] = None,
    authorization_expires_at: Optional[float] = None,
    no_update: bool = False,
    check_package_updates: Callable[[], list[dict[str, Any]]],
    upgrade_managed_packages: Callable[[], Any],
    module_spec_finder: Callable[[str], Any] = importlib.util.find_spec,
    which: Callable[[str], Optional[str]],
    adopter: Optional[Callable[..., Dict[str, Any]]] = None,
    verifier: Optional[Callable[..., Dict[str, Any]]] = None,
    bootstrap_runner: Optional[Callable[..., Dict[str, Any]]] = None,
    bundle_joiner: Optional[Callable[..., Dict[str, Any]]] = None,
    bundle_data_joiner: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    bundle_payload = None
    resolved_account = str(account_address or "").strip()
    resolved_signer_name = str(signer_name or "").strip() or None
    resolved_readonly = bool(readonly)

    if bundle is not None:
        joiner = bundle_data_joiner or join_device_from_bundle_data_payload
        try:
            bundle_payload = joiner(bundle=bundle)
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}
        if not bundle_payload.get("ok"):
            return bundle_payload
        bundle_account = str(bundle_payload.get("account_address") or "").strip()
        bundle_signer_name = str(bundle_payload.get("signer_name") or "").strip()
        if resolved_account and bundle_account and resolved_account != bundle_account:
            return {"ok": False, "error": "Bundle account does not match --account."}
        if (
            resolved_signer_name
            and bundle_signer_name
            and resolved_signer_name != bundle_signer_name
        ):
            return {"ok": False, "error": "Bundle signer does not match --signer-name."}
        resolved_account = resolved_account or bundle_account
        if not resolved_signer_name:
            resolved_signer_name = bundle_signer_name or None
        if not readonly:
            resolved_readonly = bool(bundle_payload.get("readonly"))
    elif str(bundle_path or "").strip():
        joiner = bundle_joiner or join_device_from_bundle_payload
        try:
            bundle_payload = joiner(bundle_path=str(bundle_path).strip())
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}
        if not bundle_payload.get("ok"):
            return bundle_payload
        bundle_account = str(bundle_payload.get("account_address") or "").strip()
        bundle_signer_name = str(bundle_payload.get("signer_name") or "").strip()
        if resolved_account and bundle_account and resolved_account != bundle_account:
            return {"ok": False, "error": "Bundle account does not match --account."}
        if (
            resolved_signer_name
            and bundle_signer_name
            and resolved_signer_name != bundle_signer_name
        ):
            return {"ok": False, "error": "Bundle signer does not match --signer-name."}
        resolved_account = resolved_account or bundle_account
        if not resolved_signer_name:
            resolved_signer_name = bundle_signer_name or None
        if not readonly:
            resolved_readonly = bool(bundle_payload.get("readonly"))

    if not resolved_account:
        return {
            "ok": False,
            "error": "Pass --account or --bundle to join an existing canonical account.",
        }

    adopt_payload = adopt_account_payload(
        account_address=resolved_account,
        signer_name=resolved_signer_name,
        readonly=resolved_readonly,
        authorization_expires_at=authorization_expires_at,
        adopter=adopter,
    )

    if bootstrap_runner is None:
        bootstrap_runner = run_bootstrap
    bootstrap = bootstrap_runner(
        # Device join should never mutate package state implicitly.
        # Bootstrap owns update/install behavior; join only attaches the device.
        no_update=True,
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
    device_ready = bool(environment_ready and (resolved_readonly or write_ready))

    return {
        "ok": bool(verify.get("ok") and device_ready),
        "action": "device_join",
        "readonly": bool(resolved_readonly),
        "account_address": resolved_account,
        "environment_ready": environment_ready,
        "write_ready": write_ready,
        "bundle": bundle_payload,
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
