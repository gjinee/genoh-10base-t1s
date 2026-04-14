/*******************************************************************************
 * Hardware Watchdog — SAM E70 WDT register direct access
 *
 * Slow clock = 32768 Hz, WDV counter = 12 bits
 * Timeout ≈ (WDV + 1) / 32768 * 128 seconds
 * WDV=0x1FF → ~2.05 seconds
 ******************************************************************************/

#include "watchdog.h"

/* SAM E70 WDT registers (absolute addresses) */
#define WDT_BASE   0x400E1850U
#define WDT_CR     (*(volatile uint32_t *)(WDT_BASE + 0x00))
#define WDT_MR     (*(volatile uint32_t *)(WDT_BASE + 0x04))
#define WDT_SR     (*(volatile uint32_t *)(WDT_BASE + 0x08))

/* WDT_CR bits */
#define WDT_CR_KEY      (0xA5U << 24)
#define WDT_CR_WDRSTT   (1U << 0)

/* WDT_MR bits */
#define WDT_MR_WDRSTEN  (1U << 13)  /* Reset enable */
#define WDT_MR_WDDIS    (1U << 15)  /* Disable bit */
#define WDT_MR_WDDBGHLT (1U << 28)  /* Halt in debug */
#define WDT_MR_WDIDLEHLT (1U << 29) /* Halt in idle */

/* WDV for ~2 second timeout.
 * WDT counts in slow_clock/128 = 256 Hz.  WDV=0x1FF = 511 → ~2.0s */
#define WDT_WDV   0x1FFU

void watchdog_init(void) {
    /* WDT_MR can only be written once after reset.
     * Set: counter value, reset on timeout, halt in debug. */
    WDT_MR = (WDT_WDV & 0xFFFU)        /* WDV: counter value */
           | WDT_MR_WDRSTEN             /* Reset MCU on timeout */
           | WDT_MR_WDDBGHLT            /* Halt during JTAG debug */
           | ((WDT_WDV & 0xFFFU) << 16); /* WDD: delta value (window) */
}

void watchdog_feed(void) {
    WDT_CR = WDT_CR_KEY | WDT_CR_WDRSTT;
}

void watchdog_disable(void) {
    /* NOTE: WDT_MR can only be written once. If init() was called,
     * this function has no effect. Use only for debug boot. */
    WDT_MR = WDT_MR_WDDIS;
}
