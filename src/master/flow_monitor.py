"""Program Flow Monitoring for execution integrity verification.

Verifies that the main loop executes checkpoints in the expected
order per functional_safety.md Section 4.3.
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

# Predefined checkpoint IDs
CP_SENSOR = 1
CP_ACTUATOR = 2
CP_QUERY = 3
CP_DIAG = 4

EXPECTED_FLOW = [CP_SENSOR, CP_ACTUATOR, CP_QUERY, CP_DIAG]


class FlowMonitor:
    """Checkpoint-based program flow verification.

    The main loop must call checkpoint() at each execution point.
    At the end of each cycle, verify_cycle() checks that all
    checkpoints were hit in the correct order.

    Usage:
        fm = FlowMonitor()

        while running:
            process_sensors()
            fm.checkpoint(CP_SENSOR)
            process_actuators()
            fm.checkpoint(CP_ACTUATOR)
            process_queries()
            fm.checkpoint(CP_QUERY)
            collect_diagnostics()
            fm.checkpoint(CP_DIAG)

            if not fm.verify_cycle():
                safety_manager.notify_fault(FaultType.FLOW_ERROR, ...)
    """

    def __init__(
        self,
        expected_flow: list[int] | None = None,
        on_error: Callable[[], None] | None = None,
    ):
        self._expected = expected_flow or EXPECTED_FLOW
        self._actual: list[int] = []
        self._on_error = on_error
        self._cycle_count = 0
        self._error_count = 0

    def checkpoint(self, cp_id: int) -> None:
        """Record a checkpoint in the current cycle.

        Args:
            cp_id: Checkpoint identifier (e.g., CP_SENSOR=1).
        """
        self._actual.append(cp_id)

    def verify_cycle(self) -> bool:
        """Verify that the recorded checkpoints match the expected flow.

        Resets the recorded checkpoints for the next cycle.

        Returns:
            True if the flow matches expected sequence.
        """
        self._cycle_count += 1
        ok = self._actual == self._expected
        if not ok:
            self._error_count += 1
            logger.error(
                "Flow Monitor: expected %s, got %s (cycle %d)",
                self._expected, self._actual, self._cycle_count,
            )
            if self._on_error:
                self._on_error()
        self._actual = []
        return ok

    def reset(self) -> None:
        """Reset the monitor state without verifying."""
        self._actual = []

    @property
    def cycle_count(self) -> int:
        return self._cycle_count

    @property
    def error_count(self) -> int:
        return self._error_count

    @property
    def expected_flow(self) -> list[int]:
        return list(self._expected)
