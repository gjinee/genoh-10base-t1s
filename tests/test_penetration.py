"""Penetration test scenarios from cybersecurity.md Section 10.4.

Simulates attack scenarios and verifies that security mechanisms
detect and block them correctly.
"""

import os
import time

import pytest

from src.common.e2e_protection import SequenceCounterState
from src.common.payloads import encode_e2e, encode_secoc, decode_secoc, ENCODING_JSON
from src.common.security_types import IDSRuleID, AlertSeverity
from src.master.ids_engine import IDSEngine
from src.master.secoc import (
    FreshnessCounter,
    FreshnessValue,
    compute_mac,
    secoc_encode,
)
from src.master.security_log import SecurityLog


class TestPenetration:
    """Penetration test scenarios (PT-001~PT-005)."""

    def test_spoofed_sensor_message_rejected(self):
        """PT-001: Attacker injects fake sensor message → MAC fails."""
        legit_key = os.urandom(32)
        attacker_key = os.urandom(32)

        # Attacker creates message with wrong key
        counter = SequenceCounterState()
        fake_msg = encode_secoc(
            {"value": 999.9, "unit": "celsius"},
            "vehicle/front/1/sensor/temperature",
            counter,
            attacker_key,
        )

        # Receiver verifies with legitimate key
        decoded, _, _, mac_valid = decode_secoc(fake_msg, legit_key)
        assert mac_valid is False, "Spoofed message should be rejected"

    def test_spoofed_actuator_command_rejected(self):
        """PT-002: Attacker injects fake actuator command → MAC + ACL block."""
        legit_key = os.urandom(32)
        attacker_key = os.urandom(32)

        # Attacker tries to send actuator command
        counter = SequenceCounterState()
        fake_cmd = encode_secoc(
            {"action": "set", "params": {"state": "unlock"}},
            "vehicle/front/1/actuator/lock",
            counter,
            attacker_key,
        )

        # MAC fails
        _, _, _, mac_valid = decode_secoc(fake_cmd, legit_key)
        assert mac_valid is False

        # IDS also detects the attempt
        ids = IDSEngine()
        alerts = ids.check_message(
            source_node="unknown_attacker",
            key_expr="vehicle/front/1/actuator/lock",
            payload_size=50,
            mac_valid=False,
        )
        mac_alerts = [a for a in alerts if a.rule_id == IDSRuleID.IDS_003.value]
        assert len(mac_alerts) > 0

    def test_replay_old_command_rejected(self):
        """PT-003: Attacker replays a previously valid command → Freshness fails."""
        key = os.urandom(32)
        from src.master.secoc import FreshnessCounter, secoc_encode, secoc_decode

        # Create a legitimate message
        fc = FreshnessCounter()
        data = b'{"action":"set","params":{"state":"on"}}'
        legit_msg = secoc_encode(key, data, fc)

        # First decode succeeds
        _, fv1, valid1 = secoc_decode(key, legit_msg, window_ms=10000)
        assert valid1 is True

        # Replay the exact same message — freshness check should fail
        _, _, replay_valid = secoc_decode(key, legit_msg, last_freshness=fv1, window_ms=10000)
        assert replay_valid is False, "Replayed message should be rejected"

    def test_flooding_rate_limited(self, tmp_path):
        """PT-005: Attacker floods the bus → IDS rate limits and alerts."""
        slog = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        ids = IDSEngine(security_log=slog)

        # Pre-fill rate limiter to simulate burst
        for _ in range(60):
            ids._rate_limiter.record("attacker_node")

        # Next message triggers rate alert
        alerts = ids.check_message(
            source_node="attacker_node",
            key_expr="vehicle/front/1/sensor/temperature",
            payload_size=50,
        )
        rate_alerts = [a for a in alerts if a.rule_id == IDSRuleID.IDS_002.value]
        assert len(rate_alerts) > 0
        assert slog.verify_chain() is True

    def test_unauthorized_key_expression_blocked(self):
        """PT: Attacker tries to publish to master key expression."""
        ids = IDSEngine()
        alerts = ids.check_acl(
            source_node="compromised_slave",
            key_expr="vehicle/master/command",
            allowed_key_exprs=["vehicle/front/1/sensor/*"],
        )
        assert any(a.rule_id == IDSRuleID.IDS_001.value for a in alerts)
        assert any(a.severity == AlertSeverity.CRITICAL.value for a in alerts)

    def test_combined_attack_detection(self, tmp_path):
        """Multiple simultaneous attack vectors are all detected."""
        slog = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        ids = IDSEngine(security_log=slog)

        # Simultaneous: MAC failure + oversized payload + master key publish
        alerts = ids.check_message(
            source_node="attacker",
            key_expr="vehicle/master/heartbeat",
            payload_size=5000,
            mac_valid=False,
            crc_valid=False,
        )

        rule_ids = {a.rule_id for a in alerts}
        assert IDSRuleID.IDS_003.value in rule_ids  # MAC failure
        assert IDSRuleID.IDS_006.value in rule_ids  # Oversized
        assert IDSRuleID.IDS_007.value in rule_ids  # Slave → master
        assert IDSRuleID.IDS_010.value in rule_ids  # CRC + MAC
