/*******************************************************************************
 * MCP3204 12-bit SPI ADC Driver for SAM E70
 *
 * Bit-banged SPI via GPIO (mikroBUS header on SAM E70 Xplained Ultra).
 * Reads 4 single-ended channels at up to ~500 kHz SPI clock.
 *
 * Pin mapping (mikroBUS):
 *   CS   = PD25 (GPIO output, active low)
 *   SCK  = PD22 (GPIO output)
 *   MISO = PD20 (GPIO input)
 *   MOSI = PD21 (GPIO output)
 *   INT  = PA21 (GPIO input, joystick button, active low)
 ******************************************************************************/

#ifndef DRV_MCP3204_H
#define DRV_MCP3204_H

#include <stdint.h>
#include <stdbool.h>

/* ADC channels */
#define MCP3204_CH_X    0   /* Thumbstick X axis */
#define MCP3204_CH_Y    1   /* Thumbstick Y axis */
#define MCP3204_CH2     2   /* Spare */
#define MCP3204_CH3     3   /* Spare */

/* Thumbstick data structure */
typedef struct {
    uint16_t x;         /* X axis raw ADC (0-4095) */
    uint16_t y;         /* Y axis raw ADC (0-4095) */
    uint8_t  btn;       /* Joystick button (0=released, 1=pressed) */
    float    angle;     /* Steering angle in degrees (-90 to +90) */
    uint32_t seq;       /* Sequence number */
} thumbstick_data_t;

/* Initialize GPIO pins for MCP3204 SPI + button */
void MCP3204_Initialize(void);

/* Read single channel (0-3), returns 12-bit value (0-4095) */
uint16_t MCP3204_ReadChannel(uint8_t channel);

/* Read joystick button state (true = pressed) */
bool MCP3204_ButtonPressed(void);

/* Read all thumbstick data at once */
void MCP3204_ReadThumbstick(thumbstick_data_t *data);

/* Calculate steering angle from X axis value */
float MCP3204_CalcAngle(uint16_t x);

#endif /* DRV_MCP3204_H */
