/*
 * Linker script for ATSAME70Q21
 *   Flash: 2 MB @ 0x00400000
 *   SRAM:  384 KB @ 0x20400000
 */
MEMORY
{
    FLASH (rx)  : ORIGIN = 0x00400000, LENGTH = 2M
    SRAM  (rwx) : ORIGIN = 0x20400000, LENGTH = 384K
}

ENTRY(Reset_Handler)

_estack = ORIGIN(SRAM) + LENGTH(SRAM);

SECTIONS
{
    .text :
    {
        . = ALIGN(4);
        KEEP(*(.isr_vector))
        *(.text*)
        *(.rodata*)
        . = ALIGN(4);
        _etext = .;
    } > FLASH

    _sidata = LOADADDR(.data);

    .data :
    {
        . = ALIGN(4);
        _sdata = .;
        *(.data*)
        . = ALIGN(4);
        _edata = .;
    } > SRAM AT > FLASH

    .bss (NOLOAD) :
    {
        . = ALIGN(4);
        _sbss = .;
        *(.bss*)
        *(COMMON)
        . = ALIGN(4);
        _ebss = .;
    } > SRAM

    /DISCARD/ :
    {
        *(.ARM.exidx*)
        *(.ARM.attributes*)
    }
}
