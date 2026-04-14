"""Tests for Phase 1: Safety Foundation (safety_types, safety_log, watchdog).

Covers safety enums, constants, SafetyEvent dataclass, append-only
safety log, and software watchdog timer.
"""

import json
import os
import threading
import time

import pytest

from src.common.safety_types import (
    ASILLevel,
    DATA_ID_MAP,
    DTC_CODES,
    E2EStatus,
    FaultType,
    SAFE_ACTIONS,
    SafetyEvent,
    SafetyEventType,
    SafetyLogSeverity,
    SafetyState,
    SENSOR_RANGE_LIMITS,
    SEQUENCE_GAP_LIMITS,
    TIMEOUT_CONFIG,
)
from src.master.safety_log import SafetyLog
from src.master.watchdog import Watchdog


# ============================================================
# Safety Types Tests
# ============================================================

class TestSafetyStateEnum:
    """Test SafetyState enum values and str-serialization."""

    def test_all_states_defined(self):
        states = [s.value for s in SafetyState]
        assert "NORMAL" in states
        assert "DEGRADED" in states
        assert "SAFE_STATE" in states
        assert "FAIL_SILENT" in states
        assert len(states) == 4

    def test_str_serializable(self):
        assert str(SafetyState.NORMAL) == "SafetyState.NORMAL"
        assert SafetyState.NORMAL.value == "NORMAL"
        assert SafetyState("NORMAL") == SafetyState.NORMAL


class TestFaultTypeEnum:
    """Test FaultType enum completeness."""

    def test_all_fault_types(self):
        types = [f.value for f in FaultType]
        expected = [
            "CRC_FAILURE", "SEQ_ERROR", "TIMEOUT", "NODE_OFFLINE",
            "PLCA_BEACON_LOST", "FLOW_ERROR", "WATCHDOG_EXPIRED",
            "SENSOR_PLAUSIBILITY",
        ]
        for exp in expected:
            assert exp in types


class TestE2EStatusEnum:
    """Test E2EStatus enum (5 states per Section 2.6)."""

    def test_all_e2e_states(self):
        states = [s.value for s in E2EStatus]
        assert len(states) == 5
        for expected in ["INIT", "VALID", "TIMEOUT", "INVALID", "ERROR"]:
            assert expected in states


class TestASILLevelEnum:
    """Test ASIL levels QM through D."""

    def test_all_asil_levels(self):
        levels = [a.value for a in ASILLevel]
        assert len(levels) == 5
        assert "QM" in levels
        assert "ASIL-A" in levels
        assert "ASIL-D" in levels


class TestDataIDMap:
    """Test DATA_ID_MAP coverage."""

    def test_has_all_sensor_types(self):
        sensor_keys = [k for k in DATA_ID_MAP if "sensor/" in k]
        assert len(sensor_keys) == 5
        for sensor in ["temperature", "pressure", "proximity", "light", "battery"]:
            assert f"vehicle/*/sensor/{sensor}" in DATA_ID_MAP

    def test_has_all_actuator_types(self):
        actuator_keys = [k for k in DATA_ID_MAP if "actuator/" in k]
        assert len(actuator_keys) == 5
        for actuator in ["led", "motor", "relay", "buzzer", "lock"]:
            assert f"vehicle/*/actuator/{actuator}" in DATA_ID_MAP

    def test_has_status_and_master(self):
        assert "vehicle/*/status" in DATA_ID_MAP
        assert "vehicle/master/heartbeat" in DATA_ID_MAP
        assert "vehicle/master/diagnostics" in DATA_ID_MAP

    def test_data_ids_are_unique(self):
        values = list(DATA_ID_MAP.values())
        assert len(values) == len(set(values)), "Duplicate Data IDs found"

    def test_sensor_ids_in_0x1xxx_range(self):
        for key, data_id in DATA_ID_MAP.items():
            if "sensor/" in key:
                assert 0x1000 <= data_id <= 0x1FFF, f"{key} Data ID out of range"

    def test_actuator_ids_in_0x2xxx_range(self):
        for key, data_id in DATA_ID_MAP.items():
            if "actuator/" in key:
                assert 0x2000 <= data_id <= 0x2FFF, f"{key} Data ID out of range"


class TestTimeoutConfig:
    """Test TIMEOUT_CONFIG entries."""

    def test_all_message_types_present(self):
        expected = [
            "sensor/temperature", "sensor/proximity", "actuator_response",
            "master/heartbeat", "node/liveliness",
        ]
        for key in expected:
            assert key in TIMEOUT_CONFIG
            assert "deadline_ms" in TIMEOUT_CONFIG[key]
            assert "asil" in TIMEOUT_CONFIG[key]

    def test_proximity_is_asil_d(self):
        """ASIL-D sensor (proximity) has tightest deadline."""
        prox = TIMEOUT_CONFIG["sensor/proximity"]
        assert prox["asil"] == ASILLevel.D
        assert prox["deadline_ms"] == 500


class TestSequenceGapLimits:
    """Test SEQUENCE_GAP_LIMITS by ASIL level."""

    def test_asil_d_strictest(self):
        assert SEQUENCE_GAP_LIMITS[ASILLevel.D] == 1

    def test_asil_b_gap_3(self):
        assert SEQUENCE_GAP_LIMITS[ASILLevel.B] == 3

    def test_higher_asil_stricter(self):
        assert SEQUENCE_GAP_LIMITS[ASILLevel.D] < SEQUENCE_GAP_LIMITS[ASILLevel.C]
        assert SEQUENCE_GAP_LIMITS[ASILLevel.C] < SEQUENCE_GAP_LIMITS[ASILLevel.B]


class TestSafeActions:
    """Test SAFE_ACTIONS per actuator type."""

    def test_all_actuator_safe_actions(self):
        expected = [
            "led_headlight", "led_interior", "motor_window", "motor_mirror",
            "relay", "buzzer", "lock_driving", "lock_parked",
        ]
        for key in expected:
            assert key in SAFE_ACTIONS
            assert "state" in SAFE_ACTIONS[key]
            assert "reason" in SAFE_ACTIONS[key]

    def test_headlight_stays_on(self):
        assert SAFE_ACTIONS["led_headlight"]["state"] == "on"

    def test_motor_stops(self):
        assert SAFE_ACTIONS["motor_window"]["state"] == "stop"


class TestSafetyEvent:
    """Test SafetyEvent dataclass roundtrip."""

    def test_to_dict_from_dict(self):
        event = SafetyEvent(
            seq=42,
            severity=SafetyLogSeverity.SAFETY_CRITICAL,
            event=SafetyEventType.E2E_CRC_FAILURE,
            source="vehicle/front/1/sensor/proximity",
            details={"expected_crc": "0xABCD1234", "actual_crc": "0xDEADBEEF"},
            safety_state=SafetyState.DEGRADED,
            dtc="0xC11029",
        )
        d = event.to_dict()
        restored = SafetyEvent.from_dict(d)
        assert restored.seq == 42
        assert restored.severity == SafetyLogSeverity.SAFETY_CRITICAL
        assert restored.event == SafetyEventType.E2E_CRC_FAILURE
        assert restored.source == "vehicle/front/1/sensor/proximity"
        assert restored.dtc == "0xC11029"
        assert restored.details["expected_crc"] == "0xABCD1234"

    def test_to_dict_has_all_fields(self):
        event = SafetyEvent(seq=1, severity="INFO", event="TEST", source="test")
        d = event.to_dict()
        required = ["seq", "ts_ms", "monotonic_ns", "severity", "event",
                     "source", "details", "safety_state", "dtc"]
        for field in required:
            assert field in d


# ============================================================
# Safety Log Tests
# ============================================================

class TestSafetyLog:
    """Test append-only safety event log."""

    def test_create_and_write_event(self, tmp_path):
        log = SafetyLog(path=str(tmp_path / "safety.jsonl"))
        event = log.log_event(
            severity=SafetyLogSeverity.SAFETY_CRITICAL,
            event=SafetyEventType.E2E_CRC_FAILURE,
            source="vehicle/front/1/sensor/proximity",
        )
        assert event.seq == 1
        assert event.severity == SafetyLogSeverity.SAFETY_CRITICAL.value

    def test_sequence_monotonic(self, tmp_path):
        log = SafetyLog(path=str(tmp_path / "safety.jsonl"))
        events = []
        for i in range(5):
            e = log.log_event(
                severity=SafetyLogSeverity.SAFETY_INFO,
                event="TEST_EVENT",
                source=f"test_{i}",
            )
            events.append(e)
        seqs = [e.seq for e in events]
        assert seqs == [1, 2, 3, 4, 5]

    def test_read_last_n_events(self, tmp_path):
        log = SafetyLog(path=str(tmp_path / "safety.jsonl"))
        for i in range(10):
            log.log_event(
                severity=SafetyLogSeverity.SAFETY_INFO,
                event="TEST",
                source=f"src_{i}",
            )
        events = log.read_events(last_n=3)
        assert len(events) == 3
        assert events[0].seq == 8
        assert events[2].seq == 10

    def test_severity_levels_accepted(self, tmp_path):
        log = SafetyLog(path=str(tmp_path / "safety.jsonl"))
        for sev in SafetyLogSeverity:
            e = log.log_event(severity=sev, event="TEST", source="test")
            assert e.severity == sev.value

    def test_log_persists_across_reopen(self, tmp_path):
        path = str(tmp_path / "safety.jsonl")
        log1 = SafetyLog(path=path)
        log1.log_event(severity=SafetyLogSeverity.SAFETY_INFO, event="A", source="s1")
        log1.log_event(severity=SafetyLogSeverity.SAFETY_INFO, event="B", source="s2")
        del log1

        log2 = SafetyLog(path=path)
        assert log2.current_seq == 2
        log2.log_event(severity=SafetyLogSeverity.SAFETY_INFO, event="C", source="s3")
        assert log2.current_seq == 3

        events = log2.read_events(last_n=100)
        assert len(events) == 3
        assert events[0].event == "A"
        assert events[2].event == "C"

    def test_fsync_file_exists(self, tmp_path):
        """Verify log file is created and contains valid JSON."""
        path = tmp_path / "safety.jsonl"
        log = SafetyLog(path=str(path))
        log.log_event(severity=SafetyLogSeverity.SAFETY_INFO, event="T", source="s")
        assert path.exists()
        with open(path, "r") as f:
            line = f.readline().strip()
            data = json.loads(line)
            assert data["seq"] == 1
            assert data["event"] == "T"

    def test_details_and_dtc_stored(self, tmp_path):
        log = SafetyLog(path=str(tmp_path / "safety.jsonl"))
        log.log_event(
            severity=SafetyLogSeverity.SAFETY_CRITICAL,
            event=SafetyEventType.E2E_CRC_FAILURE,
            source="test",
            details={"expected_crc": "0x1234"},
            safety_state=SafetyState.DEGRADED,
            dtc="0xC11029",
        )
        events = log.read_events(last_n=1)
        assert events[0].details["expected_crc"] == "0x1234"
        assert events[0].dtc == "0xC11029"
        assert events[0].safety_state == SafetyState.DEGRADED.value


# ============================================================
# Watchdog Tests
# ============================================================

class TestWatchdog:
    """Test software watchdog timer."""

    def test_create_default_timeout(self):
        wd = Watchdog()
        assert wd.timeout_sec == 5.0
        assert not wd.is_running

    def test_create_custom_timeout(self):
        wd = Watchdog(timeout_sec=2.0)
        assert wd.timeout_sec == 2.0

    def test_kick_resets_timer(self):
        """Kick prevents expiry callback from firing."""
        expired = threading.Event()
        wd = Watchdog(timeout_sec=0.5, expiry_callback=expired.set)
        wd.start()
        try:
            for _ in range(6):
                time.sleep(0.15)
                wd.kick()
            assert not expired.is_set(), "Watchdog expired despite regular kicks"
        finally:
            wd.stop()

    def test_expiry_callback_fires(self):
        """Without kick, the expiry callback fires."""
        expired = threading.Event()
        wd = Watchdog(timeout_sec=0.3, expiry_callback=expired.set)
        wd.start()
        try:
            result = expired.wait(timeout=2.0)
            assert result, "Watchdog did not expire within expected time"
        finally:
            wd.stop()

    def test_start_stop_lifecycle(self):
        wd = Watchdog(timeout_sec=10.0)
        assert not wd.is_running
        wd.start()
        assert wd.is_running
        wd.stop()
        assert not wd.is_running

    def test_double_start_is_safe(self):
        wd = Watchdog(timeout_sec=10.0)
        wd.start()
        wd.start()  # Should not raise
        assert wd.is_running
        wd.stop()

    def test_double_stop_is_safe(self):
        wd = Watchdog(timeout_sec=10.0)
        wd.start()
        wd.stop()
        wd.stop()  # Should not raise
        assert not wd.is_running

    def test_no_callback_on_stop(self):
        """Stopping the watchdog should not trigger the expiry callback."""
        expired = threading.Event()
        wd = Watchdog(timeout_sec=0.3, expiry_callback=expired.set)
        wd.start()
        wd.kick()
        wd.stop()
        time.sleep(0.5)
        assert not expired.is_set()
