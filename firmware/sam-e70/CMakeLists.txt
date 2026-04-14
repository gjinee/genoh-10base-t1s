cmake_minimum_required(VERSION 3.20)

project(sam-e70-harmony-tcp C ASM)

set(CMAKE_C_STANDARD 11)

# ---------- MCU flags ----------
set(MCU_FLAGS "-mcpu=cortex-m7 -mthumb -mfloat-abi=hard -mfpu=fpv5-d16")
# Debian arm-none-eabi-gcc installs newlib headers/libs in non-standard paths
set(NEWLIB_MULTILIB "/usr/lib/arm-none-eabi/newlib/thumb/v7e-m+dp/hard")
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} ${MCU_FLAGS} -Wall -O1 -ffunction-sections -fdata-sections -fno-builtin -mno-unaligned-access")
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -Wno-unused-parameter -Wno-missing-field-initializers -Wno-sign-compare")
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -isystem /usr/include/newlib")
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} ${MCU_FLAGS} \
    -T${CMAKE_SOURCE_DIR}/same70q21b_gcc.ld \
    -Wl,--gc-sections -Wl,--print-memory-usage \
    -L${NEWLIB_MULTILIB} -nostartfiles \
    -specs=${NEWLIB_MULTILIB}/nosys.specs -lc -lgcc -lnosys")

# ---------- XC32 compatibility ----------
# Add project root to system include path so #include <libpic32c.h> finds our shim
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -isystem ${CMAKE_SOURCE_DIR}")
# Define __XC32 for files that check it (most just emit a warning)
# Instead we suppress the XC32 warning
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -Wno-cpp")

# ---------- Include directories ----------
set(CFG ${CMAKE_SOURCE_DIR}/config)
include_directories(
    ${CMAKE_SOURCE_DIR}
    ${CMAKE_SOURCE_DIR}/arm
    ${CFG}
    ${CFG}/bsp
    ${CFG}/crypto
    ${CFG}/crypto/src
    ${CFG}/driver
    ${CFG}/driver/ethphy
    ${CFG}/driver/ethphy/src
    ${CFG}/driver/ethphy/src/dynamic
    ${CFG}/driver/gmac
    ${CFG}/driver/gmac/src
    ${CFG}/driver/gmac/src/dynamic
    ${CFG}/driver/miim
    ${CFG}/driver/miim/src
    ${CFG}/driver/miim/src/dynamic
    ${CFG}/library
    ${CFG}/library/tcpip
    ${CFG}/library/tcpip/src
    ${CFG}/library/tcpip/src/common
    ${CFG}/net_pres/pres
    ${CFG}/net_pres/pres/src
    ${CFG}/osal
    ${CFG}/peripheral/clk
    ${CFG}/peripheral/efc
    ${CFG}/peripheral/mpu
    ${CFG}/peripheral/nvic
    ${CFG}/peripheral/pio
    ${CFG}/peripheral/tc
    ${CFG}/peripheral/usart
    ${CFG}/stdio
    ${CFG}/system
    ${CFG}/system/cache
    ${CFG}/system/command
    ${CFG}/system/command/src
    ${CFG}/system/console
    ${CFG}/system/console/src
    ${CFG}/system/debug
    ${CFG}/system/debug/src
    ${CFG}/system/int
    ${CFG}/system/int/src
    ${CFG}/system/reset
    ${CFG}/system/time
    ${CFG}/system/time/src
    # CMSIS + DFP
    ${CMAKE_SOURCE_DIR}/packs/CMSIS/CMSIS/Core/Include
    ${CMAKE_SOURCE_DIR}/packs/ATSAME70Q21B_DFP
    # FreeRTOS
    ${CMAKE_SOURCE_DIR}/third_party/rtos/FreeRTOS/Source/include
    ${CMAKE_SOURCE_DIR}/third_party/rtos/FreeRTOS/Source/portable/GCC/SAM/CM7
)

# ---------- Source files ----------

# GCC startup (replaces startup_xc32.c and interrupts.c)
set(STARTUP_SRCS
    startup_gcc.c
)

# Application
set(APP_SRCS
    app.c
    drv_mcp3204.c
)

# Harmony config / BSP / peripheral / system / library
set(HARMONY_SRCS
    config/bsp/bsp.c
    config/exceptions.c
    config/freertos_hooks.c
    config/initialization.c
    config/libc_syscalls.c
    config/stdio/xc32_monitor.c
    config/tasks.c
    # Peripherals
    config/peripheral/clk/plib_clk.c
    config/peripheral/efc/plib_efc.c
    config/peripheral/mpu/plib_mpu.c
    config/peripheral/nvic/plib_nvic.c
    config/peripheral/pio/plib_pio.c
    config/peripheral/tc/plib_tc0.c
    config/peripheral/usart/plib_usart1.c
    # System services
    config/osal/osal_freertos.c
    config/system/cache/sys_cache.c
    config/system/command/src/sys_command.c
    config/system/console/src/sys_console.c
    config/system/console/src/sys_console_uart.c
    config/system/debug/src/sys_debug.c
    config/system/int/src/sys_int.c
    config/system/reset/sys_reset.c
    # config/system/sys_random_h2_adapter.c  # uses wolfSSL, replaced by crypto_stubs.c
    config/system/sys_time_h2_adapter.c
    config/system/time/src/sys_time.c
    # Crypto stubs (minimal, no wolfSSL)
    ${CMAKE_SOURCE_DIR}/crypto_stubs.c
    # Network presentation
    config/net_pres/pres/net_pres_cert_store.c
    config/net_pres/pres/net_pres_enc_glue.c
    config/net_pres/pres/src/net_pres.c
)

# Ethernet: GMAC + MIIM + ETHPHY + LAN867x
set(ETH_SRCS
    config/driver/gmac/src/dynamic/drv_gmac.c
    config/driver/gmac/src/dynamic/drv_gmac_lib_samE7x_V7x.c
    config/driver/miim/src/dynamic/drv_miim.c
    config/driver/miim/src/dynamic/drv_miim_gmac.c
    config/driver/ethphy/src/dynamic/drv_ethphy.c
    config/driver/ethphy/src/dynamic/drv_extphy_lan867x.c
)

# TCP/IP Stack (Harmony)
set(TCPIP_SRCS
    config/library/tcpip/src/arp.c
    config/library/tcpip/src/berkeley_api.c
    config/library/tcpip/src/dhcp.c
    config/library/tcpip/src/dns.c
    config/library/tcpip/src/hash_fnv.c
    config/library/tcpip/src/helpers.c
    config/library/tcpip/src/icmp.c
    config/library/tcpip/src/ipv4.c
    config/library/tcpip/src/oahash.c
    config/library/tcpip/src/tcp.c
    config/library/tcpip/src/tcpip_announce.c
    config/library/tcpip/src/tcpip_commands.c
    config/library/tcpip/src/tcpip_heap_alloc.c
    config/library/tcpip/src/tcpip_heap_internal.c
    config/library/tcpip/src/tcpip_helpers.c
    config/library/tcpip/src/tcpip_manager.c
    config/library/tcpip/src/tcpip_notify.c
    config/library/tcpip/src/tcpip_packet.c
    config/library/tcpip/src/udp.c
)

# FreeRTOS kernel (Cortex-M7 port + heap_1)
set(FREERTOS_SRCS
    third_party/rtos/FreeRTOS/Source/FreeRTOS_tasks.c
    third_party/rtos/FreeRTOS/Source/queue.c
    third_party/rtos/FreeRTOS/Source/list.c
    third_party/rtos/FreeRTOS/Source/timers.c
    third_party/rtos/FreeRTOS/Source/event_groups.c
    third_party/rtos/FreeRTOS/Source/stream_buffer.c
    third_party/rtos/FreeRTOS/Source/croutine.c
    third_party/rtos/FreeRTOS/Source/portable/GCC/SAM/CM7/port.c
    third_party/rtos/FreeRTOS/Source/portable/MemMang/heap_3.c
)

# ---------- Zenoh-pico ----------
set(ZP ${CMAKE_SOURCE_DIR}/zenoh-pico)

# zenoh-pico defines
add_definitions(
    -DZENOH_FREERTOS_HARMONY
    -DZ_FEATURE_MULTI_THREAD=1
    -DZ_FEATURE_PUBLICATION=1
    -DZ_FEATURE_SUBSCRIPTION=1
    -DZ_FEATURE_QUERY=1
    -DZ_FEATURE_QUERYABLE=1
    -DZ_FEATURE_LIVELINESS=1
    -DZ_FEATURE_LINK_TCP=1
    -DZ_FEATURE_LINK_UDP=0
    -DZ_FEATURE_LINK_SERIAL=0
    -DZ_FEATURE_SCOUTING=0
    -DZ_FEATURE_RAWETH_TRANSPORT=0
    -DZ_FEATURE_LINK_BLUETOOTH=0
    -DZ_FEATURE_LINK_WS=0
    -DZ_FEATURE_LINK_TLS=0
    -DZ_FEATURE_MULTICAST_TRANSPORT=0
    -DZ_FEATURE_FRAGMENTATION=1
    -DZ_FEATURE_BATCHING=1
    -DZ_FEATURE_AUTO_RECONNECT=1
    -DZ_FEATURE_INTEREST=1
    -DZ_FEATURE_DYNAMIC_MEMORY_ALLOCATION=1
    -DZ_FEATURE_MATCHING=0
)

# zenoh-pico include directories
include_directories(
    ${ZP}/include
)

# zenoh-pico system layer (FreeRTOS + Harmony)
set(ZENOH_SYSTEM_SRCS
    ${ZP}/src/system/freertos/system.c
    ${ZP}/src/system/freertos/harmony/network.c
)

# zenoh-pico core sources
file(GLOB_RECURSE ZENOH_CORE_SRCS
    ${ZP}/src/api/*.c
    ${ZP}/src/collections/*.c
    ${ZP}/src/link/config/*.c
    ${ZP}/src/link/unicast/*.c
    ${ZP}/src/net/*.c
    ${ZP}/src/protocol/*.c
    ${ZP}/src/runtime/*.c
    ${ZP}/src/session/*.c
    ${ZP}/src/transport/common/*.c
    ${ZP}/src/transport/unicast/*.c
    ${ZP}/src/utils/*.c
)
# Individual link/transport files
list(APPEND ZENOH_CORE_SRCS
    ${ZP}/src/link/endpoint.c
    ${ZP}/src/link/link.c
    ${ZP}/src/link/multicast/udp.c
    ${ZP}/src/transport/manager.c
    ${ZP}/src/transport/transport.c
    ${ZP}/src/transport/utils.c
    ${ZP}/src/transport/multicast.c
    ${ZP}/src/transport/peer.c
)
# Multicast + raweth transport
file(GLOB_RECURSE ZENOH_MC_SRCS
    ${ZP}/src/transport/multicast/*.c
    ${ZP}/src/transport/raweth/*.c
)
list(APPEND ZENOH_CORE_SRCS ${ZENOH_MC_SRCS})

# ---------- Build target ----------
add_executable(firmware.elf
    ${STARTUP_SRCS}
    ${APP_SRCS}
    app_zenoh.c
    e2e_protection.c
    secoc.c
    safety_manager.c
    watchdog.c
    ids_engine.c
    dtc_manager.c
    flow_monitor.c
    key_manager.c
    ${HARMONY_SRCS}
    ${ETH_SRCS}
    ${TCPIP_SRCS}
    ${FREERTOS_SRCS}
    ${ZENOH_SYSTEM_SRCS}
    ${ZENOH_CORE_SRCS}
)

# ---------- Post-build: .bin / .hex / size ----------
add_custom_command(TARGET firmware.elf POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O binary firmware.elf firmware.bin
    COMMAND ${CMAKE_OBJCOPY} -O ihex   firmware.elf firmware.hex
    COMMAND ${CMAKE_SIZE} firmware.elf
    COMMENT "Generating firmware.bin / firmware.hex"
)
