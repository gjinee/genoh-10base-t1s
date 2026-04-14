"""Chain-hash security event log for tamper detection.

Implements an append-only security log where each entry's hash
includes the previous entry's hash, creating a chain that detects
any insertion, deletion, or modification.
See cybersecurity.md Section 8.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from pathlib import Path

from src.common.security_types import SecurityEvent, AlertSeverity, SecurityAction

logger = logging.getLogger(__name__)

DEFAULT_SECURITY_LOG_PATH = "/var/lib/zenoh-master/security_log.jsonl"
GENESIS_HASH = "0" * 64  # SHA-256 of empty / genesis block


class SecurityLog:
    """Append-only security event log with SHA-256 chain hash.

    Each log entry includes a chain_hash field:
      chain_hash[n] = SHA-256(chain_hash[n-1] + content[n])

    This ensures that tampering with any entry breaks the chain
    and is detectable via verify_chain().
    """

    def __init__(self, path: str | None = None):
        self._path = Path(path) if path else Path(DEFAULT_SECURITY_LOG_PATH)
        self._lock = threading.Lock()
        self._seq = 0
        self._last_chain_hash = GENESIS_HASH
        self._ensure_directory()
        self._recover_state()

    def _ensure_directory(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _recover_state(self) -> None:
        """Recover sequence and last chain hash from existing log."""
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
                self._last_chain_hash = data.get("chain_hash", GENESIS_HASH)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to recover security log state: %s", e)

    def log_event(
        self,
        severity: str | AlertSeverity,
        event: str,
        category: str = "SECURITY",
        source_node: str = "",
        source_ip: str = "",
        target_key_expr: str = "",
        action: str | SecurityAction = "",
        ids_rule: str = "",
        details: dict | None = None,
    ) -> SecurityEvent:
        """Append a security event with chain hash.

        Returns:
            The SecurityEvent that was logged.
        """
        with self._lock:
            self._seq += 1
            sev_val = severity.value if hasattr(severity, "value") else str(severity)
            act_val = action.value if hasattr(action, "value") else str(action)

            # Build content for hashing (without chain_hash itself)
            content = json.dumps({
                "seq": self._seq,
                "severity": sev_val,
                "event": event,
                "source_node": source_node,
            }, separators=(",", ":"))

            # Compute chain hash
            chain_input = self._last_chain_hash + content
            chain_hash = hashlib.sha256(chain_input.encode("utf-8")).hexdigest()

            entry = SecurityEvent(
                seq=self._seq,
                severity=sev_val,
                category=category,
                event=event,
                source_node=source_node,
                source_ip=source_ip,
                target_key_expr=target_key_expr,
                action=act_val,
                ids_rule=ids_rule,
                chain_hash=chain_hash,
                details=details or {},
            )

            self._write_entry(entry)
            self._last_chain_hash = chain_hash
            return entry

    def _write_entry(self, entry: SecurityEvent) -> None:
        line = json.dumps(entry.to_dict(), separators=(",", ":")) + "\n"
        fd = os.open(str(self._path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)

    def read_events(self, last_n: int = 100) -> list[SecurityEvent]:
        """Read the last N events from the log."""
        with self._lock:
            lines = self._read_all_lines()
            selected = lines[-last_n:] if last_n < len(lines) else lines
            events = []
            for line in selected:
                try:
                    data = json.loads(line.strip())
                    events.append(SecurityEvent.from_dict(data))
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("Skipping malformed security log entry: %s", e)
            return events

    def verify_chain(self) -> bool:
        """Verify the integrity of the entire chain.

        Returns:
            True if the chain is intact (no tampering detected).
        """
        with self._lock:
            lines = self._read_all_lines()
            prev_hash = GENESIS_HASH

            for line in lines:
                try:
                    data = json.loads(line.strip())
                    stored_hash = data.get("chain_hash", "")

                    # Recompute content hash
                    content = json.dumps({
                        "seq": data["seq"],
                        "severity": data["severity"],
                        "event": data["event"],
                        "source_node": data.get("source", {}).get("node_id", ""),
                    }, separators=(",", ":"))
                    expected_hash = hashlib.sha256(
                        (prev_hash + content).encode("utf-8")
                    ).hexdigest()

                    if stored_hash != expected_hash:
                        logger.error(
                            "Chain hash mismatch at seq %d: expected %s, got %s",
                            data.get("seq"), expected_hash, stored_hash,
                        )
                        return False

                    prev_hash = stored_hash
                except (json.JSONDecodeError, KeyError) as e:
                    logger.error("Chain verification failed: %s", e)
                    return False

            return True

    def _read_all_lines(self) -> list[str]:
        if not self._path.exists():
            return []
        with open(self._path, "r") as f:
            return [line for line in f if line.strip()]

    @property
    def current_seq(self) -> int:
        return self._seq

    @property
    def path(self) -> Path:
        return self._path
