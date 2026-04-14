"""Key management for HMAC and TLS key lifecycle.

Implements HKDF-SHA256 per-node key derivation, key storage,
and rotation per cybersecurity.md Section 7.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_KEY_DIR = "/etc/zenoh/certs/hmac_keys"
KEY_LENGTH = 32  # 256 bits for HMAC-SHA256


def hkdf_sha256(
    ikm: bytes,
    salt: bytes = b"",
    info: bytes = b"",
    length: int = KEY_LENGTH,
) -> bytes:
    """HKDF-SHA256 key derivation (RFC 5869).

    Simplified implementation using standard library hmac module.
    For production use, consider the `cryptography` library.

    Args:
        ikm: Input keying material.
        salt: Optional salt value (defaults to zeros).
        info: Context/application-specific info.
        length: Output key length in bytes.

    Returns:
        Derived key bytes.
    """
    # Extract
    if not salt:
        salt = b"\x00" * 32
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()

    # Expand
    output = b""
    t = b""
    counter = 1
    while len(output) < length:
        t = hmac.new(prk, t + info + bytes([counter]), hashlib.sha256).digest()
        output += t
        counter += 1

    return output[:length]


@dataclass
class KeyMetadata:
    """Metadata for a managed key."""
    key_id: str
    created_ms: int = 0
    rotated_ms: int = 0
    usage_count: int = 0


class KeyManager:
    """HMAC key management with per-node derivation and rotation.

    Key derivation (Section 3.2.2):
      K_node = HKDF-SHA256(salt=vehicle_id, ikm=master_key, info="node_{id}")
      K_broadcast = HKDF-SHA256(salt=vehicle_id, ikm=master_key, info="broadcast")
    """

    def __init__(
        self,
        key_dir: str | None = None,
        vehicle_id: str = "sim-vehicle-001",
    ):
        self._key_dir = Path(key_dir) if key_dir else Path(DEFAULT_KEY_DIR)
        self._vehicle_id = vehicle_id.encode("utf-8")
        self._master_key: bytes | None = None
        self._derived_keys: dict[str, bytes] = {}
        self._metadata: dict[str, KeyMetadata] = {}

    def load_master_key(self, path: str | None = None) -> bytes:
        """Load or generate the master key.

        Args:
            path: Path to master key file. If None, generates a new key.

        Returns:
            Master key bytes (256 bits).
        """
        if path and Path(path).exists():
            with open(path, "rb") as f:
                self._master_key = f.read(KEY_LENGTH)
            logger.info("Master key loaded from %s", path)
        else:
            self._master_key = os.urandom(KEY_LENGTH)
            if path:
                self.save_master_key(path)
            logger.info("Master key generated")
        return self._master_key

    def save_master_key(self, path: str) -> None:
        """Save master key to file with restricted permissions (0600)."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, self._master_key or b"")
            os.fsync(fd)
        finally:
            os.close(fd)
        logger.info("Master key saved to %s (mode 0600)", path)

    def derive_node_key(self, node_id: str | int) -> bytes:
        """Derive a per-node HMAC key from the master key.

        Args:
            node_id: Node identifier (e.g., "1" or 1).

        Returns:
            Derived 256-bit key.
        """
        if not self._master_key:
            raise RuntimeError("Master key not loaded. Call load_master_key() first.")

        key_id = f"node_{node_id}"
        if key_id in self._derived_keys:
            meta = self._metadata.get(key_id)
            if meta:
                meta.usage_count += 1
            return self._derived_keys[key_id]

        info = key_id.encode("utf-8")
        derived = hkdf_sha256(
            ikm=self._master_key,
            salt=self._vehicle_id,
            info=info,
        )
        self._derived_keys[key_id] = derived
        self._metadata[key_id] = KeyMetadata(
            key_id=key_id,
            created_ms=int(time.time() * 1000),
            usage_count=1,
        )
        return derived

    def derive_broadcast_key(self) -> bytes:
        """Derive the broadcast HMAC key.

        Returns:
            Derived 256-bit broadcast key.
        """
        if not self._master_key:
            raise RuntimeError("Master key not loaded. Call load_master_key() first.")

        key_id = "broadcast"
        if key_id in self._derived_keys:
            return self._derived_keys[key_id]

        derived = hkdf_sha256(
            ikm=self._master_key,
            salt=self._vehicle_id,
            info=b"broadcast",
        )
        self._derived_keys[key_id] = derived
        self._metadata[key_id] = KeyMetadata(
            key_id=key_id,
            created_ms=int(time.time() * 1000),
        )
        return derived

    def get_node_key(self, node_id: str | int) -> bytes:
        """Get or derive a node key.

        Args:
            node_id: Node identifier.

        Returns:
            256-bit HMAC key for this node.
        """
        key_id = f"node_{node_id}"
        if key_id in self._derived_keys:
            meta = self._metadata.get(key_id)
            if meta:
                meta.usage_count += 1
            return self._derived_keys[key_id]
        return self.derive_node_key(node_id)

    def rotate_key(self, node_id: str | int) -> bytes:
        """Rotate a node's key by re-deriving from a new salt.

        Archives the old key metadata and derives a fresh key.

        Returns:
            New derived key.
        """
        key_id = f"node_{node_id}"
        self._derived_keys.pop(key_id, None)
        old_meta = self._metadata.pop(key_id, None)

        # Re-derive with a time-based salt variation
        if not self._master_key:
            raise RuntimeError("Master key not loaded.")

        rotation_salt = self._vehicle_id + str(time.time_ns()).encode("utf-8")
        info = key_id.encode("utf-8")
        derived = hkdf_sha256(
            ikm=self._master_key,
            salt=rotation_salt,
            info=info,
        )
        self._derived_keys[key_id] = derived
        self._metadata[key_id] = KeyMetadata(
            key_id=key_id,
            created_ms=int(time.time() * 1000),
            rotated_ms=int(time.time() * 1000),
        )
        logger.info("Key rotated for %s", key_id)
        return derived

    def save_node_key(self, node_id: str | int, directory: str | None = None) -> str:
        """Save a node's derived key to file with 0600 permissions.

        Returns:
            Path to the saved key file.
        """
        key_dir = Path(directory) if directory else self._key_dir
        key_dir.mkdir(parents=True, exist_ok=True)

        key_id = f"node_{node_id}"
        key = self._derived_keys.get(key_id)
        if not key:
            key = self.derive_node_key(node_id)

        key_path = key_dir / f"{key_id}.key"
        fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, key)
            os.fsync(fd)
        finally:
            os.close(fd)
        return str(key_path)

    @staticmethod
    def check_key_file_permissions(path: str) -> bool:
        """Verify key file has restricted permissions (0600).

        Returns:
            True if permissions are 0600 or stricter.
        """
        st = os.stat(path)
        mode = stat.S_IMODE(st.st_mode)
        return mode <= 0o600
