# SAM E70 Zenoh-pico Slave Node over 10BASE-T1S

SAM E70 Xplained Ultra (ATSAME70Q21) + EVB-LAN8670-RMII 보드에서 동작하는
zenoh-pico 슬레이브 노드 펌웨어. Raspberry Pi 5 마스터와 10BASE-T1S 물리 버스를
통해 Zenoh 프로토콜로 통신한다.

## 하드웨어 구성

```
[RPi 5]                                 [SAM E70 Xplained Ultra]
├── EVB-LAN8670-USB (eth1)              ├── EVB-LAN8670-RMII (ETHERNET PHY 헤더)
│   └── 10BASE-T1S ────wire────────────→│   └── LAN8670 PHY (RMII, CSMA/CD)
├── USB ─────────────DEBUG USB──────────→│   └── EDBG CMSIS-DAP (플래싱/디버깅/시리얼)
└── zenohd router (tcp/192.168.100.1:7447)  └── zenoh-pico client (192.168.100.11)
```

| 구성 요소 | 상세 |
|-----------|------|
| MCU | ATSAME70Q21 (Cortex-M7, 300MHz, 2MB Flash, 384KB SRAM) |
| PHY | LAN8670 10BASE-T1S via RMII (PD0-PD9) |
| RTOS | FreeRTOS v10.5.1 |
| TCP/IP | Microchip Harmony v3 TCP/IP Stack |
| Protocol | Zenoh-pico v1.9.0 (TCP client mode) |
| LED | PA5 (STAT), PB8 (LED2) |
| Switch | PA11 |
| EDBG | USB VID:PID 03eb:2111, Serial /dev/ttyACM0 |

## 빌드 환경

### 필수 패키지 (Raspberry Pi OS / Debian)

```bash
sudo apt install gcc-arm-none-eabi libnewlib-arm-none-eabi openocd
```

### 빌드

```bash
cd firmware/sam-e70
mkdir build && cd build
cmake .. -DCMAKE_TOOLCHAIN_FILE=../toolchain-sam-e70.cmake -DCMAKE_BUILD_TYPE=Release
cmake --build . -j4
```

결과물:
- `build/firmware.elf` (265KB Flash, 18KB SRAM)
- `build/firmware.bin`
- `build/firmware.hex`

### 플래싱

```bash
openocd -f interface/cmsis-dap.cfg -f target/atsamv.cfg \
  -c "program build/firmware.elf verify reset exit"
```

### 시리얼 콘솔

```bash
# 115200 8N1
minicom -D /dev/ttyACM0 -b 115200
# 또는
stty -F /dev/ttyACM0 115200 raw -echo && cat /dev/ttyACM0
```

## 동작 확인

### 1. Ping 테스트

```bash
# RPi에서 10BASE-T1S 인터페이스에 IP 할당
sudo ip addr add 192.168.100.1/24 dev eth1

# SAM E70 ping
ping -I eth1 192.168.100.11
# RTT: ~1.4ms
```

### 2. Zenoh Pub/Sub 테스트

```bash
# RPi: zenohd 라우터 시작
zenohd --listen tcp/192.168.100.1:7447

# RPi: 센서 데이터 수신 (다른 터미널)
python3 -c "
import zenoh, time
conf = zenoh.Config()
conf.insert_json5('connect/endpoints', '[\"tcp/192.168.100.1:7447\"]')
conf.insert_json5('mode', '\"client\"')
session = zenoh.open(conf)
sub = session.declare_subscriber('vehicle/**',
    lambda s: print(f'{s.key_expr}: {s.payload.to_string()}'))
time.sleep(30)
"
```

SAM E70 시리얼 출력:
```
LAN867x Rev.B Initial Setting Ended
TCP/IP Stack: Initialization Ended - success
GMAC IP Address: 192.168.100.11
[ZENOH] Session opened!
[ZENOH] Publisher: vehicle/front_left/1/sensor/temperature
[ZENOH] Publishing every 1000 ms
[ZENOH] Published 10 messages (temp=21.0)
```

RPi 수신 데이터:
```
vehicle/front_left/1/sensor/temperature: {"temp":20.2,"unit":"C","seq":1}
vehicle/front_left/1/sensor/temperature: {"temp":20.3,"unit":"C","seq":2}
...
```

## 프로젝트 구조

```
firmware/sam-e70/
├── CMakeLists.txt              # 통합 빌드 (Harmony + zenoh-pico + app)
├── toolchain-sam-e70.cmake     # ARM Cortex-M7 크로스 컴파일 툴체인
├── same70q21b_gcc.ld           # GCC 링커 스크립트 (2MB Flash, 384KB SRAM)
├── startup_gcc.c               # GCC 스타트업 (벡터 테이블 + Reset_Handler)
├── libpic32c.h                 # XC32 → GCC 호환 심
├── crypto_stubs.c              # wolfSSL 대체 스텁 (MD5, PRNG)
├── app.c / app.h               # Harmony TCP echo server (Berkeley socket)
├── app_zenoh.c                 # zenoh-pico 센서 노드 앱 (FreeRTOS task)
├── main.c                      # Harmony main (SYS_Initialize + SYS_Tasks)
│
├── config/                     # Harmony v3 생성 코드 (sam_e70_xult_freertos)
│   ├── configuration.h         # 전체 설정 (PHY, GMAC, FreeRTOS, TCP/IP)
│   ├── FreeRTOSConfig.h        # FreeRTOS 설정 (128KB heap, recursive mutex)
│   ├── initialization.c        # 시스템 초기화 (LAN867x PHY 포함)
│   ├── tasks.c                 # FreeRTOS 태스크 생성 (zenoh_task 포함)
│   ├── bsp/                    # BSP (LED PA5, Switch PA11)
│   ├── driver/
│   │   ├── ethphy/src/dynamic/drv_extphy_lan867x.c  # LAN867x PHY 드라이버
│   │   ├── gmac/               # GMAC Ethernet MAC 드라이버
│   │   └── miim/               # MDIO/MDC PHY 레지스터 접근
│   ├── library/tcpip/          # Harmony TCP/IP 스택 (ARP, ICMP, TCP, UDP, DHCP, DNS, Berkeley API)
│   └── peripheral/             # 페리페럴 라이브러리 (CLK, PIO, USART, TC, MPU, EFC, NVIC)
│
├── zenoh-pico/                 # zenoh-pico v1.9.0 소스
│   ├── include/                # zenoh-pico 헤더
│   │   └── zenoh-pico/system/platform/freertos/harmony.h  # Harmony 플랫폼 헤더
│   └── src/
│       ├── system/freertos/
│       │   ├── system.c        # FreeRTOS 시스템 레이어 (수정: Harmony 분기 추가)
│       │   └── harmony/
│       │       └── network.c   # Harmony Native TCP API 네트워크 레이어 (신규)
│       └── (api, collections, link, net, protocol, session, transport, utils)
│
├── third_party/rtos/FreeRTOS/  # FreeRTOS 커널
├── packs/                      # CMSIS + ATSAME70Q21B DFP
│
└── blink/                      # LED blink 테스트 (bare-metal, 참고용)
    ├── src/main.c
    └── src/startup_same70.c
```

## 핵심 설정 (configuration.h)

```c
/* 10BASE-T1S: 10 Mbps Half-Duplex, No Auto-Negotiation */
#define TCPIP_GMAC_ETH_OPEN_FLAGS  (TCPIP_ETH_OPEN_HDUPLEX | TCPIP_ETH_OPEN_10 | TCPIP_ETH_OPEN_RMII)

/* LAN867x PHY */
#define DRV_LAN867X_PHY_ADDRESS    0
/* #define DRV_ETHPHY_PLCA_ENABLED */  /* CSMA/CD mode (RPi 호환) */

/* Network */
Static IP: 192.168.100.11/24, Gateway: 192.168.100.1
MAC: 00:04:25:1C:A0:02

/* FreeRTOS */
#define configTOTAL_HEAP_SIZE      131072  /* 128KB */
#define configUSE_RECURSIVE_MUTEXES 1      /* zenoh-pico 필수 */

/* BSD Sockets */
#define MAX_BSD_SOCKETS            8
#define TCPIP_TCP_MAX_SOCKETS      10
```

## Zenoh-pico Harmony 포팅 노트

### 네트워크 레이어 (`harmony/network.c`)

Harmony Berkeley Socket API 대신 **Harmony Native TCP API**를 사용:

| 동작 | Berkeley API (미동작) | Native API (사용) |
|------|----------------------|-------------------|
| 연결 | `connect()` → EINPROGRESS 영원히 | `TCPIP_TCP_ClientOpen()` + `TCPIP_TCP_IsConnected()` |
| 송신 | `send()` | `TCPIP_TCP_ArrayPut()` + `TCPIP_TCP_Flush()` |
| 수신 | `recv()` | `TCPIP_TCP_GetIsReady()` + `TCPIP_TCP_ArrayGet()` |
| 종료 | `closesocket()` | `TCPIP_TCP_Close()` |

### getaddrinfo 워커라운드

Harmony `getaddrinfo()`가 포트를 0으로 설정하는 버그 → `sockaddr_in`을 수동 구성.

### 해결한 GCC 포팅 이슈

| 이슈 | 원인 | 해결 |
|------|------|------|
| GMAC DMA 실패 (HRESP error) | D-Cache + DMA 충돌 | D-Cache 비활성화 |
| UsageFault UNALIGNED | GCC -O3가 LDRD 생성 | `-mno-unaligned-access` |
| `nosys.specs` 미존재 | Debian 패키지 경로 | `-L/usr/lib/arm-none-eabi/newlib/thumb/v7e-m+dp/hard` |
| `libpic32c.h` 미존재 | XC32 전용 | 호환 심 헤더 제공 |
| wolfSSL 의존성 | 37MB 크기 | `crypto_stubs.c`로 대체 |
| FreeRTOS `tasks.c` 버전 충돌 | task.h 매크로 불일치 | `FreeRTOS_tasks.c` 사용 |
| LAN867x API 버전 차이 | `phy_*` vs `DRV_ETHPHY_*` | sed로 멤버 이름 교체 |
| `atomic_init` `__val` 접근 | bare-metal GCC stdatomic | 직접 대입으로 교체 |

## 참고 자료

- [Microchip net_10base_t1s](https://github.com/Microchip-MPLAB-Harmony/net_10base_t1s) — LAN867x PHY 드라이버
- [Microchip net_apps_sam_e70_v71](https://github.com/Microchip-MPLAB-Harmony/net_apps_sam_e70_v71) — Berkeley TCP server 데모 기반
- [zenoh-pico](https://github.com/eclipse-zenoh/zenoh-pico) — v1.9.0, FreeRTOS 지원
- [EVB-LAN8670-RMII](https://www.microchip.com/en-us/development-tool/EV06Q48A) — 10BASE-T1S PHY 평가 보드
- [SAM E70 Xplained Ultra](https://www.microchip.com/en-us/development-tool/DM320113) — DM320113
