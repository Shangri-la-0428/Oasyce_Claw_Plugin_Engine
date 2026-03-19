"""Agent Scheduler — autonomous scan/register/trade cycle.

Periodically runs: scan -> classify -> auto-register -> auto-trade.
Uses existing Scanner + ConfirmationInbox with trust levels.
No external dependencies — stdlib only.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from oasyce.services.scanner import AssetScanner, ScanResult
from oasyce.services.inbox import (
    ConfirmationInbox,
    TRUST_MANUAL,
    TRUST_SEMI_AUTO,
    TRUST_FULL_AUTO,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class SchedulerConfig:
    """Configuration for the AgentScheduler."""

    enabled: bool = False
    interval_hours: int = 24
    scan_paths: List[str] = field(default_factory=list)
    auto_register: bool = True
    auto_trade: bool = False
    trade_tags: List[str] = field(default_factory=list)
    trade_max_spend: float = 10.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SchedulerConfig":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)


# ---------------------------------------------------------------------------
# Run result
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    """Result of a single scheduler cycle."""

    timestamp: int = 0
    scan_count: int = 0
    register_count: int = 0
    trade_count: int = 0
    errors: List[str] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# AgentScheduler
# ---------------------------------------------------------------------------


class AgentScheduler:
    """Lightweight periodic scheduler for autonomous agent cycles."""

    def __init__(
        self,
        config: SchedulerConfig,
        scanner: AssetScanner,
        inbox: ConfirmationInbox,
        data_dir: str,
    ) -> None:
        self._config = config
        self._scanner = scanner
        self._inbox = inbox
        self._data_dir = data_dir

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running = False

        # Stats
        self._last_run: Optional[int] = None
        self._next_run: Optional[int] = None
        self._last_result: Optional[RunResult] = None
        self._total_runs = 0
        self._total_registered = 0
        self._total_errors = 0

        # Persistence
        self._config_path = os.path.join(data_dir, "agent_config.json")
        self._db_path = os.path.join(data_dir, "agent_runs.db")
        os.makedirs(data_dir, exist_ok=True)

        self._init_db()
        self._load_config()
        self._load_stats()

    # ── DB ──────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS agent_runs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp  INTEGER NOT NULL,
                scan_count INTEGER NOT NULL DEFAULT 0,
                register_count INTEGER NOT NULL DEFAULT 0,
                trade_count INTEGER NOT NULL DEFAULT 0,
                errors     TEXT NOT NULL DEFAULT '[]',
                duration_ms INTEGER NOT NULL DEFAULT 0
            )"""
        )
        conn.commit()
        conn.close()

    def _record_run(self, result: RunResult) -> None:
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                """INSERT INTO agent_runs
                   (timestamp, scan_count, register_count, trade_count, errors, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    result.timestamp,
                    result.scan_count,
                    result.register_count,
                    result.trade_count,
                    json.dumps(result.errors),
                    result.duration_ms,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.error("Failed to record agent run: %s", exc)

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return recent run history."""
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM agent_runs ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            conn.close()
            return [
                {
                    "id": r["id"],
                    "timestamp": r["timestamp"],
                    "scan_count": r["scan_count"],
                    "register_count": r["register_count"],
                    "trade_count": r["trade_count"],
                    "errors": json.loads(r["errors"]),
                    "duration_ms": r["duration_ms"],
                }
                for r in rows
            ]
        except Exception as exc:
            logger.error("Failed to read agent history: %s", exc)
            return []

    # ── Config persistence ──────────────────────────────────────────────

    def _save_config(self) -> None:
        os.makedirs(self._data_dir, exist_ok=True)
        with open(self._config_path, "w") as f:
            json.dump(self._config.to_dict(), f, indent=2)

    def _load_config(self) -> None:
        if os.path.exists(self._config_path):
            try:
                with open(self._config_path) as f:
                    data = json.load(f)
                self._config = SchedulerConfig.from_dict(data)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not load agent config: %s", exc)

    def _load_stats(self) -> None:
        """Reload cumulative stats from the database."""
        try:
            conn = sqlite3.connect(self._db_path)
            row = conn.execute(
                "SELECT COUNT(*) as cnt, COALESCE(SUM(register_count),0) as regs, "
                "COALESCE(SUM(CASE WHEN errors != '[]' THEN 1 ELSE 0 END),0) as errs "
                "FROM agent_runs"
            ).fetchone()
            conn.close()
            if row:
                self._total_runs = row[0]
                self._total_registered = row[1]
                self._total_errors = row[2]
        except Exception:
            pass

    # ── Public API ──────────────────────────────────────────────────────

    def start(self) -> None:
        """Enable and start the scheduler background thread."""
        with self._lock:
            if self._running:
                return
            self._config.enabled = True
            self._save_config()
            self._running = True
            self._stop_event.clear()
            self._next_run = int(time.time()) + self._config.interval_hours * 3600
            self._thread = threading.Thread(target=self._loop, name="agent-scheduler", daemon=True)
            self._thread.start()
            logger.info("Agent scheduler started (interval=%dh)", self._config.interval_hours)

    def stop(self) -> None:
        """Disable and stop the scheduler."""
        with self._lock:
            self._config.enabled = False
            self._save_config()
            self._running = False
            self._next_run = None
            self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Agent scheduler stopped")

    def run_once(self) -> RunResult:
        """Execute one full cycle (scan -> register -> trade). Thread-safe."""
        t0 = time.time()
        result = RunResult(timestamp=int(t0))
        errors: List[str] = []

        # 1. Scan configured paths
        all_results: List[ScanResult] = []
        with self._lock:
            scan_paths = list(self._config.scan_paths)
            auto_register = self._config.auto_register
            auto_trade = self._config.auto_trade
            trade_tags = list(self._config.trade_tags)
            trade_max_spend = self._config.trade_max_spend

        for path in scan_paths:
            try:
                results = self._scanner.scan_directory(path)
                all_results.extend(results)
            except Exception as exc:
                errors.append(f"scan {path}: {exc}")

        result.scan_count = len(all_results)

        # 2. Push to inbox (auto-approve based on trust level)
        register_count = 0
        if auto_register:
            for sr in all_results:
                if sr.sensitivity == "sensitive":
                    continue
                try:
                    item = self._inbox.add_pending_register(
                        file_path=sr.file_path,
                        suggested_name=sr.suggested_name,
                        suggested_tags=sr.suggested_tags,
                        suggested_description=sr.suggested_description,
                        sensitivity=sr.sensitivity,
                        confidence=sr.confidence,
                    )
                    if item.status == "approved":
                        register_count += 1
                except Exception as exc:
                    errors.append(f"register {sr.file_path}: {exc}")

        result.register_count = register_count

        # 3. Auto-trade (search capabilities matching trade_tags, buy within budget)
        trade_count = 0
        if auto_trade and trade_tags:
            trade_count = self._execute_trades(trade_tags, trade_max_spend, errors)
        result.trade_count = trade_count

        duration_ms = int((time.time() - t0) * 1000)
        result.duration_ms = duration_ms
        result.errors = errors

        # Record and update stats
        self._record_run(result)
        with self._lock:
            self._last_run = result.timestamp
            self._last_result = result
            self._total_runs += 1
            self._total_registered += register_count
            if errors:
                self._total_errors += 1

        logger.info(
            "Agent cycle complete: scanned=%d registered=%d traded=%d errors=%d (%dms)",
            result.scan_count,
            result.register_count,
            result.trade_count,
            len(errors),
            duration_ms,
        )
        return result

    def _execute_trades(self, trade_tags: List[str], max_spend: float, errors: List[str]) -> int:
        """Search for capabilities matching tags and auto-buy within budget.

        This is a best-effort integration point. If the discovery/capability
        subsystems are not available, it gracefully returns 0.
        """
        trade_count = 0
        spent = 0.0
        try:
            from oasyce.services.discovery.engine import DiscoveryEngine

            discovery = DiscoveryEngine(data_dir=self._data_dir)
            candidates = discovery.discover(
                query_tags=trade_tags,
                limit=10,
            )
            for cap in candidates:
                price = getattr(cap, "base_price", 0.0) or 0.0
                if spent + price > max_spend:
                    break
                cap_id = getattr(cap, "capability_id", None)
                if cap_id is None:
                    continue
                # Add as purchase in inbox (trust level controls auto-approve)
                try:
                    item = self._inbox.add_pending_purchase(
                        asset_id=cap_id,
                        price=price,
                        reason=f"auto-trade: tags={','.join(trade_tags)}",
                    )
                    if item.status == "approved":
                        trade_count += 1
                        spent += price
                except Exception as exc:
                    errors.append(f"trade {cap_id}: {exc}")
        except ImportError:
            pass  # Discovery not available
        except Exception as exc:
            errors.append(f"trade discovery: {exc}")
        return trade_count

    def status(self) -> Dict[str, Any]:
        """Return current scheduler status."""
        with self._lock:
            return {
                "running": self._running,
                "last_run": self._last_run,
                "next_run": self._next_run,
                "last_result": self._last_result.to_dict() if self._last_result else None,
                "total_runs": self._total_runs,
                "total_registered": self._total_registered,
                "total_errors": self._total_errors,
                "config": self._config.to_dict(),
            }

    def update_config(self, config: SchedulerConfig) -> None:
        """Update schedule config at runtime. Survives without restart."""
        with self._lock:
            was_enabled = self._config.enabled
            self._config = config
            self._save_config()
            # Recalculate next_run if interval changed and scheduler is running
            if self._running and self._last_run is not None:
                self._next_run = self._last_run + config.interval_hours * 3600
        # If enabled state changed, start or stop
        if config.enabled and not was_enabled:
            self.start()
        elif not config.enabled and was_enabled:
            self.stop()

    def get_config(self) -> SchedulerConfig:
        """Return a copy of the current config."""
        with self._lock:
            return SchedulerConfig.from_dict(self._config.to_dict())

    # ── Background loop ─────────────────────────────────────────────────

    def _loop(self) -> None:
        """Background thread loop. Waits on stop_event with timeout."""
        while not self._stop_event.is_set():
            with self._lock:
                if not self._config.enabled:
                    break
                interval_s = self._config.interval_hours * 3600

            # Wait for interval or stop signal
            signaled = self._stop_event.wait(timeout=interval_s)
            if signaled:
                break  # stop() was called

            with self._lock:
                if not self._config.enabled:
                    break

            try:
                self.run_once()
            except Exception as exc:
                logger.exception("Agent scheduler cycle failed: %s", exc)

            with self._lock:
                if self._running:
                    self._next_run = int(time.time()) + interval_s

        with self._lock:
            self._running = False


# ---------------------------------------------------------------------------
# Convenience: module-level singleton for GUI integration
# ---------------------------------------------------------------------------

_scheduler_instance: Optional[AgentScheduler] = None
_scheduler_lock = threading.Lock()


def get_scheduler(data_dir: Optional[str] = None) -> AgentScheduler:
    """Get or create the module-level AgentScheduler singleton."""
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance is None:
            if data_dir is None:
                data_dir = os.path.join(os.path.expanduser("~"), ".oasyce")
            scanner = AssetScanner()
            inbox = ConfirmationInbox(data_dir=data_dir)
            config = SchedulerConfig()
            _scheduler_instance = AgentScheduler(config, scanner, inbox, data_dir)
        return _scheduler_instance
