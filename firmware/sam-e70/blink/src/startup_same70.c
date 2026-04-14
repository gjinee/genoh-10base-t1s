/*
 * Startup code for ATSAME70Q21
 * Vector table + Reset handler (data copy, bss zero)
 */
#include <stdint.h>

/* Linker symbols */
extern uint32_t _estack;
extern uint32_t _sidata, _sdata, _edata;
extern uint32_t _sbss, _ebss;

extern int main(void);

void Reset_Handler(void);
void Default_Handler(void);

/* Cortex-M7 exception handlers (weak → Default_Handler) */
void NMI_Handler(void)        __attribute__((weak, alias("Default_Handler")));
void HardFault_Handler(void)  __attribute__((weak, alias("Default_Handler")));
void MemManage_Handler(void)  __attribute__((weak, alias("Default_Handler")));
void BusFault_Handler(void)   __attribute__((weak, alias("Default_Handler")));
void UsageFault_Handler(void) __attribute__((weak, alias("Default_Handler")));
void SVC_Handler(void)        __attribute__((weak, alias("Default_Handler")));
void DebugMon_Handler(void)   __attribute__((weak, alias("Default_Handler")));
void PendSV_Handler(void)     __attribute__((weak, alias("Default_Handler")));
void SysTick_Handler(void)    __attribute__((weak, alias("Default_Handler")));

/* Vector table — placed at start of flash */
__attribute__((section(".isr_vector"), used))
const void *vector_table[] = {
    &_estack,            /* 0  Initial Stack Pointer */
    Reset_Handler,       /* 1  Reset */
    NMI_Handler,         /* 2  NMI */
    HardFault_Handler,   /* 3  Hard Fault */
    MemManage_Handler,   /* 4  MPU Fault */
    BusFault_Handler,    /* 5  Bus Fault */
    UsageFault_Handler,  /* 6  Usage Fault */
    0, 0, 0, 0,         /* 7-10 Reserved */
    SVC_Handler,         /* 11 SVCall */
    DebugMon_Handler,    /* 12 Debug Monitor */
    0,                   /* 13 Reserved */
    PendSV_Handler,      /* 14 PendSV */
    SysTick_Handler,     /* 15 SysTick */
};

void Reset_Handler(void)
{
    /* Copy .data section from flash to SRAM */
    uint32_t *src = &_sidata;
    uint32_t *dst = &_sdata;
    while (dst < &_edata)
        *dst++ = *src++;

    /* Zero .bss section */
    dst = &_sbss;
    while (dst < &_ebss)
        *dst++ = 0;

    main();

    /* Should never reach here */
    while (1)
        ;
}

void Default_Handler(void)
{
    while (1)
        ;
}
