"""Append-only safety event log for functional safety (ISO 26262).

Provides an immutable, durable safety event log with monotonic sequence
numbers and fsync-after-write per Section 6 of functional_safety.md.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from src.common.safety_types import SafetyEvent, SafetyLogSeverity, SafetyState

logger = logging.getLogger(__name__)

DEFAULT_LOG_PATH = "/var/lib/zenoh-master/safety_log.jsonl"
MAX_EVENTS = 10_000


class SafetyLog:
    """Append-only safety event log with guaranteed ordering and durability.

    Requirements (Section 6.1):
    - Immutability: once written, entries cannot be modified or deleted
    - Ordering: monotonically increasing sequence number + timestamp
    - Durability: fsync after every write
    - Retention: last 10,000 events or 7 days
    """

    def __init__(self, path: str | None = None):
        self._path = Path(path) if path else Path(DEFAULT_LOG_PATH)
        self._lock = threading.Lock()
        self._seq = 0
        self._ensure_directory()
        self._recover_sequence()

    def _ensure_directory(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _recover_sequence(self) -> None:
        """Recover the last sequence number from the existing log file."""
        if not self._path.exists():
            return
        try:
            last_line = ""
            with open(self._path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        last_line = line
            if last_line:
                data = json.loads(last_line)
                self._seq = data.get("seq", 0)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to recover safety log sequence: %s", e)

    def log_event(
        self,
        severity: str | SafetyLogSeverity,
        event: str,
        source: str,
        details: dict | None = None,
        safety_state: str | SafetyState = SafetyState.NORMAL,
        dtc: str = "",
    ) -> SafetyEvent:
        """Append a safety event to the log.

        Args:
            severity: SAFETY_CRITICAL, SAFETY_WARNING, or SAFETY_INFO
            event: Event type identifier
            source: Key expression or component that generated the event
            details: Optional event-specific details
            safety_state: Current safety state at time of event
            dtc: Associated DTC code (hex string), if any

        Returns:
            The SafetyEvent that was logged.
        """
        with self._lock:
            self._seq += 1
            entry = SafetyEvent(
                seq=self._seq,
                severity=severity.value if hasattr(severity, "value") else str(severity),
                event=event.value if hasattr(event, "value") else str(event),
                source=source,
                details=details or {},
                safety_state=safety_state.value if hasattr(safety_state, "value") else str(safety_state),
                dtc=dtc,
            )
            self._write_entry(entry)
            self._rotate_if_needed()
            return entry

    def _write_entry(self, entry: SafetyEvent) -> None:
        """Write a single entry with fsync for durability."""
        line = json.dumps(entry.to_dict(), separators=(",", ":")) + "\n"
        fd = os.open(str(self._path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)

    def _rotate_if_needed(self) -> None:
        """Keep only the last MAX_EVENTS entries."""
        if self._seq % 500 != 0:
            return
        try:
            lines = self._read_all_lines()
            if len(lines) > MAX_EVENTS:
                keep = lines[-MAX_EVENTS:]
                with open(self._path, "w") as f:
                    f.writelines(keep)
                    f.flush()
                    os.fsync(f.fileno())
        except OSError as e:
            logger.warning("Failed to rotate safety log: %s", e)

    def _read_all_lines(self) -> list[str]:
        """Read all lines from the log file."""
        if not self._path.exists():
            return []
        with open(self._path, "r") as f:
            return [line for line in f if line.strip()]

    def read_events(self, last_n: int = 100) -> list[SafetyEvent]:
        """Read the last N events from the log.

        Args:
            last_n: Number of most recent events to return.

        Returns:
            List of SafetyEvent objects, ordered oldest-first.
        """
        with self._lock:
            lines = self._read_all_lines()
            selected = lines[-last_n:] if last_n < len(lines) else lines
            events = []
            for line in selected:
                try:
                    data = json.loads(line.strip())
                    events.append(SafetyEvent.from_dict(data))
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("Skipping malformed safety log entry: %s", e)
            return events

    @property
    def current_seq(self) -> int:
        """Current sequence number."""
        return self._seq

    @property
    def path(self) -> Path:
        """Path to the log file."""
        return self._path
