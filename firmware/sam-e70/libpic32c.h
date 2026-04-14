/*******************************************************************************
 * libpic32c.h -- Compatibility shim for arm-none-eabi-gcc
 *
 * XC32's libpic32c.h provides linker symbols and startup helpers. This header
 * maps them to standard GCC/newlib equivalents so that existing Harmony source
 * files (startup_xc32.c, libc_syscalls.c, etc.) can compile unchanged.
 *
 * The actual symbol values come from the linker script. This header only
 * declares them as extern.
 ******************************************************************************/

#ifndef LIBPIC32C_H
#define LIBPIC32C_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---- Linker-provided section symbols ------------------------------------ */

/* Flash / text */
extern uint32_t _sfixed;      /* start of .vectors (flash)     */
extern uint32_t _efixed;      /* end of .text (flash)          */
extern uint32_t _etext;       /* end of all RO data in flash   */

/* Initialized data (.data) -- "relocate" in Harmony naming */
extern uint32_t _srelocate;   /* .data VMA start (in RAM)      */
extern uint32_t _erelocate;   /* .data VMA end   (in RAM)      */

/* Zero-initialized data (.bss) */
extern uint32_t _szero;       /* .bss start                    */
extern uint32_t _ezero;       /* .bss end                      */

/* Stack */
extern uint32_t _sstack;      /* bottom of stack               */
extern uint32_t _estack;      /* top of stack (initial SP)     */

/* Legacy aliases used by some Harmony code */
extern uint32_t _stack;       /* alias for _estack (top of stack) */

/* ---- XC32-specific functions -- provide stubs / no-ops ------------------ */

/*
 * __pic32c_data_initialization() is XC32's proprietary .dinit-based data
 * copy. Under GCC we handle .data/.bss in startup_gcc.c with explicit
 * loops, so this is a no-op.
 */
static inline void __pic32c_data_initialization(void)
{
    /* no-op: handled by startup_gcc.c */
}

#ifdef __cplusplus
}
#endif

#endif /* LIBPIC32C_H */
