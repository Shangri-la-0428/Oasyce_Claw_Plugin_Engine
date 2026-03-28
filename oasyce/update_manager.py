from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Iterable, List, Optional

MANAGED_INSTALL_FILE = Path.home() / ".oasyce" / "managed_install.json"
AUTO_UPDATE_INTERVAL_SECONDS = 86400


def _managed_install_file() -> Path:
    return Path.home() / ".oasyce" / "managed_install.json"


def read_managed_install_state() -> dict:
    path = _managed_install_file()
    if not path.exists():
        return {"auto_update": False}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"auto_update": False}


def write_managed_install_state(**updates) -> dict:
    state = read_managed_install_state()
    state.update(updates)
    path = _managed_install_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True))
    return state


def enable_managed_install(auto_update: bool = True) -> dict:
    now = time.time()
    return write_managed_install_state(
        auto_update=auto_update,
        installed_via_bootstrap=True,
        last_bootstrap=now,
        last_auto_update_check=0,
    )


def is_auto_update_enabled() -> bool:
    return bool(read_managed_install_state().get("auto_update"))


def fetch_latest_pypi_version(package_name: str) -> Optional[str]:
    try:
        req = urllib.request.Request(
            f"https://pypi.org/pypi/{package_name}/json",
            headers={"Accept": "application/json", "User-Agent": "oasyce-cli"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            return data.get("info", {}).get("version")
    except Exception:
        return None


def installed_package_version(package_name: str) -> Optional[str]:
    try:
        return version(package_name)
    except PackageNotFoundError:
        return None


def parse_version_tuple(value: Optional[str]):
    if not value:
        return tuple()
    parts: List[object] = []
    for part in value.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(part)
    return tuple(parts)


def check_package_updates(package_names: Iterable[str] = ("oasyce", "odv")) -> List[dict]:
    packages = []
    for package_name in package_names:
        current = installed_package_version(package_name)
        latest = fetch_latest_pypi_version(package_name)
        up_to_date = bool(
            current and latest and parse_version_tuple(latest) <= parse_version_tuple(current)
        )
        packages.append(
            {
                "name": package_name,
                "current": current,
                "latest": latest,
                "installed": current is not None,
                "up_to_date": up_to_date,
            }
        )
    return packages


def update_command_for_agents() -> str:
    return f"{sys.executable} -m pip install --upgrade --upgrade-strategy eager oasyce odv"


def upgrade_managed_packages() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--upgrade-strategy",
            "eager",
            "oasyce",
            "odv",
        ],
        capture_output=True,
        text=True,
    )


def maybe_auto_update_for_cli(
    *,
    module_name: str,
    argv: List[str],
    command_name: Optional[str],
    package_names: Iterable[str] = ("oasyce", "odv"),
) -> bool:
    if not command_name:
        return False
    if command_name in {"bootstrap", "update"}:
        return False
    if os.environ.get("OASYCE_SKIP_AUTO_UPDATE") == "1":
        return False

    state = read_managed_install_state()
    if not state.get("auto_update"):
        return False

    now = time.time()
    last_check = float(state.get("last_auto_update_check", 0) or 0)
    if now - last_check < AUTO_UPDATE_INTERVAL_SECONDS:
        return False

    packages = check_package_updates(package_names)
    state = write_managed_install_state(last_auto_update_check=now, packages=packages)
    if any(pkg["latest"] is None for pkg in packages):
        return False

    needs_update = any((not pkg["installed"]) or (not pkg["up_to_date"]) for pkg in packages)
    if not needs_update:
        return False

    result = upgrade_managed_packages()
    if result.returncode != 0:
        write_managed_install_state(
            last_auto_update_error=result.stderr or "upgrade failed",
            last_auto_update_check=now,
        )
        return False

    write_managed_install_state(
        last_auto_update_error="",
        last_auto_update_check=now,
        last_auto_update_success=now,
        packages=check_package_updates(package_names),
    )

    env = os.environ.copy()
    env["OASYCE_SKIP_AUTO_UPDATE"] = "1"
    os.execvpe(sys.executable, [sys.executable, "-m", module_name, *argv], env)
    return True
