# PRD: 10BASE-T1S Zenoh 기반 자동차 마스터 제어기 시뮬레이션 모듈

## 문서 정보

| 항목 | 내용 |
|------|------|
| 프로젝트명 | Zenoh-10BASE-T1S Automotive Master Controller Simulator |
| 버전 | v0.2.0 |
| 작성일 | 2026-04-13 |
| 상태 | Draft (리뷰 반영) |

---

## 1. 개요 (Overview)

### 1.1 배경

자동차 E/E(Electrical/Electronic) 아키텍처가 도메인 기반에서 **존(Zone) 기반 아키텍처**로 전환되고 있다. 이 과정에서 기존 CAN/LIN 버스를 대체할 경량 이더넷 기술로 **IEEE 802.3cg 10BASE-T1S**(Single Pair Ethernet, Multidrop)가 주목받고 있다.

10BASE-T1S는 단일 비차폐 트위스티드 페어(UTP) 케이블에 최대 8개 노드를 멀티드롭으로 연결할 수 있으며, **PLCA(Physical Layer Collision Avoidance)** 메커니즘을 통해 결정론적(deterministic) 통신을 보장한다.

**Eclipse Zenoh**는 pub/sub/query를 통합한 경량 프로토콜로, 최근 자동차 분야에서의 적합성이 학술적으로 검증되었다:
- IEEE Access 2025 논문 "Stepping Toward Zenoh Protocol in Automotive Scenarios"에서 4-Zone 아키텍처 PoC가 구현됨
- DDS 대비 2배 처리량, MQTT 대비 50배 처리량 달성
- 메시지 지연 13μs, 와이어 오버헤드 5바이트의 초경량 프로토콜
- arXiv 2025 벤치마크에서 FastDDS(51.6ms), vSomeIP(98.4ms) 대비 디스커버리 시간 11.6ms 달성, 100% 메시지 전달 신뢰성 확인

본 프로젝트는 **Eclipse Zenoh** 프로토콜을 10BASE-T1S 물리 네트워크 위에서 운용하여, 자동차 존 컨트롤러(Zone Controller)의 **마스터 제어기 시뮬레이션 모듈**을 개발하는 것을 목표로 한다.

### 1.2 목적

- Raspberry Pi + EVB-LAN8670-USB 기반 10BASE-T1S 네트워크 환경 구축
- **Zenoh Router(zenohd)** 를 마스터(Coordinator)로 운용하는 시뮬레이터 개발
- **Zenoh-pico** 기반 슬레이브 노드와의 Pub/Sub/Query 통신 시뮬레이션
- 자동차 존 아키텍처에서의 센서/액추에이터 제어 시나리오 검증

### 1.3 프로젝트 범위

| 범위 | 포함 | 제외 |
|------|------|------|
| 하드웨어 | EVB-LAN8670-USB, Raspberry Pi | 실차 ECU, 상용 스위치 |
| 프로토콜 | Zenoh (마스터), Zenoh-pico (슬레이브) | CAN, LIN, SOME/IP |
| 네트워크 | 10BASE-T1S (PLCA multidrop) | 100BASE-T1, 1000BASE-T |
| 소프트웨어 | 시뮬레이션 모듈, 모니터링 도구 | 양산용 소프트웨어 |

---

## 2. 시스템 아키텍처 (System Architecture)

### 2.1 전체 토폴로지

```
┌──────────────────────────────────────────────────────────┐
│                 10BASE-T1S Multidrop Bus                   │
│            (Single UTP Cable, PLCA Enabled)                │
├──────────┬──────────┬──────────┬──────────┬──────────────┤
│          │          │          │          │  최대 8 노드   │
▼          ▼          ▼          ▼          │               │
┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐│               │
│ Master │ │Slave 1 │ │Slave 2 │ │Slave N ││               │
│(Node 0)│ │(Node 1)│ │(Node 2)│ │(Node N)││               │
├────────┤ ├────────┤ ├────────┤ ├────────┤│               │
│  RPi   │ │  MCU   │ │  MCU   │ │  MCU   ││               │
│   +    │ │   +    │ │   +    │ │   +    ││               │
│EVB-USB │ │LAN8670 │ │LAN8670 │ │LAN8670 ││               │
├────────┤ ├────────┤ ├────────┤ ├────────┤│               │
│ Zenoh  │ │ Zenoh- │ │ Zenoh- │ │ Zenoh- ││               │
│ Router │ │  pico  │ │  pico  │ │  pico  ││               │
│(zenohd)│ │(client)│ │(client)│ │(client)││               │
└────────┘ └────────┘ └────────┘ └────────┘│               │
    │          │          │          │      │               │
    │   PLCA Coordinator  │          │      │               │
    │   (Beacon Gen.)     │          │      │               │
    └──────────┴──────────┴──────────┴──────┘               │
└──────────────────────────────────────────────────────────┘
```

### 2.2 계층 구조

```
┌─────────────────────────────────────────────┐
│          Application Layer                   │
│  (Sensor/Actuator Simulation Logic)         │
├─────────────────────────────────────────────┤
│          Zenoh Protocol Layer                │
│  Master: Zenoh Router (Rust, zenohd)        │
│  Slave:  Zenoh-pico (C, client mode)        │
├─────────────────────────────────────────────┤
│          Transport Layer                     │
│  TCP/UDP over IPv4/IPv6                      │
│  (10BASE-T1S 버스 위 표준 IP 통신)           │
├─────────────────────────────────────────────┤
│          Network Interface Layer             │
│  Linux eth (USB-CDC-ECM via LAN9500A)       │
├─────────────────────────────────────────────┤
│          MAC-PHY Layer (OA TC6)              │
│  SPI ↔ LAN8670 (10BASE-T1S MAC-PHY)        │
├─────────────────────────────────────────────┤
│          Physical Layer                      │
│  10BASE-T1S (IEEE 802.3cg)                  │
│  PLCA (Multidrop, Deterministic Access)     │
└─────────────────────────────────────────────┘
```

> **참고**: Zenoh-pico는 `Z_FEATURE_RAWETH_TRANSPORT` 플래그로 Raw Ethernet(Layer 2) 트랜스포트를 지원하지만, 이는 **zenoh-pico 간 peer-to-peer 전용**이며 zenohd(Rust router)는 raweth를 지원하지 않는다. 본 프로젝트에서 마스터(zenohd)↔슬레이브(zenoh-pico) 통신은 **TCP/UDP 기반**으로 고정한다. 향후 마스터도 zenoh-pico(C)로 전환할 경우에 한해 raweth 검토가 가능하다.

### 2.3 마스터(Master) 역할 정의

마스터 노드는 두 가지 레벨에서 "마스터" 역할을 수행한다:

| 레벨 | 역할 | 구현 |
|------|------|------|
| **PHY 레벨** | PLCA Coordinator (Node ID 0) | EVB-LAN8670-USB PLCA 설정 (ethtool) |
| **Application 레벨** | Zenoh Router | zenohd 데몬 + 커스텀 플러그인/애플리케이션 |

### 2.4 zenohd와 마스터 애플리케이션 간 통신 구조

zenohd(Rust 바이너리)와 Python 마스터 애플리케이션은 **동일 호스트에서 별개 프로세스**로 동작한다. Python 앱은 zenoh Python API(`eclipse-zenoh`)를 **client 모드**로 설정하여 로컬 zenohd에 TCP loopback(`tcp/127.0.0.1:7447`)으로 연결한다.

```
┌────────────────────────────────────────────┐
│              Raspberry Pi                   │
│                                             │
│  ┌─────────────┐    ┌───────────────────┐  │
│  │   zenohd    │    │  Master App       │  │
│  │  (Router)   │◄───│  (Python)         │  │
│  │             │    │  mode: client     │  │
│  │ listen:     │    │  connect:         │  │
│  │  tcp/*:7447 │    │   tcp/127.0.0.1   │  │
│  └──────┬──────┘    └───────────────────┘  │
│         │ bind: eth1 (10BASE-T1S)          │
└─────────┼──────────────────────────────────┘
          │
    10BASE-T1S Bus ── Slave(zenoh-pico client)
```

> **설계 근거**: zenoh-python은 Rust Zenoh 엔진을 래핑하여 peer 모드(zenohd 없이 단독 실행)도 가능하지만, zenoh-pico 슬레이브가 client 모드로 zenohd router에 접속하는 구조이므로 zenohd를 별도 실행하는 것이 필수적이다. Python 앱은 client 모드로 로컬 라우터에 접속하며, 로컬 IPC 수준의 저지연(<1ms)으로 동작한다.

---

## 3. 하드웨어 요구사항 (Hardware Requirements)

### 3.1 마스터 노드

| 구성요소 | 사양 | 비고 |
|----------|------|------|
| SBC | Raspberry Pi 4B / 5 | Linux 호스트 |
| 10BASE-T1S 인터페이스 | EVB-LAN8670-USB (EV08L38A) | USB 2.0 연결 |
| PHY | LAN8670 (10BASE-T1S MAC-PHY) | PLCA 지원 |
| USB-Ethernet Bridge | LAN9500A | USB-CDC-ECM |
| OS | Raspberry Pi OS (커널 6.6+) | LAN867x 드라이버 내장 |

### 3.2 슬레이브 노드 (개발 대상 외, 참고)

| 구성요소 | 사양 | 비고 |
|----------|------|------|
| MCU | STM32, ESP32, Arduino 등 | Zenoh-pico 지원 플랫폼 |
| PHY | LAN8670/8671/8672 | SPI 인터페이스 |
| 프로토콜 스택 | Zenoh-pico (C) | Client 모드 |

### 3.3 네트워크 물리 구성

| 파라미터 | 사양 |
|----------|------|
| 토폴로지 | Multidrop Bus |
| 케이블 | Single UTP (비차폐 트위스티드 페어) |
| 최대 노드 수 | 8 (PLCA) |
| 최대 세그먼트 길이 | 25m |
| 데이터 레이트 | 10 Mbps |

---

## 4. 소프트웨어 요구사항 (Software Requirements)

### 4.1 시스템 소프트웨어

| 구성요소 | 요구사항 | 비고 |
|----------|----------|------|
| Linux 커널 | 6.6 이상 | LAN867x PHY 드라이버 포함 |
| ethtool | 6.7 이상 | PLCA 설정 지원 |
| Rust toolchain | stable (latest) | Zenoh 빌드 |
| Python | 3.9+ | 시뮬레이션 스크립트, 모니터링 |

### 4.2 Zenoh 구성요소

| 구성요소 | 역할 | 설치 방법 |
|----------|------|-----------|
| zenohd | Zenoh Router (마스터) | cargo install / 바이너리 |
| zenoh Python API | 마스터 애플리케이션 개발 | pip install eclipse-zenoh |
| zenoh-pico | 슬레이브 클라이언트 (C) | 소스 빌드 (CMake) |

### 4.3 마스터 시뮬레이션 모듈 기능 요구사항

#### FR-001: PLCA Coordinator 설정
- 시스템 시작 시 EVB-LAN8670-USB를 PLCA Coordinator(Node ID 0)로 자동 설정
- `ethtool --set-plca-cfg <iface> enable on node-id 0 node-cnt <N> to-timer <T>`
- 네트워크 인터페이스 상태 모니터링 및 자동 재설정

#### FR-002: Zenoh Router 운영
- zenohd를 10BASE-T1S 네트워크 인터페이스에 바인딩하여 실행
- 슬레이브 노드(Zenoh-pico client)의 자동 디스커버리 및 세션 관리
- 멀티캐스트 스카우팅(224.0.0.224:7446) 또는 유니캐스트 연결

#### FR-003: 센서 데이터 수집 (Subscribe)
- 슬레이브 노드가 퍼블리시하는 센서 데이터를 구독(Subscribe)
- Key Expression 패턴: `vehicle/<zone>/<node_id>/sensor/<type>`
- 지원 센서 타입: temperature, pressure, proximity, light, battery

#### FR-004: 액추에이터 제어 명령 (Publish)
- 슬레이브 노드의 액추에이터에 제어 명령 퍼블리시
- Key Expression 패턴: `vehicle/<zone>/<node_id>/actuator/<type>`
- 지원 액추에이터 타입: led, motor, relay, buzzer, lock

#### FR-005: 노드 상태 조회 (Query/Reply)
- Zenoh Queryable을 통한 슬레이브 노드 상태 조회
- Key Expression 패턴: `vehicle/<zone>/<node_id>/status`
- 조회 항목: alive, uptime, firmware_version, error_count, plca_node_id

#### FR-006: 노드 관리 및 디스커버리
- 네트워크에 연결된 슬레이브 노드 목록 관리
- **Zenoh Liveliness Token 기반** 노드 온라인/오프라인 감지
  - 슬레이브: `z_liveliness_declare_token()` — 세션 종료 또는 크래시 시 자동 소멸
  - 마스터: `z_liveliness_declare_subscriber()` — PUT(온라인)/DELETE(오프라인) 이벤트 수신
  - 초기 상태 조회: `z_liveliness_get()` — 현재 활성 노드 스냅샷 질의
- 별도 heartbeat 구현 불필요 (Zenoh 트랜스포트 세션 keepalive 메커니즘 활용)
- Liveliness Key Expression: `vehicle/<zone>/<node_id>/alive`
- 노드별 PLCA ID 매핑 테이블 관리

#### FR-007: 진단 및 모니터링
- 실시간 네트워크 트래픽 통계 (메시지 수, 바이트 수, 지연 시간)
- PLCA 상태 모니터링 (beacon 상태, 충돌 횟수)
- 슬레이브 노드별 통신 품질 지표
- 로그 기록 및 CLI/웹 대시보드 출력

#### FR-008: 시나리오 기반 시뮬레이션
- 사전 정의된 자동차 시나리오 재생 기능
- 시나리오 예시:
  - 도어 존(Zone) 제어: 도어락, 윈도우, 미러 제어
  - 라이팅 존 제어: 헤드라이트, 인테리어 조명
  - 센서 폴링: 온도, 근접, 조도 센서 주기적 수집
- YAML/JSON 기반 시나리오 정의 파일
- 시나리오 조건 표현식은 **단순 비교 연산자**(`<`, `>`, `<=`, `>=`, `==`, `!=`)만 지원하며, 복합 룰 엔진은 범위 외

### 4.4 에러 핸들링 정책

| 이벤트 | 감지 방법 | 동작 |
|--------|-----------|------|
| 네트워크 단절 (eth1 link down) | netlink 이벤트 모니터링 | 로그 기록 → 30초 간격 재연결 시도 (최대 10회) → 알림 |
| 슬레이브 노드 무응답 | Liveliness token DELETE 이벤트 | 노드 오프라인 표시 → 로그 기록 → 재연결 시 자동 복구 |
| PLCA beacon 소실 | `ethtool --get-plca-status` 주기적 폴링 | PLCA 재설정 시도 → 실패 시 인터페이스 재초기화 |
| Zenoh 세션 단절 | zenoh 세션 콜백 | 자동 재연결 (`Z_FEATURE_AUTO_RECONNECT` 활용) |
| zenohd 프로세스 종료 | systemd watchdog | 자동 재시작 (RestartSec=5) |

### 4.5 비기능 요구사항

| ID | 요구사항 | 목표치 | 근거 |
|----|----------|--------|------|
| NFR-001 | Pub/Sub 메시지 지연 | < 15ms (단일 홉, 8노드 worst-case) | PLCA 사이클 ~9.7ms + Zenoh 처리 ~1ms + TCP/IP 스택 ~2ms. 노드 수 감소 시 비례 단축 (4노드: <8ms) |
| NFR-002 | 최대 동시 슬레이브 수 | 7 (PLCA 제한: 8노드 - 1마스터) | IEEE 802.3cg PLCA 권장 최대 8노드 |
| NFR-003 | 센서 데이터 수집 주기 | 최소 PLCA 사이클 시간 ~ 1000ms (설정 가능) | 노드 수별 최소값: 2노드 ~2.5ms, 4노드 ~5ms, 8노드 ~10ms (모든 노드 최대 프레임 전송 가정) |
| NFR-004 | 시스템 가동 안정성 | 24시간 연속 무장애 운영 | |
| NFR-005 | 메모리 사용량 (마스터) | < 256MB | |
| NFR-006 | 부팅 후 초기화 시간 | < 30초 | Zenoh 디스커버리: ~11.6ms |
| NFR-007 | Zenoh 와이어 오버헤드 | ≤ 5 bytes/message | Zenoh 프로토콜 특성 |

---

## 5. Zenoh Key Expression 설계 (Data Model)

### 5.1 Key Expression 체계

```
vehicle/
├── {zone_id}/                          # 존 식별자 (front, rear, left, right)
│   ├── {node_id}/                      # 슬레이브 노드 ID (1~7)
│   │   ├── sensor/
│   │   │   ├── temperature             # 온도 센서 값
│   │   │   ├── pressure                # 압력 센서 값
│   │   │   ├── proximity               # 근접 센서 값
│   │   │   ├── light                   # 조도 센서 값
│   │   │   └── battery                 # 배터리 전압
│   │   ├── actuator/
│   │   │   ├── led                     # LED 제어
│   │   │   ├── motor                   # 모터 제어
│   │   │   ├── relay                   # 릴레이 제어
│   │   │   ├── buzzer                  # 부저 제어
│   │   │   └── lock                    # 잠금장치 제어
│   │   ├── status                      # 노드 상태 (Queryable)
│   │   ├── alive                       # Liveliness Token (자동 온/오프라인 감지)
│   │   └── config                      # 노드 설정 (Put)
│   └── summary                         # 존 요약 정보
└── master/
    ├── heartbeat                       # 마스터 하트비트
    ├── command                         # 브로드캐스트 명령
    └── diagnostics                     # 진단 데이터
```

### 5.2 데이터 페이로드 형식

페이로드 형식은 **JSON** 또는 **CBOR**(경량 바이너리)을 사용한다.

**직렬화 정책:**
| 구간 | 기본 형식 | 근거 |
|------|-----------|------|
| 슬레이브(MCU) → 마스터 | CBOR | MCU 리소스 절약, 10Mbps 대역폭 최적화 |
| 마스터 → 슬레이브 | CBOR | 동일 |
| 디버깅/CLI 출력 | JSON | 가독성 |
| 시나리오 파일 | YAML/JSON | 사람이 편집 가능 |

마스터는 Zenoh Content-Type 헤더(`application/json` 또는 `application/cbor`)를 확인하여 자동 전환한다.

> **설계 원칙**: `node_id`, `zone`, `type` 등 Key Expression에 이미 포함된 정보는 페이로드에서 **제외**하여 10Mbps 공유 버스의 대역폭을 절약한다.

**센서 데이터 예시 (Slave → Master):**
Key: `vehicle/front_left/1/sensor/temperature`
```json
{
  "value": 25.3,
  "unit": "celsius",
  "ts": 1713000000000
}
```

**액추에이터 명령 예시 (Master → Slave):**
Key: `vehicle/rear_right/2/actuator/led`
```json
{
  "action": "set",
  "params": {
    "state": "on",
    "brightness": 80,
    "color": "white"
  },
  "ts": 1713000000100
}
```

**노드 상태 조회 응답 예시 (Query Reply):**
Key: `vehicle/front_left/1/status`
```json
{
  "alive": true,
  "uptime_sec": 3600,
  "firmware_version": "1.0.0",
  "error_count": 0,
  "plca_node_id": 1,
  "rssi": -30,
  "tx_count": 15000,
  "rx_count": 14980
}
```

---

## 6. 시스템 초기화 흐름 (Startup Sequence)

```
[시스템 부팅]
     │
     ▼
[1] 네트워크 인터페이스 감지
     │  EVB-LAN8670-USB → eth1 (USB-CDC-ECM)
     ▼
[2] PLCA Coordinator 설정
     │  ethtool --set-plca-cfg eth1 enable on node-id 0 node-cnt 8 to-timer 50
     ▼
[3] IP 주소 할당
     │  ip addr add 192.168.1.1/24 dev eth1
     │  ip link set eth1 up
     ▼
[4] PLCA 상태 확인
     │  ethtool --get-plca-status eth1
     │  → plca-status on (beacon 생성 확인)
     ▼
[5] Zenoh Router (zenohd) 시작
     │  zenohd --config master_config.json5
     │  → listen: tcp/192.168.1.1:7447
     │  → scouting: multicast/224.0.0.224:7446
     ▼
[6] Master Application 시작
     │  Python/Rust 마스터 시뮬레이션 모듈
     │  → Subscriber 등록 (vehicle/**/sensor/*)
     │  → Publisher 준비 (vehicle/**/actuator/*)
     │  → Queryable 등록 (vehicle/master/*)
     ▼
[7] 슬레이브 연결 대기
     │  Zenoh-pico 클라이언트 디스커버리
     ▼
[8] 시뮬레이션 루프 시작
     │  시나리오 실행 또는 인터랙티브 모드
     ▼
[운영 중...]
```

---

## 7. 소프트웨어 모듈 구조 (Module Design)

```
genoh_10base_t1s/
├── docs/
│   └── PRD.md                          # 본 문서
├── config/
│   ├── master_config.json5             # zenohd 라우터 설정
│   ├── plca_config.yaml                # PLCA 파라미터 설정
│   └── scenarios/                      # 시뮬레이션 시나리오 파일
│       ├── door_zone.yaml
│       ├── lighting_zone.yaml
│       └── sensor_polling.yaml
├── src/
│   ├── master/                         # 마스터 시뮬레이션 모듈 (Python)
│   │   ├── __init__.py
│   │   ├── main.py                     # 엔트리 포인트
│   │   ├── network_setup.py            # PLCA 설정, 네트워크 초기화
│   │   ├── zenoh_master.py             # Zenoh 세션 및 Pub/Sub/Query 관리
│   │   ├── node_manager.py             # 슬레이브 노드 등록/관리
│   │   ├── scenario_runner.py          # 시나리오 기반 시뮬레이션 실행
│   │   ├── diagnostics.py              # 진단 및 통계 수집
│   │   └── cli.py                      # CLI 인터페이스
│   └── common/
│       ├── __init__.py
│       ├── models.py                   # 데이터 모델 (센서, 액추에이터, 노드)
│       ├── key_expressions.py          # Zenoh Key Expression 정의
│       └── payloads.py                 # 페이로드 직렬화/역직렬화
├── scripts/
│   ├── setup_plca.sh                   # PLCA 초기화 스크립트
│   ├── start_master.sh                 # 마스터 전체 시작 스크립트
│   └── install_deps.sh                 # 의존성 설치 스크립트
├── systemd/
│   ├── zenoh-plca-setup.service        # 부팅 시 PLCA Coordinator 자동 설정
│   ├── zenoh-router.service            # zenohd 라우터 데몬 서비스
│   └── zenoh-master-app.service        # Python 마스터 앱 서비스 (zenoh-router 의존)
├── tests/
│   ├── test_network_setup.py
│   ├── test_zenoh_master.py
│   ├── test_node_manager.py
│   └── test_scenario_runner.py
├── slave_examples/                     # 슬레이브 참고 예제 (Zenoh-pico, C)
│   ├── CMakeLists.txt
│   ├── sensor_node.c                   # 센서 노드 예제
│   └── actuator_node.c                 # 액추에이터 노드 예제
├── pyproject.toml
└── README.md
```

---

## 8. 인터페이스 설계 (Interface Design)

### 8.1 CLI 인터페이스

```bash
# 시스템 시작
$ zenoh-t1s-master start [--config config.yaml] [--scenario door_zone]

# 노드 관리
$ zenoh-t1s-master nodes list                    # 연결된 노드 목록
$ zenoh-t1s-master nodes status <node_id>        # 특정 노드 상태
$ zenoh-t1s-master nodes ping <node_id>          # 노드 핑

# 데이터 조회
$ zenoh-t1s-master sub vehicle/front/1/sensor/*  # 센서 데이터 구독
$ zenoh-t1s-master pub vehicle/rear/2/actuator/led '{"state":"on"}'

# 진단
$ zenoh-t1s-master diag plca                     # PLCA 상태
$ zenoh-t1s-master diag traffic                  # 트래픽 통계
$ zenoh-t1s-master diag network                  # 네트워크 상태

# 시나리오
$ zenoh-t1s-master scenario run door_zone        # 시나리오 실행
$ zenoh-t1s-master scenario list                 # 사용 가능한 시나리오
```

### 8.2 zenohd 라우터 설정 (master_config.json5)

```json5
{
  mode: "router",
  listen: {
    endpoints: [
      "tcp/192.168.1.1:7447",
      "udp/192.168.1.1:7447"
    ]
  },
  scouting: {
    multicast: {
      enabled: true,
      address: "224.0.0.224:7446",
      interface: "eth1"    // 10BASE-T1S 인터페이스
    }
  },
  transport: {
    unicast: {
      max_sessions: 7     // 최대 슬레이브 수
    }
  }
}
```

---

## 9. 개발 환경 설정 (Development Setup)

### 9.1 사전 요구사항

```bash
# 1. 커널 버전 확인 (6.6 이상)
uname -r

# 2. ethtool 버전 확인 (6.7 이상)
ethtool --version

# 3. EVB-LAN8670-USB 연결 확인
lsusb | grep -i microchip
ip link show  # eth1 등 새 인터페이스 확인
```

### 9.2 PLCA 설정

```bash
# PLCA Coordinator(Node 0)로 설정, 최대 노드 수 8
sudo ethtool --set-plca-cfg eth1 enable on node-id 0 node-cnt 8 to-timer 50

# 설정 확인
ethtool --get-plca-cfg eth1
# 예상 출력:
#   PLCA support: supported
#   PLCA status: enabled/on
#   PLCA node id: 0
#   PLCA node count: 8

# PLCA 상태 확인 (beacon 수신/생성 여부)
ethtool --get-plca-status eth1
```

### 9.3 Zenoh 설치

```bash
# Zenoh Router 설치 (Rust)
cargo install zenoh-router

# 또는 바이너리 다운로드
# https://github.com/eclipse-zenoh/zenoh/releases

# Python API 설치
pip install eclipse-zenoh

# Zenoh-pico (슬레이브용, C 라이브러리)
git clone https://github.com/eclipse-zenoh/zenoh-pico.git
cd zenoh-pico && mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make
```

---

## 10. 시뮬레이션 시나리오 (Use Cases)

### 10.1 시나리오 A: 도어 존(Door Zone) 제어

```yaml
name: door_zone_control
description: "프론트 도어 존의 도어락, 윈도우, 사이드미러 제어"
zone: front_left
nodes:
  - node_id: 1
    role: door_lock_sensor
    publish:
      - key: vehicle/front_left/1/sensor/proximity
        interval_ms: 200
  - node_id: 2
    role: door_lock_actuator
    subscribe:
      - key: vehicle/front_left/2/actuator/lock

sequence:
  - step: 1
    action: wait_sensor
    condition: "vehicle/front_left/1/sensor/proximity < 30"
  - step: 2
    action: publish
    key: vehicle/front_left/2/actuator/lock
    payload: {"action": "unlock"}
  - step: 3
    action: log
    message: "Door unlocked by proximity detection"
```

### 10.2 시나리오 B: 센서 폴링 및 집계

```yaml
name: sensor_polling
description: "모든 존의 온도 센서 주기적 수집 및 집계"
interval_ms: 1000

subscribe:
  - key: "vehicle/*/*/sensor/temperature"

aggregation:
  method: average
  window_sec: 10
  publish_key: "vehicle/master/diagnostics"
```

### 10.3 시나리오 C: 라이팅 제어

```yaml
name: lighting_control
description: "헤드라이트 및 인테리어 조명 제어 시퀀스"
zone: front

sequence:
  - step: 1
    action: publish
    key: vehicle/front/3/actuator/led
    payload: {"state": "on", "brightness": 100, "mode": "headlight"}
  - step: 2
    delay_ms: 5000
    action: publish
    key: vehicle/front/3/actuator/led
    payload: {"state": "on", "brightness": 30, "mode": "drl"}
```

---

## 11. 테스트 계획 (Test Plan)

### 11.1 단위 테스트

| ID | 테스트 항목 | 검증 내용 |
|----|------------|-----------|
| UT-001 | PLCA 설정 모듈 | ethtool 명령 생성 및 파싱 정확성 |
| UT-002 | Key Expression 빌더 | 올바른 키 경로 생성 |
| UT-003 | 페이로드 직렬화 | JSON/CBOR 인코딩/디코딩 |
| UT-004 | 노드 매니저 | 노드 등록/제거/상태 관리 |
| UT-005 | 시나리오 파서 | YAML 시나리오 파일 로딩 |

### 11.2 통합 테스트

| ID | 테스트 항목 | 검증 내용 |
|----|------------|-----------|
| IT-001 | 마스터-슬레이브 연결 | Zenoh 세션 수립 및 디스커버리 |
| IT-002 | Pub/Sub 통신 | 센서 데이터 수신 정상 확인 |
| IT-003 | Query/Reply | 노드 상태 조회 응답 확인 |
| IT-004 | 다중 노드 동시 통신 | 3개 이상 슬레이브 동시 운용 |
| IT-005 | PLCA 결정론성 | 메시지 지연 시간 측정 및 일관성 |

### 11.3 시스템 테스트

| ID | 테스트 항목 | 검증 내용 |
|----|------------|-----------|
| ST-001 | 24시간 연속 운영 | 메모리 누수, 연결 끊김 없음 |
| ST-002 | 노드 핫플러그 | 슬레이브 동적 추가/제거 |
| ST-003 | 시나리오 전체 실행 | 도어존, 라이팅, 센서폴링 시나리오 |
| ST-004 | 에러 복구 | 네트워크 단절 후 자동 재연결 |

---

## 12. 마일스톤 (Milestones)

| 단계 | 목표 | 산출물 |
|------|------|--------|
| **M1: 환경 구축** | HW 연결, 커널 드라이버, PLCA 설정 | 네트워크 인터페이스 동작 확인 |
| **M2: Zenoh 기본 통신** | zenohd 라우터 + zenoh-pico 클라이언트 Pub/Sub 확인 | 기본 메시지 송수신 |
| **M3: 마스터 코어 모듈** | network_setup, zenoh_master, node_manager 구현 | 마스터 코어 동작 |
| **M4: 시나리오 엔진** | scenario_runner, YAML 파서, CLI 구현 | 시나리오 실행 가능 |
| **M5: 진단 및 모니터링** | diagnostics, 통계, 로깅 구현 | 모니터링 대시보드 |
| **M6: 통합 테스트 및 안정화** | 전체 시나리오 테스트, 버그 수정 | v1.0 릴리즈 |

---

## 13. 위험 요소 및 완화 방안 (Risks & Mitigations)

| 위험 | 영향도 | 발생 가능성 | 완화 방안 |
|------|--------|------------|-----------|
| LAN867x 커널 드라이버 호환성 문제 | 높음 | 중간 | Microchip 공식 드라이버 패치 적용, 커널 6.6+ 사용 |
| PLCA 설정이 재부팅 시 초기화됨 | 중간 | 높음 | systemd 서비스로 자동 설정 스크립트 등록 |
| Zenoh-pico의 10BASE-T1S 환경 미검증 | 중간 | 중간 | 단계적 검증 (로컬 → USB → 10BASE-T1S) |
| 10BASE-T1S 25m 케이블 길이 제한 | 낮음 | 낮음 | 랩 환경에서는 1~2m 케이블 사용 |
| 멀티캐스트 스카우팅 10BASE-T1S 호환성 | 중간 | 중간 | 유니캐스트 연결 모드 대안 준비 |

### 13.1 보안 고려사항 (향후 적용)

시뮬레이션 단계에서는 보안 기능을 비활성화하되, 이후 적용 가능한 경로를 명시한다.

| 기능 | Zenoh (zenohd) | zenoh-pico | 비고 |
|------|----------------|------------|------|
| TLS/mTLS | 지원 | 지원 (Mbed TLS, Unix) | `Z_FEATURE_LINK_TLS=ON` 빌드 필요 |
| User-Password 인증 | 지원 | 지원 | SHA256 해시 권장 |
| ACL (접근 제어) | 지원 (라우터 레벨) | N/A (라우터에서 강제) | Key Expression 기반 pub/sub/query 제어 |

> **참고**: 10BASE-T1S는 물리적 접근이 필요한 유선 버스이며, 본 프로젝트는 단일 홉(마스터↔슬레이브 직접 연결) 구조이므로 hop-by-hop TLS의 중간 노드 평문 노출 문제가 해당되지 않는다. 시뮬레이션 이후 보안 적용 시 TLS + user-password 조합을 권장한다.

---

## 14. Zenoh 기술 상세 (Zenoh Technical Details)

### 14.1 Zenoh 프로토콜 핵심 특성

| 항목 | 상세 |
|------|------|
| 와이어 오버헤드 | 4~6 bytes/message (VLE 인코딩된 리소스 ID) |
| 지연 시간 | 13μs (unicast), 15μs (multicast, peer mode) |
| 처리량 | 최대 20M msg/s (8B payload, peer-to-peer) |
| 신뢰성 | best-effort / reliable (hop-by-hop 또는 end-to-end) |
| 타임스탬프 | Hybrid Logical Clock (64-bit time + router UUID) |
| 혼잡 제어 | per-sample drop 또는 block |
| 자동 배칭 | 다수 메시지를 프레임에 패킹 |
| 프래그멘테이션 | 대용량 메시지 자동 분할/조립 |

### 14.2 Zenoh-pico 리소스 프로파일

| 플랫폼 | Flash 사용량 | RAM 사용량 | 처리량 |
|--------|-------------|------------|--------|
| 최소 (Publisher-only) | ~15 KB | 최소 | - |
| 풀 기능 | ~50 KB | ~101 KB (peer) | - |
| ESP32 | 0.9% | - | >5,200 msg/s (8B) |
| STM32 nucleo-f767zi | 2.8% | - | 9.2 Mbps |

### 14.3 Zenoh-pico 컴파일 옵션 (10BASE-T1S 관련)

| 플래그 | 기본값 | 용도 |
|--------|--------|------|
| `Z_FEATURE_LINK_TCP` | ON | TCP 트랜스포트 |
| `Z_FEATURE_LINK_UDP_UNICAST` | ON | UDP 유니캐스트 |
| `Z_FEATURE_LINK_UDP_MULTICAST` | ON | UDP 멀티캐스트 |
| `Z_FEATURE_LINK_SERIAL` | OFF | Serial/UART 트랜스포트 |
| `Z_FEATURE_LIVELINESS` | ON | **노드 온/오프라인 감지 (Liveliness Token)** |
| `Z_FEATURE_RAWETH_TRANSPORT` | OFF | Raw Ethernet (Layer 2) - zenoh-pico 간 peer 전용, zenohd 미지원 |

### 14.4 Zenoh 자동차 벤치마크 결과 (2025 학술 논문)

**"Stepping Toward Zenoh Protocol in Automotive Scenarios" (IEEE Access, 2025)**
- 4-Zone 자동차 아키텍처 PoC 구현
- Zenoh: DDS 대비 **2배** 처리량, MQTT 대비 **50배** 처리량
- 메시지 지연: **13μs**, 와이어 오버헤드: **5 bytes**
- 결론: "차세대 차량 내 통신 시스템의 실행 가능한 후보"

**"Automotive Middleware Performance Comparison" (arXiv, 2025)**
- 디스커버리 시간: Zenoh **11.6ms** vs FastDDS 51.6ms vs vSomeIP 98.4ms
- 메시지 전달 신뢰성: Zenoh **100%** (FastDDS는 일부 토폴로지에서 실패)
- 카메라 데이터(4MB) 지연: Zenoh 92ms vs FastDDS 103ms

---

## 15. PLCA 기술 상세 (PLCA Technical Details)

### 15.1 PLCA 사이클 구조

```
┌──BEACON──┬──TO[0]──┬──TO[1]──┬──TO[2]──┬─...─┬──TO[N]──┬──(idle)──┐
│  20 bits │ Master  │ Slave1  │ Slave2  │     │ SlaveN  │          │
│  (2 μs)  │  TX/Idle│  TX/Idle│  TX/Idle│     │  TX/Idle│          │
└──────────┴─────────┴─────────┴─────────┴─────┴─────────┴──────────┘
                              ↓
                    다음 BEACON으로 반복
```

### 15.2 Worst-Case 지연 계산

```
8노드, 기본 TO_TIMER(32 bit-times), 모든 노드 최대 프레임 전송 시:

  최대 사이클 = BEACON + (8 × 1518B 프레임)
              = 20 bits + (8 × 12,144 bits)
              = 97,172 bit-times
              = ~9.7 ms @ 10 MHz

8노드, 모든 노드 Idle 시:
  최소 사이클 = BEACON + (8 × TO_TIMER)
              = 20 + (8 × 32) = 276 bit-times
              = ~27.6 μs @ 10 MHz
```

### 15.3 PLCA 레지스터 맵 (MMD 31, Clause 45)

| 레지스터 | 주소 | 주요 필드 | 설명 |
|----------|------|----------|------|
| PLCA_CTRL0 | 0xCA01 | EN (bit 15) | PLCA 활성화 |
| PLCA_CTRL1 | 0xCA02 | NCNT [15:8], ID [7:0] | 노드 수, 로컬 노드 ID |
| PLCA_STS | 0xCA03 | PST (bit 15) | PLCA 상태 (BEACON 감지) |
| PLCA_TOTMR | 0xCA04 | TOTMR [7:0] | TO 타이머 (기본 0x20=32 bit-times) |
| PLCA_BURST | 0xCA05 | MAXBC [15:8], BTMR [7:0] | 버스트 카운트/타이머 |

### 15.4 Coordinator 장애 시 동작

- PLCA에는 **자동 Coordinator 페일오버가 없음** (IEEE 802.3cg 기본 사양)
- Coordinator 장애 시 Follower 노드는 BEACON 타임아웃 후 PLCA_STS.PST 클리어
- CSMA/CD 모드로 폴백하거나 통신 중단
- 시스템 레벨에서 이중화(dual-coordinator) 대응 필요

---

## 16. 참고 자료 (References)

### Zenoh
- [Eclipse Zenoh GitHub](https://github.com/eclipse-zenoh/zenoh)
- [Zenoh-pico GitHub](https://github.com/eclipse-zenoh/zenoh-pico)
- [Zenoh Documentation](https://zenoh.io/docs/overview/what-is-zenoh/)
- [Zenoh Deployment Guide](https://zenoh.io/docs/getting-started/deployment/)
- [Zenoh Automotive Use Cases (ZettaScale)](https://www.zettascale.tech/news/advancing-automotive-technologies-for-the-future-with-eclipse-zenoh/)
- [Stepping Toward Zenoh in Automotive Scenarios (IEEE Access, 2025)](https://ieeexplore.ieee.org/document/11175385/)
- [Automotive Middleware Comparison: FastDDS, Zenoh, vSomeIP (arXiv, 2025)](https://arxiv.org/html/2505.02734v2)
- [Zenoh-pico Performance Blog](https://zenoh.io/blog/2025-04-09-zenoh-pico-performance/)

### 10BASE-T1S / PLCA
- [IEEE 802.3cg-2019 Standard](https://standards.ieee.org/standard/802_3cg-2019.html)
- [10BASE-T1S Automotive Zonal Architecture (Analog Devices)](https://www.analog.com/en/resources/analog-dialogue/articles/how-10base-t1s-ethernet-simplifies-zonal-architectures.html)
- [PLCA in 10BASE-T1S (Teledyne LeCroy)](https://blog.teledynelecroy.com/2022/08/physical-layer-collision-avoidance-in.html)
- [PLCA Cycle Timing Measurements (Teledyne LeCroy)](https://blog.teledynelecroy.com/2022/10/oscilloscope-measurements-of-10base-t1s.html)
- [Open Alliance PLCA Management Registers v1.4](https://opensig.org/wp-content/uploads/2025/03/2024-12-10BASE-T1S-PLCA-Management-Registers-v1.4.pdf)

### Microchip Hardware
- [EVB-LAN8670-USB Product Page (EV08L38A)](https://www.microchip.com/en-us/development-tool/ev08l38a)
- [LAN867x Linux Driver Installation (AN-00005992)](https://ww1.microchip.com/downloads/aemDocuments/documents/AIS/ApplicationNotes/ApplicationNotes/LAN867x-Linux-Driver-Install-Application-Note-00005992.pdf)
- [LAN8670/1/2 Configuration (AN-60001699)](https://ww1.microchip.com/downloads/aemDocuments/documents/AIS/ApplicationNotes/ApplicationNotes/LAN8670-1-2-Configuration-Appnote-60001699.pdf)
- [Microchip PLCA Auto-Config Tool](https://github.com/MicrochipTech/linux-auto-ethtool-plca-config)
- [Linux Kernel microchip_t1s.c Driver](https://github.com/torvalds/linux/blob/master/drivers/net/phy/microchip_t1s.c)
- [EVB-LAN8670-USB Enablement for Raspbian](https://microchip.my.site.com/s/article/EVB-LAN8670-USB-Enablement-for-Debian-Ubuntu-Raspbian)
