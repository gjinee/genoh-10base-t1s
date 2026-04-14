"""Simulation tests for End-to-End scenarios.

Full lifecycle tests: startup → normal operation → fault → recovery,
with E2E protection + SecOC on all messages.

Test IDs: SIM-E1~SIM-E8
"""

import os
import time

import pytest

from src.common.e2e_protection import (
    SequenceCounterState,
    e2e_decode,
    resolve_data_id,
)
from src.common.payloads import (
    ENCODING_JSON,
    decode_e2e,
    decode_secoc,
    encode_e2e,
    encode_secoc,
)
from src.common.safety_types import (
    E2EStatus,
    FaultType,
    SafetyState,
)
from src.common.security_types import NodeSecurityRole
from src.master.acl_manager import ACLManager
from src.master.dtc_manager import DTCManager
from src.master.e2e_supervisor import E2ESupervisor
from src.master.flow_monitor import (
    CP_ACTUATOR,
    CP_DIAG,
    CP_QUERY,
    CP_SENSOR,
    FlowMonitor,
)
from src.master.ids_engine import IDSEngine
from src.master.key_manager import KeyManager
from src.master.safety_log import SafetyLog
from src.master.safety_manager import SafetyManager
from src.master.security_log import SecurityLog
from src.master.self_test import SelfTest
from src.master.watchdog import Watchdog


class TestE2EActuatorCommand:
    """SIM-E1: Master sends actuator command with E2E+SecOC."""

    def test_secoc_actuator_command_roundtrip(self, tmp_path):
        """SIM-E1: Master → SecOC encode → slave decodes → verified."""
        km = KeyManager(key_dir=str(tmp_path))
        km.load_master_key()
        master_key = km.derive_node_key("0")

        counter = SequenceCounterState()
        command = {"action": "set", "params": {"state": "on", "brightness": 100}}
        key_expr = "vehicle/front/1/actuator/led"

        # Master encodes with SecOC
        encoded = encode_secoc(command, key_expr, counter, master_key)

        # Slave receives and verifies
        decoded, header, crc_valid, mac_valid = decode_secoc(encoded, master_key)
        assert mac_valid is True
        assert crc_valid is True
        assert decoded["action"] == "set"
        assert decoded["params"]["brightness"] == 100
        assert header.data_id == 0x2001

    def test_actuator_with_wrong_key_rejected(self, tmp_path):
        """SIM-E1b: Actuator command with wrong key → rejected."""
        km = KeyManager(key_dir=str(tmp_path))
        km.load_master_key()
        master_key = km.derive_node_key("0")
        attacker_key = km.derive_node_key("99")

        counter = SequenceCounterState()
        command = {"action": "set", "params": {"state": "unlock"}}

        encoded = encode_secoc(command, "vehicle/front/1/actuator/lock", counter, attacker_key)
        _, _, _, mac_valid = decode_secoc(encoded, master_key)
        assert mac_valid is False


class TestE2ESensorToMaster:
    """SIM-E2: Sensor publishes E2E → master receives → processes."""

    def test_sensor_publish_master_verify(self, tmp_path):
        """SIM-E2: Sensor node publishes E2E data, master verifies with supervisor."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog)
        sv = E2ESupervisor(safety_manager=sm, safety_log=slog)
        sv.register_channel(0x1001, deadline_ms=5000)

        counter = SequenceCounterState()

        # Simulate 10 sensor readings
        for i in range(10):
            data = {"value": 20.0 + i * 0.3, "unit": "celsius", "ts": 1713000000000 + i * 1000}
            encoded = encode_e2e(data, "vehicle/front/1/sensor/temperature", counter)

            # Master decodes
            decoded, header, crc_valid = decode_e2e(encoded, ENCODING_JSON)
            assert crc_valid is True

            # E2E supervisor validates
            raw_h, raw_p = e2e_decode(encoded)
            status = sv.on_message_received(raw_h, raw_p)
            assert status == E2EStatus.VALID

        stats = sv.get_channel_stats(0x1001)
        assert stats["total_received"] == 10
        assert stats["total_crc_failures"] == 0
        assert sm.state == SafetyState.NORMAL


class TestE2EFullSafetyCycle:
    """SIM-E3: Full lifecycle — startup → normal → fault → recovery."""

    def test_full_lifecycle(self, tmp_path):
        """SIM-E3: Complete safety lifecycle test."""
        # --- Phase 1: Startup ---
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        dtc = DTCManager(path=str(tmp_path / "d.json"))
        sm = SafetyManager(safety_log=slog, dtc_manager=dtc, total_nodes=4)
        wd = Watchdog(timeout_sec=10.0)

        st = SelfTest(safety_manager=sm, dtc_manager=dtc, safety_log=slog, watchdog=wd)
        ok, results = st.run()
        assert ok is True
        assert sm.state == SafetyState.NORMAL

        sv = E2ESupervisor(safety_manager=sm, dtc_manager=dtc, safety_log=slog)
        sv.register_channel(0x1001, deadline_ms=5000)
        sv.register_channel(0x1003, deadline_ms=500)

        fm = FlowMonitor()

        # --- Phase 2: Normal operation (3 cycles) ---
        counter_temp = SequenceCounterState()
        counter_prox = SequenceCounterState()

        for cycle in range(3):
            # Sensor processing
            enc_t = encode_e2e(
                {"value": 22.0 + cycle * 0.1}, "vehicle/front/1/sensor/temperature", counter_temp,
            )
            h_t, p_t = e2e_decode(enc_t)
            sv.on_message_received(h_t, p_t)
            fm.checkpoint(CP_SENSOR)

            # Actuator processing
            fm.checkpoint(CP_ACTUATOR)

            # Query processing
            fm.checkpoint(CP_QUERY)

            # Diagnostics
            fm.checkpoint(CP_DIAG)

            assert fm.verify_cycle() is True
            wd.kick()

        assert sm.state == SafetyState.NORMAL
        assert fm.cycle_count == 3
        assert fm.error_count == 0

        # --- Phase 3: Fault injection (node offline) ---
        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        assert sm.state == SafetyState.DEGRADED
        assert dtc.count > 0

        # --- Phase 4: Recovery ---
        sm.notify_recovery(source="n1")
        assert sm.state == SafetyState.NORMAL

        # --- Phase 5: Verify logs ---
        events = slog.read_events(last_n=100)
        assert len(events) >= 3  # self-test + faults + recovery


class TestE2EMultiNode:
    """SIM-E4: Multi-node scenario with concurrent messages."""

    def test_four_node_mixed_roles(self, tmp_path):
        """SIM-E4: 4 nodes (2 sensor, 1 actuator, 1 mixed) simultaneous."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)
        sv = E2ESupervisor(safety_manager=sm, safety_log=slog)

        # Register channels for all data types
        channels = {
            "vehicle/front/1/sensor/temperature": 0x1001,
            "vehicle/front/2/sensor/proximity": 0x1003,
            "vehicle/front/3/actuator/led": 0x2001,
            "vehicle/front/4/sensor/light": 0x1004,
        }
        for key_expr, data_id in channels.items():
            sv.register_channel(data_id, deadline_ms=5000)

        counters = {key: SequenceCounterState() for key in channels}

        # Each node sends 5 messages
        for i in range(5):
            for key_expr, data_id in channels.items():
                data = {"value": float(i), "ts": 1713000000000 + i}
                encoded = encode_e2e(data, key_expr, counters[key_expr])
                h, p = e2e_decode(encoded)
                status = sv.on_message_received(h, p)
                assert status == E2EStatus.VALID

        # All channels should have 5 messages
        for data_id in channels.values():
            stats = sv.get_channel_stats(data_id)
            assert stats["total_received"] == 5
            assert stats["total_crc_failures"] == 0

        assert sm.state == SafetyState.NORMAL


class TestE2ESecurityIntegrated:
    """SIM-E5~E6: End-to-end with full security stack."""

    def test_full_stack_sensor_to_master(self, tmp_path):
        """SIM-E5: Sensor → SecOC+E2E encode → IDS check → ACL verify → master decode."""
        km = KeyManager(key_dir=str(tmp_path))
        km.load_master_key()
        node_key = km.derive_node_key("1")

        slog_sec = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        ids = IDSEngine(security_log=slog_sec)
        acl = ACLManager()
        acl.add_node("1", "front", NodeSecurityRole.SENSOR_NODE)

        counter = SequenceCounterState()
        sensor_data = {"value": 25.3, "unit": "celsius"}
        key_expr = "vehicle/front/1/sensor/temperature"

        # Sensor encodes
        encoded = encode_secoc(sensor_data, key_expr, counter, node_key)

        # IDS checks (all clean)
        alerts = ids.check_message("1", key_expr, len(encoded))
        assert len(alerts) == 0

        # ACL check
        assert acl.check_access("1", key_expr, "put") is True

        # Master decodes
        decoded, header, crc_valid, mac_valid = decode_secoc(encoded, node_key)
        assert mac_valid is True
        assert crc_valid is True
        assert decoded["value"] == 25.3

    def test_full_stack_attack_blocked(self, tmp_path):
        """SIM-E6: Attacker message → IDS alert + MAC fail + ACL deny."""
        km = KeyManager(key_dir=str(tmp_path))
        km.load_master_key()
        legit_key = km.derive_node_key("1")
        attacker_key = os.urandom(32)

        slog_sec = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        ids = IDSEngine(security_log=slog_sec)
        acl = ACLManager()
        acl.add_node("1", "front", NodeSecurityRole.SENSOR_NODE)

        counter = SequenceCounterState()

        # Attacker tries to send actuator command (wrong key + unauthorized)
        fake_msg = encode_secoc(
            {"action": "set", "params": {"state": "unlock"}},
            "vehicle/front/1/actuator/lock",
            counter, attacker_key,
        )

        # MAC verification fails
        _, _, _, mac_valid = decode_secoc(fake_msg, legit_key)
        assert mac_valid is False

        # IDS: MAC failure detected
        alerts = ids.check_message(
            "attacker", "vehicle/front/1/actuator/lock", len(fake_msg), mac_valid=False,
        )
        assert len(alerts) > 0

        # ACL: attacker not registered
        assert acl.check_access("attacker", "vehicle/front/1/actuator/lock", "put") is False


class TestE2ESelfTestStartup:
    """SIM-E7: Self-test at startup verifies all components."""

    def test_self_test_passes_clean_system(self, tmp_path):
        """SIM-E7: Self-test passes on fresh initialization."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        dtc = DTCManager(path=str(tmp_path / "d.json"))
        sm = SafetyManager(safety_log=slog, dtc_manager=dtc)
        wd = Watchdog(timeout_sec=10.0)

        st = SelfTest(safety_manager=sm, dtc_manager=dtc, safety_log=slog, watchdog=wd)
        ok, results = st.run()

        assert ok is True
        # Check that critical tests all passed
        critical_results = [r for r in results if r.critical]
        assert all(r.passed for r in critical_results)


class TestE2EDTCPersistence:
    """SIM-E8: DTC codes persist across restart."""

    def test_dtc_persist_and_clear(self, tmp_path):
        """SIM-E8: DTCs set, persisted, queried, and cleared."""
        dtc_path = str(tmp_path / "dtc.json")
        dtc = DTCManager(path=dtc_path)

        # Set DTCs via fault
        dtc.set_dtc(0xC10000, "CRC_FAILURE")
        dtc.set_dtc(0xC10001, "SEQ_ERROR")
        assert dtc.count == 2

        # Simulate restart — reload from file
        dtc2 = DTCManager(path=dtc_path)
        assert dtc2.count == 2

        # Clear one
        dtc2.clear_dtc(0xC10000)
        assert dtc2.count == 1

        # Clear all
        dtc2.clear_all()
        assert dtc2.count == 0
