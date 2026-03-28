from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any, Callable, Dict, Optional

from oasyce.config import NetworkMode, get_chain_rest_url, get_network_mode
from oasyce.update_manager import read_managed_install_state, write_managed_install_state

DEFAULT_PUBLIC_BETA_SIGNER_NAME = "oasyce-agent"
DEFAULT_PUBLIC_BETA_FAUCET_URL = "http://47.93.32.88:8080"


class PublicBetaSignerError(RuntimeError):
    """Raised when the public beta chain signer cannot be prepared."""


def _http_get_json(url: str, timeout: int = 5) -> dict[str, Any]:
    import requests

    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _configured_signer_name() -> str:
    state = read_managed_install_state()
    return (
        os.getenv("OASYCE_CHAIN_FROM")
        or str(state.get("chain_signer_name") or "").strip()
        or DEFAULT_PUBLIC_BETA_SIGNER_NAME
    )


def _target_rest_url(rest_url: Optional[str]) -> str:
    if rest_url:
        return rest_url.rstrip("/")
    return get_chain_rest_url(NetworkMode.TESTNET).rstrip("/")


def _target_faucet_url(faucet_url: Optional[str]) -> str:
    return (
        faucet_url or os.getenv("OASYCE_TESTNET_FAUCET_URL") or DEFAULT_PUBLIC_BETA_FAUCET_URL
    ).rstrip("/")


def _run_oasyced(
    args: list[str],
    *,
    timeout: int = 30,
    find_oasyced: Optional[Callable[[], Optional[str]]] = None,
) -> dict[str, Any]:
    from oasyce.chain_client import _find_oasyced

    binary = (find_oasyced or _find_oasyced)()
    if not binary:
        raise PublicBetaSignerError("Missing `oasyced` needed for public beta chain signing")

    result = subprocess.run(
        [binary] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = result.stdout.strip() or result.stderr.strip()
    if result.returncode != 0:
        raise PublicBetaSignerError(output or "oasyced command failed")
    if not output:
        return {}
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return {"raw_output": output}


def inspect_public_beta_signer(
    *,
    signer_name: Optional[str] = None,
    rest_url: Optional[str] = None,
    find_oasyced: Optional[Callable[[], Optional[str]]] = None,
    run_oasyced: Optional[Callable[..., dict[str, Any]]] = None,
    http_get_json: Callable[[str, int], dict[str, Any]] = _http_get_json,
) -> Dict[str, Any]:
    target_name = signer_name or _configured_signer_name()
    target_rest_url = _target_rest_url(rest_url)
    runner = run_oasyced or _run_oasyced

    address = ""
    key_exists = False
    key_error = ""
    try:
        raw = runner(
            ["keys", "show", target_name, "-a", "--keyring-backend", "test"],
            find_oasyced=find_oasyced,
        )
        address = str(raw.get("raw_output", "") or "").strip()
        if not address and isinstance(raw, dict):
            address = str(raw.get("address", "")).strip()
        key_exists = bool(address)
    except PublicBetaSignerError as exc:
        key_error = str(exc)

    account_exists = False
    balance_uoas = 0
    account_error = ""
    if address:
        try:
            http_get_json(f"{target_rest_url}/cosmos/auth/v1beta1/accounts/{address}", timeout=5)
            account_exists = True
        except Exception as exc:
            account_error = str(exc)
        try:
            payload = http_get_json(
                f"{target_rest_url}/cosmos/bank/v1beta1/balances/{address}/by_denom?denom=uoas",
                timeout=5,
            )
            balance_uoas = int(payload.get("balance", {}).get("amount", "0") or "0")
        except Exception:
            try:
                payload = http_get_json(
                    f"{target_rest_url}/cosmos/bank/v1beta1/balances/{address}", timeout=5
                )
                balances = payload.get("balances", [])
                for item in balances:
                    if item.get("denom") == "uoas":
                        balance_uoas = int(item.get("amount", "0") or "0")
                        break
            except Exception as exc:
                if not account_error:
                    account_error = str(exc)

    return {
        "name": target_name,
        "address": address,
        "key_exists": key_exists,
        "key_error": key_error,
        "account_exists": account_exists,
        "balance_uoas": balance_uoas,
        "ready": key_exists and account_exists and balance_uoas > 0,
        "rest_url": target_rest_url,
        "account_error": account_error,
    }


def ensure_public_beta_signer(
    *,
    signer_name: Optional[str] = None,
    rest_url: Optional[str] = None,
    faucet_url: Optional[str] = None,
    wait_seconds: int = 10,
    find_oasyced: Optional[Callable[[], Optional[str]]] = None,
    run_oasyced: Optional[Callable[..., dict[str, Any]]] = None,
    http_get_json: Callable[[str, int], dict[str, Any]] = _http_get_json,
    http_get: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    target_name = signer_name or _configured_signer_name()
    target_rest_url = _target_rest_url(rest_url)
    target_faucet_url = _target_faucet_url(faucet_url)
    runner = run_oasyced or _run_oasyced

    created = False
    claimed_faucet = False
    inspect = inspect_public_beta_signer(
        signer_name=target_name,
        rest_url=target_rest_url,
        find_oasyced=find_oasyced,
        run_oasyced=runner,
        http_get_json=http_get_json,
    )
    if not inspect["key_exists"]:
        created_raw = runner(
            ["keys", "add", target_name, "--keyring-backend", "test", "--output", "json"],
            find_oasyced=find_oasyced,
        )
        address = str(created_raw.get("address", "")).strip()
        if not address:
            raise PublicBetaSignerError("Created chain signer key but could not resolve address")
        created = True
        inspect = inspect_public_beta_signer(
            signer_name=target_name,
            rest_url=target_rest_url,
            find_oasyced=find_oasyced,
            run_oasyced=runner,
            http_get_json=http_get_json,
        )

    if inspect["address"] and (not inspect["account_exists"] or inspect["balance_uoas"] <= 0):
        try:
            request_get = http_get
            if request_get is None:
                import requests

                request_get = requests.get

            request_get(
                f"{target_faucet_url}/faucet",
                params={"address": inspect["address"]},
                timeout=5,
            ).raise_for_status()
        except Exception as exc:
            raise PublicBetaSignerError(f"Public beta faucet request failed: {exc}") from exc
        claimed_faucet = True

        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            inspect = inspect_public_beta_signer(
                signer_name=target_name,
                rest_url=target_rest_url,
                find_oasyced=find_oasyced,
                run_oasyced=runner,
                http_get_json=http_get_json,
            )
            if inspect["account_exists"] and inspect["balance_uoas"] > 0:
                break
            time.sleep(1)

    if not inspect["ready"]:
        raise PublicBetaSignerError(
            inspect.get("account_error")
            or inspect.get("key_error")
            or "Public beta signer is still not ready after preparation"
        )

    state = write_managed_install_state(
        chain_signer_name=inspect["name"],
        chain_signer_address=inspect["address"],
        chain_signer_ready=True,
    )

    return {
        **inspect,
        "created": created,
        "claimed_faucet": claimed_faucet,
        "managed_state": state,
    }


def public_beta_bootstrap_required() -> bool:
    return get_network_mode() == NetworkMode.TESTNET
