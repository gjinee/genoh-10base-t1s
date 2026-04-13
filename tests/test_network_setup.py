"""Tests for PLCA/10BASE-T1S network setup (PRD FR-001)."""

import pytest

from src.common.models import PLCAConfig
from src.master.network_setup import NetworkSetup, PLCAStatus


class TestNetworkSetupInit:
    def test_default_config(self):
        config = PLCAConfig()
        ns = NetworkSetup(config)
        assert ns._iface == "eth1"

    def test_custom_interface(self):
        config = PLCAConfig(interface="eth2")
        ns = NetworkSetup(config)
        assert ns._iface == "eth2"


class TestPLCAStatus:
    def test_default_status(self):
        status = PLCAStatus()
        assert status.supported is False
        assert status.beacon_active is False
        assert status.node_id == -1


class TestParseHelpers:
    def test_parse_int(self):
        text = "PLCA node id: 0\nPLCA node count: 8"
        assert NetworkSetup._parse_int(text, r"PLCA node id:\s*(\d+)") == 0
        assert NetworkSetup._parse_int(text, r"PLCA node count:\s*(\d+)") == 8
        assert NetworkSetup._parse_int(text, r"nonexistent:\s*(\d+)", default=99) == 99

    def test_parse_bool(self):
        assert NetworkSetup._parse_bool("PLCA status: enabled", r"PLCA status:\s*(enabled|on)") is True
        assert NetworkSetup._parse_bool("PLCA status: disabled", r"PLCA status:\s*(enabled|on)") is False


@pytest.mark.asyncio
class TestNetworkSetupCommands:
    async def test_detect_interface_missing(self):
        """Detect should fail gracefully when interface doesn't exist."""
        config = PLCAConfig(interface="nonexistent99")
        ns = NetworkSetup(config)
        result = await ns.detect_interface()
        assert result is False

    async def test_link_status_missing_interface(self):
        """Link status should return False for nonexistent interface."""
        config = PLCAConfig(interface="nonexistent99")
        ns = NetworkSetup(config)
        result = await ns.get_link_status()
        assert result is False
