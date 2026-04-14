/*
 * LED Blink — SAM E70 Xplained Ultra
 * LED0 = PC8, active low
 * Clock: 12 MHz internal RC (reset default)
 */
#include "same70.h"

static volatile uint32_t ms_ticks;

void SysTick_Handler(void)
{
    ms_ticks++;
}

static void delay_ms(uint32_t ms)
{
    uint32_t start = ms_ticks;
    while ((ms_ticks - start) < ms)
        ;
}

int main(void)
{
    /* Disable watchdog (enabled by default) */
    WDT_MR = WDT_MR_WDDIS;

    /* Enable PIOC peripheral clock (ID 12) */
    PMC_PCER0 = (1U << LED0_PIO_ID);

    /* Configure PC8 as PIO output */
    LED0_PIO->PIO_PER = LED0_PIN;   /* PIO controls the pin */
    LED0_PIO->PIO_OER = LED0_PIN;   /* Set as output */

    /* SysTick: 1 ms interrupt @ 12 MHz internal RC */
    SYSTICK_RVR = 12000U - 1U;
    SYSTICK_CVR = 0U;
    SYSTICK_CSR = 0x07U;  /* Enable + interrupt + processor clock */

    while (1) {
        LED0_PIO->PIO_CODR = LED0_PIN;  /* LED on  (active low) */
        delay_ms(500);
        LED0_PIO->PIO_SODR = LED0_PIN;  /* LED off */
        delay_ms(500);
    }
}
