#ifndef SECOC_H
#define SECOC_H
/*******************************************************************************
 * SecOC — Secure Onboard Communication (HMAC-SHA256)
 *
 * Wire format appended after E2E message:
 *   [E2E msg (11+N bytes)] [Freshness 8B] [MAC 16B]
 *
 * Freshness (big-endian): timestamp_ms(6B) + counter(2B)
 * MAC: HMAC-SHA256 truncated to 16 bytes
 *
 * Compatible with Python master: src/master/secoc.py
 ******************************************************************************/

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#define SECOC_FRESHNESS_SIZE  8
#define SECOC_MAC_SIZE       16
#define SECOC_OVERHEAD       (SECOC_FRESHNESS_SIZE + SECOC_MAC_SIZE)  /* 24B */
#define SECOC_KEY_SIZE       32  /* 256-bit HMAC key */

/* Pre-shared HMAC key (32 bytes, hex: 00112233...1e1f) for testing */
extern const uint8_t SECOC_TEST_KEY[SECOC_KEY_SIZE];

/* SecOC freshness counter state */
typedef struct {
    uint16_t counter;
} secoc_freshness_t;

/* Encode: append freshness + MAC to an E2E message.
 * out_buf must be >= e2e_len + SECOC_OVERHEAD.
 * Returns total bytes written, or 0 on error. */
size_t secoc_encode(const uint8_t *e2e_msg, size_t e2e_len,
                    const uint8_t *key,
                    secoc_freshness_t *freshness,
                    uint8_t *out_buf, size_t out_buf_size);

/* Replay protection window (milliseconds) */
#define SECOC_REPLAY_WINDOW_MS  5000

/* Decode: verify MAC, check freshness window, strip overhead.
 * On success: *e2e_len_out = length without SecOC overhead.
 * Returns true if MAC valid and freshness within window. */
bool secoc_decode(const uint8_t *buf, size_t buf_len,
                  const uint8_t *key,
                  size_t *e2e_len_out);

/* Decode with replay info: also reports if replay was detected */
typedef struct {
    bool mac_valid;
    bool freshness_valid;
    uint64_t freshness_ts;
    uint16_t freshness_counter;
} secoc_decode_result_t;

bool secoc_decode_ex(const uint8_t *buf, size_t buf_len,
                     const uint8_t *key,
                     size_t *e2e_len_out,
                     secoc_decode_result_t *result);

/*--- Low-level crypto ---*/
void sha256(const uint8_t *data, size_t len, uint8_t out[32]);
void hmac_sha256(const uint8_t *key, size_t key_len,
                 const uint8_t *data, size_t data_len,
                 uint8_t out[32]);

#endif /* SECOC_H */
