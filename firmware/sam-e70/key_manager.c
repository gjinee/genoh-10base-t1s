/*******************************************************************************
 * Key Manager — HMAC-SHA256 key derivation + epoch management
 ******************************************************************************/

#include "key_manager.h"
#include "secoc.h"  /* for hmac_sha256 */
#include "definitions.h"
#include <string.h>
#include <stdio.h>

static void derive_node_key(key_manager_t *km) {
    /* node_key = HMAC-SHA256(master_key, "epoch:XXXX:" + node_id) */
    char input[48];
    int len = snprintf(input, sizeof(input), "epoch:%u:%s",
                       km->epoch, km->node_id);
    hmac_sha256(km->master_key, KEY_SIZE,
                (const uint8_t *)input, (size_t)len,
                km->node_key);
}

void key_init(key_manager_t *km, const uint8_t *master_key,
              const char *node_id) {
    memcpy(km->master_key, master_key, KEY_SIZE);
    strncpy(km->node_id, node_id, sizeof(km->node_id) - 1);
    km->node_id[sizeof(km->node_id) - 1] = '\0';
    km->epoch = 1;
    derive_node_key(km);
    SYS_CONSOLE_PRINT("[KEY] Node key derived (epoch=%u, id=%s)\r\n",
                      km->epoch, km->node_id);
}

const uint8_t *key_get_node_key(const key_manager_t *km) {
    return km->node_key;
}

uint16_t key_get_epoch(const key_manager_t *km) {
    return km->epoch;
}

void key_rotate(key_manager_t *km) {
    km->epoch++;
    derive_node_key(km);
    SYS_CONSOLE_PRINT("[KEY] Key rotated (epoch=%u)\r\n", km->epoch);
}
