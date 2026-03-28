from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from oasyce.update_manager import read_managed_install_state

ACCOUNT_STATE_PATH = Path.home() / ".oasyce" / "account.json"
_SCHEMA_VERSION = 1

_DEFAULT_ACCOUNT_STATE: Dict[str, Any] = {
    "version": _SCHEMA_VERSION,
    "account_address": "",
    "account_mode": "",
    "signer_type": "",
    "signer_name": "",
    "updated_at": 0.0,
}


class AccountStateError(RuntimeError):
    """Raised when the local account configuration is incoherent."""


def _state_path(path: Optional[Path] = None) -> Path:
    return path or ACCOUNT_STATE_PATH


def _wallet_address(
    wallet_get_address: Optional[Callable[[], Optional[str]]] = None,
) -> str:
    if wallet_get_address is None:
        from oasyce.identity import Wallet

        wallet_get_address = Wallet.get_address
    try:
        return str(wallet_get_address() or "").strip()
    except Exception:
        return ""


def _inspect_signer(
    signer_name: str,
    *,
    signer_inspector: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not signer_name:
        return {"name": "", "address": "", "ready": False}
    if signer_inspector is None:
        from oasyce.services.public_beta_signer import inspect_public_beta_signer

        signer_inspector = inspect_public_beta_signer
    try:
        payload = signer_inspector(signer_name=signer_name)
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        return {"name": signer_name, "address": "", "ready": False, "error": str(exc)}
    return {"name": signer_name, "address": "", "ready": False}


def read_account_state(path: Optional[Path] = None) -> Dict[str, Any]:
    target = _state_path(path)
    if not target.exists():
        return dict(_DEFAULT_ACCOUNT_STATE)
    try:
        raw = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError):
        return dict(_DEFAULT_ACCOUNT_STATE)
    state = dict(_DEFAULT_ACCOUNT_STATE)
    for key in _DEFAULT_ACCOUNT_STATE:
        if key in raw:
            state[key] = raw[key]
    state["account_address"] = str(state.get("account_address") or "").strip()
    state["account_mode"] = str(state.get("account_mode") or "").strip()
    state["signer_type"] = str(state.get("signer_type") or "").strip()
    state["signer_name"] = str(state.get("signer_name") or "").strip()
    return state


def write_account_state(path: Optional[Path] = None, **updates: Any) -> Dict[str, Any]:
    state = read_account_state(path)
    for key in _DEFAULT_ACCOUNT_STATE:
        if key in updates:
            state[key] = updates[key]
    state["version"] = _SCHEMA_VERSION
    state["updated_at"] = float(updates.get("updated_at", time.time()))
    target = _state_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(state, indent=2, sort_keys=True))
    return state


def clear_account_state(path: Optional[Path] = None) -> Dict[str, Any]:
    target = _state_path(path)
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    return dict(_DEFAULT_ACCOUNT_STATE)


def build_account_status(
    *,
    path: Optional[Path] = None,
    signer_name: Optional[str] = None,
    wallet_get_address: Optional[Callable[[], Optional[str]]] = None,
    managed_state_reader: Callable[[], Dict[str, Any]] = read_managed_install_state,
    signer_inspector: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    state = read_account_state(path)
    managed_state = managed_state_reader()
    wallet_address = _wallet_address(wallet_get_address)

    resolved_signer_name = (
        str(signer_name or "").strip()
        or str(state.get("signer_name") or "").strip()
        or str(managed_state.get("chain_signer_name") or "").strip()
    )
    signer_info = _inspect_signer(resolved_signer_name, signer_inspector=signer_inspector)
    signer_address = (
        str(signer_info.get("address") or "").strip()
        or str(managed_state.get("chain_signer_address") or "").strip()
    )
    account_address = (
        str(state.get("account_address") or "").strip() or signer_address or wallet_address
    )
    wallet_matches_account = bool(
        wallet_address and account_address and wallet_address == account_address
    )
    signer_matches_account = bool(
        signer_address and account_address and signer_address == account_address
    )

    account_mode = str(state.get("account_mode") or "").strip()
    if not account_mode:
        if account_address and signer_matches_account:
            account_mode = "managed_local"
        elif account_address and wallet_matches_account and not signer_address:
            account_mode = "managed_local"
        elif account_address:
            account_mode = "attached_readonly"
        else:
            account_mode = "unconfigured"

    signer_type = str(state.get("signer_type") or "").strip()
    if not signer_type:
        signer_type = "oasyced_local" if signer_address else "none"

    return {
        "version": _SCHEMA_VERSION,
        "configured": bool(account_address),
        "account_address": account_address,
        "account_mode": account_mode,
        "signer_type": signer_type,
        "signer_name": resolved_signer_name,
        "signer_address": signer_address,
        "signer_ready": bool(signer_info.get("ready")),
        "wallet_address": wallet_address,
        "wallet_present": bool(wallet_address),
        "wallet_matches_account": wallet_matches_account,
        "signer_matches_account": signer_matches_account,
        "can_sign": bool(
            account_mode != "attached_readonly"
            and signer_matches_account
            and (signer_address or signer_info.get("ready"))
        ),
        "managed_chain_signer_name": str(managed_state.get("chain_signer_name") or ""),
        "managed_chain_signer_address": str(managed_state.get("chain_signer_address") or ""),
        "managed_auto_update": bool(managed_state.get("auto_update")),
        "updated_at": float(state.get("updated_at") or 0.0),
    }


def resolve_canonical_account_address(
    *,
    fallback: str = "",
    path: Optional[Path] = None,
    wallet_get_address: Optional[Callable[[], Optional[str]]] = None,
    managed_state_reader: Callable[[], Dict[str, Any]] = read_managed_install_state,
    signer_inspector: Optional[Callable[..., Dict[str, Any]]] = None,
) -> str:
    status = build_account_status(
        path=path,
        wallet_get_address=wallet_get_address,
        managed_state_reader=managed_state_reader,
        signer_inspector=signer_inspector,
    )
    return str(status.get("account_address") or "").strip() or fallback


def adopt_account(
    *,
    account_address: Optional[str] = None,
    signer_name: Optional[str] = None,
    readonly: bool = False,
    path: Optional[Path] = None,
    wallet_get_address: Optional[Callable[[], Optional[str]]] = None,
    managed_state_reader: Callable[[], Dict[str, Any]] = read_managed_install_state,
    signer_inspector: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    managed_state = managed_state_reader()
    wallet_address = _wallet_address(wallet_get_address)
    resolved_signer_name = (
        str(signer_name or "").strip() or str(managed_state.get("chain_signer_name") or "").strip()
    )
    signer_info = _inspect_signer(resolved_signer_name, signer_inspector=signer_inspector)
    signer_address = (
        str(signer_info.get("address") or "").strip()
        or str(managed_state.get("chain_signer_address") or "").strip()
    )
    resolved_account = str(account_address or "").strip() or signer_address or wallet_address
    if not resolved_account:
        raise AccountStateError(
            "Could not resolve an account address. Pass --address or prepare a local signer first."
        )

    if readonly:
        mode = "attached_readonly"
    else:
        if not signer_address:
            raise AccountStateError(
                "Write-capable account attach requires a local signer. Use --readonly or prepare the signer first."
            )
        if resolved_account != signer_address:
            raise AccountStateError(
                "Requested account address does not match the local signer address."
            )
        mode = (
            "managed_local"
            if resolved_signer_name
            and resolved_signer_name == str(managed_state.get("chain_signer_name") or "").strip()
            else "attached_signing"
        )

    write_account_state(
        path=path,
        account_address=resolved_account,
        account_mode=mode,
        signer_type="oasyced_local" if signer_address else "none",
        signer_name=resolved_signer_name,
    )
    return build_account_status(
        path=path,
        wallet_get_address=wallet_get_address,
        managed_state_reader=managed_state_reader,
        signer_inspector=signer_inspector,
    )


def configure_bootstrap_account(
    *,
    wallet_address: str,
    chain_signer: Optional[Dict[str, Any]] = None,
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    # Default bootstrap should not create a second "snapshot account state".
    # It clears any explicit attach override so the canonical account is derived
    # live from the local wallet and managed signer configuration.
    _ = wallet_address, chain_signer
    return clear_account_state(path)
