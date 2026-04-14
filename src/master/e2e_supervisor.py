"""E2E Supervision — per-data_id timeout monitoring and sequence verification.

Manages the E2E receiver state machine (INIT→VALID→TIMEOUT/INVALID→ERROR)
for each data_id and integrates with SafetyManager and DTCManager.
See functional_safety.md Sections 2.4, 2.6.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from src.common.e2e_protection import (
    E2EHeader,
    SequenceChecker,
    e2e_verify,
)
from src.common.safety_types import (
    DTC_CODES,
    E2EStatus,
    FaultType,
    SafetyEventType,
    SafetyLogSeverity,
)

logger = logging.getLogger(__name__)

# Default timeout if not configured per data_id
DEFAULT_DEADLINE_MS = 5000
# Consecutive errors before E2E state → ERROR
ERROR_THRESHOLD = 3


@dataclass
class E2EChannelState:
    """Per-data_id E2E monitoring state."""
    data_id: int
    status: E2EStatus = E2EStatus.INIT
    deadline_ms: int = DEFAULT_DEADLINE_MS
    last_valid_time: float = 0.0
    seq_checker: SequenceChecker = field(default_factory=lambda: SequenceChecker(max_gap=3))
    consecutive_failures: int = 0
    total_received: int = 0
    total_crc_failures: int = 0
    total_seq_errors: int = 0
    total_timeouts: int = 0


class E2ESupervisor:
    """Supervises E2E protection for multiple data_id channels.

    For each registered data_id, monitors:
    - CRC integrity (via e2e_verify)
    - Sequence counter continuity (via SequenceChecker)
    - Reception timeout (deadline_ms)

    Reports faults to SafetyManager and DTCManager when thresholds are exceeded.
    """

    def __init__(
        self,
        safety_manager=None,
        dtc_manager=None,
        safety_log=None,
    ):
        self._safety_manager = safety_manager
        self._dtc_manager = dtc_manager
        self._safety_log = safety_log
        self._channels: dict[int, E2EChannelState] = {}
        self._lock = threading.Lock()
        self._running = False
        self._monitor_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def register_channel(
        self,
        data_id: int,
        deadline_ms: int = DEFAULT_DEADLINE_MS,
        max_seq_gap: int = 3,
    ) -> None:
        """Register a data_id channel for monitoring.

        Args:
            data_id: 16-bit E2E data identifier.
            deadline_ms: Maximum time between messages before timeout.
            max_seq_gap: Maximum allowed sequence counter gap.
        """
        with self._lock:
            self._channels[data_id] = E2EChannelState(
                data_id=data_id,
                deadline_ms=deadline_ms,
                last_valid_time=time.monotonic(),
                seq_checker=SequenceChecker(max_gap=max_seq_gap),
            )

    def on_message_received(
        self,
        header: E2EHeader,
        payload: bytes,
    ) -> E2EStatus:
        """Process a received E2E-protected message.

        Verifies CRC and sequence, updates channel state, and
        reports faults if thresholds are exceeded.

        Args:
            header: Decoded E2E header.
            payload: Payload bytes.

        Returns:
            Current E2E status for this channel.
        """
        with self._lock:
            data_id = header.data_id
            if data_id not in self._channels:
                self.register_channel(data_id)
            ch = self._channels[data_id]
            ch.total_received += 1

            # CRC check
            if not e2e_verify(header, payload):
                ch.total_crc_failures += 1
                ch.consecutive_failures += 1
                self._update_status(ch, E2EStatus.INVALID)
                self._report_fault(FaultType.CRC_FAILURE, data_id, "CRC mismatch")
                return ch.status

            # Sequence check
            seq_result = ch.seq_checker.check(header.sequence_counter)

            if seq_result in ("OK", "INIT"):
                ch.consecutive_failures = 0
                ch.last_valid_time = time.monotonic()
                self._update_status(ch, E2EStatus.VALID)
            elif seq_result == "OK_SOME_LOST":
                ch.consecutive_failures = 0
                ch.last_valid_time = time.monotonic()
                ch.total_seq_errors += 1
                self._update_status(ch, E2EStatus.VALID)
                self._log_warning(data_id, f"Sequence gap detected (result={seq_result})")
            elif seq_result == "REPEATED":
                # Ignore duplicates, don't count as failure
                pass
            elif seq_result == "ERROR":
                ch.total_seq_errors += 1
                ch.consecutive_failures += 1
                self._update_status(ch, E2EStatus.INVALID)
                self._report_fault(FaultType.SEQ_ERROR, data_id, f"Seq gap exceeded")

            return ch.status

    def get_channel_status(self, data_id: int) -> E2EStatus | None:
        """Get current E2E status for a data_id."""
        with self._lock:
            ch = self._channels.get(data_id)
            return ch.status if ch else None

    def get_channel_stats(self, data_id: int) -> dict | None:
        """Get statistics for a data_id channel."""
        with self._lock:
            ch = self._channels.get(data_id)
            if not ch:
                return None
            return {
                "data_id": ch.data_id,
                "status": ch.status.value,
                "total_received": ch.total_received,
                "total_crc_failures": ch.total_crc_failures,
                "total_seq_errors": ch.total_seq_errors,
                "total_timeouts": ch.total_timeouts,
            }

    # --- Timeout monitoring ---

    def start_monitoring(self) -> None:
        """Start background timeout monitoring thread."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._timeout_loop,
            name="e2e_supervisor",
            daemon=True,
        )
        self._monitor_thread.start()

    def stop_monitoring(self) -> None:
        """Stop background timeout monitoring."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)
        self._monitor_thread = None

    def check_timeouts(self) -> list[int]:
        """Manually check all channels for timeout. Returns list of timed-out data_ids."""
        timed_out = []
        now = time.monotonic()
        with self._lock:
            for data_id, ch in self._channels.items():
                elapsed_ms = (now - ch.last_valid_time) * 1000
                if elapsed_ms > ch.deadline_ms and ch.status != E2EStatus.ERROR:
                    ch.total_timeouts += 1
                    ch.consecutive_failures += 1
                    self._update_status(ch, E2EStatus.TIMEOUT)
                    self._report_fault(FaultType.TIMEOUT, data_id, "Reception deadline exceeded")
                    timed_out.append(data_id)
        return timed_out

    def _timeout_loop(self) -> None:
        """Background loop checking for timeouts."""
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=0.5)
            if self._stop_event.is_set():
                break
            self.check_timeouts()

    # --- Internal helpers ---

    def _update_status(self, ch: E2EChannelState, new_status: E2EStatus) -> None:
        """Update channel E2E status with ERROR escalation."""
        if ch.consecutive_failures >= ERROR_THRESHOLD:
            ch.status = E2EStatus.ERROR
        else:
            ch.status = new_status

    def _report_fault(self, fault_type: FaultType, data_id: int, detail: str) -> None:
        source = f"data_id=0x{data_id:04X}"
        if self._safety_manager:
            self._safety_manager.notify_fault(
                fault_type, source=source, details={"detail": detail},
            )
        if self._dtc_manager:
            dtc_map = {
                FaultType.CRC_FAILURE: DTC_CODES.get("e2e_crc_failure"),
                FaultType.SEQ_ERROR: DTC_CODES.get("e2e_seq_error"),
                FaultType.TIMEOUT: DTC_CODES.get("e2e_timeout"),
            }
            dtc_code = dtc_map.get(fault_type)
            if dtc_code:
                self._dtc_manager.set_dtc(dtc_code, fault_type.value)

    def _log_warning(self, data_id: int, message: str) -> None:
        if self._safety_log:
            self._safety_log.log_event(
                severity=SafetyLogSeverity.SAFETY_WARNING,
                event=SafetyEventType.SEQ_COUNTER_GAP,
                source=f"data_id=0x{data_id:04X}",
                details={"message": message},
            )
