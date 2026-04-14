"""Simulation tests for Security: IDS, SecOC, ACL.

Simulates attack scenarios and verifies that security mechanisms
detect and respond correctly.

Test IDs: SIM-X1~SIM-X10
"""

import os
import time

import pytest

from src.common.e2e_protection import SequenceCounterState
from src.common.payloads import (
    ENCODING_JSON,
    decode_secoc,
    encode_secoc,
)
from src.common.security_types import (
    AlertSeverity,
    IDSRuleID,
    NodeSecurityRole,
)
from src.master.acl_manager import ACLManager
from src.master.ids_engine import IDSEngine
from src.master.key_manager import KeyManager
from src.master.secoc import (
    FreshnessCounter,
    secoc_decode,
    secoc_encode,
)
from src.master.security_log import SecurityLog


class TestSecOCAuthentication:
    """SIM-X1~X2: SecOC message authentication scenarios."""

    def test_legitimate_message_accepted(self):
        """SIM-X1: Legitimate node with correct key → accepted."""
        key = os.urandom(32)
        counter = SequenceCounterState()
        data = {"value": 25.3, "unit": "celsius"}

        encoded = encode_secoc(data, "vehicle/front/1/sensor/temperature", counter, key)
        decoded, header, crc_valid, mac_valid = decode_secoc(encoded, key)

        assert mac_valid is True
        assert crc_valid is True
        assert decoded["value"] == 25.3

    def test_spoofed_message_rejected(self):
        """SIM-X1b: Attacker with wrong key → MAC rejected."""
        legit_key = os.urandom(32)
        attacker_key = os.urandom(32)
        counter = SequenceCounterState()

        encoded = encode_secoc(
            {"value": 999.9}, "vehicle/front/1/sensor/temperature",
            counter, attacker_key,
        )
        decoded, header, crc_valid, mac_valid = decode_secoc(encoded, legit_key)
        assert mac_valid is False

    def test_replay_attack_detected(self):
        """SIM-X2: Replay of previously valid message → freshness rejected."""
        key = os.urandom(32)
        fc = FreshnessCounter()
        data = b'{"action":"set","params":{"state":"on"}}'

        legit_msg = secoc_encode(key, data, fc)

        # First decode: OK
        _, fv1, valid1 = secoc_decode(key, legit_msg, window_ms=10000)
        assert valid1 is True

        # Replay: freshness check fails
        _, _, replay_valid = secoc_decode(key, legit_msg, last_freshness=fv1, window_ms=10000)
        assert replay_valid is False

    def test_per_node_key_isolation(self, tmp_path):
        """SIM-X2b: Per-node keys are isolated — cross-node decode fails."""
        km = KeyManager(key_dir=str(tmp_path))
        km.load_master_key()

        key1 = km.derive_node_key("1")
        key2 = km.derive_node_key("2")
        assert key1 != key2

        counter = SequenceCounterState()
        encoded = encode_secoc(
            {"v": 1}, "vehicle/front/1/sensor/temperature", counter, key1,
        )

        # Decode with node 2's key → fails
        _, _, _, mac_valid = decode_secoc(encoded, key2)
        assert mac_valid is False


class TestIDSDetection:
    """SIM-X3~X6: IDS rule-based detection scenarios."""

    def test_mac_failure_triggers_ids003(self, tmp_path):
        """SIM-X3: MAC failure → IDS-003 CRITICAL alert."""
        slog = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        ids = IDSEngine(security_log=slog)

        alerts = ids.check_message(
            source_node="attacker",
            key_expr="vehicle/front/1/sensor/temperature",
            payload_size=50,
            mac_valid=False,
        )
        rule_ids = {a.rule_id for a in alerts}
        assert IDSRuleID.IDS_003.value in rule_ids
        assert any(a.severity == AlertSeverity.CRITICAL.value for a in alerts)

    def test_flooding_triggers_ids002(self, tmp_path):
        """SIM-X4: Message rate exceeded → IDS-002 alert."""
        slog = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        ids = IDSEngine(security_log=slog)

        # Pre-fill rate limiter to simulate burst
        for _ in range(60):
            ids._rate_limiter.record("flood_node")

        alerts = ids.check_message(
            source_node="flood_node",
            key_expr="vehicle/front/1/sensor/temperature",
            payload_size=50,
        )
        rate_alerts = [a for a in alerts if a.rule_id == IDSRuleID.IDS_002.value]
        assert len(rate_alerts) > 0

    def test_oversized_payload_triggers_ids006(self, tmp_path):
        """SIM-X5: Payload > 4KB → IDS-006 alert."""
        slog = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        ids = IDSEngine(security_log=slog)

        alerts = ids.check_message(
            source_node="n1",
            key_expr="vehicle/front/1/sensor/temperature",
            payload_size=5000,
        )
        rule_ids = {a.rule_id for a in alerts}
        assert IDSRuleID.IDS_006.value in rule_ids

    def test_slave_to_master_key_triggers_ids007(self, tmp_path):
        """SIM-X5b: Slave publishes to master key expression → IDS-007."""
        slog = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        ids = IDSEngine(security_log=slog)

        alerts = ids.check_message(
            source_node="compromised_slave",
            key_expr="vehicle/master/heartbeat",
            payload_size=50,
        )
        rule_ids = {a.rule_id for a in alerts}
        assert IDSRuleID.IDS_007.value in rule_ids

    def test_unauthorized_key_expr_triggers_ids001(self):
        """SIM-X6: Unauthorized key expression → IDS-001."""
        ids = IDSEngine()
        alerts = ids.check_acl(
            source_node="sensor_1",
            key_expr="vehicle/rear/3/actuator/lock",
            allowed_key_exprs=["vehicle/front/1/sensor/*"],
        )
        assert any(a.rule_id == IDSRuleID.IDS_001.value for a in alerts)
        assert any(a.severity == AlertSeverity.CRITICAL.value for a in alerts)

    def test_simultaneous_offline_triggers_ids008(self, tmp_path):
        """SIM-X6b: ≥3 nodes offline simultaneously → IDS-008."""
        slog = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        ids = IDSEngine(security_log=slog)

        ids.report_node_offline("n1")
        ids.report_node_offline("n2")
        alerts = ids.report_node_offline("n3")  # 3rd → trigger

        assert any(a.rule_id == IDSRuleID.IDS_008.value for a in alerts)

    def test_crc_mac_combined_triggers_ids010(self, tmp_path):
        """SIM-X6c: CRC + MAC both fail → IDS-010."""
        slog = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        ids = IDSEngine(security_log=slog)

        alerts = ids.check_message(
            source_node="attacker",
            key_expr="vehicle/front/1/sensor/temperature",
            payload_size=50,
            mac_valid=False,
            crc_valid=False,
        )
        rule_ids = {a.rule_id for a in alerts}
        assert IDSRuleID.IDS_010.value in rule_ids


class TestACLEnforcement:
    """SIM-X7~X8: ACL role-based access control."""

    def test_coordinator_full_access(self):
        """SIM-X7: Coordinator has full access to vehicle/**."""
        acl = ACLManager()
        acl.add_node("0", "master", NodeSecurityRole.COORDINATOR)

        assert acl.check_access("0", "vehicle/front/1/sensor/temperature", "put") is True
        assert acl.check_access("0", "vehicle/rear/3/actuator/lock", "put") is True

    def test_sensor_node_restricted(self):
        """SIM-X7b: Sensor node can only publish to own sensor keys."""
        acl = ACLManager()
        acl.add_node("1", "front", NodeSecurityRole.SENSOR_NODE)

        assert acl.check_access("1", "vehicle/front/1/sensor/temperature", "put") is True
        # Cannot publish to other zones or actuators
        assert acl.check_access("1", "vehicle/rear/3/sensor/temperature", "put") is False
        assert acl.check_access("1", "vehicle/front/1/actuator/led", "put") is False

    def test_acl_with_ids_integration(self, tmp_path):
        """SIM-X8: ACL violation triggers IDS alert."""
        slog = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        ids = IDSEngine(security_log=slog)
        acl = ACLManager()
        acl.add_node("1", "front", NodeSecurityRole.SENSOR_NODE)

        policy = acl.get_policy("1")
        allowed = policy.allowed_key_exprs
        alerts = ids.check_acl(
            source_node="1",
            key_expr="vehicle/rear/3/actuator/lock",
            allowed_key_exprs=allowed,
        )
        assert len(alerts) > 0
        assert alerts[0].rule_id == IDSRuleID.IDS_001.value

    def test_zenohd_acl_config_generation(self):
        """SIM-X8b: ACL config generated for zenohd."""
        acl = ACLManager()
        acl.add_node("0", "master", NodeSecurityRole.COORDINATOR)
        acl.add_node("1", "front", NodeSecurityRole.SENSOR_NODE)
        acl.add_node("2", "front", NodeSecurityRole.ACTUATOR_NODE)
        acl.add_node("3", "rear", NodeSecurityRole.MIXED_NODE)

        config = acl.generate_zenohd_acl_config()
        assert "access_control" in config
        rules = config["access_control"]["rules"]
        assert len(rules) == 4


class TestSecurityLogChain:
    """SIM-X9~X10: Security log chain hash integrity."""

    def test_chain_valid_after_mixed_operations(self, tmp_path):
        """SIM-X9: Chain hash remains valid after diverse operations."""
        slog = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        ids = IDSEngine(security_log=slog)

        # Normal traffic
        ids.check_message("n1", "vehicle/front/1/sensor/temp", 50)
        # MAC failure
        ids.check_message("n2", "vehicle/front/2/sensor/temp", 50, mac_valid=False)
        # Oversized
        ids.check_message("n3", "vehicle/front/3/sensor/temp", 5000)
        # Unauthorized
        ids.check_acl("n4", "vehicle/master/cmd", ["vehicle/front/4/sensor/*"])
        # Offline nodes
        ids.report_node_offline("n5")
        ids.report_node_offline("n6")
        ids.report_node_offline("n7")

        assert slog.verify_chain() is True
        assert slog.current_seq >= 4

    def test_chain_detects_tampering(self, tmp_path):
        """SIM-X10: Tampered log entry detected by chain verification."""
        slog = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        ids = IDSEngine(security_log=slog)

        ids.check_message("n1", "vehicle/front/1/sensor/temp", 50, mac_valid=False)
        ids.check_message("n2", "vehicle/front/2/sensor/temp", 50)

        assert slog.verify_chain() is True

        # Tamper with the log file
        log_path = str(tmp_path / "sec.jsonl")
        import json
        with open(log_path, "r") as f:
            lines = f.readlines()

        if len(lines) >= 2:
            entry = json.loads(lines[0])
            entry["event"] = "TAMPERED"
            lines[0] = json.dumps(entry) + "\n"
            with open(log_path, "w") as f:
                f.writelines(lines)

            # Re-read and verify — should fail
            slog2 = SecurityLog(path=log_path)
            assert slog2.verify_chain() is False
