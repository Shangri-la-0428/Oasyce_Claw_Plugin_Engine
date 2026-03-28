from __future__ import annotations

import importlib
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import requests

from oasyce.client import Oasyce
from oasyce.services.public_beta_signer import inspect_public_beta_signer

DEFAULT_PUBLIC_BETA_NODE_URL = "http://localhost:8420"
DEFAULT_PUBLIC_BETA_REST_URL = "http://47.93.32.88:1317"
DEFAULT_PUBLIC_BETA_RPC_URL = "http://47.93.32.88:26657"


def _normalize_rest_url(rest_url: Optional[str]) -> str:
    return (
        rest_url
        or os.getenv("OASYCE_PUBLIC_BETA_REST_URL")
        or os.getenv("OASYCE_CHAIN_REST_URL")
        or DEFAULT_PUBLIC_BETA_REST_URL
    ).rstrip("/")


def _normalize_rpc_url(rpc_url: Optional[str]) -> str:
    return (
        rpc_url
        or os.getenv("OASYCE_PUBLIC_BETA_RPC_URL")
        or os.getenv("OASYCE_CHAIN_RPC")
        or DEFAULT_PUBLIC_BETA_RPC_URL
    ).rstrip("/")


def _add_check(
    checks: list[dict[str, Any]],
    name: str,
    status: str,
    detail: str,
    *,
    data: Optional[dict[str, Any]] = None,
) -> None:
    item: dict[str, Any] = {"name": name, "status": status, "detail": detail}
    if data:
        item["data"] = data
    checks.append(item)


def _http_get_json(url: str, timeout: int = 5) -> dict[str, Any]:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def run_public_beta_doctor(
    *,
    rest_url: Optional[str] = None,
    rpc_url: Optional[str] = None,
    import_optional_module: Callable[[str], Any] = importlib.import_module,
    wallet_exists: Optional[Callable[[], bool]] = None,
    managed_install_reader: Optional[Callable[[], Dict[str, Any]]] = None,
    network_mode_reader: Optional[Callable[[], Any]] = None,
    security_reader: Optional[Callable[[Any], Dict[str, Any]]] = None,
    which: Callable[[str], Optional[str]] = shutil.which,
    find_oasyced: Optional[Callable[[], Optional[str]]] = None,
    http_get_json: Callable[[str, int], Dict[str, Any]] = _http_get_json,
    signer_inspector: Callable[..., Dict[str, Any]] = inspect_public_beta_signer,
) -> Dict[str, Any]:
    from oasyce.chain_client import _find_oasyced
    from oasyce.config import get_network_mode, get_security
    from oasyce.identity import Wallet
    from oasyce.update_manager import read_managed_install_state

    checks: list[dict[str, Any]] = []
    errors = 0
    warnings = 0
    target_rest_url = _normalize_rest_url(rest_url)
    target_rpc_url = _normalize_rpc_url(rpc_url)

    def _check(name: str, status: str, detail: str) -> None:
        nonlocal errors, warnings
        if status == "error":
            errors += 1
        elif status == "warning":
            warnings += 1
        _add_check(checks, name, status, detail)

    mode = (network_mode_reader or get_network_mode)()
    if getattr(mode, "name", str(mode)) == "TESTNET":
        _check("Network mode", "ok", "OASYCE_NETWORK_MODE=testnet")
    else:
        _check("Network mode", "error", "Set OASYCE_NETWORK_MODE=testnet")

    security = (security_reader or get_security)(mode)
    if security.get("allow_local_fallback") is False:
        _check("Strict chain mode", "ok", "Local fallback disabled")
    else:
        _check("Strict chain mode", "error", "Enable strict chain mode for public beta")

    if (wallet_exists or Wallet.exists)():
        _check("Wallet", "ok", "Wallet exists")
    else:
        _check("Wallet", "error", "Missing wallet — run `oas bootstrap`")

    managed_state = (managed_install_reader or read_managed_install_state)()
    if managed_state.get("auto_update") and managed_state.get("installed_via_bootstrap"):
        _check("Managed install", "ok", "Auto-update enabled via bootstrap")
    else:
        _check("Managed install", "error", "Run `oas bootstrap` to enable managed updates")

    try:
        import_optional_module("datavault")
        _check("DataVault module", "ok", "Importable")
    except ImportError:
        _check("DataVault module", "error", "Missing Python module `datavault`")

    if which("datavault"):
        _check("DataVault CLI", "ok", "CLI on PATH")
    else:
        _check("DataVault CLI", "error", "Missing `datavault` CLI on PATH")

    if (find_oasyced or _find_oasyced)():
        _check("Chain signer CLI", "ok", "`oasyced` available")
    else:
        _check(
            "Chain signer CLI", "error", "Missing `oasyced` needed for strict-chain transactions"
        )

    signer = signer_inspector(rest_url=target_rest_url, find_oasyced=find_oasyced)
    if signer.get("key_exists"):
        _check(
            "Chain signer key",
            "ok",
            f"{signer['name']} -> {str(signer.get('address', ''))[:20]}...",
        )
    else:
        _check("Chain signer key", "error", "Run `oas bootstrap` to create the chain signer key")
    if signer.get("ready"):
        balance_oas = int(signer.get("balance_uoas", 0)) / 1e8
        _check("Chain signer account", "ok", f"Signer funded on testnet ({balance_oas:.2f} OAS)")
    else:
        _check(
            "Chain signer account",
            "error",
            "Run `oas bootstrap` in testnet mode so the signer is funded on public beta",
        )

    try:
        payload = http_get_json(f"{target_rpc_url}/status", timeout=5)
        node_info = payload.get("result", {}).get("node_info", {})
        if node_info.get("network") == "oasyce-testnet-1":
            _check("Public chain RPC", "ok", f"{target_rpc_url}/status reachable")
        else:
            _check("Public chain RPC", "error", "Unexpected network from signer RPC endpoint")
    except Exception as exc:
        _check("Public chain RPC", "error", f"Unreachable: {exc}")

    try:
        payload = http_get_json(f"{target_rest_url}/health", timeout=5)
        if payload.get("chain_id") == "oasyce-testnet-1":
            _check("Public chain health", "ok", f"{target_rest_url}/health reachable")
        else:
            _check("Public chain health", "error", "Unexpected chain_id from public endpoint")
    except Exception as exc:
        _check("Public chain health", "error", f"Unreachable: {exc}")

    try:
        payload = http_get_json(f"{target_rest_url}/oasyce/onboarding/v1/params", timeout=5)
        params = payload.get("params", {})
        if {"airdrop_amount", "pow_difficulty"} <= set(params):
            _check("Onboarding params", "ok", "Public onboarding params reachable")
        else:
            _check("Onboarding params", "error", "Public onboarding params incomplete")
    except Exception as exc:
        _check("Onboarding params", "error", f"Unreachable: {exc}")

    return {
        "scope": "public_beta",
        "rest_url": target_rest_url,
        "rpc_url": target_rpc_url,
        "status": "error" if errors > 0 else ("warning" if warnings > 0 else "ok"),
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }


def _write_smoke_asset(smoke_dir: Path, trace_prefix: str) -> Path:
    smoke_dir.mkdir(parents=True, exist_ok=True)
    path = smoke_dir / f"{trace_prefix}.txt"
    path.write_text(
        "\n".join(
            [
                "oasyce public beta smoke asset",
                f"trace_prefix={trace_prefix}",
                f"generated_at={int(time.time())}",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _resolve_wallet_actor(fallback: str) -> str:
    try:
        from oasyce.identity import Wallet

        if Wallet.exists():
            wallet = Wallet.load()
            if getattr(wallet, "address", ""):
                return str(wallet.address)
    except Exception:
        pass
    return fallback


def run_public_beta_smoke(
    *,
    base_url: str = DEFAULT_PUBLIC_BETA_NODE_URL,
    rest_url: Optional[str] = None,
    rpc_url: Optional[str] = None,
    asset_id: Optional[str] = None,
    owner: str = "beta-smoke-owner",
    buyer: str = "beta-smoke-buyer",
    amount: float = 0.05,
    trace_prefix: Optional[str] = None,
    portfolio_wait_seconds: int = 8,
    doctor_runner: Optional[Callable[..., Dict[str, Any]]] = None,
    signer_inspector: Callable[..., Dict[str, Any]] = inspect_public_beta_signer,
    client_cls: type[Oasyce] = Oasyce,
    smoke_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    from oasyce.config import Config

    checks: list[dict[str, Any]] = []
    errors = 0
    warnings = 0
    created_asset = False
    local_asset_id = asset_id or ""
    local_trace_prefix = trace_prefix or f"beta-smoke-{int(time.time())}"
    target_rest_url = _normalize_rest_url(rest_url)
    target_rpc_url = _normalize_rpc_url(rpc_url)
    node_url = base_url.rstrip("/")
    signer = signer_inspector(rest_url=target_rest_url)
    default_signer_address = str(signer.get("address") or "").strip()
    resolved_owner = (
        default_signer_address
        if owner == "beta-smoke-owner" and default_signer_address
        else _resolve_wallet_actor(owner)
    )
    resolved_buyer = (
        default_signer_address
        if buyer == "beta-smoke-buyer" and default_signer_address
        else _resolve_wallet_actor(buyer)
    )

    def _check(
        name: str, status: str, detail: str, *, data: Optional[dict[str, Any]] = None
    ) -> None:
        nonlocal errors, warnings
        if status == "error":
            errors += 1
        elif status == "warning":
            warnings += 1
        _add_check(checks, name, status, detail, data=data)

    doctor = (doctor_runner or run_public_beta_doctor)(
        rest_url=target_rest_url,
        rpc_url=target_rpc_url,
    )
    if doctor.get("status") == "ok":
        _check("Doctor gate", "ok", "Public beta doctor passed")
    else:
        _check("Doctor gate", "error", "Doctor must pass before running smoke", data=doctor)
        return {
            "scope": "public_beta_smoke",
            "base_url": node_url,
            "rest_url": target_rest_url,
            "rpc_url": target_rpc_url,
            "status": "error",
            "errors": errors,
            "warnings": warnings,
            "checks": checks,
            "doctor": doctor,
            "asset_id": local_asset_id,
            "created_asset": created_asset,
            "trace_prefix": local_trace_prefix,
        }

    try:
        client = client_cls(node_url)
        client.status()
        _check("Local node API", "ok", f"{node_url} reachable")

        if not local_asset_id:
            asset_root = smoke_dir or (Path(Config.from_env().data_dir) / "smoke")
            asset_path = _write_smoke_asset(asset_root, local_trace_prefix)
            register_trace = f"{local_trace_prefix}-register"
            register = client.register(
                str(asset_path),
                resolved_owner,
                tags="beta-smoke,agent",
                price_model="auto",
                machine=True,
                trace_id=register_trace,
            )
            if not register.get("ok"):
                raise RuntimeError(f"register failed: {register.get('error', 'unknown error')}")
            local_asset_id = str(register.get("data", {}).get("asset_id", "")).strip()
            if not local_asset_id:
                raise RuntimeError("register succeeded without asset_id")
            created_asset = True
            _check("Register", "ok", f"Asset registered as {local_asset_id}")

        quote_trace = f"{local_trace_prefix}-quote"
        quote = client.quote(local_asset_id, amount=1, machine=True, trace_id=quote_trace)
        if not quote.get("ok"):
            raise RuntimeError(f"quote failed: {quote.get('error', 'unknown error')}")
        _check("Quote", "ok", f"Quoted asset {local_asset_id}")

        buy_trace = f"{local_trace_prefix}-buy"
        idempotency_key = f"{local_trace_prefix}-idem"
        buy = client.buy(
            local_asset_id,
            resolved_buyer,
            amount=amount,
            machine=True,
            trace_id=buy_trace,
            idempotency_key=idempotency_key,
        )
        if not buy.get("ok"):
            raise RuntimeError(f"buy failed: {buy.get('error', 'unknown error')}")
        _check("Buy", "ok", f"Bought {amount} OAS worth of {local_asset_id}")

        replay = client.buy(
            local_asset_id,
            resolved_buyer,
            amount=amount,
            machine=True,
            trace_id=f"{local_trace_prefix}-buy-replay",
            idempotency_key=idempotency_key,
        )
        if not replay.get("ok") or not replay.get("idempotent_replay"):
            raise RuntimeError("buy replay did not return idempotent_replay=true")
        _check("Buy replay", "ok", "Duplicate buy replayed instead of executing twice")

        portfolio_trace = f"{local_trace_prefix}-portfolio"
        portfolio = {}
        deadline = time.time() + max(portfolio_wait_seconds, 0)
        while True:
            portfolio = client.portfolio(resolved_buyer, machine=True, trace_id=portfolio_trace)
            if not portfolio.get("ok"):
                raise RuntimeError(f"portfolio failed: {portfolio.get('error', 'unknown error')}")
            holdings = portfolio.get("data", {}).get("holdings", [])
            if any(item.get("asset_id") == local_asset_id for item in holdings):
                break
            if time.time() >= deadline:
                raise RuntimeError("portfolio does not include the smoke asset")
            time.sleep(1)
        _check("Portfolio", "ok", f"Holding for {local_asset_id} is visible")

        support = client.support_beta(limit=25, transactions_limit=10)
        trace_ids = {str(item.get("trace_id", "")).strip() for item in support.get("events", [])}
        expected = {buy_trace}
        if created_asset:
            expected.add(f"{local_trace_prefix}-register")
        if not expected <= trace_ids:
            raise RuntimeError("support trace log is missing one or more smoke trace IDs")
        _check("Support trace", "ok", "Trace IDs visible in support history")
    except Exception as exc:
        _check("Core flow", "error", str(exc))

    return {
        "scope": "public_beta_smoke",
        "base_url": node_url,
        "rest_url": target_rest_url,
        "rpc_url": target_rpc_url,
        "status": "error" if errors > 0 else ("warning" if warnings > 0 else "ok"),
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "doctor": doctor,
        "asset_id": local_asset_id,
        "created_asset": created_asset,
        "trace_prefix": local_trace_prefix,
        "owner": resolved_owner,
        "buyer": resolved_buyer,
    }
