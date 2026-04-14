"""Access Control List (ACL) Manager for Zenoh key expression authorization.

Implements role-based access control (RBAC) and generates zenohd
ACL configuration per cybersecurity.md Section 4.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from src.common.security_types import NodeSecurityRole, SecurityAction

logger = logging.getLogger(__name__)


@dataclass
class ACLPolicy:
    """Access control policy for a single node."""
    node_id: str
    role: NodeSecurityRole
    allowed_key_exprs: list[str] = field(default_factory=list)
    allowed_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "role": self.role.value,
            "allowed_key_exprs": self.allowed_key_exprs,
            "allowed_actions": self.allowed_actions,
        }


# Default allowed actions per role
ROLE_ACTIONS: dict[str, list[str]] = {
    NodeSecurityRole.COORDINATOR: ["put", "get", "declare_subscriber", "declare_queryable"],
    NodeSecurityRole.SENSOR_NODE: ["put", "declare_subscriber", "declare_queryable"],
    NodeSecurityRole.ACTUATOR_NODE: ["put", "declare_subscriber", "declare_queryable"],
    NodeSecurityRole.MIXED_NODE: ["put", "declare_subscriber", "declare_queryable"],
    NodeSecurityRole.DIAGNOSTIC: ["declare_subscriber"],  # Read-only
}


class ACLManager:
    """Manages access control policies and authorization checks.

    Generates zenohd ACL configuration from node registry and
    provides runtime access control verification.
    """

    def __init__(self):
        self._policies: dict[str, ACLPolicy] = {}

    def add_policy(self, policy: ACLPolicy) -> None:
        """Register an ACL policy for a node."""
        self._policies[policy.node_id] = policy

    def add_node(
        self,
        node_id: str,
        zone: str,
        role: NodeSecurityRole,
    ) -> ACLPolicy:
        """Create and register an ACL policy for a node based on its role.

        Automatically generates allowed key expressions based on the
        node's zone, id, and role per Section 4.2.1.
        """
        key_exprs = self._generate_key_exprs(node_id, zone, role)
        actions = ROLE_ACTIONS.get(role, [])
        policy = ACLPolicy(
            node_id=node_id,
            role=role,
            allowed_key_exprs=key_exprs,
            allowed_actions=list(actions),
        )
        self._policies[node_id] = policy
        return policy

    def check_access(self, node_id: str, key_expr: str, action: str = "put") -> bool:
        """Check if a node is authorized for a key expression and action.

        Args:
            node_id: Node identifier.
            key_expr: Zenoh key expression being accessed.
            action: Action type (put, get, declare_subscriber, etc.).

        Returns:
            True if access is allowed.
        """
        policy = self._policies.get(node_id)
        if not policy:
            return False

        # Check action
        if action not in policy.allowed_actions:
            return False

        # Check key expression
        return any(
            self._key_expr_matches(key_expr, pattern)
            for pattern in policy.allowed_key_exprs
        )

    def log_violation(self, node_id: str, key_expr: str, action: str) -> dict:
        """Log an ACL violation.

        Returns:
            Violation details dict.
        """
        violation = {
            "node_id": node_id,
            "key_expr": key_expr,
            "action": action,
            "result": "DENIED",
        }
        logger.warning("ACL violation: %s", violation)
        return violation

    def get_policy(self, node_id: str) -> ACLPolicy | None:
        return self._policies.get(node_id)

    def get_all_policies(self) -> list[ACLPolicy]:
        return list(self._policies.values())

    def generate_zenohd_acl_config(self) -> dict:
        """Generate zenohd-compatible ACL configuration.

        Returns:
            Dict suitable for JSON5 serialization as zenohd access_control config.
        """
        rules = []

        for node_id, policy in self._policies.items():
            rule = {
                "id": f"acl_{node_id}",
                "cert_common_name": f"zenoh-node-{node_id}",
                "permission": "allow",
                "key_exprs": policy.allowed_key_exprs,
                "actions": policy.allowed_actions,
            }
            rules.append(rule)

        return {
            "access_control": {
                "enabled": True,
                "default_permission": "deny",
                "rules": rules,
            }
        }

    # --- Internal helpers ---

    def _generate_key_exprs(
        self,
        node_id: str,
        zone: str,
        role: NodeSecurityRole,
    ) -> list[str]:
        """Generate allowed key expressions based on role."""
        if role == NodeSecurityRole.COORDINATOR:
            return ["vehicle/**"]

        key_exprs = [
            f"vehicle/{zone}/{node_id}/status",
            f"vehicle/{zone}/{node_id}/alive",
            "vehicle/master/heartbeat",
            "vehicle/master/command",
        ]

        if role in (NodeSecurityRole.SENSOR_NODE, NodeSecurityRole.MIXED_NODE):
            key_exprs.append(f"vehicle/{zone}/{node_id}/sensor/*")

        if role in (NodeSecurityRole.ACTUATOR_NODE, NodeSecurityRole.MIXED_NODE):
            key_exprs.append(f"vehicle/{zone}/{node_id}/actuator/*")

        if role == NodeSecurityRole.DIAGNOSTIC:
            return ["vehicle/**"]  # Read-only via actions

        return key_exprs

    @staticmethod
    def _key_expr_matches(key_expr: str, pattern: str) -> bool:
        """Simple wildcard matching for Zenoh key expressions."""
        if pattern == key_expr:
            return True
        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            return key_expr.startswith(prefix + "/") or key_expr == prefix
        if pattern.endswith("/*"):
            prefix = pattern[:-2]
            parts = key_expr.split("/")
            pattern_parts = prefix.split("/")
            if len(parts) == len(pattern_parts) + 1:
                return key_expr.startswith(prefix + "/")
        return False
