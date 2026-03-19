"""Node event monitor — structured logging for diagnostics."""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class NodeEvent:
    timestamp: float = field(default_factory=time.time)
    event_type: str = (
        ""  # peer_discovered, peer_lost, msg_sent, msg_received, msg_dropped, consensus_reached, consensus_failed, error
    )
    detail: str = ""
    peer: str = ""  # peer address or node_id
    msg_id: str = ""
    msg_type: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


class NodeMonitor:
    """Collects and stores structured events for a node."""

    def __init__(self, max_events: int = 10000, log_dir: Optional[str] = None) -> None:
        self.events: deque = deque(maxlen=max_events)
        self.stats: Dict[str, int] = {
            "msgs_sent": 0,
            "msgs_received": 0,
            "msgs_dropped": 0,
            "peers_discovered": 0,
            "peers_lost": 0,
            "consensus_reached": 0,
            "consensus_failed": 0,
            "errors": 0,
        }
        self._start_time = time.time()
        self._log_file = None
        if log_dir:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            self._log_file = open(os.path.join(log_dir, "node_events.jsonl"), "a")

    def record(
        self,
        event_type: str,
        detail: str = "",
        peer: str = "",
        msg_id: str = "",
        msg_type: str = "",
        **extra: Any,
    ) -> None:
        evt = NodeEvent(
            event_type=event_type,
            detail=detail,
            peer=peer,
            msg_id=msg_id,
            msg_type=msg_type,
            extra=extra,
        )
        self.events.append(evt)

        # Update stats
        stat_key = event_type
        if stat_key in self.stats:
            self.stats[stat_key] += 1
        elif event_type == "error":
            self.stats["errors"] += 1

        # Write to log file if configured
        if self._log_file:
            self._log_file.write(json.dumps(asdict(evt)) + "\n")
            self._log_file.flush()

        logger.debug("Event: %s — %s", event_type, detail)

    def get_recent(self, count: int = 50, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        events = list(self.events)
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return [asdict(e) for e in events[-count:]]

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self.stats,
            "uptime_seconds": round(time.time() - self._start_time, 1),
            "event_buffer_size": len(self.events),
        }

    def get_errors(self, count: int = 20) -> List[Dict[str, Any]]:
        errors = [e for e in self.events if e.event_type in ("error", "msgs_dropped")]
        return [asdict(e) for e in errors[-count:]]

    def close(self) -> None:
        if self._log_file:
            self._log_file.close()
            self._log_file = None
