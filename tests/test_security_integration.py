"""Tests for Phase 8: Security Integration.

Verifies full SecOC encode/decode through payloads.py, security log
chain integrity after operations, and ACL config generation.
"""

import os

import pytest

from src.common.e2e_protection import SequenceCounterState
from src.common.payloads import (
    ENCODING_JSON,
    decode_secoc,
    encode_secoc,
)
from src.common.security_types import NodeSecurityRole
from src.master.acl_manager import ACLManager
from src.master.cert_provisioner import CertProvisioner
from src.master.ids_engine import IDSEngine
from src.master.key_manager import KeyManager
from src.master.security_log import SecurityLog


class TestFullStackEncodeDecode:
    """Test full protection stack: App → SecOC → E2E → ... → E2E → SecOC → App."""

    def test_full_stack_roundtrip(self):
        key = os.urandom(32)
        data = {"value": 25.3, "unit": "celsius", "ts": 1713000000000}
        counter = SequenceCounterState()

        encoded = encode_secoc(
            data,
            "vehicle/front/1/sensor/temperature",
            counter,
            key,
            ENCODING_JSON,
        )

        decoded, header, crc_valid, mac_valid = decode_secoc(encoded, key)
        assert mac_valid is True
        assert crc_valid is True
        assert decoded["value"] == 25.3
        assert header.data_id == 0x1001

    def test_wrong_key_fails_mac(self):
        key1 = os.urandom(32)
        key2 = os.urandom(32)
        counter = SequenceCounterState()

        encoded = encode_secoc(
            {"v": 1}, "vehicle/front/1/sensor/temperature",
            counter, key1,
        )
        decoded, header, crc_valid, mac_valid = decode_secoc(encoded, key2)
        assert mac_valid is False

    def test_corrupted_data_fails_both(self):
        key = os.urandom(32)
        counter = SequenceCounterState()

        encoded = encode_secoc(
            {"v": 1}, "vehicle/front/1/sensor/temperature",
            counter, key,
        )
        corrupted = bytearray(encoded)
        corrupted[15] ^= 0xFF
        decoded, header, crc_valid, mac_valid = decode_secoc(bytes(corrupted), key)
        assert mac_valid is False


class TestSecurityLogChainAfterOps:
    """Verify security log chain remains valid after multiple operations."""

    def test_chain_valid_after_mixed_events(self, tmp_path):
        slog = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        ids = IDSEngine(security_log=slog)

        # Normal traffic
        ids.check_message("n1", "vehicle/front/1/sensor/temp", 50)
        # MAC failure
        ids.check_message("n2", "vehicle/front/2/sensor/temp", 50, mac_valid=False)
        # Large payload
        ids.check_message("n3", "vehicle/front/3/sensor/temp", 5000)

        assert slog.verify_chain() is True
        assert slog.current_seq >= 2


class TestACLConfigGeneration:
    """Verify ACL config generation matches node registry."""

    def test_config_matches_registered_nodes(self):
        acl = ACLManager()
        acl.add_node("0", "master", NodeSecurityRole.COORDINATOR)
        acl.add_node("1", "front_left", NodeSecurityRole.SENSOR_NODE)
        acl.add_node("2", "front_right", NodeSecurityRole.ACTUATOR_NODE)

        config = acl.generate_zenohd_acl_config()
        rules = config["access_control"]["rules"]
        assert len(rules) == 3
        node_ids = {r["id"] for r in rules}
        assert "acl_0" in node_ids
        assert "acl_1" in node_ids
        assert "acl_2" in node_ids


class TestKeyDerivationIntegration:
    """Test key derivation works with SecOC encode/decode."""

    def test_derived_key_works_for_secoc(self, tmp_path):
        km = KeyManager(key_dir=str(tmp_path))
        km.load_master_key()
        node_key = km.derive_node_key("1")

        counter = SequenceCounterState()
        data = {"value": 42.0}

        encoded = encode_secoc(
            data, "vehicle/front/1/sensor/temperature",
            counter, node_key,
        )
        decoded, _, crc_valid, mac_valid = decode_secoc(encoded, node_key)
        assert mac_valid is True
        assert crc_valid is True
        assert decoded["value"] == 42.0

    def test_different_node_keys_cant_decode(self, tmp_path):
        km = KeyManager(key_dir=str(tmp_path))
        km.load_master_key()
        key1 = km.derive_node_key("1")
        key2 = km.derive_node_key("2")

        counter = SequenceCounterState()
        encoded = encode_secoc(
            {"v": 1}, "vehicle/front/1/sensor/temperature",
            counter, key1,
        )
        _, _, _, mac_valid = decode_secoc(encoded, key2)
        assert mac_valid is False


class TestCertProvisioner:
    """Test CA and device certificate generation."""

    def test_generate_ca_creates_files(self, tmp_path):
        prov = CertProvisioner(cert_dir=str(tmp_path))
        cert_path, key_path = prov.generate_ca(output_dir=str(tmp_path))
        assert os.path.exists(cert_path)
        assert os.path.exists(key_path)

    def test_generate_device_cert_signed_by_ca(self, tmp_path):
        prov = CertProvisioner(cert_dir=str(tmp_path))
        ca_cert, ca_key = prov.generate_ca(output_dir=str(tmp_path))
        dev_cert, dev_key = prov.generate_device_cert(
            ca_cert, ca_key, "1", "192.168.1.2",
            output_dir=str(tmp_path),
        )
        assert os.path.exists(dev_cert)
        assert os.path.exists(dev_key)

    def test_verify_valid_cert(self, tmp_path):
        prov = CertProvisioner(cert_dir=str(tmp_path))
        ca_cert, ca_key = prov.generate_ca(output_dir=str(tmp_path))
        dev_cert, _ = prov.generate_device_cert(
            ca_cert, ca_key, "1", output_dir=str(tmp_path),
        )
        assert prov.verify_cert(dev_cert, ca_cert) is True

    def test_verify_invalid_cert_fails(self, tmp_path):
        prov = CertProvisioner(cert_dir=str(tmp_path))
        # Generate two separate CAs
        ca1_cert, ca1_key = prov.generate_ca(
            cn="CA1", output_dir=str(tmp_path / "ca1"),
        )
        ca2_cert, _ = prov.generate_ca(
            cn="CA2", output_dir=str(tmp_path / "ca2"),
        )
        # Sign cert with CA1 but verify against CA2
        dev_cert, _ = prov.generate_device_cert(
            ca1_cert, ca1_key, "1", output_dir=str(tmp_path / "dev"),
        )
        assert prov.verify_cert(dev_cert, ca2_cert) is False
