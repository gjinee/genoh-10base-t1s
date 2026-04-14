/*******************************************************************************
 * stdio redirect for arm-none-eabi-gcc (newlib)
 *
 * Implements the minimal newlib syscalls _write() and _read() so that
 * printf/puts/etc. output via USART1 (Harmony ring-buffer PLIB).
 *
 * Original XC32 version used write()/read() stubs returning -1.
 * This GCC version routes stdout/stderr to USART1_Write().
 ******************************************************************************/

#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>
#include "device.h"
#include "peripheral/usart/plib_usart1.h"

/* ---- _write: newlib syscall for stdout/stderr output -------------------- */
int _write(int handle, const char *buf, int count);
int _write(int handle, const char *buf, int count)
{
    if (buf == NULL || count <= 0)
    {
        return -1;
    }

    /* handle: 1 = stdout, 2 = stderr -- route both to USART1 */
    if (handle == 1 || handle == 2)
    {
        /* USART1_Write returns number of bytes accepted into ring buffer */
        return (int)USART1_Write((uint8_t *)buf, (size_t)count);
    }

    return -1;
}

/* ---- _read: newlib syscall for stdin ------------------------------------ */
int _read(int handle, char *buf, int count);
int _read(int handle, char *buf, int count)
{
    (void)handle;
    (void)buf;
    (void)count;

    /* stdin not supported */
    return -1;
}
