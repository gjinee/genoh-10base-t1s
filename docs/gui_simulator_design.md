# GUI 시뮬레이터 설계 문서

## 문서 정보

| 항목 | 내용 |
|------|------|
| 프로젝트명 | 10BASE-T1S Zenoh Vehicle GUI Simulator |
| 버전 | v1.0.0 |
| 작성일 | 2026-04-13 |
| 상태 | Implementation |

---

## 1. 개요

### 1.1 목적

10BASE-T1S 멀티드롭 버스 위에서 Zenoh 프로토콜을 사용하는 차량 네트워크의
**실시간 GUI 시뮬레이터**를 개발한다. 마스터(Zone Controller)와 슬레이브(ECU 노드)
각각에 독립 GUI를 제공하여, 실제 하드웨어 또는 시뮬레이션 모드에서 양방향
통신을 시각적으로 확인하고 제어한다.

### 1.2 핵심 요구사항

| ID | 요구사항 | 설명 |
|----|----------|------|
| G-01 | 마스터 GUI | PLCA Coordinator + Zenoh Router 관점의 대시보드 |
| G-02 | 슬레이브 GUI | 개별 노드 관점의 센서/액추에이터 제어 패널 |
| G-03 | 실시간 통신 | WebSocket 기반 실시간 메시지 스트리밍 |
| G-04 | 듀얼 모드 | 시뮬레이션 모드 + 실제 하드웨어(10BASE-T1S) 모드 |
| G-05 | 멀티에이전트 | Claude Agent SDK 에이전트가 GUI를 통해 시뮬레이션 실행 |
| G-06 | 시나리오 실행 | YAML 시나리오 로드 및 실시간 실행/시각화 |
| G-07 | Safety 시각화 | FSM 상태, E2E 보호, DTC, 워치독 실시간 표시 |
| G-08 | Security 시각화 | IDS 경보, SecOC 상태, ACL 위반 실시간 표시 |

---

## 2. 시스템 아키텍처

### 2.1 전체 구성

```
┌─────────────────────────────────────────────────────────────────┐
│                    Raspberry Pi 5                                │
│                                                                  │
│  ┌──────────────────┐     ┌──────────────────┐                  │
│  │  Master GUI      │     │  Slave GUI       │                  │
│  │  (FastAPI:8010)  │     │  (FastAPI:8020)  │                  │
│  │  ┌────────────┐  │     │  ┌────────────┐  │                  │
│  │  │ Browser UI │  │     │  │ Browser UI │  │                  │
│  │  │ HTML/JS/CSS│  │     │  │ HTML/JS/CSS│  │                  │
│  │  └─────┬──────┘  │     │  └─────┬──────┘  │                  │
│  │        │ WS      │     │        │ WS      │                  │
│  │  ┌─────┴──────┐  │     │  ┌─────┴──────┐  │                  │
│  │  │ FastAPI    │  │     │  │ FastAPI    │  │                  │
│  │  │ Backend    │  │     │  │ Backend    │  │                  │
│  │  └─────┬──────┘  │     │  └─────┬──────┘  │                  │
│  └────────┼─────────┘     └────────┼─────────┘                  │
│           │                        │                             │
│  ┌────────┴────────────────────────┴─────────┐                  │
│  │         Simulation Engine (공통)           │                  │
│  │  ┌──────────┐ ┌──────────┐ ┌───────────┐  │                  │
│  │  │ Zenoh    │ │ Safety   │ │ Security  │  │                  │
│  │  │ Session  │ │ Manager  │ │ Manager   │  │                  │
│  │  └────┬─────┘ └──────────┘ └───────────┘  │                  │
│  └───────┼───────────────────────────────────┘                  │
│          │                                                       │
│  ┌───────┴──────────────────┐                                   │
│  │   zenohd (Router)        │                                   │
│  │   tcp/127.0.0.1:7447     │                                   │
│  │   tcp/192.168.1.1:7447   │                                   │
│  └───────┬──────────────────┘                                   │
│          │ bind: eth1                                            │
└──────────┼──────────────────────────────────────────────────────┘
           │
    ═══════╧═══════════════════════════════════
           10BASE-T1S Multidrop Bus (PLCA)
    ═══════╤═══════════════════════════════════
           │
    ┌──────┴──────┐   ┌──────────────┐
    │ Slave Node  │   │ Slave Node   │
    │ (zenoh-pico)│   │ (zenoh-pico) │
    │ or GUI Slave│   │ or MCU       │
    └─────────────┘   └──────────────┘
```

### 2.2 디렉토리 구조

```
gui/
├── __init__.py
├── common/
│   ├── __init__.py
│   ├── ws_manager.py        # WebSocket 연결 관리
│   ├── sim_engine.py         # 시뮬레이션 엔진 (Zenoh ↔ GUI 브릿지)
│   ├── protocol.py           # WebSocket 메시지 프로토콜 정의
│   └── bus_monitor.py        # 10BASE-T1S 버스 모니터
├── master/
│   ├── __init__.py
│   ├── app.py                # Master FastAPI 앱 (포트 8010)
│   ├── templates/
│   │   └── master.html       # Master GUI HTML
│   └── static/
│       ├── css/
│       │   └── master.css
│       └── js/
│           └── master.js
├── slave/
│   ├── __init__.py
│   ├── app.py                # Slave FastAPI 앱 (포트 8020)
│   ├── templates/
│   │   └── slave.html        # Slave GUI HTML
│   └── static/
│       ├── css/
│       │   └── slave.css
│       └── js/
│           └── slave.js
└── run.py                    # 통합 실행 스크립트
```

---

## 3. 마스터 GUI 설계

### 3.1 화면 구성 (4-Panel Layout)

```
┌─────────────────────────────────────────────────────────────┐
│  10BASE-T1S Master Controller    [SIM|HW] [Scenario ▾] [▶]│
├───────────────────────────┬─────────────────────────────────┤
│                           │                                 │
│   Vehicle Topology        │    Safety Dashboard             │
│   (SVG 차량 다이어그램)     │    ┌─────────────────────┐     │
│                           │    │ FSM: [NORMAL]        │     │
│   ┌─────────┐             │    │ Watchdog: 4.2s       │     │
│   │  Zone:   │             │    │ Flow: SENSOR→ACT..   │     │
│   │front_left│  ←Node 1   │    │ DTC: 0 active        │     │
│   │  Node 2  │             │    └─────────────────────┘     │
│   │  Node 3  │             │                                │
│   └─────────┘             │    Security Panel               │
│                           │    ┌─────────────────────┐     │
│   PLCA Bus Status         │    │ IDS Alerts: 0        │     │
│   ┌───┬───┬───┬───┐      │    │ SecOC: ACTIVE        │     │
│   │ 0 │ 1 │ 2 │ 3 │      │    │ ACL Violations: 0    │     │
│   │ M │ S │ S │ S │      │    │ Log Chain: VALID     │     │
│   └───┴───┴───┴───┘      │    └─────────────────────┘     │
│                           │                                 │
├───────────────────────────┴─────────────────────────────────┤
│                                                             │
│   Message Stream (실시간 메시지 로그)                         │
│   ┌─────────────────────────────────────────────────────┐  │
│   │ 14:30:01.234 [PUB] vehicle/front_left/1/sensor/temp │  │
│   │ 14:30:01.456 [SUB] vehicle/front_left/2/actuator/..│  │
│   │ 14:30:02.001 [QRY] vehicle/front_left/3/status     │  │
│   └─────────────────────────────────────────────────────┘  │
│                                                             │
│   Agent Activity (에이전트 활동 로그)                         │
│   ┌─────────────────────────────────────────────────────┐  │
│   │ [master-controller] Phase 4: Main loop cycle #12    │  │
│   │ [network-monitor] PLCA health check: OK             │  │
│   │ [agent-evaluator] Scoring: E2E Protection = PASS    │  │
│   └─────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 마스터 GUI 기능

| 패널 | 기능 | 데이터 소스 |
|------|------|------------|
| Vehicle Topology | 차량 존 다이어그램, 노드 상태 아이콘 | Zenoh liveliness |
| PLCA Bus | 버스 슬롯 시각화, 비콘 상태, 충돌 카운트 | ethtool / sim |
| Safety Dashboard | FSM 상태, 워치독 타이머, 플로우 체크포인트, DTC | SafetyManager |
| Security Panel | IDS 경보, SecOC 상태, ACL 위반, 로그 체인 | IDS Engine |
| Message Stream | 실시간 pub/sub/query 메시지 로그 | Zenoh session |
| Agent Activity | 멀티에이전트 활동 로그 | Claude Agent SDK |

### 3.3 마스터 제어 기능

- 시나리오 선택 및 실행/정지
- 개별 노드에 액추에이터 명령 전송
- Safety FSM 수동 리셋
- 워치독 수동 킥
- IDS 규칙 활성화/비활성화
- PLCA 재설정

---

## 4. 슬레이브 GUI 설계

### 4.1 화면 구성

```
┌─────────────────────────────────────────────────────────────┐
│  10BASE-T1S Slave Node [ID: ___] [Zone: ___]  [SIM|HW] [▶]│
├───────────────────────────┬─────────────────────────────────┤
│                           │                                 │
│   Sensor Simulator        │    Node Status                  │
│   ┌─────────────────┐    │    ┌─────────────────────┐     │
│   │ Temperature      │    │    │ PLCA ID: 1           │     │
│   │ [====|====] 25.3°C   │    │ Role: SENSOR_NODE    │     │
│   │ Auto ○  Manual ●  │    │    │ Uptime: 00:12:34     │     │
│   │                  │    │    │ TX: 1,234  RX: 1,230 │     │
│   │ Proximity        │    │    │ Errors: 2            │     │
│   │ [====|====] 45cm │    │    └─────────────────────┘     │
│   │ Auto ○  Manual ●  │    │                                │
│   │                  │    │    E2E Protection               │
│   │ Battery          │    │    ┌─────────────────────┐     │
│   │ [====|====] 3.7V │    │    │ Status: VALID        │     │
│   │ Auto ○  Manual ●  │    │    │ Seq Counter: 1234    │     │
│   └─────────────────┘    │    │ CRC Errors: 0        │     │
│                           │    │ Last CRC: 0xA1B2C3D4 │     │
│   Actuator Receiver       │    └─────────────────────┘     │
│   ┌─────────────────┐    │                                 │
│   │ Lock: LOCKED 🔒  │    │    SecOC Status                 │
│   │ Motor: STOP ⏹    │    │    ┌─────────────────────┐     │
│   │ LED: OFF ○       │    │    │ HMAC Key: Active     │     │
│   └─────────────────┘    │    │ Auth OK: 45          │     │
│                           │    │ Auth Fail: 0         │     │
│                           │    └─────────────────────┘     │
├───────────────────────────┴─────────────────────────────────┤
│                                                             │
│   Attack Simulation (보안 테스트)                             │
│   [Spoof] [Replay] [Flood] [Unauthorized]  Status: IDLE    │
│                                                             │
│   Message Log                                               │
│   ┌─────────────────────────────────────────────────────┐  │
│   │ 14:30:01 [TX] sensor/temperature → 25.3°C (E2E OK) │  │
│   │ 14:30:01 [RX] actuator/lock → {action: lock} SecOC  │  │
│   └─────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 슬레이브 GUI 기능

| 패널 | 기능 | 설명 |
|------|------|------|
| Sensor Simulator | 센서값 생성 (자동/수동) | 슬라이더 + 자동 드리프트 |
| Actuator Receiver | 수신된 액추에이터 명령 표시 | 마스터에서 SecOC로 수신 |
| Node Status | PLCA ID, 역할, 통신 통계 | 노드 상태 모니터링 |
| E2E Protection | CRC/시퀀스 카운터 상태 | E2E 보호 상태 |
| SecOC Status | HMAC 인증 상태 | 수신 메시지 인증 결과 |
| Attack Simulation | 공격 시나리오 실행 버튼 | IDS 테스트용 |
| Message Log | TX/RX 메시지 로그 | 실시간 통신 이력 |

### 4.3 슬레이브 제어 기능

- 노드 ID / 존 설정
- 센서값 수동 조정 (슬라이더)
- 센서 자동 생성 간격 설정
- 공격 시뮬레이션 실행 (Spoof/Replay/Flood/Unauthorized)
- E2E 보호 ON/OFF (테스트용)
- 노드 오프라인 시뮬레이션

---

## 5. WebSocket 프로토콜

### 5.1 메시지 형식

```json
{
  "type": "sensor_data|actuator_cmd|safety_state|ids_alert|node_status|...",
  "source": "master|slave|agent",
  "timestamp": 1713000000000,
  "payload": { ... }
}
```

### 5.2 메시지 타입

| Type | Direction | Payload |
|------|-----------|---------|
| `sensor_data` | Slave → Master | `{node_id, sensor_type, value, unit, e2e_status}` |
| `actuator_cmd` | Master → Slave | `{node_id, actuator_type, action, params, secoc_status}` |
| `safety_state` | Master → All | `{state, prev_state, fault_type, dtc_codes}` |
| `ids_alert` | Master → All | `{rule_id, severity, source_node, description}` |
| `node_status` | Both | `{node_id, alive, plca_id, uptime, errors}` |
| `plca_status` | Master → All | `{beacon_active, node_count, collisions}` |
| `agent_log` | Engine → GUI | `{agent_name, phase, message}` |
| `scenario_step` | Engine → GUI | `{step, action, description, status}` |
| `bus_message` | Monitor → GUI | `{direction, key_expr, payload_size, encoding}` |

---

## 6. 멀티에이전트 연동

### 6.1 에이전트 → GUI 연동

Claude Agent SDK의 4개 에이전트가 시뮬레이션 엔진을 통해 GUI에 실시간 이벤트를 전달:

```
Agent SDK Orchestrator
    ├── master-controller  ──→  Master GUI (Safety/Security 이벤트)
    ├── slave-simulator    ──→  Slave GUI (센서/공격 이벤트)
    ├── network-monitor    ──→  Master GUI (진단 리포트)
    └── agent-evaluator    ──→  Master GUI (평가 결과)
```

### 6.2 GUI → 에이전트 연동

GUI에서 시뮬레이션 시작/정지/시나리오 변경 시 에이전트에 전달:

- `start_simulation`: 시나리오 선택 후 8단계 워크플로우 시작
- `stop_simulation`: 현재 시뮬레이션 중단
- `inject_fault`: 수동 장애 주입 (GUI에서 직접)
- `manual_command`: 수동 액추에이터 명령

---

## 7. 동작 모드

### 7.1 시뮬레이션 모드 (SIM)

- 하드웨어 불필요
- 인메모리 Zenoh 시뮬레이션 (기존 sim_harness 도구 사용)
- 에이전트가 가상 노드 생성 및 메시지 교환
- 개발 및 데모용

### 7.2 하드웨어 모드 (HW)

- 실제 EVB-LAN8670-USB + 10BASE-T1S 버스 사용
- zenohd 라우터 + eclipse-zenoh Python 세션
- 실제 zenoh-pico C 바이너리 또는 GUI 슬레이브
- RTT 측정, PLCA 상태 실시간 확인

---

## 8. 기술 스택

| 계층 | 기술 | 이유 |
|------|------|------|
| Backend | FastAPI 0.115+ | 비동기, WebSocket 지원, 경량 |
| Frontend | Vanilla HTML/JS/CSS | 빌드 도구 불필요 (RPi 적합) |
| WebSocket | FastAPI WebSocket | 실시간 양방향 통신 |
| 시각화 | SVG + CSS Animation | 차량 다이어그램, 버스 토폴로지 |
| 차트 | Canvas 2D API | 센서 데이터 시계열 그래프 |
| Zenoh | eclipse-zenoh (Python) | 실제 하드웨어 모드 |
| 에이전트 | Claude Agent SDK | 멀티에이전트 오케스트레이션 |

---

## 9. 실행 방법

```bash
# 마스터 + 슬레이브 동시 실행
python -m gui.run --mode sim

# 마스터만 실행 (하드웨어 모드)
python -m gui.master.app --mode hw --port 8010

# 슬레이브만 실행 (노드 ID 1, 하드웨어 모드)
python -m gui.slave.app --mode hw --port 8020 --node-id 1 --zone front_left

# 브라우저 접속
# Master: http://localhost:8010
# Slave:  http://localhost:8020
```
