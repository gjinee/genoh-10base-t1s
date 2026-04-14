#ifndef WATCHDOG_H
#define WATCHDOG_H
/*******************************************************************************
 * Hardware Watchdog (WDT) — SAM E70, ASIL-D (~2 second timeout)
 ******************************************************************************/

#include <stdint.h>

/* Initialize WDT: ~2s timeout, reset on expiry */
void watchdog_init(void);

/* Feed (kick) the watchdog — must be called periodically */
void watchdog_feed(void);

/* Disable watchdog (for debug only) */
void watchdog_disable(void);

#endif /* WATCHDOG_H */
