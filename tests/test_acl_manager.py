"""Tests for ACL Manager (Access Control List).

Test IDs: CST-010~013 from cybersecurity.md Section 10.2.
"""

import pytest

from src.common.security_types import NodeSecurityRole
from src.master.acl_manager import ACLManager, ACLPolicy


class TestACLManager:
    """Test access control policy management."""

    def test_allowed_access_succeeds(self):
        """CST-010: Authorized key expression access succeeds."""
        acl = ACLManager()
        acl.add_node("1", "front_left", NodeSecurityRole.SENSOR_NODE)
        assert acl.check_access("1", "vehicle/front_left/1/sensor/temperature") is True

    def test_denied_access_blocked(self):
        """CST-011: Non-authorized key expression access is blocked."""
        acl = ACLManager()
        acl.add_node("1", "front_left", NodeSecurityRole.SENSOR_NODE)
        assert acl.check_access("1", "vehicle/rear_right/2/sensor/temperature") is False

    def test_slave_cannot_publish_master_key(self):
        """CST-012: Slave cannot publish to master key expression."""
        acl = ACLManager()
        acl.add_node("1", "front_left", NodeSecurityRole.SENSOR_NODE)
        # Slave has subscribe access to master/heartbeat but not publish
        # The key_expr match allows reading, but "vehicle/master/diagnostics" is not in allowed list
        assert acl.check_access("1", "vehicle/master/diagnostics") is False

    def test_cross_node_publish_blocked(self):
        """CST-013: Node 1 cannot publish to Node 2's key expressions."""
        acl = ACLManager()
        acl.add_node("1", "front_left", NodeSecurityRole.SENSOR_NODE)
        acl.add_node("2", "front_right", NodeSecurityRole.SENSOR_NODE)
        # Node 1 tries to access node 2's sensor key
        assert acl.check_access("1", "vehicle/front_right/2/sensor/temperature") is False

    def test_coordinator_full_access(self):
        """Coordinator (master) has full access to vehicle/**."""
        acl = ACLManager()
        acl.add_node("0", "master", NodeSecurityRole.COORDINATOR)
        assert acl.check_access("0", "vehicle/front/1/sensor/temperature") is True
        assert acl.check_access("0", "vehicle/master/heartbeat") is True
        assert acl.check_access("0", "vehicle/rear/3/actuator/motor") is True

    def test_mixed_node_has_sensor_and_actuator(self):
        acl = ACLManager()
        acl.add_node("3", "rear_left", NodeSecurityRole.MIXED_NODE)
        assert acl.check_access("3", "vehicle/rear_left/3/sensor/temperature") is True
        assert acl.check_access("3", "vehicle/rear_left/3/actuator/motor") is True

    def test_diagnostic_read_only(self):
        """Diagnostic role can only subscribe (read), not put."""
        acl = ACLManager()
        acl.add_node("diag", "master", NodeSecurityRole.DIAGNOSTIC)
        assert acl.check_access("diag", "vehicle/front/1/sensor/temp", action="declare_subscriber") is True
        assert acl.check_access("diag", "vehicle/front/1/sensor/temp", action="put") is False

    def test_generate_zenohd_config(self):
        acl = ACLManager()
        acl.add_node("0", "master", NodeSecurityRole.COORDINATOR)
        acl.add_node("1", "front_left", NodeSecurityRole.SENSOR_NODE)
        config = acl.generate_zenohd_acl_config()
        assert config["access_control"]["enabled"] is True
        assert config["access_control"]["default_permission"] == "deny"
        assert len(config["access_control"]["rules"]) == 2

    def test_violation_logged(self):
        acl = ACLManager()
        violation = acl.log_violation("node_1", "vehicle/master/command", "put")
        assert violation["result"] == "DENIED"
        assert violation["node_id"] == "node_1"

    def test_unknown_node_denied(self):
        """Unregistered node is denied."""
        acl = ACLManager()
        assert acl.check_access("unknown", "vehicle/front/1/sensor/temp") is False

    def test_heartbeat_subscribe_allowed(self):
        """All slave nodes can subscribe to master heartbeat."""
        acl = ACLManager()
        acl.add_node("1", "front_left", NodeSecurityRole.SENSOR_NODE)
        assert acl.check_access("1", "vehicle/master/heartbeat") is True

    def test_get_policy(self):
        acl = ACLManager()
        acl.add_node("1", "front_left", NodeSecurityRole.SENSOR_NODE)
        policy = acl.get_policy("1")
        assert policy is not None
        assert policy.role == NodeSecurityRole.SENSOR_NODE
        assert len(policy.allowed_key_exprs) > 0
