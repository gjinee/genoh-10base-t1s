"""Tests for Phase 6: Security Foundation (security_types, security_log, key_manager)."""

import json

import pytest

from src.common.security_types import (
    ANOMALY_BASELINE_COUNT,
    AlertSeverity,
    FRESHNESS_WINDOW_MS,
    IDSAlert,
    IDSRuleID,
    MAX_PAYLOAD_SIZE,
    NodeSecurityRole,
    RATE_LIMITS,
    SecurityAction,
    SecurityEvent,
    SecurityEventType,
)
from src.master.security_log import SecurityLog, GENESIS_HASH
from src.master.key_manager import KeyManager, hkdf_sha256


# ============================================================
# Security Types Tests
# ============================================================

class TestSecurityTypes:
    """Test security enums and constants."""

    def test_alert_severity_enum(self):
        values = [s.value for s in AlertSeverity]
        assert len(values) == 4
        assert "CRITICAL" in values
        assert "LOW" in values

    def test_security_event_type_enum(self):
        values = [e.value for e in SecurityEventType]
        assert "UNAUTHORIZED_PUBLISH" in values
        assert "MAC_FAILURE" in values
        assert "REPLAY_DETECTED" in values

    def test_ids_rule_enum_all_10(self):
        assert len(IDSRuleID) == 10
        assert IDSRuleID.IDS_001.value == "IDS-001"
        assert IDSRuleID.IDS_010.value == "IDS-010"

    def test_node_security_roles(self):
        roles = [r.value for r in NodeSecurityRole]
        assert len(roles) == 5
        assert "COORDINATOR" in roles
        assert "DIAGNOSTIC" in roles

    def test_rate_limits_defined(self):
        assert "sensor_per_node" in RATE_LIMITS
        assert "actuator_command" in RATE_LIMITS
        assert "total_bus" in RATE_LIMITS
        for key, limits in RATE_LIMITS.items():
            assert "warning" in limits
            assert "block" in limits
            assert limits["warning"] < limits["block"]

    def test_freshness_window(self):
        assert FRESHNESS_WINDOW_MS == 5000

    def test_max_payload_size(self):
        assert MAX_PAYLOAD_SIZE == 4096

    def test_security_event_to_dict_from_dict(self):
        event = SecurityEvent(
            seq=1,
            severity=AlertSeverity.CRITICAL.value,
            category="INTRUSION_DETECTION",
            event=SecurityEventType.UNAUTHORIZED_PUBLISH.value,
            source_node="zenoh-node-3",
            source_ip="192.168.1.4",
            target_key_expr="vehicle/master/command",
            action=SecurityAction.BLOCKED.value,
            ids_rule=IDSRuleID.IDS_001.value,
        )
        d = event.to_dict()
        restored = SecurityEvent.from_dict(d)
        assert restored.seq == 1
        assert restored.severity == "CRITICAL"
        assert restored.source_node == "zenoh-node-3"
        assert restored.target_key_expr == "vehicle/master/command"
        assert restored.ids_rule == "IDS-001"

    def test_ids_alert_to_dict(self):
        alert = IDSAlert(
            alert_id="IDS-20260413-001",
            rule_id=IDSRuleID.IDS_001.value,
            severity=AlertSeverity.CRITICAL.value,
            source_node="zenoh-node-3",
            description="Unauthorized publish",
            evidence={"key_expr": "vehicle/master/command"},
            action_taken=SecurityAction.BLOCKED.value,
        )
        d = alert.to_dict()
        assert d["alert_id"] == "IDS-20260413-001"
        assert d["evidence"]["key_expr"] == "vehicle/master/command"


# ============================================================
# Security Log Tests
# ============================================================

class TestSecurityLog:
    """Test chain-hash security event log."""

    def test_write_and_read(self, tmp_path):
        log = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        log.log_event(
            severity=AlertSeverity.CRITICAL,
            event="TEST_EVENT",
            source_node="node-1",
        )
        events = log.read_events(last_n=1)
        assert len(events) == 1
        assert events[0].event == "TEST_EVENT"

    def test_chain_hash_integrity(self, tmp_path):
        """Chain hash validates after multiple writes."""
        log = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        for i in range(5):
            log.log_event(
                severity=AlertSeverity.HIGH,
                event=f"EVENT_{i}",
                source_node=f"node-{i}",
            )
        assert log.verify_chain() is True

    def test_chain_hash_tamper_detected(self, tmp_path):
        """Modifying an entry breaks the chain."""
        path = tmp_path / "sec.jsonl"
        log = SecurityLog(path=str(path))
        for i in range(3):
            log.log_event(
                severity=AlertSeverity.LOW,
                event=f"E{i}",
                source_node="n1",
            )
        # Tamper with the second line
        lines = path.read_text().strip().split("\n")
        data = json.loads(lines[1])
        data["event"] = "TAMPERED"
        lines[1] = json.dumps(data, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n")

        log2 = SecurityLog(path=str(path))
        assert log2.verify_chain() is False

    def test_chain_hash_deletion_detected(self, tmp_path):
        """Deleting an entry breaks the chain."""
        path = tmp_path / "sec.jsonl"
        log = SecurityLog(path=str(path))
        for i in range(3):
            log.log_event(
                severity=AlertSeverity.LOW,
                event=f"E{i}",
                source_node="n1",
            )
        # Delete the middle line
        lines = path.read_text().strip().split("\n")
        del lines[1]
        path.write_text("\n".join(lines) + "\n")

        log2 = SecurityLog(path=str(path))
        assert log2.verify_chain() is False

    def test_separate_from_safety_log(self, tmp_path):
        """Security log and safety log use different files."""
        from src.master.safety_log import SafetyLog
        sec_path = str(tmp_path / "security.jsonl")
        safety_path = str(tmp_path / "safety.jsonl")
        sec_log = SecurityLog(path=sec_path)
        safety_log = SafetyLog(path=safety_path)
        assert sec_log.path != safety_log.path

    def test_persists_across_reopen(self, tmp_path):
        path = str(tmp_path / "sec.jsonl")
        log1 = SecurityLog(path=path)
        log1.log_event(severity=AlertSeverity.LOW, event="A", source_node="n1")
        log1.log_event(severity=AlertSeverity.LOW, event="B", source_node="n1")
        del log1

        log2 = SecurityLog(path=path)
        assert log2.current_seq == 2
        log2.log_event(severity=AlertSeverity.LOW, event="C", source_node="n1")
        assert log2.verify_chain() is True


# ============================================================
# Key Manager Tests
# ============================================================

class TestKeyManager:
    """Test HKDF key derivation and management."""

    def test_hkdf_sha256_deterministic(self):
        """Same input produces same output."""
        k1 = hkdf_sha256(b"secret", salt=b"salt", info=b"ctx")
        k2 = hkdf_sha256(b"secret", salt=b"salt", info=b"ctx")
        assert k1 == k2
        assert len(k1) == 32

    def test_hkdf_different_info_different_key(self):
        k1 = hkdf_sha256(b"secret", info=b"node_01")
        k2 = hkdf_sha256(b"secret", info=b"node_02")
        assert k1 != k2

    def test_derive_node_keys_unique(self, tmp_path):
        """Different nodes get different keys."""
        km = KeyManager(key_dir=str(tmp_path))
        km.load_master_key()
        k1 = km.derive_node_key("1")
        k2 = km.derive_node_key("2")
        assert k1 != k2
        assert len(k1) == 32

    def test_derive_broadcast_key(self, tmp_path):
        km = KeyManager(key_dir=str(tmp_path))
        km.load_master_key()
        kb = km.derive_broadcast_key()
        assert len(kb) == 32
        # Broadcast key differs from node keys
        k1 = km.derive_node_key("1")
        assert kb != k1

    def test_key_file_permissions(self, tmp_path):
        km = KeyManager(key_dir=str(tmp_path))
        km.load_master_key()
        km.derive_node_key("1")
        key_path = km.save_node_key("1", directory=str(tmp_path))
        assert KeyManager.check_key_file_permissions(key_path) is True

    def test_key_rotation(self, tmp_path):
        km = KeyManager(key_dir=str(tmp_path))
        km.load_master_key()
        k_old = km.derive_node_key("1")
        k_new = km.rotate_key("1")
        assert k_old != k_new
        assert len(k_new) == 32

    def test_load_save_master_key(self, tmp_path):
        path = str(tmp_path / "master.key")
        km1 = KeyManager()
        km1.load_master_key(path)
        saved_key = km1._master_key

        km2 = KeyManager()
        km2.load_master_key(path)
        assert km2._master_key == saved_key

    def test_master_key_file_permissions(self, tmp_path):
        path = str(tmp_path / "master.key")
        km = KeyManager()
        km.load_master_key(path)
        assert KeyManager.check_key_file_permissions(path) is True

    def test_get_node_key_derives_on_demand(self, tmp_path):
        km = KeyManager(key_dir=str(tmp_path))
        km.load_master_key()
        k = km.get_node_key("5")
        assert len(k) == 32
