#!/bin/bash
# Generate device certificate signed by CA
# See cybersecurity.md Section 4.1
#
# Usage: ./generate_device_cert.sh <node_id> <ip_addr> [cert_dir] [validity_days]
#   Example: ./generate_device_cert.sh master 192.168.1.1
#   Example: ./generate_device_cert.sh 1 192.168.1.2

set -e

NODE_ID="${1:?Usage: $0 <node_id> <ip_addr> [cert_dir] [validity_days]}"
IP_ADDR="${2:?Usage: $0 <node_id> <ip_addr> [cert_dir] [validity_days]}"
CERT_DIR="${3:-/etc/zenoh/certs}"
VALIDITY="${4:-365}"  # 1 year

CA_CERT="$CERT_DIR/ca.crt"
CA_KEY="$CERT_DIR/ca.key"

if [ ! -f "$CA_CERT" ] || [ ! -f "$CA_KEY" ]; then
    echo "ERROR: CA cert/key not found. Run generate_ca.sh first."
    exit 1
fi

CN="zenoh-node-$NODE_ID"
KEY_FILE="$CERT_DIR/$CN.key"
CSR_FILE="$CERT_DIR/$CN.csr"
CERT_FILE="$CERT_DIR/$CN.crt"

echo "=== Generating certificate for $CN (IP: $IP_ADDR) ==="

# Generate key + CSR
openssl req -newkey ec \
    -pkeyopt ec_paramgen_curve:prime256v1 \
    -keyout "$KEY_FILE" \
    -out "$CSR_FILE" \
    -nodes \
    -subj "/CN=$CN/O=Zenoh-10BASE-T1S/OU=zone-controller"

# Sign with CA (with SAN extension)
openssl x509 -req \
    -in "$CSR_FILE" \
    -CA "$CA_CERT" \
    -CAkey "$CA_KEY" \
    -CAcreateserial \
    -out "$CERT_FILE" \
    -days "$VALIDITY" \
    -extfile <(echo "subjectAltName=IP:$IP_ADDR")

chmod 600 "$KEY_FILE"
chmod 644 "$CERT_FILE"
rm -f "$CSR_FILE"

echo "Certificate: $CERT_FILE"
echo "Private key: $KEY_FILE"
echo "=== Done ==="
