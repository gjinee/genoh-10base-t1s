/*
 * GCC Linker Script for ATSAME70Q21B
 * Flash: 2 MB @ 0x00400000
 * SRAM:  384 KB @ 0x20400000
 *
 * Symbol names match Harmony convention expected by startup_gcc.c:
 *   _etext, _srelocate, _erelocate, _szero, _ezero, _stack
 */

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x00400000, LENGTH = 2M
    SRAM  (rwx) : ORIGIN = 0x20400000, LENGTH = 384K
}

ENTRY(Reset_Handler)

_stack = ORIGIN(SRAM) + LENGTH(SRAM);

SECTIONS
{
    /* Vector table + code + read-only data */
    .text :
    {
        . = ALIGN(4);
        _sfixed = .;
        KEEP(*(.vectors .vectors.*))
        *(.text .text.*)
        *(.rodata .rodata.*)
        *(.gnu.linkonce.t.*)
        *(.gnu.linkonce.r.*)
        *(.ARM.extab* .gnu.linkonce.armextab.*)
        . = ALIGN(4);
        KEEP(*(.init))
        KEEP(*(.fini))
        . = ALIGN(4);
        /* C++ constructors / destructors */
        __preinit_array_start = .;
        KEEP(*(.preinit_array))
        __preinit_array_end = .;
        __init_array_start = .;
        KEEP(*(SORT(.init_array.*)))
        KEEP(*(.init_array))
        __init_array_end = .;
        __fini_array_start = .;
        KEEP(*(SORT(.fini_array.*)))
        KEEP(*(.fini_array))
        __fini_array_end = .;
        . = ALIGN(4);
        _efixed = .;
        _etext = .;
    } > FLASH

    /* Initialized data: lives in RAM, loaded from FLASH */
    .data :
    {
        . = ALIGN(4);
        _srelocate = .;
        *(.data .data.*)
        *(.gnu.linkonce.d.*)
        *(.ramfunc .ramfunc.*)
        . = ALIGN(4);
        _erelocate = .;
    } > SRAM AT > FLASH

    /* Uninitialized data */
    .bss (NOLOAD) :
    {
        . = ALIGN(4);
        _szero = .;
        *(.bss .bss.*)
        *(.gnu.linkonce.b.*)
        *(COMMON)
        . = ALIGN(4);
        _ezero = .;
        end = .;       /* for newlib _sbrk() */
        _end = .;
    } > SRAM

    /* Stack (fill from top of SRAM down) */
    .stack (NOLOAD) :
    {
        . = ALIGN(8);
        _sstack = .;
        . = . + 4096;   /* minimum 4KB stack guard */
        _estack = .;
    } > SRAM

    /* Heap - whatever RAM is left between _ezero and _stack */
    _heap_start = _ezero;
    _heap_end = _stack - 4096;

    /* ARM exception handling - not needed, discard */
    /DISCARD/ :
    {
        *(.ARM.exidx* .gnu.linkonce.armexidx.*)
    }
}
