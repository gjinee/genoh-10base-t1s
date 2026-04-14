/* Minimal stubs for crypto functions used by TCP stack.
 * These are simple implementations — NOT cryptographically secure.
 * For production, integrate a proper crypto library. */
#include <stdint.h>
#include <string.h>

typedef struct { uint32_t state[4]; uint8_t buffer[64]; uint32_t count; } CRYPT_MD5_CTX;

int CRYPT_MD5_Initialize(CRYPT_MD5_CTX *ctx) {
    memset(ctx, 0, sizeof(*ctx));
    ctx->state[0] = 0x67452301;
    ctx->state[1] = 0xefcdab89;
    ctx->state[2] = 0x98badcfe;
    ctx->state[3] = 0x10325476;
    return 0;
}

int CRYPT_MD5_DataAdd(CRYPT_MD5_CTX *ctx, const uint8_t *data, unsigned int len) {
    /* Simplified: XOR data into state for basic uniqueness */
    for (unsigned int i = 0; i < len; i++)
        ctx->state[i % 4] ^= (uint32_t)data[i] << ((i % 4) * 8);
    ctx->count += len;
    return 0;
}

int CRYPT_MD5_Finalize(CRYPT_MD5_CTX *ctx, uint8_t *digest) {
    memcpy(digest, ctx->state, 16);
    return 0;
}

/* Pseudo-random number generator for TCP stack */
static uint32_t prng_next(void) {
    static uint32_t seed = 0x12345678;
    volatile uint32_t *systick_val = (volatile uint32_t *)0xE000E018;
    seed ^= *systick_val;
    seed = seed * 1103515245 + 12345;
    return seed;
}

uint32_t SYS_RANDOM_CryptoGet(void) {
    return prng_next();
}

int SYS_RANDOM_CryptoBlockGet(void *buf, unsigned int len) {
    uint8_t *p = (uint8_t *)buf;
    for (unsigned int i = 0; i < len; i++)
        p[i] = (uint8_t)(prng_next() >> 16);
    return 0;
}
