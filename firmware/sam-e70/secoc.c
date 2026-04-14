/*******************************************************************************
 * SecOC — HMAC-SHA256 authentication + freshness value
 *
 * Includes software SHA-256 (FIPS 180-4) and HMAC (RFC 2104).
 * Wire-compatible with Python master's secoc_encode/secoc_decode.
 ******************************************************************************/

#include "secoc.h"
#include <string.h>
#include "FreeRTOS.h"
#include "task.h"

/* Pre-shared test key: 0x00,0x01,...,0x1F (32 bytes) */
const uint8_t SECOC_TEST_KEY[SECOC_KEY_SIZE] = {
    0x00,0x01,0x02,0x03,0x04,0x05,0x06,0x07,
    0x08,0x09,0x0A,0x0B,0x0C,0x0D,0x0E,0x0F,
    0x10,0x11,0x12,0x13,0x14,0x15,0x16,0x17,
    0x18,0x19,0x1A,0x1B,0x1C,0x1D,0x1E,0x1F,
};

/* ========================================================================= */
/*  SHA-256 (FIPS 180-4)                                                     */
/* ========================================================================= */

static const uint32_t K[64] = {
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
};

#define ROTR(x,n) (((x)>>(n))|((x)<<(32-(n))))
#define CH(x,y,z)  (((x)&(y))^((~(x))&(z)))
#define MAJ(x,y,z) (((x)&(y))^((x)&(z))^((y)&(z)))
#define EP0(x) (ROTR(x,2)^ROTR(x,13)^ROTR(x,22))
#define EP1(x) (ROTR(x,6)^ROTR(x,11)^ROTR(x,25))
#define SIG0(x) (ROTR(x,7)^ROTR(x,18)^((x)>>3))
#define SIG1(x) (ROTR(x,17)^ROTR(x,19)^((x)>>10))

typedef struct {
    uint32_t state[8];
    uint8_t  buf[64];
    uint64_t total_len;
    uint8_t  buf_len;
} sha256_ctx_t;

static void sha256_init(sha256_ctx_t *ctx) {
    ctx->state[0] = 0x6a09e667; ctx->state[1] = 0xbb67ae85;
    ctx->state[2] = 0x3c6ef372; ctx->state[3] = 0xa54ff53a;
    ctx->state[4] = 0x510e527f; ctx->state[5] = 0x9b05688c;
    ctx->state[6] = 0x1f83d9ab; ctx->state[7] = 0x5be0cd19;
    ctx->total_len = 0;
    ctx->buf_len   = 0;
}

static void sha256_transform(sha256_ctx_t *ctx, const uint8_t block[64]) {
    uint32_t w[64], a, b, c, d, e, f, g, h, t1, t2;

    for (int i = 0; i < 16; i++)
        w[i] = ((uint32_t)block[i*4]<<24) | ((uint32_t)block[i*4+1]<<16) |
               ((uint32_t)block[i*4+2]<<8) | (uint32_t)block[i*4+3];
    for (int i = 16; i < 64; i++)
        w[i] = SIG1(w[i-2]) + w[i-7] + SIG0(w[i-15]) + w[i-16];

    a=ctx->state[0]; b=ctx->state[1]; c=ctx->state[2]; d=ctx->state[3];
    e=ctx->state[4]; f=ctx->state[5]; g=ctx->state[6]; h=ctx->state[7];

    for (int i = 0; i < 64; i++) {
        t1 = h + EP1(e) + CH(e,f,g) + K[i] + w[i];
        t2 = EP0(a) + MAJ(a,b,c);
        h=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
    }

    ctx->state[0]+=a; ctx->state[1]+=b; ctx->state[2]+=c; ctx->state[3]+=d;
    ctx->state[4]+=e; ctx->state[5]+=f; ctx->state[6]+=g; ctx->state[7]+=h;
}

static void sha256_update(sha256_ctx_t *ctx, const uint8_t *data, size_t len) {
    ctx->total_len += len;
    while (len > 0) {
        size_t space = 64 - ctx->buf_len;
        size_t chunk = (len < space) ? len : space;
        memcpy(ctx->buf + ctx->buf_len, data, chunk);
        ctx->buf_len += (uint8_t)chunk;
        data += chunk;
        len  -= chunk;
        if (ctx->buf_len == 64) {
            sha256_transform(ctx, ctx->buf);
            ctx->buf_len = 0;
        }
    }
}

static void sha256_final(sha256_ctx_t *ctx, uint8_t out[32]) {
    uint64_t bit_len = ctx->total_len * 8;
    uint8_t pad = 0x80;
    sha256_update(ctx, &pad, 1);
    pad = 0;
    while (ctx->buf_len != 56)
        sha256_update(ctx, &pad, 1);
    uint8_t len_be[8];
    for (int i = 7; i >= 0; i--) { len_be[i] = (uint8_t)bit_len; bit_len >>= 8; }
    sha256_update(ctx, len_be, 8);
    for (int i = 0; i < 8; i++) {
        out[i*4+0] = (uint8_t)(ctx->state[i] >> 24);
        out[i*4+1] = (uint8_t)(ctx->state[i] >> 16);
        out[i*4+2] = (uint8_t)(ctx->state[i] >> 8);
        out[i*4+3] = (uint8_t)(ctx->state[i]);
    }
}

void sha256(const uint8_t *data, size_t len, uint8_t out[32]) {
    sha256_ctx_t ctx;
    sha256_init(&ctx);
    sha256_update(&ctx, data, len);
    sha256_final(&ctx, out);
}

/* ========================================================================= */
/*  HMAC-SHA256 (RFC 2104)                                                   */
/* ========================================================================= */

void hmac_sha256(const uint8_t *key, size_t key_len,
                 const uint8_t *data, size_t data_len,
                 uint8_t out[32]) {
    uint8_t k_pad[64];
    uint8_t tk[32];

    /* If key > 64 bytes, hash it first */
    if (key_len > 64) {
        sha256(key, key_len, tk);
        key = tk;
        key_len = 32;
    }

    /* Inner: SHA256( (key ^ ipad) || data ) */
    memset(k_pad, 0x36, 64);
    for (size_t i = 0; i < key_len; i++) k_pad[i] ^= key[i];

    sha256_ctx_t ctx;
    sha256_init(&ctx);
    sha256_update(&ctx, k_pad, 64);
    sha256_update(&ctx, data, data_len);
    uint8_t inner[32];
    sha256_final(&ctx, inner);

    /* Outer: SHA256( (key ^ opad) || inner ) */
    memset(k_pad, 0x5C, 64);
    for (size_t i = 0; i < key_len; i++) k_pad[i] ^= key[i];

    sha256_init(&ctx);
    sha256_update(&ctx, k_pad, 64);
    sha256_update(&ctx, inner, 32);
    sha256_final(&ctx, out);
}

/* ========================================================================= */
/*  SecOC Encode / Decode                                                    */
/* ========================================================================= */

static void put_be16(uint8_t *p, uint16_t v) {
    p[0] = (uint8_t)(v >> 8);
    p[1] = (uint8_t)(v);
}
static void put_be48(uint8_t *p, uint64_t v) {
    p[0] = (uint8_t)(v >> 40);
    p[1] = (uint8_t)(v >> 32);
    p[2] = (uint8_t)(v >> 24);
    p[3] = (uint8_t)(v >> 16);
    p[4] = (uint8_t)(v >> 8);
    p[5] = (uint8_t)(v);
}

static uint64_t get_tick_ms(void) {
    /* FreeRTOS tick count as milliseconds (configTICK_RATE_HZ = 1000) */
    return (uint64_t)xTaskGetTickCount();
}

size_t secoc_encode(const uint8_t *e2e_msg, size_t e2e_len,
                    const uint8_t *key,
                    secoc_freshness_t *freshness,
                    uint8_t *out_buf, size_t out_buf_size) {
    size_t total = e2e_len + SECOC_OVERHEAD;
    if (out_buf_size < total) return 0;

    /* Copy E2E message */
    memcpy(out_buf, e2e_msg, e2e_len);

    /* Build freshness value: timestamp_ms(6B) + counter(2B) */
    uint8_t fv[SECOC_FRESHNESS_SIZE];
    uint64_t ts = get_tick_ms();
    put_be48(fv, ts);
    put_be16(fv + 6, freshness->counter);
    freshness->counter++;

    /* Append freshness */
    memcpy(out_buf + e2e_len, fv, SECOC_FRESHNESS_SIZE);

    /* Compute HMAC-SHA256(key, e2e_msg + freshness) → truncate to 16B */
    size_t hmac_input_len = e2e_len + SECOC_FRESHNESS_SIZE;
    uint8_t hmac_input[600];
    if (hmac_input_len > sizeof(hmac_input)) return 0;
    memcpy(hmac_input, e2e_msg, e2e_len);
    memcpy(hmac_input + e2e_len, fv, SECOC_FRESHNESS_SIZE);

    uint8_t full_mac[32];
    hmac_sha256(key, SECOC_KEY_SIZE, hmac_input, hmac_input_len, full_mac);

    /* Append truncated MAC (first 16 bytes) */
    memcpy(out_buf + e2e_len + SECOC_FRESHNESS_SIZE, full_mac, SECOC_MAC_SIZE);

    return total;
}

static uint64_t get_freshness_ts(const uint8_t *fv) {
    /* Parse 6-byte big-endian timestamp from freshness value */
    uint64_t ts = 0;
    for (int i = 0; i < 6; i++)
        ts = (ts << 8) | fv[i];
    return ts;
}

static uint16_t get_freshness_counter(const uint8_t *fv) {
    return (uint16_t)((fv[6] << 8) | fv[7]);
}

bool secoc_decode_ex(const uint8_t *buf, size_t buf_len,
                     const uint8_t *key,
                     size_t *e2e_len_out,
                     secoc_decode_result_t *result) {
    result->mac_valid = false;
    result->freshness_valid = false;
    result->freshness_ts = 0;
    result->freshness_counter = 0;

    if (buf_len < SECOC_OVERHEAD)
        return false;

    size_t e2e_len = buf_len - SECOC_OVERHEAD;
    const uint8_t *freshness = buf + e2e_len;
    const uint8_t *mac       = buf + e2e_len + SECOC_FRESHNESS_SIZE;

    /* Parse freshness value */
    result->freshness_ts = get_freshness_ts(freshness);
    result->freshness_counter = get_freshness_counter(freshness);

    /* Verify MAC: HMAC-SHA256(key, e2e_msg + freshness) */
    size_t hmac_input_len = e2e_len + SECOC_FRESHNESS_SIZE;
    uint8_t hmac_input[600];
    if (hmac_input_len > sizeof(hmac_input)) return false;
    memcpy(hmac_input, buf, e2e_len);
    memcpy(hmac_input + e2e_len, freshness, SECOC_FRESHNESS_SIZE);

    uint8_t computed_mac[32];
    hmac_sha256(key, SECOC_KEY_SIZE, hmac_input, hmac_input_len, computed_mac);

    /* Constant-time comparison */
    uint8_t diff = 0;
    for (int i = 0; i < SECOC_MAC_SIZE; i++)
        diff |= computed_mac[i] ^ mac[i];

    result->mac_valid = (diff == 0);
    if (!result->mac_valid)
        return false;

    /* Replay protection: check freshness within window */
    uint64_t local_tick = get_tick_ms();
    int64_t delta = (int64_t)result->freshness_ts - (int64_t)local_tick;
    if (delta < 0) delta = -delta;
    result->freshness_valid = (delta <= SECOC_REPLAY_WINDOW_MS);

    *e2e_len_out = e2e_len;
    return result->mac_valid;  /* Return true if MAC valid (freshness check in caller) */
}

bool secoc_decode(const uint8_t *buf, size_t buf_len,
                  const uint8_t *key,
                  size_t *e2e_len_out) {
    secoc_decode_result_t result;
    return secoc_decode_ex(buf, buf_len, key, e2e_len_out, &result);
}
