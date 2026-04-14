"""Tests for SelfTest (Startup Self-Test).

Test ID FST-015 from functional_safety.md Section 9.2.
"""

import pytest

from src.common.safety_types import SafetyState
from src.master.dtc_manager import DTCManager
from src.master.safety_log import SafetyLog
from src.master.safety_manager import SafetyManager
from src.master.self_test import SelfTest, SelfTestResult
from src.master.watchdog import Watchdog


class TestSelfTest:
    """Test startup self-test sequence."""

    def test_all_pass_returns_true(self, tmp_path):
        """FST-015: All items pass → overall pass."""
        slog = SafetyLog(path=str(tmp_path / "safety.jsonl"))
        sm = SafetyManager(safety_log=slog)
        dtc = DTCManager(path=str(tmp_path / "dtc.json"))
        wd = Watchdog(timeout_sec=10.0)

        st = SelfTest(
            safety_manager=sm,
            dtc_manager=dtc,
            safety_log=slog,
            watchdog=wd,
        )
        overall, results = st.run()
        assert overall is True
        # Check that all items ran
        item_names = [r.item_name for r in results]
        assert "crc_engine" in item_names
        assert "e2e_counters" in item_names
        assert "fsm_initial" in item_names
        assert "timestamp" in item_names

    def test_critical_failure_returns_false(self, tmp_path):
        """A critical item failure causes overall failure."""
        slog = SafetyLog(path=str(tmp_path / "safety.jsonl"))
        sm = SafetyManager(safety_log=slog)
        # Put FSM in wrong state to fail check 3
        sm._state = SafetyState.DEGRADED

        st = SelfTest(safety_manager=sm, safety_log=slog)
        overall, results = st.run()
        assert overall is False
        fsm_result = next(r for r in results if r.item_name == "fsm_initial")
        assert fsm_result.passed is False

    def test_non_critical_failure_still_passes(self, tmp_path):
        """Non-critical item failure doesn't prevent overall pass."""
        slog = SafetyLog(path=str(tmp_path / "safety.jsonl"))
        sm = SafetyManager()

        # Run without network (non-critical item)
        st = SelfTest(safety_manager=sm, safety_log=slog)
        overall, results = st.run()
        assert overall is True

    def test_crc_engine_check(self, tmp_path):
        slog = SafetyLog(path=str(tmp_path / "safety.jsonl"))
        st = SelfTest(safety_log=slog)
        overall, results = st.run()
        crc_result = next(r for r in results if r.item_name == "crc_engine")
        assert crc_result.passed is True
        assert "CRC=0x" in crc_result.message

    def test_e2e_counter_init_check(self, tmp_path):
        slog = SafetyLog(path=str(tmp_path / "safety.jsonl"))
        st = SelfTest(safety_log=slog)
        overall, results = st.run()
        counter_result = next(r for r in results if r.item_name == "e2e_counters")
        assert counter_result.passed is True

    def test_fsm_initial_state_check(self, tmp_path):
        slog = SafetyLog(path=str(tmp_path / "safety.jsonl"))
        sm = SafetyManager()
        st = SelfTest(safety_manager=sm, safety_log=slog)
        overall, results = st.run()
        fsm_result = next(r for r in results if r.item_name == "fsm_initial")
        assert fsm_result.passed is True

    def test_safety_log_check(self, tmp_path):
        slog = SafetyLog(path=str(tmp_path / "safety.jsonl"))
        st = SelfTest(safety_log=slog)
        overall, results = st.run()
        log_result = next(r for r in results if r.item_name == "safety_log")
        assert log_result.passed is True

    def test_timestamp_check(self, tmp_path):
        slog = SafetyLog(path=str(tmp_path / "safety.jsonl"))
        st = SelfTest(safety_log=slog)
        overall, results = st.run()
        ts_result = next(r for r in results if r.item_name == "timestamp")
        assert ts_result.passed is True

    def test_self_test_logged(self, tmp_path):
        """Self-test results are recorded in safety log."""
        slog = SafetyLog(path=str(tmp_path / "safety.jsonl"))
        st = SelfTest(safety_log=slog)
        st.run()
        events = slog.read_events(last_n=10)
        # Should contain SELF_TEST_VERIFY and SELF_TEST_PASS events
        event_types = [e.event for e in events]
        assert "SELF_TEST_VERIFY" in event_types
        assert "SELF_TEST_PASS" in event_types

    def test_returns_10_results(self, tmp_path):
        """All 10 self-test items produce results."""
        slog = SafetyLog(path=str(tmp_path / "safety.jsonl"))
        st = SelfTest(safety_log=slog)
        overall, results = st.run()
        assert len(results) == 10
