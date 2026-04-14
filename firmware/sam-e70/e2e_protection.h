#ifndef E2E_PROTECTION_H
#define E2E_PROTECTION_H
/*******************************************************************************
 * E2E (End-to-End) Protection — AUTOSAR-style, ASIL-D
 *
 * Wire format (big-endian, 11 bytes):
 *   data_id(2) | seq(2) | alive(1) | length(2) | crc32(4)
 *
 * Compatible with Python master: src/common/e2e_protection.py
 ******************************************************************************/

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

/* E2E header size: 2+2+1+2+4 = 11 bytes */
#define E2E_HEADER_SIZE  11

/* Data IDs for MCU key expressions */
#define DATA_ID_STEERING   0x1010
#define DATA_ID_HEADLIGHT  0x2010
#define DATA_ID_HAZARD     0x2011

/* ASIL-D: max sequence gap = 1 */
#define E2E_ASILD_MAX_GAP  1

/* Return codes */
typedef enum {
    E2E_OK = 0,
    E2E_ERR_CRC,
    E2E_ERR_SEQ_REPEATED,
    E2E_ERR_SEQ_GAP,
    E2E_ERR_TOO_SHORT,
    E2E_ERR_LENGTH_MISMATCH,
} e2e_status_t;

/* E2E header (parsed) */
typedef struct {
    uint16_t data_id;
    uint16_t sequence_counter;
    uint8_t  alive_counter;
    uint16_t length;
    uint32_t crc32;
} e2e_header_t;

/* Transmit-side sequence counter state */
typedef struct {
    uint16_t seq;
    uint8_t  alive;
} e2e_counter_state_t;

/* Receive-side sequence checker (ASIL-D) */
typedef struct {
    int32_t  last_seq;      /* -1 = not initialized */
    uint16_t max_gap;
    uint16_t valid_count;
    uint16_t init_count;    /* messages before leaving INIT */
} e2e_seq_checker_t;

/*--- CRC-32 ---*/
uint32_t e2e_crc32(const uint8_t *data, size_t len);

/*--- Encode ---*/
/* Encode payload with E2E header.  Writes to out_buf (must be >= E2E_HEADER_SIZE + payload_len).
 * Returns total bytes written. */
size_t e2e_encode(const uint8_t *payload, size_t payload_len,
                  uint16_t data_id, e2e_counter_state_t *counter,
                  uint8_t *out_buf, size_t out_buf_size);

/*--- Decode ---*/
/* Decode and verify an E2E message.
 * On success: header is populated, *payload_out points into buf, *payload_len_out is set.
 * Returns E2E_OK or error code. */
e2e_status_t e2e_decode(const uint8_t *buf, size_t buf_len,
                        e2e_header_t *header,
                        const uint8_t **payload_out, size_t *payload_len_out);

/*--- Sequence Checker ---*/
void e2e_seq_checker_init(e2e_seq_checker_t *chk, uint16_t max_gap);
e2e_status_t e2e_seq_check(e2e_seq_checker_t *chk, uint16_t seq);

#endif /* E2E_PROTECTION_H */
