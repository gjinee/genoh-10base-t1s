# 양방향 제어 데모 설계 문서

## 1. 개요

SAM E70 슬레이브 MCU와 Raspberry Pi 마스터 간 10BASE-T1S 물리 버스 위에서
Zenoh 프로토콜을 사용한 양방향 실시간 제어 데모.

### 시나리오

| 방향 | 기능 | 설명 |
|------|------|------|
| RPi → MCU (Downlink) | 전조등/비상등 제어 | GUI에서 버튼으로 MCU의 LED 2개를 ON/OFF |
| MCU → RPi (Uplink) | 핸들 조향 시뮬레이션 | Thumbstick Click 조이스틱으로 핸들 각도 전송, GUI에 실시간 표시 |

```
┌──── Raspberry Pi 5 (Master) ────┐          ┌──── SAM E70 (Slave) ────────────┐
│                                  │          │                                 │
│  ┌──────────── GUI ───────────┐  │  Zenoh   │  ┌─────────┐    ┌───────────┐  │
│  │  [전조등 ON/OFF]           │──┼──publish──┼─►│ LED1    │    │Thumbstick │  │
│  │  [비상등 ON/OFF]           │──┼──publish──┼─►│ LED2    │    │Click      │  │
│  │                            │  │  TCP /    │  │ (PA5)   │    │(MCP3204)  │  │
│  │  핸들 각도: ◄──── -15° ──► │◄─┼─subscribe─┼──│ (PB8)   │    │ X/Y/Btn   │  │
│  │  [●] 버튼 상태             │◄─┼──────────┼──│         │    │           │  │
│  └────────────────────────────┘  │ 10BASE   │  └─────────┘    └───────────┘  │
│                                  │  -T1S    │                                 │
│  zenohd router                   │          │  zenoh-pico client              │
│  tcp/192.168.100.1:7447          │          │  192.168.100.11                 │
└──────────────────────────────────┘          └─────────────────────────────────┘
```

## 2. 하드웨어 구성

### 2.1 SAM E70 Xplained Ultra

| 구성 요소 | 핀 | 기능 |
|-----------|-----|------|
| LED1 (전조등) | PA5 | Active Low, BSP `LED1_Toggle()` |
| LED2 (비상등) | PB8 | Active Low, BSP `LED2_Toggle()` |
| Switch (SW0) | PA11 | Active Low, Pull-up |

### 2.2 Thumbstick Click (MIKROE-2024)

| 특성 | 값 |
|------|-----|
| 조이스틱 | 2축 아날로그 (10K 포텐셔미터 x2) |
| ADC | MCP3204 12-bit, 4채널 SPI |
| X축 범위 | 0 ~ 4095 (중앙 ~2048) |
| Y축 범위 | 0 ~ 4095 (중앙 ~2048) |
| 버튼 | 조이스틱 누름 (디지털) |
| 인터페이스 | SPI + GPIO (INT) |
| 전압 | 3.3V |

### 2.3 온보드 mikroBUS 헤더 핀 매핑 (J900/J903)

SAM E70 Xplained Ultra에는 **전용 mikroBUS 헤더**가 보드 하단 중앙에 있다.
(EXT1/EXT2 확장 헤더와는 별도. User Guide Table 1 #3, 회로도 p37 참조)

Thumbstick Click은 이 mikroBUS 헤더에 직접 장착한다.

| mikroBUS 핀 | 이름 | Thumbstick 용도 | SAM E70 핀 | 페리페럴 |
|-------------|------|---------------|-----------|----------|
| 16 | AN | (미사용, SPI ADC 사용) | PD30 | AFEC0_AD0 |
| 15 | RST | (미사용) | PA25 | GPIO |
| 14 | CS | MCP3204 Chip Select | PD25 | SPI0_NPCS1 / GPIO |
| 13 | SCK | SPI Clock | PD22 | SPI0_SPCK |
| 12 | MISO | SPI Data Out (ADC→MCU) | PD20 | SPI0_MISO |
| 11 | MOSI | SPI Data In (MCU→ADC) | PD21 | SPI0_MOSI |
| 10 | +3.3V | 전원 | 3.3V | - |
| 9 | GND | 그라운드 | GND | - |
| 8 | PWM | (미사용) | PA0 | PWMC0_H0 |
| 7 | INT | 조이스틱 버튼 (눌림=LOW) | PA21 | GPIO Input |
| 6 | RX | (미사용) | PB4 | USART1_TXD1 |
| 5 | TX | (미사용) | PA21 | USART1_RXD1 |
| 4 | SCL | (미사용) | PA4 | TWIHS0_TWCK0 |
| 3 | SDA | (미사용) | PA3 | TWIHS0_TWD0 |
| 2 | +5V | 전원 | 5V | - |
| 1 | GND | 그라운드 | GND | - |

**주의**: SPI0 버스는 EDBG, EXT1, mikroBUS, Ethernet PHY 간 **공유**됨.
각 디바이스는 별도 CS 라인으로 선택. Thumbstick CS = PD25.

**주의**: LED2(PB8)는 USB VBUS detect 점퍼(J204)와 공유됨.
점퍼를 LED2 위치(pin1-2)에 설정해야 LED2로 동작함. (User Guide p20)

## 3. Zenoh 프로토콜 설계

### 3.1 Key Expressions

```
vehicle/front_left/1/
├── actuator/
│   ├── headlight     ← RPi → MCU (전조등 제어)
│   └── hazard        ← RPi → MCU (비상등 제어)
└── sensor/
    └── steering      ← MCU → RPi (핸들 조향 데이터)
```

### 3.2 메시지 페이로드

#### 전조등 제어 (RPi → MCU)
```json
{"state": "on"}
{"state": "off"}
```

#### 비상등 제어 (RPi → MCU)
```json
{"state": "on"}
{"state": "off"}
```

#### 핸들 조향 데이터 (MCU → RPi)
```json
{
  "x": 2048,
  "y": 2030,
  "btn": 0,
  "angle": -15.2,
  "seq": 142
}
```

| 필드 | 타입 | 범위 | 설명 |
|------|------|------|------|
| x | uint16 | 0~4095 | X축 ADC raw 값 (좌=0, 중앙=2048, 우=4095) |
| y | uint16 | 0~4095 | Y축 ADC raw 값 (하=0, 중앙=2048, 상=4095) |
| btn | uint8 | 0 or 1 | 조이스틱 버튼 (0=미눌림, 1=눌림) |
| angle | float | -90~+90 | X축 기반 조향 각도 (도) |
| seq | uint32 | 0~ | 시퀀스 번호 |

#### 조향 각도 계산
```
angle = (x - 2048) / 2048.0 * 90.0
// x=0 → angle=-90° (좌회전 최대)
// x=2048 → angle=0° (직진)
// x=4095 → angle=+90° (우회전 최대)
```

## 4. 구현 계획

### Phase 0: 하드웨어 테스트 (선행)

#### 0-1. LED + 버튼 양방향 테스트 (추가 하드웨어 불필요)

**목적**: Zenoh 양방향 통신 검증 (Thumbstick 없이)

**MCU 펌웨어 수정 (`app_zenoh.c`)**:
- subscriber 2개 추가: `actuator/headlight`, `actuator/hazard`
- 수신 시 LED1(PA5), LED2(PB8) 제어
- 기존 SW0(PA11) 버튼 누르면 steering 이벤트 publish

**RPi 테스트 스크립트**:
```bash
# LED 제어 테스트
python3 -c "
import zenoh
s = zenoh.open(zenoh.Config())
s.put('vehicle/front_left/1/actuator/headlight', '{\"state\":\"on\"}')
"

# 버튼 이벤트 수신
python3 -c "
import zenoh, time
s = zenoh.open(zenoh.Config())
sub = s.declare_subscriber('vehicle/front_left/1/sensor/steering',
    lambda sample: print(sample.payload.to_string()))
time.sleep(30)
"
```

**완료 기준**: RPi에서 LED ON/OFF 명령 → MCU LED 변화 확인, MCU 버튼 → RPi 콘솔 출력 확인

#### 0-2. Thumbstick Click SPI 통신 테스트

**목적**: MCP3204 ADC SPI 통신 검증

**MCU 펌웨어 추가**:
- SPI 페리페럴 초기화 (SPI0 또는 SPI1, 헤더 위치에 따라)
- MCP3204 SPI 프로토콜 구현:
  ```
  TX: [0x06 | (ch>>2), (ch<<6), 0x00]  (single-ended, 12-bit)
  RX: [x, MSB 4bit, LSB 8bit]
  ```
- CH0=X축, CH1=Y축 읽기
- INT 핀으로 버튼 상태 읽기
- 시리얼 콘솔에 ADC 값 출력 (100ms 간격)

**완료 기준**: 조이스틱 움직임에 따라 시리얼에 X/Y 값 변화 확인 (0~4095)

### Phase 1: MCU 펌웨어 통합

**파일**: `firmware/sam-e70/app_zenoh.c` (수정)

```c
// 기존 sensor/temperature publish + 추가:

// Subscribers (RPi → MCU)
subscribe("vehicle/front_left/1/actuator/headlight", headlight_handler);
subscribe("vehicle/front_left/1/actuator/hazard", hazard_handler);

// headlight_handler: parse JSON → LED1_Set(on/off)
// hazard_handler: parse JSON → LED2_Set(on/off) + 비상등 깜빡임 타이머

// Publisher (MCU → RPi)
// 100ms 타이머로:
//   1. MCP3204 SPI read (CH0=X, CH1=Y)
//   2. GPIO read (button)
//   3. angle 계산
//   4. zenoh publish "vehicle/.../sensor/steering"
```

**Harmony 페리페럴 추가 필요**:
- SPI0 PLIB 초기화 (`plib_spi0.c`) — SCK=PD22, MISO=PD20, MOSI=PD21
- GPIO 출력: CS=PD25 (MCP3204 선택)
- GPIO 입력: INT=PA21 (조이스틱 버튼, Pull-up)
- PIO_Initialize()에 위 핀 설정 추가

**비상등 깜빡임 구현**:
```c
// hazard_state가 "on"이면 500ms 간격 LED2 토글
// FreeRTOS software timer 사용
```

### Phase 2: RPi GUI (Python tkinter)

**파일**: `gui/vehicle_control.py` (신규)

```
┌─────────────────────────────────────────────────┐
│            Vehicle Control Panel                 │
│                                                  │
│  ┌─── Actuators ────────────────────────────┐    │
│  │                                          │    │
│  │   [💡 전조등 ON ]    [⚠️ 비상등 OFF]     │    │
│  │                                          │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  ┌─── Steering ─────────────────────────────┐    │
│  │                                          │    │
│  │     ◄━━━━━━━━━━╋━━━━━━━━━━►              │    │
│  │              ▲                            │    │
│  │         angle: -15.2°                     │    │
│  │                                          │    │
│  │   X: 1820  Y: 2048  Button: [Released]   │    │
│  │                                          │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  ┌─── Connection ───────────────────────────┐    │
│  │  Router: tcp/192.168.100.1:7447          │    │
│  │  Status: Connected                       │    │
│  │  MCU IP: 192.168.100.11                  │    │
│  │  Messages: TX 42 / RX 1523              │    │
│  └──────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

**기능**:
1. 전조등/비상등 토글 버튼 (클릭 → zenoh publish)
2. 핸들 각도 게이지 바 (실시간 업데이트)
3. X/Y/Button raw 데이터 표시
4. 연결 상태 모니터링

**코드 구조**:
```python
class VehicleControlGUI:
    def __init__(self):
        self.session = zenoh.open(config)
        # Publishers
        self.pub_headlight = session.declare_publisher("vehicle/.../actuator/headlight")
        self.pub_hazard = session.declare_publisher("vehicle/.../actuator/hazard")
        # Subscriber
        self.sub_steering = session.declare_subscriber("vehicle/.../sensor/steering",
                                                        self.on_steering)
    def on_headlight_toggle(self):
        self.pub_headlight.put('{"state":"on"}' or '{"state":"off"}')

    def on_steering(self, sample):
        data = json.loads(sample.payload.to_string())
        self.update_steering_display(data['angle'], data['x'], data['y'], data['btn'])
```

### Phase 3: 통합 테스트

| 테스트 | 절차 | 기대 결과 |
|--------|------|----------|
| T1: 전조등 ON/OFF | GUI 버튼 클릭 | MCU LED1(PA5) 점등/소등 |
| T2: 비상등 ON/OFF | GUI 버튼 클릭 | MCU LED2(PB8) 500ms 깜빡임/소등 |
| T3: 조향 좌회전 | 조이스틱 좌로 | GUI angle < -10° |
| T4: 조향 우회전 | 조이스틱 우로 | GUI angle > +10° |
| T5: 조향 중립 | 조이스틱 놓기 | GUI angle ≈ 0° |
| T6: 버튼 누름 | 조이스틱 눌러서 | GUI "Pressed" 표시 |
| T7: 양방향 동시 | 전조등 ON + 조향 동시 | 양쪽 모두 정상 |
| T8: 지연 시간 | LED 명령 → LED 반응 | < 50ms |
| T9: 연결 끊김 | 10BASE-T1S 와이어 분리 | GUI "Disconnected" 표시 |
| T10: 재연결 | 와이어 재연결 | 자동 복구 |

## 5. 파일 구조

```
firmware/sam-e70/
├── app_zenoh.c          ← 수정: LED subscriber + steering publisher + MCP3204 읽기
├── drv_mcp3204.c        ← 신규: MCP3204 SPI ADC 드라이버 (SPI0, CS=PD25)
├── drv_mcp3204.h        ← 신규: MCP3204 헤더
├── config/
│   ├── peripheral/spi/  ← 추가: SPI0 PLIB (plib_spi0.c, SCK=PD22/MISO=PD20/MOSI=PD21)
│   ├── peripheral/pio/  ← 수정: PD25 GPIO출력(CS), PA21 GPIO입력(Button)
│   └── initialization.c ← 수정: SPI0 초기화 추가

gui/
├── vehicle_control.py   ← 신규: tkinter 제어 GUI
└── requirements.txt     ← zenoh, tkinter 등
```

## 6. 일정 추정

| Phase | 작업 | 예상 시간 |
|-------|------|----------|
| 0-1 | LED + 버튼 양방향 테스트 | 즉시 가능 |
| 0-2 | Thumbstick SPI 통신 테스트 | 어댑터 연결 후 |
| 1 | MCU 펌웨어 통합 | Phase 0 완료 후 |
| 2 | RPi GUI | Phase 1과 병행 가능 |
| 3 | 통합 테스트 | Phase 1+2 완료 후 |

## 7. 제약 사항 및 고려 사항

1. **SPI0 버스 공유**: mikroBUS의 SPI0는 EDBG, EXT1, Ethernet PHY와 공유. CS(PD25)로 MCP3204만 선택하도록 주의.
2. **FreeRTOS 태스크 우선순위**: zenoh task(1) vs TCPIP_STACK task(높음). 조이스틱 폴링이 TCP 통신에 지장 없도록 주의.
3. **MCP3204 SPI 속도**: 최대 2MHz @ 3.3V. SAM E70 SPI는 최대 MCK/2 = 75MHz이므로 분주비 설정 필요.
4. **비상등 깜빡임**: FreeRTOS software timer로 500ms 간격 토글. hazard "off" 시 타이머 중지 + LED OFF.
5. **JSON 파싱**: MCU에서 경량 JSON 파싱 필요. zenoh-pico의 payload는 raw bytes → `strstr()`/`sscanf()`로 간단 파싱.
6. **디스크 공간**: RPi 잔여 ~1.3GB. GUI는 Python이므로 추가 공간 거의 불필요.
