/*
 * Minimal register definitions for ATSAME70Q21
 * SAM E70 Xplained Ultra - LED blink test
 */
#ifndef SAME70_H
#define SAME70_H

#include <stdint.h>

/* ---- Peripheral base addresses ---- */
#define PMC_BASE    0x400E0600U
#define WDT_BASE    0x400E1850U
#define PIOA_BASE   0x400E0E00U
#define PIOB_BASE   0x400E1000U
#define PIOC_BASE   0x400E1200U
#define PIOD_BASE   0x400E1400U
#define PIOE_BASE   0x400E1600U

/* ---- PMC (Power Management Controller) ---- */
#define PMC_PCER0   (*(volatile uint32_t *)(PMC_BASE + 0x10U))

/* ---- WDT (Watchdog Timer) ---- */
#define WDT_MR      (*(volatile uint32_t *)(WDT_BASE + 0x04U))
#define WDT_MR_WDDIS (1U << 15)

/* ---- PIO (Parallel I/O) ---- */
typedef struct {
    volatile uint32_t PIO_PER;      /* 0x0000 PIO Enable */
    volatile uint32_t PIO_PDR;      /* 0x0004 PIO Disable */
    volatile uint32_t PIO_PSR;      /* 0x0008 PIO Status */
    uint32_t          _reserved0;
    volatile uint32_t PIO_OER;      /* 0x0010 Output Enable */
    volatile uint32_t PIO_ODR;      /* 0x0014 Output Disable */
    volatile uint32_t PIO_OSR;      /* 0x0018 Output Status */
    uint32_t          _reserved1;
    volatile uint32_t PIO_IFER;     /* 0x0020 Input Filter Enable */
    volatile uint32_t PIO_IFDR;     /* 0x0024 Input Filter Disable */
    volatile uint32_t PIO_IFSR;     /* 0x0028 Input Filter Status */
    uint32_t          _reserved2;
    volatile uint32_t PIO_SODR;     /* 0x0030 Set Output Data */
    volatile uint32_t PIO_CODR;     /* 0x0034 Clear Output Data */
    volatile uint32_t PIO_ODSR;     /* 0x0038 Output Data Status */
    volatile uint32_t PIO_PDSR;     /* 0x003C Pin Data Status */
} Pio;

#define PIOA    ((Pio *)PIOA_BASE)
#define PIOB    ((Pio *)PIOB_BASE)
#define PIOC    ((Pio *)PIOC_BASE)
#define PIOD    ((Pio *)PIOD_BASE)
#define PIOE    ((Pio *)PIOE_BASE)

/* ---- SAM E70 Xplained Ultra: LED0 = PA5 (active low) ---- */
#define LED0_PIN        (1U << 5)
#define LED0_PIO        PIOA
#define LED0_PIO_ID     10U

/* ---- SysTick ---- */
#define SYSTICK_CSR (*(volatile uint32_t *)0xE000E010U)
#define SYSTICK_RVR (*(volatile uint32_t *)0xE000E014U)
#define SYSTICK_CVR (*(volatile uint32_t *)0xE000E018U)

#endif /* SAME70_H */
