"""Architecture enforcement tests.

These tests scan the codebase to verify structural invariants that prevent
the kind of issues found in audit rounds 1-3.

Rules enforced:
1. No WRITE SQL (_conn.execute with UPDATE/DELETE/INSERT) outside storage/
2. No direct SettlementEngine() instantiation outside facade
3. READ-only _conn access is tracked as tech debt (warning, not failure)
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent / "oasyce"

# Dirs that are ALLOWED to use _conn directly
STORAGE_ALLOWLIST = {"storage"}

# SQL write keywords (case-insensitive patterns)
_WRITE_SQL = re.compile(r"(UPDATE|DELETE|INSERT|DROP|ALTER|CREATE)\s", re.IGNORECASE)


def _python_files(base: Path):
    """Yield all .py files under base."""
    for p in base.rglob("*.py"):
        yield p


def _read_lines(path: Path):
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []


class TestNoDirectWriteAccess:
    """No WRITE SQL outside oasyce/storage/.

    WRITE operations (UPDATE/DELETE/INSERT) via _conn.execute MUST go through
    Ledger methods which hold the thread lock and handle commits.
    """

    def test_no_write_sql_outside_storage(self):
        violations = []
        for py in _python_files(ROOT):
            rel = py.relative_to(ROOT)
            if rel.parts[0] in STORAGE_ALLOWLIST:
                continue
            lines = _read_lines(py)
            for i, line in enumerate(lines, 1):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                # Only flag access through _ledger._conn (bypassing Ledger API)
                # Services with their own _conn (e.g., escrow, provider_cache) are fine
                if "_ledger._conn" not in line:
                    continue
                if "_conn.commit" in line or _WRITE_SQL.search(line):
                    violations.append(f"{rel}:{i}: {stripped.strip()}")

        if violations:
            msg = f"Found {len(violations)} direct WRITE SQL outside storage/:\n"
            msg += "\n".join(f"  {v}" for v in violations)
            pytest.fail(msg)


class TestReadOnlySqlDebt:
    """Track READ-only _conn.execute outside storage/ as tech debt.

    These are not blocking but are logged as warnings for gradual migration.
    """

    def test_read_sql_debt_warning(self):
        reads = []
        for py in _python_files(ROOT):
            rel = py.relative_to(ROOT)
            if rel.parts[0] in STORAGE_ALLOWLIST:
                continue
            lines = _read_lines(py)
            for i, line in enumerate(lines, 1):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if "_ledger._conn" in line and not _WRITE_SQL.search(line):
                    reads.append(f"{rel}:{i}")

        if reads:
            warnings.warn(
                f"Tech debt: {len(reads)} READ-only _conn.execute calls "
                f"outside storage/ should migrate to Ledger methods",
                stacklevel=1,
            )


class TestNoDirectEngineInstantiation:
    """Verify SettlementEngine() is not instantiated outside facade and tests."""

    ALLOWED_FILES = {
        "services/facade.py",
        "services/settlement/engine.py",
    }

    def test_no_settlement_engine_instantiation(self):
        pattern = re.compile(r"SettlementEngine\(\)")
        violations = []
        for py in _python_files(ROOT):
            rel = py.relative_to(ROOT)
            rel_str = str(rel)
            if rel_str in self.ALLOWED_FILES:
                continue
            for i, line in enumerate(_read_lines(py), 1):
                if pattern.search(line) and not line.lstrip().startswith("#"):
                    violations.append(f"{rel}:{i}: {line.strip()}")

        if violations:
            msg = f"Found {len(violations)} direct SettlementEngine() outside facade:\n"
            msg += "\n".join(f"  {v}" for v in violations)
            pytest.fail(msg)


class TestFacadeNoDirectSql:
    """Verify facade.py has zero direct _conn access (fully migrated)."""

    def test_facade_clean(self):
        facade = ROOT / "services" / "facade.py"
        violations = []
        for i, line in enumerate(_read_lines(facade), 1):
            if "_conn.execute" in line and not line.lstrip().startswith("#"):
                violations.append(f"facade.py:{i}: {line.strip()}")

        if violations:
            msg = f"Facade has {len(violations)} direct _conn.execute calls:\n"
            msg += "\n".join(f"  {v}" for v in violations)
            pytest.fail(msg)


class TestGuiTransportNoOfficialAssetWrites:
    """GUI transport must not directly mutate official asset metadata.

    Runtime probe-cache updates for `_cached_size/_cached_mtime` are allowed
    for now. Official user-driven asset mutations must route through facade.
    """

    def test_gui_app_no_direct_asset_metadata_write(self):
        app = ROOT / "gui" / "app.py"
        lines = _read_lines(app)
        violations = []
        for i, line in enumerate(lines, 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if (
                "_ledger.update_asset_metadata(" not in line
                and "_ledger.set_asset_metadata(" not in line
            ):
                continue
            window = "\n".join(lines[i - 1 : i + 6])
            if '"_cached_size"' in window and '"_cached_mtime"' in window:
                continue
            violations.append(f"gui/app.py:{i}: {stripped.strip()}")

        if violations:
            msg = "Found direct official asset metadata writes in gui/app.py:\n"
            msg += "\n".join(f"  {v}" for v in violations)
            pytest.fail(msg)


class TestGuiTransportNoDirectStakeWrites:
    """GUI transport must not directly mutate stake state."""

    def test_gui_app_no_direct_stake_write(self):
        app = ROOT / "gui" / "app.py"
        violations = []
        for i, line in enumerate(_read_lines(app), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if "_ledger.update_stake(" in line:
                violations.append(f"gui/app.py:{i}: {stripped.strip()}")

        if violations:
            msg = "Found direct stake writes in gui/app.py:\n"
            msg += "\n".join(f"  {v}" for v in violations)
            pytest.fail(msg)


class TestGuiBuyTransportNoSettlementLookup:
    """GUI buy transport should not inspect settlement state directly."""

    def test_gui_buy_handler_does_not_call_get_settlement(self):
        app = ROOT / "gui" / "app.py"
        lines = _read_lines(app)
        start = None
        end = None

        for i, line in enumerate(lines, 1):
            if 'if path == "/api/buy":' in line:
                start = i
            elif start is not None and 'if path == "/api/sell":' in line:
                end = i
                break

        assert start is not None, "Could not locate /api/buy handler in gui/app.py"
        assert end is not None, "Could not locate /api/sell boundary in gui/app.py"

        violations = []
        for i in range(start, end - 1):
            line = lines[i - 1]
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if "_get_settlement(" in line:
                violations.append(f"gui/app.py:{i}: {stripped.strip()}")

        if violations:
            msg = "Found settlement lookup inside gui buy handler:\n"
            msg += "\n".join(f"  {v}" for v in violations)
            pytest.fail(msg)


class TestGuiRegisterTransportNoDirectBusinessLogic:
    """GUI register transport should not touch skills or ledger directly."""

    def test_gui_register_handler_does_not_call_skills_or_ledger(self):
        app = ROOT / "gui" / "app.py"
        lines = _read_lines(app)
        start = None
        end = None

        for i, line in enumerate(lines, 1):
            if 'if path == "/api/register":' in line:
                start = i
            elif start is not None and 'if path == "/api/register-bundle":' in line:
                end = i
                break

        assert start is not None, "Could not locate /api/register handler in gui/app.py"
        assert end is not None, "Could not locate /api/register-bundle boundary in gui/app.py"

        violations = []
        for i in range(start, end - 1):
            line = lines[i - 1]
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if "_get_skills(" in line or "_ledger" in line:
                violations.append(f"gui/app.py:{i}: {stripped.strip()}")

        if violations:
            msg = "Found direct business logic access inside gui register handler:\n"
            msg += "\n".join(f"  {v}" for v in violations)
            pytest.fail(msg)


class TestGuiRegisterBundleTransportNoDirectBusinessLogic:
    """GUI register-bundle transport should not touch skills or chain bridge directly."""

    def test_gui_register_bundle_handler_is_transport_only(self):
        app = ROOT / "gui" / "app.py"
        lines = _read_lines(app)
        start = None
        end = None

        for i, line in enumerate(lines, 1):
            if 'if path == "/api/register-bundle":' in line:
                start = i
            elif start is not None and 'if path == "/api/re-register":' in line:
                end = i
                break

        assert start is not None, "Could not locate /api/register-bundle handler in gui/app.py"
        assert end is not None, "Could not locate /api/re-register boundary in gui/app.py"

        violations = []
        for i in range(start, end - 1):
            line = lines[i - 1]
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if "_get_skills(" in line or "_ledger" in line or "bridge_register" in line:
                violations.append(f"gui/app.py:{i}: {stripped.strip()}")

        if violations:
            msg = "Found direct business logic access inside gui register-bundle handler:\n"
            msg += "\n".join(f"  {v}" for v in violations)
            pytest.fail(msg)


class TestQueryAssetsNoDeepIntegrityScan:
    """Asset list query should stay cheap and avoid content hashing."""

    def test_query_assets_does_not_open_or_hash_files(self):
        facade = ROOT / "services" / "facade.py"
        lines = _read_lines(facade)
        start = None
        end = None

        for i, line in enumerate(lines, 1):
            if "def query_assets(self)" in line:
                start = i
            elif start is not None and "def query_fingerprints(self" in line:
                end = i
                break

        assert start is not None, "Could not locate query_assets in facade.py"
        assert end is not None, "Could not locate query_fingerprints boundary in facade.py"

        violations = []
        for i in range(start, end - 1):
            line = lines[i - 1]
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if "open(" in line or "sha256" in line or "hashlib" in line:
                violations.append(f"services/facade.py:{i}: {stripped.strip()}")

        if violations:
            msg = "Found deep integrity scan logic inside query_assets:\n"
            msg += "\n".join(f"  {v}" for v in violations)
            pytest.fail(msg)


class TestCliAccountCommandsStayThin:
    """CLI account/bootstrap commands should delegate to service helpers."""

    @staticmethod
    def _function_block(path: Path, start_marker: str, end_marker: str) -> str:
        lines = _read_lines(path)
        start = None
        end = None
        for i, line in enumerate(lines, 1):
            if start is None and line.startswith(start_marker):
                start = i
                continue
            if start is not None and line.startswith(end_marker):
                end = i
                break
        assert start is not None, f"Could not find {start_marker}"
        assert end is not None, f"Could not find {end_marker}"
        return "\n".join(lines[start - 1 : end - 1])

    def test_cmd_bootstrap_does_not_inline_account_or_signer_orchestration(self):
        cli = ROOT / "cli.py"
        block = self._function_block(
            cli, "def cmd_bootstrap(args):", "def cmd_account_status(args):"
        )

        forbidden = [
            "from oasyce.account_state",
            "from oasyce.identity import Wallet",
            "from oasyce.services.public_beta_signer",
            "adopt_account(",
            "build_account_status(",
            "configure_bootstrap_account(",
            "ensure_public_beta_signer(",
            "Wallet.create(",
        ]
        violations = [token for token in forbidden if token in block]
        if violations:
            pytest.fail(
                "cmd_bootstrap should stay transport-thin; found inline orchestration tokens:\n  "
                + "\n  ".join(violations)
            )

    def test_cmd_account_status_and_verify_do_not_read_state_directly(self):
        cli = ROOT / "cli.py"
        block = self._function_block(
            cli, "def cmd_account_status(args):", "def cmd_account_adopt(args):"
        )

        forbidden = [
            "from oasyce.account_state",
            "build_account_status(",
        ]
        violations = [token for token in forbidden if token in block]
        if violations:
            pytest.fail(
                "cmd_account_status/cmd_account_verify should delegate to account_service:\n  "
                + "\n  ".join(violations)
            )

    def test_cmd_device_join_stays_thin(self):
        cli = ROOT / "cli.py"
        block = self._function_block(
            cli, "def cmd_device_join(args):", "def _maybe_check_for_update():"
        )

        forbidden = [
            "from oasyce.account_state",
            "from oasyce.identity import Wallet",
            "from oasyce.services.public_beta_signer",
            "adopt_account(",
            "run_bootstrap(",
            "verify_account_payload(",
        ]
        violations = [token for token in forbidden if token in block]
        if violations:
            pytest.fail(
                "cmd_device_join should delegate to account_service:\n  " + "\n  ".join(violations)
            )
