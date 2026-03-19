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
