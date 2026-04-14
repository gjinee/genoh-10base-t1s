"""Certificate provisioner for TLS/mTLS PKI infrastructure.

Generates CA and device certificates for Zenoh TLS communication.
See cybersecurity.md Section 4.1 and 7.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CERT_DIR = "/etc/zenoh/certs"


class CertProvisioner:
    """Generates X.509 certificates for Zenoh mTLS.

    PKI hierarchy:
      Root CA → Vehicle Sub-CA → Device Certs (Master, Slave 1..N)
    """

    def __init__(self, cert_dir: str | None = None):
        self._cert_dir = Path(cert_dir) if cert_dir else Path(DEFAULT_CERT_DIR)

    def generate_ca(
        self,
        cn: str = "Zenoh-10BASE-T1S Root CA",
        validity_days: int = 730,
        output_dir: str | None = None,
    ) -> tuple[str, str]:
        """Generate a self-signed CA certificate and private key.

        Args:
            cn: Common Name for the CA.
            validity_days: Certificate validity in days.
            output_dir: Output directory (defaults to cert_dir).

        Returns:
            Tuple of (cert_path, key_path).
        """
        out = Path(output_dir) if output_dir else self._cert_dir
        out.mkdir(parents=True, exist_ok=True)

        key_path = out / "ca.key"
        cert_path = out / "ca.crt"

        cmd = [
            "openssl", "req", "-x509", "-newkey", "ec",
            "-pkeyopt", "ec_paramgen_curve:prime256v1",
            "-keyout", str(key_path),
            "-out", str(cert_path),
            "-days", str(validity_days),
            "-nodes",
            "-subj", f"/CN={cn}/O=Zenoh-10BASE-T1S/OU=Root-CA",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"CA generation failed: {result.stderr}")

        os.chmod(str(key_path), 0o600)
        logger.info("CA generated: %s, %s", cert_path, key_path)
        return str(cert_path), str(key_path)

    def generate_device_cert(
        self,
        ca_cert: str,
        ca_key: str,
        node_id: str | int,
        ip_addr: str = "",
        validity_days: int = 365,
        output_dir: str | None = None,
    ) -> tuple[str, str]:
        """Generate a device certificate signed by the CA.

        Args:
            ca_cert: Path to CA certificate.
            ca_key: Path to CA private key.
            node_id: Node identifier for CN.
            ip_addr: IP address for SAN.
            validity_days: Certificate validity.
            output_dir: Output directory.

        Returns:
            Tuple of (cert_path, key_path).
        """
        out = Path(output_dir) if output_dir else self._cert_dir
        out.mkdir(parents=True, exist_ok=True)

        key_path = out / f"node_{node_id}.key"
        csr_path = out / f"node_{node_id}.csr"
        cert_path = out / f"node_{node_id}.crt"
        cn = f"zenoh-node-{node_id}"

        # Generate key + CSR
        cmd_csr = [
            "openssl", "req", "-newkey", "ec",
            "-pkeyopt", "ec_paramgen_curve:prime256v1",
            "-keyout", str(key_path),
            "-out", str(csr_path),
            "-nodes",
            "-subj", f"/CN={cn}/O=Zenoh-10BASE-T1S/OU=zone-controller",
        ]
        result = subprocess.run(cmd_csr, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"CSR generation failed: {result.stderr}")

        # Sign with CA
        cmd_sign = [
            "openssl", "x509", "-req",
            "-in", str(csr_path),
            "-CA", ca_cert,
            "-CAkey", ca_key,
            "-CAcreateserial",
            "-out", str(cert_path),
            "-days", str(validity_days),
        ]
        if ip_addr:
            cmd_sign.extend(["-extfile", "/dev/stdin"])
            ext_data = f"subjectAltName=IP:{ip_addr}"
            result = subprocess.run(
                cmd_sign, input=ext_data, capture_output=True, text=True, timeout=30,
            )
        else:
            result = subprocess.run(cmd_sign, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            raise RuntimeError(f"Cert signing failed: {result.stderr}")

        os.chmod(str(key_path), 0o600)
        csr_path.unlink(missing_ok=True)
        logger.info("Device cert generated for %s: %s", cn, cert_path)
        return str(cert_path), str(key_path)

    def verify_cert(self, cert_path: str, ca_cert_path: str) -> bool:
        """Verify a certificate against the CA.

        Returns:
            True if verification succeeds.
        """
        cmd = ["openssl", "verify", "-CAfile", ca_cert_path, cert_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.returncode == 0
