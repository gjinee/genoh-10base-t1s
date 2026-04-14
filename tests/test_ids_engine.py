"""Tests for IDS Engine (Intrusion Detection System).

Test IDs: CST-020~023 from cybersecurity.md Section 10.3.
"""

import pytest

from src.common.security_types import IDSRuleID, AlertSeverity, RATE_LIMITS
from src.master.ids_engine import IDSEngine, RateLimiter
from src.master.security_log import SecurityLog


class TestRateLimiter:
    """Test per-node rate limiting."""

    def test_record_returns_rate(self):
        rl = RateLimiter(window_sec=1.0)
        rate = rl.record("node_1")
        assert rate > 0

    def test_rate_accumulates(self):
        rl = RateLimiter(window_sec=1.0)
        for _ in range(10):
            rate = rl.record("node_1")
        assert rate >= 10.0


class TestIDSEngine:
    """Test IDS rule-based and rate-based detection."""

    def test_normal_traffic_no_alerts(self):
        """CST-023: Normal traffic produces zero alerts."""
        ids = IDSEngine()
        alerts = ids.check_message(
            source_node="node_1",
            key_expr="vehicle/front/1/sensor/temperature",
            payload_size=50,
            mac_valid=True,
            freshness_valid=True,
            crc_valid=True,
        )
        assert len(alerts) == 0

    def test_mac_failure_detected(self):
        """IDS-003: MAC verification failure triggers CRITICAL alert."""
        ids = IDSEngine()
        alerts = ids.check_message(
            source_node="node_1",
            key_expr="vehicle/front/1/sensor/temperature",
            payload_size=50,
            mac_valid=False,
        )
        mac_alerts = [a for a in alerts if a.rule_id == IDSRuleID.IDS_003.value]
        assert len(mac_alerts) == 1
        assert mac_alerts[0].severity == AlertSeverity.CRITICAL.value

    def test_replay_detected(self):
        """IDS-004: Replay (freshness failure) triggers HIGH alert."""
        ids = IDSEngine()
        alerts = ids.check_message(
            source_node="node_1",
            key_expr="vehicle/front/1/sensor/temperature",
            payload_size=50,
            mac_valid=True,
            freshness_valid=False,
        )
        replay_alerts = [a for a in alerts if a.rule_id == IDSRuleID.IDS_004.value]
        assert len(replay_alerts) == 1

    def test_rate_limit_warning(self):
        """CST-020: Rate exceeding warning threshold generates alert."""
        ids = IDSEngine()
        # Directly pump the rate limiter to simulate high rate
        for _ in range(60):
            ids._rate_limiter.record("node_flood")
        # Now check_message should see the high rate
        alerts = ids.check_message(
            source_node="node_flood",
            key_expr="vehicle/front/1/sensor/temperature",
            payload_size=50,
        )
        rate_alerts = [a for a in alerts if a.rule_id == IDSRuleID.IDS_002.value]
        assert len(rate_alerts) > 0

    def test_unauthorized_publish_detected(self):
        """CST-021: Unauthorized key expression publish detected."""
        ids = IDSEngine()
        alerts = ids.check_acl(
            source_node="node_1",
            key_expr="vehicle/master/command",
            allowed_key_exprs=["vehicle/front/1/sensor/*"],
        )
        acl_alerts = [a for a in alerts if a.rule_id == IDSRuleID.IDS_001.value]
        assert len(acl_alerts) == 1
        assert acl_alerts[0].severity == AlertSeverity.CRITICAL.value

    def test_slave_publishes_master_key(self):
        """IDS-007: Slave publishing to master key expression."""
        ids = IDSEngine()
        alerts = ids.check_message(
            source_node="node_3",
            key_expr="vehicle/master/heartbeat",
            payload_size=50,
        )
        ids007 = [a for a in alerts if a.rule_id == IDSRuleID.IDS_007.value]
        assert len(ids007) == 1

    def test_abnormal_payload_size(self):
        """IDS-006: Payload > 4KB triggers alert."""
        ids = IDSEngine()
        alerts = ids.check_message(
            source_node="node_1",
            key_expr="vehicle/front/1/sensor/temperature",
            payload_size=5000,
        )
        size_alerts = [a for a in alerts if a.rule_id == IDSRuleID.IDS_006.value]
        assert len(size_alerts) == 1

    def test_crc_and_mac_simultaneous_failure(self):
        """IDS-010: CRC + MAC simultaneous failure → CRITICAL."""
        ids = IDSEngine()
        alerts = ids.check_message(
            source_node="node_1",
            key_expr="vehicle/front/1/sensor/temperature",
            payload_size=50,
            mac_valid=False,
            crc_valid=False,
        )
        ids010 = [a for a in alerts if a.rule_id == IDSRuleID.IDS_010.value]
        assert len(ids010) == 1
        assert ids010[0].severity == AlertSeverity.CRITICAL.value

    def test_simultaneous_nodes_offline(self):
        """IDS-008: ≥3 nodes simultaneously offline."""
        ids = IDSEngine()
        ids.report_node_offline("node_1")
        ids.report_node_offline("node_2")
        alerts = ids.report_node_offline("node_3")
        ids008 = [a for a in alerts if a.rule_id == IDSRuleID.IDS_008.value]
        assert len(ids008) == 1

    def test_alerts_logged_to_security_log(self, tmp_path):
        slog = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        ids = IDSEngine(security_log=slog)
        ids.check_message(
            source_node="node_1",
            key_expr="vehicle/front/1/sensor/temp",
            payload_size=50,
            mac_valid=False,
        )
        events = slog.read_events(last_n=10)
        assert len(events) > 0

    def test_authorized_access_no_alert(self):
        """Authorized key expression access produces no alerts."""
        ids = IDSEngine()
        alerts = ids.check_acl(
            source_node="node_1",
            key_expr="vehicle/front/1/sensor/temperature",
            allowed_key_exprs=["vehicle/front/1/sensor/*"],
        )
        assert len(alerts) == 0
