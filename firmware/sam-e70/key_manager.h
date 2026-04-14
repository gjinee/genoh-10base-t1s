#ifndef KEY_MANAGER_H
#define KEY_MANAGER_H
/*******************************************************************************
 * Key Manager — Per-node HMAC key derivation from master key
 *
 * Derives: node_key = HMAC-SHA256(master_key, node_id_string)
 * Supports key epoch for future rotation.
 ******************************************************************************/

#include <stdint.h>

#define KEY_SIZE  32  /* 256-bit */

typedef struct {
    uint8_t  master_key[KEY_SIZE];
    uint8_t  node_key[KEY_SIZE];
    uint16_t epoch;       /* key version, starts at 1 */
    char     node_id[16]; /* e.g. "front_left/1" */
} key_manager_t;

/* Initialize with master key and derive node key */
void key_init(key_manager_t *km, const uint8_t *master_key,
              const char *node_id);

/* Get current node key */
const uint8_t *key_get_node_key(const key_manager_t *km);

/* Get current epoch */
uint16_t key_get_epoch(const key_manager_t *km);

/* Rotate key: increment epoch, re-derive node key */
void key_rotate(key_manager_t *km);

#endif /* KEY_MANAGER_H */
