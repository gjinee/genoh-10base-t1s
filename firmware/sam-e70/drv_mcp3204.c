/*******************************************************************************
 * MCP3204 12-bit SPI ADC Driver for SAM E70
 *
 * Bit-banged SPI implementation via GPIO.
 * SPI mode 0,0 (CPOL=0, CPHA=0): data sampled on rising edge.
 *
 * MCP3204 single-ended read protocol (24 clock cycles, 3-byte frame):
 *   Byte 0 TX: 0 0 0 0 0 1 SG D2   (start bit + single-ended + ch bit2)
 *   Byte 1 TX: D1 D0 x x x x x x   (ch bits 1,0 + don't care)
 *   Byte 2 TX: x x x x x x x x     (don't care)
 *   Byte 1 RX: x x x x x 0 B11 B10 (null bit + top 2 data bits)
 *   Byte 2 RX: B9 B8 B7 B6 B5 B4 B3 B2 (middle 8 bits)
 *   + B1 B0 from extra clocks
 ******************************************************************************/

#include "drv_mcp3204.h"
#include "definitions.h"

/* GPIO pin masks */
#define PIN_CS    (1UL << 25)   /* PD25 */
#define PIN_SCK   (1UL << 22)   /* PD22 */
#define PIN_MISO  (1UL << 20)   /* PD20 */
#define PIN_MOSI  (1UL << 21)   /* PD21 */
#define PIN_BTN   (1UL << 21)   /* PA21 */

/* Direct register access for speed */
#define PORTD     ((pio_registers_t *)PIO_PORT_D)
#define PORTA     ((pio_registers_t *)PIO_PORT_A)

/* Sequence counter */
static uint32_t seq_counter = 0;

/* SPI delay: ~200 kHz clock (safe for MCP3204 @ 3.3V, max 2 MHz) */
static inline void spi_delay(void) {
    volatile int i;
    for (i = 0; i < 150; i++) { __asm__ volatile("nop"); }
}

static inline void cs_low(void)   { PORTD->PIO_CODR = PIN_CS; }
static inline void cs_high(void)  { PORTD->PIO_SODR = PIN_CS; }
static inline void sck_low(void)  { PORTD->PIO_CODR = PIN_SCK; }
static inline void sck_high(void) { PORTD->PIO_SODR = PIN_SCK; }
static inline void mosi_low(void) { PORTD->PIO_CODR = PIN_MOSI; }
static inline void mosi_high(void){ PORTD->PIO_SODR = PIN_MOSI; }
static inline bool miso_read(void){ return (PORTD->PIO_PDSR & PIN_MISO) != 0; }

/* Clock out one bit, read MISO on rising edge (SPI mode 0,0) */
static inline bool spi_xfer_bit(bool mosi_val) {
    /* Set MOSI before rising edge */
    if (mosi_val) mosi_high(); else mosi_low();
    spi_delay();
    /* Rising edge: slave latches MOSI, we sample MISO */
    sck_high();
    spi_delay();
    bool miso_val = miso_read();
    /* Falling edge: slave shifts out next bit */
    sck_low();
    spi_delay();
    return miso_val;
}

void MCP3204_Initialize(void) {
    /* Ensure GPIO mode for SPI pins (override any peripheral assignment) */
    PORTD->PIO_PER = PIN_CS | PIN_SCK | PIN_MOSI | PIN_MISO;

    /* Output pins: CS, SCK, MOSI */
    PORTD->PIO_OER = PIN_CS | PIN_SCK | PIN_MOSI;
    /* Input pin: MISO */
    PORTD->PIO_ODR = PIN_MISO;

    /* Initial state: CS high (deselect), SCK low, MOSI low */
    PORTD->PIO_SODR = PIN_CS;   /* CS high */
    PORTD->PIO_CODR = PIN_SCK;  /* SCK low */
    PORTD->PIO_CODR = PIN_MOSI; /* MOSI low */

    /* PA21 (button INT): GPIO input with pull-up */
    PORTA->PIO_PER  = (PORTA->PIO_PER) | PIN_BTN;
    PORTA->PIO_ODR  = PIN_BTN;
    PORTA->PIO_PUER = PIN_BTN;

    /* Simple MCP3204 test read on SPI0 (PD20-22, CS=PD25) */
    uint16_t test_val = MCP3204_ReadChannel(0);
    SYS_CONSOLE_PRINT("[MCP3204] Test CH0=%u MISO=%d\r\n",
                      test_val,
                      (int)((PORTD->PIO_PDSR >> 20) & 1));
}

uint16_t MCP3204_ReadChannel(uint8_t channel) {
    uint16_t result = 0;
    channel &= 0x03;

    /*
     * 3-byte SPI frame for MCP3204 single-ended read:
     *
     * Byte 0: [0 0 0 0 0 Start SGL D2]
     *   Start=1, SGL=1, D2=0 for ch 0-3
     *   = 0x06 for all channels (D2 always 0 on MCP3204)
     *
     * Byte 1: [D1 D0 x x x x x x]
     *   Channel bits + don't care
     *
     * Byte 2: [x x x x x x x x]
     *   Don't care (clocking out remaining data bits)
     */

    uint8_t tx[3];
    uint8_t rx[3] = {0, 0, 0};

    tx[0] = 0x06;                   /* 0b00000110: start + single-ended */
    tx[1] = (channel & 0x03) << 6;  /* D1,D0 in top 2 bits */
    tx[2] = 0x00;

    cs_low();
    spi_delay();
    spi_delay();  /* Extra setup time for CS low */

    /* Transfer 3 bytes (24 clocks) */
    for (int byte = 0; byte < 3; byte++) {
        for (int bit = 7; bit >= 0; bit--) {
            bool mosi_val = (tx[byte] >> bit) & 1;
            bool miso_val = spi_xfer_bit(mosi_val);
            if (miso_val) {
                rx[byte] |= (1U << bit);
            }
        }
    }

    cs_high();
    spi_delay();

    /*
     * Extract 12-bit result from rx bytes:
     * rx[1] bits 3..0 = B11..B8 (after null bit at bit 4)
     * rx[2] bits 7..0 = B7..B0
     */
    result = ((uint16_t)(rx[1] & 0x0F) << 8) | rx[2];

    return result;
}

bool MCP3204_ButtonPressed(void) {
    return (PORTA->PIO_PDSR & PIN_BTN) == 0;
}

float MCP3204_CalcAngle(uint16_t x) {
    return ((float)x - 2048.0f) / 2048.0f * 90.0f;
}

void MCP3204_ReadThumbstick(thumbstick_data_t *data) {
    data->x     = MCP3204_ReadChannel(MCP3204_CH_X);
    data->y     = MCP3204_ReadChannel(MCP3204_CH_Y);
    data->btn   = MCP3204_ButtonPressed() ? 1 : 0;
    data->angle = MCP3204_CalcAngle(data->x);
    data->seq   = seq_counter++;
}
