/*******************************************************************************
 * GCC Startup for ATSAME70Q21B (Cortex-M7)
 *
 * Replaces config/startup_xc32.c for arm-none-eabi-gcc builds.
 * Also includes the full vector table (replacing config/interrupts.c).
 *
 * Build this file instead of startup_xc32.c and interrupts.c.
 * Keep config/exceptions.c (it provides the core fault handlers).
 *
 * - Full vector table for 74 peripheral IRQs (H3DeviceVectors)
 * - Copies .data from flash to RAM
 * - Zeros .bss
 * - Enables FPU (CP10/CP11)
 * - Sets SCB->VTOR to flash base
 * - Calls SYS_Initialize() / SYS_Tasks() (Harmony + FreeRTOS)
 ******************************************************************************/

#include <stdint.h>
#include "config/device.h"
#include "config/device_vectors.h"
#include "config/interrupts.h"

/* ---- Harmony entry points ------------------------------------------------ */
extern void SYS_Initialize(void *data);
extern void SYS_Tasks(void);

/* ---- C library init (constructors / static initializers) ----------------- */
void __libc_init_array(void) __attribute__((weak));

/* ---- MPU init from Harmony ----------------------------------------------- */
extern void MPU_Initialize(void);

/* ---- Linker-provided symbols --------------------------------------------- */
extern uint32_t _etext;       /* end of RO in flash = LMA of .data          */
extern uint32_t _srelocate;   /* .data VMA start (RAM)                      */
extern uint32_t _erelocate;   /* .data VMA end   (RAM)                      */
extern uint32_t _szero;       /* .bss start                                 */
extern uint32_t _ezero;       /* .bss end                                   */
extern uint32_t _stack;       /* top of stack (initial SP)                  */

/*==========================================================================*
 *  Default handler for unused interrupts
 *==========================================================================*/
void __attribute__((optimize("-O1"), noreturn, used)) Dummy_Handler(void)
{
    __BKPT(0);
    while (1)
    {
    }
}

/*==========================================================================*
 *  Weak aliases -- peripheral handlers default to Dummy_Handler
 *  Handlers actually used by the project are defined in their PLIB .c files.
 *==========================================================================*/

/* Core exception handlers (overridden in config/exceptions.c) */
extern void NonMaskableInt_Handler     (void) __attribute__((weak, alias("Dummy_Handler")));
extern void HardFault_Handler          (void) __attribute__((weak, alias("Dummy_Handler")));
extern void MemoryManagement_Handler   (void) __attribute__((weak, alias("Dummy_Handler")));
extern void BusFault_Handler           (void) __attribute__((weak, alias("Dummy_Handler")));
extern void UsageFault_Handler         (void) __attribute__((weak, alias("Dummy_Handler")));
extern void DebugMonitor_Handler       (void) __attribute__((weak, alias("Dummy_Handler")));

/* FreeRTOS handlers (defined in FreeRTOS port) */
extern void vPortSVCHandler            (void) __attribute__((weak, alias("Dummy_Handler")));
extern void xPortPendSVHandler         (void) __attribute__((weak, alias("Dummy_Handler")));
extern void xPortSysTickHandler        (void) __attribute__((weak, alias("Dummy_Handler")));

/* Peripheral ISRs used by this project (defined in PLIB sources) */
extern void USART1_InterruptHandler    (void) __attribute__((weak, alias("Dummy_Handler")));
extern void TC0_CH0_InterruptHandler   (void) __attribute__((weak, alias("Dummy_Handler")));
extern void GMAC_InterruptHandler      (void) __attribute__((weak, alias("Dummy_Handler")));

/* All other peripheral handlers */
extern void SUPC_Handler               (void) __attribute__((weak, alias("Dummy_Handler")));
extern void RSTC_Handler               (void) __attribute__((weak, alias("Dummy_Handler")));
extern void RTC_Handler                (void) __attribute__((weak, alias("Dummy_Handler")));
extern void RTT_Handler                (void) __attribute__((weak, alias("Dummy_Handler")));
extern void WDT_Handler                (void) __attribute__((weak, alias("Dummy_Handler")));
extern void PMC_Handler                (void) __attribute__((weak, alias("Dummy_Handler")));
extern void EFC_Handler                (void) __attribute__((weak, alias("Dummy_Handler")));
extern void UART0_Handler              (void) __attribute__((weak, alias("Dummy_Handler")));
extern void UART1_Handler              (void) __attribute__((weak, alias("Dummy_Handler")));
extern void PIOA_Handler               (void) __attribute__((weak, alias("Dummy_Handler")));
extern void PIOB_Handler               (void) __attribute__((weak, alias("Dummy_Handler")));
extern void PIOC_Handler               (void) __attribute__((weak, alias("Dummy_Handler")));
extern void USART0_Handler             (void) __attribute__((weak, alias("Dummy_Handler")));
extern void USART2_Handler             (void) __attribute__((weak, alias("Dummy_Handler")));
extern void PIOD_Handler               (void) __attribute__((weak, alias("Dummy_Handler")));
extern void PIOE_Handler               (void) __attribute__((weak, alias("Dummy_Handler")));
extern void HSMCI_Handler              (void) __attribute__((weak, alias("Dummy_Handler")));
extern void TWIHS0_Handler             (void) __attribute__((weak, alias("Dummy_Handler")));
extern void TWIHS1_Handler             (void) __attribute__((weak, alias("Dummy_Handler")));
extern void SPI0_Handler               (void) __attribute__((weak, alias("Dummy_Handler")));
extern void SSC_Handler                (void) __attribute__((weak, alias("Dummy_Handler")));
extern void TC0_CH1_Handler            (void) __attribute__((weak, alias("Dummy_Handler")));
extern void TC0_CH2_Handler            (void) __attribute__((weak, alias("Dummy_Handler")));
extern void TC1_CH0_Handler            (void) __attribute__((weak, alias("Dummy_Handler")));
extern void TC1_CH1_Handler            (void) __attribute__((weak, alias("Dummy_Handler")));
extern void TC1_CH2_Handler            (void) __attribute__((weak, alias("Dummy_Handler")));
extern void AFEC0_Handler              (void) __attribute__((weak, alias("Dummy_Handler")));
extern void DACC_Handler               (void) __attribute__((weak, alias("Dummy_Handler")));
extern void PWM0_Handler               (void) __attribute__((weak, alias("Dummy_Handler")));
extern void ICM_Handler                (void) __attribute__((weak, alias("Dummy_Handler")));
extern void ACC_Handler                (void) __attribute__((weak, alias("Dummy_Handler")));
extern void USBHS_Handler              (void) __attribute__((weak, alias("Dummy_Handler")));
extern void MCAN0_INT0_Handler         (void) __attribute__((weak, alias("Dummy_Handler")));
extern void MCAN0_INT1_Handler         (void) __attribute__((weak, alias("Dummy_Handler")));
extern void MCAN1_INT0_Handler         (void) __attribute__((weak, alias("Dummy_Handler")));
extern void MCAN1_INT1_Handler         (void) __attribute__((weak, alias("Dummy_Handler")));
extern void AFEC1_Handler              (void) __attribute__((weak, alias("Dummy_Handler")));
extern void TWIHS2_Handler             (void) __attribute__((weak, alias("Dummy_Handler")));
extern void SPI1_Handler               (void) __attribute__((weak, alias("Dummy_Handler")));
extern void QSPI_Handler               (void) __attribute__((weak, alias("Dummy_Handler")));
extern void UART2_Handler              (void) __attribute__((weak, alias("Dummy_Handler")));
extern void UART3_Handler              (void) __attribute__((weak, alias("Dummy_Handler")));
extern void UART4_Handler              (void) __attribute__((weak, alias("Dummy_Handler")));
extern void TC2_CH0_Handler            (void) __attribute__((weak, alias("Dummy_Handler")));
extern void TC2_CH1_Handler            (void) __attribute__((weak, alias("Dummy_Handler")));
extern void TC2_CH2_Handler            (void) __attribute__((weak, alias("Dummy_Handler")));
extern void TC3_CH0_Handler            (void) __attribute__((weak, alias("Dummy_Handler")));
extern void TC3_CH1_Handler            (void) __attribute__((weak, alias("Dummy_Handler")));
extern void TC3_CH2_Handler            (void) __attribute__((weak, alias("Dummy_Handler")));
extern void AES_Handler                (void) __attribute__((weak, alias("Dummy_Handler")));
extern void TRNG_Handler               (void) __attribute__((weak, alias("Dummy_Handler")));
extern void XDMAC_Handler              (void) __attribute__((weak, alias("Dummy_Handler")));
extern void ISI_Handler                (void) __attribute__((weak, alias("Dummy_Handler")));
extern void PWM1_Handler               (void) __attribute__((weak, alias("Dummy_Handler")));
extern void FPU_Handler                (void) __attribute__((weak, alias("Dummy_Handler")));
extern void RSWDT_Handler              (void) __attribute__((weak, alias("Dummy_Handler")));
extern void CCW_Handler                (void) __attribute__((weak, alias("Dummy_Handler")));
extern void CCF_Handler                (void) __attribute__((weak, alias("Dummy_Handler")));
extern void GMAC_Q1_Handler            (void) __attribute__((weak, alias("Dummy_Handler")));
extern void GMAC_Q2_Handler            (void) __attribute__((weak, alias("Dummy_Handler")));
extern void IXC_Handler                (void) __attribute__((weak, alias("Dummy_Handler")));
extern void I2SC0_Handler              (void) __attribute__((weak, alias("Dummy_Handler")));
extern void I2SC1_Handler              (void) __attribute__((weak, alias("Dummy_Handler")));
extern void GMAC_Q3_Handler            (void) __attribute__((weak, alias("Dummy_Handler")));
extern void GMAC_Q4_Handler            (void) __attribute__((weak, alias("Dummy_Handler")));
extern void GMAC_Q5_Handler            (void) __attribute__((weak, alias("Dummy_Handler")));

/*==========================================================================*
 *  Vector table -- placed in .vectors by linker script
 *  Matches H3DeviceVectors from config/device_vectors.h exactly.
 *==========================================================================*/
__attribute__((section(".vectors"), used))
const H3DeviceVectors exception_table =
{
    /* Initial stack pointer */
    .pvStack                       = &_stack,

    /* Cortex-M7 core handlers */
    .pfnReset_Handler              = Reset_Handler,
    .pfnNonMaskableInt_Handler     = NonMaskableInt_Handler,
    .pfnHardFault_Handler          = HardFault_Handler,
    .pfnMemoryManagement_Handler   = MemoryManagement_Handler,
    .pfnBusFault_Handler           = BusFault_Handler,
    .pfnUsageFault_Handler         = UsageFault_Handler,
    .pfnReservedC9                 = (void *)0,
    .pfnReservedC8                 = (void *)0,
    .pfnReservedC7                 = (void *)0,
    .pfnReservedC6                 = (void *)0,
    .pfnSVCall_Handler             = vPortSVCHandler,
    .pfnDebugMonitor_Handler       = DebugMonitor_Handler,
    .pfnReservedC3                 = (void *)0,
    .pfnPendSV_Handler             = xPortPendSVHandler,
    .pfnSysTick_Handler            = xPortSysTickHandler,

    /* Peripheral handlers (IRQ 0..73) */
    .pfnSUPC_Handler               = SUPC_Handler,              /*  0 */
    .pfnRSTC_Handler               = RSTC_Handler,              /*  1 */
    .pfnRTC_Handler                = RTC_Handler,               /*  2 */
    .pfnRTT_Handler                = RTT_Handler,               /*  3 */
    .pfnWDT_Handler                = WDT_Handler,               /*  4 */
    .pfnPMC_Handler                = PMC_Handler,               /*  5 */
    .pfnEFC_Handler                = EFC_Handler,               /*  6 */
    .pfnUART0_Handler              = UART0_Handler,             /*  7 */
    .pfnUART1_Handler              = UART1_Handler,             /*  8 */
    .pfnReserved9                  = (void *)0,                 /*  9 */
    .pfnPIOA_Handler               = PIOA_Handler,              /* 10 */
    .pfnPIOB_Handler               = PIOB_Handler,              /* 11 */
    .pfnPIOC_Handler               = PIOC_Handler,              /* 12 */
    .pfnUSART0_Handler             = USART0_Handler,            /* 13 */
    .pfnUSART1_Handler             = USART1_InterruptHandler,   /* 14 */
    .pfnUSART2_Handler             = USART2_Handler,            /* 15 */
    .pfnPIOD_Handler               = PIOD_Handler,              /* 16 */
    .pfnPIOE_Handler               = PIOE_Handler,              /* 17 */
    .pfnHSMCI_Handler              = HSMCI_Handler,             /* 18 */
    .pfnTWIHS0_Handler             = TWIHS0_Handler,            /* 19 */
    .pfnTWIHS1_Handler             = TWIHS1_Handler,            /* 20 */
    .pfnSPI0_Handler               = SPI0_Handler,              /* 21 */
    .pfnSSC_Handler                = SSC_Handler,               /* 22 */
    .pfnTC0_CH0_Handler            = TC0_CH0_InterruptHandler,  /* 23 */
    .pfnTC0_CH1_Handler            = TC0_CH1_Handler,           /* 24 */
    .pfnTC0_CH2_Handler            = TC0_CH2_Handler,           /* 25 */
    .pfnTC1_CH0_Handler            = TC1_CH0_Handler,           /* 26 */
    .pfnTC1_CH1_Handler            = TC1_CH1_Handler,           /* 27 */
    .pfnTC1_CH2_Handler            = TC1_CH2_Handler,           /* 28 */
    .pfnAFEC0_Handler              = AFEC0_Handler,             /* 29 */
    .pfnDACC_Handler               = DACC_Handler,              /* 30 */
    .pfnPWM0_Handler               = PWM0_Handler,              /* 31 */
    .pfnICM_Handler                = ICM_Handler,               /* 32 */
    .pfnACC_Handler                = ACC_Handler,               /* 33 */
    .pfnUSBHS_Handler              = USBHS_Handler,             /* 34 */
    .pfnMCAN0_INT0_Handler         = MCAN0_INT0_Handler,        /* 35 */
    .pfnMCAN0_INT1_Handler         = MCAN0_INT1_Handler,        /* 36 */
    .pfnMCAN1_INT0_Handler         = MCAN1_INT0_Handler,        /* 37 */
    .pfnMCAN1_INT1_Handler         = MCAN1_INT1_Handler,        /* 38 */
    .pfnGMAC_Handler               = GMAC_InterruptHandler,     /* 39 */
    .pfnAFEC1_Handler              = AFEC1_Handler,             /* 40 */
    .pfnTWIHS2_Handler             = TWIHS2_Handler,            /* 41 */
    .pfnSPI1_Handler               = SPI1_Handler,              /* 42 */
    .pfnQSPI_Handler               = QSPI_Handler,             /* 43 */
    .pfnUART2_Handler              = UART2_Handler,             /* 44 */
    .pfnUART3_Handler              = UART3_Handler,             /* 45 */
    .pfnUART4_Handler              = UART4_Handler,             /* 46 */
    .pfnTC2_CH0_Handler            = TC2_CH0_Handler,           /* 47 */
    .pfnTC2_CH1_Handler            = TC2_CH1_Handler,           /* 48 */
    .pfnTC2_CH2_Handler            = TC2_CH2_Handler,           /* 49 */
    .pfnTC3_CH0_Handler            = TC3_CH0_Handler,           /* 50 */
    .pfnTC3_CH1_Handler            = TC3_CH1_Handler,           /* 51 */
    .pfnTC3_CH2_Handler            = TC3_CH2_Handler,           /* 52 */
    .pfnReserved53                 = (void *)0,                 /* 53 */
    .pfnReserved54                 = (void *)0,                 /* 54 */
    .pfnReserved55                 = (void *)0,                 /* 55 */
    .pfnAES_Handler                = AES_Handler,               /* 56 */
    .pfnTRNG_Handler               = TRNG_Handler,              /* 57 */
    .pfnXDMAC_Handler              = XDMAC_Handler,             /* 58 */
    .pfnISI_Handler                = ISI_Handler,               /* 59 */
    .pfnPWM1_Handler               = PWM1_Handler,              /* 60 */
    .pfnFPU_Handler                = FPU_Handler,               /* 61 */
    .pfnReserved62                 = (void *)0,                 /* 62 */
    .pfnRSWDT_Handler              = RSWDT_Handler,             /* 63 */
    .pfnCCW_Handler                = CCW_Handler,               /* 64 */
    .pfnCCF_Handler                = CCF_Handler,               /* 65 */
    .pfnGMAC_Q1_Handler            = GMAC_Q1_Handler,           /* 66 */
    .pfnGMAC_Q2_Handler            = GMAC_Q2_Handler,           /* 67 */
    .pfnIXC_Handler                = IXC_Handler,               /* 68 */
    .pfnI2SC0_Handler              = I2SC0_Handler,             /* 69 */
    .pfnI2SC1_Handler              = I2SC1_Handler,             /* 70 */
    .pfnGMAC_Q3_Handler            = GMAC_Q3_Handler,           /* 71 */
    .pfnGMAC_Q4_Handler            = GMAC_Q4_Handler,           /* 72 */
    .pfnGMAC_Q5_Handler            = GMAC_Q5_Handler,           /* 73 */
};

/*==========================================================================*
 *  TCM helpers (same logic as XC32 startup)
 *==========================================================================*/
static inline void TCM_Disable(void)
{
    __DSB();
    __ISB();
    SCB->ITCMCR &= ~(uint32_t)SCB_ITCMCR_EN_Msk;
    SCB->DTCMCR &= ~(uint32_t)SCB_ITCMCR_EN_Msk;
    __DSB();
    __ISB();
}

#define GPNVM_TCM_SIZE_Pos   7u
#define GPNVM_TCM_SIZE_Msk   (0x3u << GPNVM_TCM_SIZE_Pos)

static inline void TCM_Configure(uint32_t neededGpnvmValue)
{
    uint32_t gpnvmReg;
    uint32_t cmd;

    EFC_REGS->EEFC_FCR = (EEFC_FCR_FKEY_PASSWD | EEFC_FCR_FCMD_GGPB);
    while ((EFC_REGS->EEFC_FSR & EEFC_FSR_FRDY_Msk) == 0U)
    {
    }

    gpnvmReg = EFC_REGS->EEFC_FRR;

    if (((gpnvmReg & GPNVM_TCM_SIZE_Msk) >> GPNVM_TCM_SIZE_Pos) != neededGpnvmValue)
    {
        cmd = ((neededGpnvmValue & 0x2U) != 0U) ? EEFC_FCR_FCMD_SGPB : EEFC_FCR_FCMD_CGPB;
        EFC_REGS->EEFC_FCR = (EEFC_FCR_FKEY_PASSWD | cmd | EEFC_FCR_FARG(8U));
        while ((EFC_REGS->EEFC_FSR & EEFC_FSR_FRDY_Msk) == 0U)
        {
        }

        cmd = ((neededGpnvmValue & 0x1U) != 0U) ? EEFC_FCR_FCMD_SGPB : EEFC_FCR_FCMD_CGPB;
        EFC_REGS->EEFC_FCR = (EEFC_FCR_FKEY_PASSWD | cmd | EEFC_FCR_FARG(7U));
        while ((EFC_REGS->EEFC_FSR & EEFC_FSR_FRDY_Msk) == 0U)
        {
        }

        /* Reset MCU to apply the new fuse value */
        RSTC_REGS->RSTC_CR = RSTC_CR_KEY_PASSWD | RSTC_CR_PROCRST_Msk;
    }
}

/*==========================================================================*
 *  FPU enable (Cortex-M7 CP10/CP11)
 *==========================================================================*/
static inline void FPU_Enable(void)
{
    uint32_t primask = __get_PRIMASK();
    __disable_irq();

    /* Grant full access to CP10 and CP11 */
    SCB->CPACR |= (0xFU << 20);
    __DSB();
    __ISB();

    if (primask == 0U)
    {
        __enable_irq();
    }
}

/*==========================================================================*
 *  Reset_Handler -- entry point after power-on / warm reset
 *==========================================================================*/
void __attribute__((noreturn, used, section(".text.Reset_Handler")))
Reset_Handler(void)
{
    uint32_t *pSrc, *pDst;

    /* 1. Enable FPU before any possible FP instruction */
    FPU_Enable();

    /* 2. Configure TCM: disable (0 = no TCM allocated) */
    TCM_Configure(0U);
    TCM_Disable();

    /* 3. Copy .data from flash (LMA after _etext) to RAM (VMA) */
    pSrc = &_etext;
    pDst = &_srelocate;
    while (pDst < &_erelocate)
    {
        *pDst++ = *pSrc++;
    }

    /* 4. Zero .bss */
    pDst = &_szero;
    while (pDst < &_ezero)
    {
        *pDst++ = 0U;
    }

    /* 5. Set VTOR to flash base so the CPU finds our vector table */
    SCB->VTOR = ((uint32_t)0x00400000U & SCB_VTOR_TBLOFF_Msk);

    /* 6. C library initialisation (static constructors, etc.) */
    if (__libc_init_array)
    {
        __libc_init_array();
    }

    /* 7. Initialize MPU (Harmony-generated) */
    MPU_Initialize();

    /* 8. Enable I-cache only; D-cache disabled for GMAC DMA compatibility */
    SCB_EnableICache();
    /* SCB_EnableDCache(); -- disabled: GMAC DMA needs non-cached SRAM access */

    /* 8b. Disable unaligned access trap (needed for TCP/IP packet parsing) */
    SCB->CCR &= ~SCB_CCR_UNALIGN_TRP_Msk;

    /* 9. Enter Harmony -- SYS_Initialize starts FreeRTOS scheduler via SYS_Tasks */
    SYS_Initialize(NULL);

    while (1)
    {
        SYS_Tasks();
    }
}
