cmake_minimum_required(VERSION 3.20)

project(sam-e70-firmware C ASM)

set(CMAKE_C_STANDARD 11)

# Cortex-M7 with hardware FPU
set(MCU_FLAGS "-mcpu=cortex-m7 -mthumb -mfloat-abi=hard -mfpu=fpv5-d16")

set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} ${MCU_FLAGS} -Wall -Wextra -Os -ffunction-sections -fdata-sections -fno-builtin")
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} ${MCU_FLAGS} \
    -T${CMAKE_SOURCE_DIR}/linker/same70q21_flash.ld \
    -Wl,--gc-sections -nostdlib -lgcc")

include_directories(include)

add_executable(firmware.elf
    src/main.c
    src/startup_same70.c
)

# Post-build: generate .bin, .hex, print size
add_custom_command(TARGET firmware.elf POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O binary firmware.elf firmware.bin
    COMMAND ${CMAKE_OBJCOPY} -O ihex   firmware.elf firmware.hex
    COMMAND ${CMAKE_SIZE} firmware.elf
    COMMENT "Generating firmware.bin / firmware.hex"
)
