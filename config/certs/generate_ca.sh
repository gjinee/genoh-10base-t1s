#!/bin/bash
# Generate Root CA certificate for Zenoh 10BASE-T1S mTLS
# See cybersecurity.md Section 4.1

set -e

CERT_DIR="${1:-/etc/zenoh/certs}"
CA_CN="${2:-Zenoh-10BASE-T1S Root CA}"
VALIDITY="${3:-730}"  # 2 years

mkdir -p "$CERT_DIR"

echo "=== Generating Root CA ==="
openssl req -x509 -newkey ec \
    -pkeyopt ec_paramgen_curve:prime256v1 \
    -keyout "$CERT_DIR/ca.key" \
    -out "$CERT_DIR/ca.crt" \
    -days "$VALIDITY" \
    -nodes \
    -subj "/CN=$CA_CN/O=Zenoh-10BASE-T1S/OU=Root-CA"

chmod 600 "$CERT_DIR/ca.key"
chmod 644 "$CERT_DIR/ca.crt"

echo "CA certificate: $CERT_DIR/ca.crt"
echo "CA private key: $CERT_DIR/ca.key"
echo "=== Done ==="
