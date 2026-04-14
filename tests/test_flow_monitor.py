"""Tests for FlowMonitor (Program Flow Monitoring)."""

import pytest

from src.master.flow_monitor import (
    CP_ACTUATOR,
    CP_DIAG,
    CP_QUERY,
    CP_SENSOR,
    FlowMonitor,
)


class TestFlowMonitor:
    """Test checkpoint-based flow verification."""

    def test_correct_sequence_passes(self):
        fm = FlowMonitor()
        fm.checkpoint(CP_SENSOR)
        fm.checkpoint(CP_ACTUATOR)
        fm.checkpoint(CP_QUERY)
        fm.checkpoint(CP_DIAG)
        assert fm.verify_cycle() is True

    def test_wrong_order_fails(self):
        fm = FlowMonitor()
        fm.checkpoint(CP_ACTUATOR)  # Wrong: should be SENSOR first
        fm.checkpoint(CP_SENSOR)
        fm.checkpoint(CP_QUERY)
        fm.checkpoint(CP_DIAG)
        assert fm.verify_cycle() is False

    def test_missing_checkpoint_fails(self):
        fm = FlowMonitor()
        fm.checkpoint(CP_SENSOR)
        fm.checkpoint(CP_ACTUATOR)
        # Missing CP_QUERY
        fm.checkpoint(CP_DIAG)
        assert fm.verify_cycle() is False

    def test_extra_checkpoint_fails(self):
        fm = FlowMonitor()
        fm.checkpoint(CP_SENSOR)
        fm.checkpoint(CP_ACTUATOR)
        fm.checkpoint(CP_QUERY)
        fm.checkpoint(CP_DIAG)
        fm.checkpoint(CP_SENSOR)  # Extra
        assert fm.verify_cycle() is False

    def test_verify_resets_for_next_cycle(self):
        fm = FlowMonitor()
        fm.checkpoint(CP_SENSOR)
        fm.checkpoint(CP_ACTUATOR)
        fm.checkpoint(CP_QUERY)
        fm.checkpoint(CP_DIAG)
        assert fm.verify_cycle() is True

        # Next cycle starts fresh
        fm.checkpoint(CP_SENSOR)
        fm.checkpoint(CP_ACTUATOR)
        fm.checkpoint(CP_QUERY)
        fm.checkpoint(CP_DIAG)
        assert fm.verify_cycle() is True
        assert fm.cycle_count == 2

    def test_error_callback_fires(self):
        errors = []
        fm = FlowMonitor(on_error=lambda: errors.append(True))
        fm.checkpoint(CP_SENSOR)
        fm.verify_cycle()  # Incomplete → error
        assert len(errors) == 1

    def test_error_count_tracked(self):
        fm = FlowMonitor()
        fm.checkpoint(CP_SENSOR)
        fm.verify_cycle()  # Error
        fm.checkpoint(CP_SENSOR)
        fm.checkpoint(CP_ACTUATOR)
        fm.checkpoint(CP_QUERY)
        fm.checkpoint(CP_DIAG)
        fm.verify_cycle()  # OK
        assert fm.error_count == 1
        assert fm.cycle_count == 2

    def test_custom_expected_flow(self):
        fm = FlowMonitor(expected_flow=[10, 20, 30])
        fm.checkpoint(10)
        fm.checkpoint(20)
        fm.checkpoint(30)
        assert fm.verify_cycle() is True

    def test_reset_clears_without_verify(self):
        fm = FlowMonitor()
        fm.checkpoint(CP_SENSOR)
        fm.reset()
        # Start fresh after reset
        fm.checkpoint(CP_SENSOR)
        fm.checkpoint(CP_ACTUATOR)
        fm.checkpoint(CP_QUERY)
        fm.checkpoint(CP_DIAG)
        assert fm.verify_cycle() is True
