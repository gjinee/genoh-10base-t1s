/*******************************************************************************
 * E2E Protection — CRC-32 (IEEE 802.3), header encode/decode, sequence check
 *
 * Wire-compatible with Python: binascii.crc32, struct.pack(">HHBHI", ...)
 ******************************************************************************/

#include "e2e_protection.h"
#include <string.h>

/* ---- CRC-32 lookup table (reflected poly 0xEDB88320, Python binascii.crc32 compatible) ---- */
static uint32_t crc32_table[256];
static bool crc32_table_ready = false;

static void crc32_init_table(void) {
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t c = i;
        for (int j = 0; j < 8; j++)
            c = (c & 1) ? ((c >> 1) ^ 0xEDB88320U) : (c >> 1);
        crc32_table[i] = c;
    }
    crc32_table_ready = true;
}

uint32_t e2e_crc32(const uint8_t *data, size_t len) {
    if (!crc32_table_ready) crc32_init_table();
    uint32_t crc = 0xFFFFFFFF;
    for (size_t i = 0; i < len; i++)
        crc = crc32_table[(crc ^ data[i]) & 0xFF] ^ (crc >> 8);
    return crc ^ 0xFFFFFFFF;
}

/* ---- Big-endian helpers ---- */
static inline void put_be16(uint8_t *p, uint16_t v) {
    p[0] = (uint8_t)(v >> 8);
    p[1] = (uint8_t)(v);
}
static inline void put_be32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)(v >> 24);
    p[1] = (uint8_t)(v >> 16);
    p[2] = (uint8_t)(v >> 8);
    p[3] = (uint8_t)(v);
}
static inline uint16_t get_be16(const uint8_t *p) {
    return (uint16_t)((p[0] << 8) | p[1]);
}
static inline uint32_t get_be32(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8)  | (uint32_t)p[3];
}

/* ---- Encode ---- */
size_t e2e_encode(const uint8_t *payload, size_t payload_len,
                  uint16_t data_id, e2e_counter_state_t *counter,
                  uint8_t *out_buf, size_t out_buf_size) {
    size_t total = E2E_HEADER_SIZE + payload_len;
    if (out_buf_size < total) return 0;

    uint16_t seq   = counter->seq;
    uint8_t  alive = counter->alive;
    counter->seq   = (uint16_t)((counter->seq + 1) % 65536);
    counter->alive = (uint8_t)((counter->alive + 1) % 256);

    /* CRC input: header fields (7 bytes) + payload */
    uint8_t hdr_fields[7];
    put_be16(hdr_fields + 0, data_id);
    put_be16(hdr_fields + 2, seq);
    hdr_fields[4] = alive;
    put_be16(hdr_fields + 5, (uint16_t)payload_len);

    /* Compute CRC-32 over header_fields(7B) + payload */
    uint8_t crc_input[7 + 512];  /* max payload 512 */
    size_t crc_len = 7 + payload_len;
    if (crc_len > sizeof(crc_input)) return 0;
    memcpy(crc_input, hdr_fields, 7);
    memcpy(crc_input + 7, payload, payload_len);
    uint32_t crc = e2e_crc32(crc_input, crc_len);

    /* Write header: data_id(2) + seq(2) + alive(1) + length(2) + crc(4) = 11B */
    memcpy(out_buf, hdr_fields, 7);
    put_be32(out_buf + 7, crc);

    /* Write payload after header */
    memcpy(out_buf + E2E_HEADER_SIZE, payload, payload_len);

    return total;
}

/* ---- Decode ---- */
e2e_status_t e2e_decode(const uint8_t *buf, size_t buf_len,
                        e2e_header_t *header,
                        const uint8_t **payload_out, size_t *payload_len_out) {
    if (buf_len < E2E_HEADER_SIZE)
        return E2E_ERR_TOO_SHORT;

    /* Parse header */
    header->data_id          = get_be16(buf + 0);
    header->sequence_counter = get_be16(buf + 2);
    header->alive_counter    = buf[4];
    header->length           = get_be16(buf + 5);
    header->crc32            = get_be32(buf + 7);

    /* Verify length */
    size_t expected_total = (size_t)E2E_HEADER_SIZE + header->length;
    if (expected_total != buf_len)
        return E2E_ERR_LENGTH_MISMATCH;

    /* Recompute CRC over header_fields(7B) + payload */
    size_t crc_len = 7 + header->length;
    uint8_t crc_input[7 + 512];
    if (crc_len > sizeof(crc_input)) return E2E_ERR_TOO_SHORT;
    memcpy(crc_input, buf, 7);  /* header fields without crc */
    memcpy(crc_input + 7, buf + E2E_HEADER_SIZE, header->length);
    uint32_t computed_crc = e2e_crc32(crc_input, crc_len);

    if (computed_crc != header->crc32)
        return E2E_ERR_CRC;

    *payload_out     = buf + E2E_HEADER_SIZE;
    *payload_len_out = header->length;
    return E2E_OK;
}

/* ---- Sequence Checker ---- */
void e2e_seq_checker_init(e2e_seq_checker_t *chk, uint16_t max_gap) {
    chk->last_seq    = -1;
    chk->max_gap     = max_gap;
    chk->valid_count = 0;
    chk->init_count  = 3;
}

e2e_status_t e2e_seq_check(e2e_seq_checker_t *chk, uint16_t seq) {
    if (chk->last_seq < 0) {
        chk->last_seq    = (int32_t)seq;
        chk->valid_count = 1;
        return E2E_OK;  /* first message */
    }

    uint16_t delta = (uint16_t)((seq - (uint16_t)chk->last_seq) & 0xFFFF);

    if (delta == 0)
        return E2E_ERR_SEQ_REPEATED;

    if (delta <= chk->max_gap) {
        chk->last_seq    = (int32_t)seq;
        chk->valid_count++;
        return E2E_OK;
    }

    /* Gap exceeds ASIL-D limit */
    chk->last_seq    = (int32_t)seq;
    chk->valid_count = 0;
    return E2E_ERR_SEQ_GAP;
}
