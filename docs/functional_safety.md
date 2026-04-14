# 기능안전 설계 명세서 (Functional Safety Specification)

## 문서 정보

| 항목 | 내용 |
|------|------|
| 프로젝트명 | Zenoh-10BASE-T1S Automotive Master Controller Simulator |
| 문서 버전 | v0.1.0 |
| 작성일 | 2026-04-13 |
| 상태 | Draft |
| 관련 표준 | ISO 26262:2018 (Part 4, 5, 6), AUTOSAR E2E Protection |
| 관련 문서 | PRD.md, cybersecurity.md |

---

## 1. 개요 (Overview)

### 1.1 목적

본 문서는 10BASE-T1S Zenoh 기반 자동차 존 네트워크의 **기능안전(Functional Safety)** 요구사항과 설계를 정의한다. ISO 26262 Part 6(소프트웨어 레벨)을 기준으로, 통신 무결성, 안전 상태 관리, 장애 감지 메커니즘을 명세한다.

### 1.2 적용 범위

| 범위 | 포함 | 제외 |
|------|------|------|
| 안전 등급 | ASIL-B ~ ASIL-D (기능별 차등) | QM(Quality Management) 기능 |
| 통신 보호 | E2E Protection (CRC, Sequence, Timeout) | PHY 레벨 오류 정정 (FEC) |
| 상태 관리 | 안전 상태 머신, Degraded 모드 | 하드웨어 이중화 설계 |
| 진단 | SW 자체 진단, DTC, Safety Log | 하드웨어 진단 (BIST) |

### 1.3 ASIL 등급 할당

10BASE-T1S 존 네트워크에서 전달하는 기능별 ASIL 등급:

| 기능 | ASIL 등급 | 근거 |
|------|-----------|------|
| 도어락 제어 (lock/unlock) | ASIL-B | 차량 접근 보안, 주행 중 잠금 해제 위험 |
| 조명 제어 (헤드라이트) | ASIL-B | 야간 주행 시 조명 실패 위험 |
| 센서 데이터 수집 (온도, 압력) | ASIL-A | 간접적 안전 기능 (과열 경고 등) |
| 모터/액추에이터 제어 | ASIL-C | 윈도우, 미러 등 주행 중 오작동 위험 |
| 안전 크리티컬 센서 (근접) | ASIL-D | 충돌 회피 등 생명 직결 기능 |
| 네트워크 진단/모니터링 | QM | 운영 지원, 안전 기능 아님 |

> **참고**: 본 시뮬레이터는 양산 ECU가 아니므로, 위 ASIL 등급은 양산 전환 시 적용할 **목표 등급**이다. 시뮬레이션 단계에서는 ASIL-D 수준의 메커니즘을 **SW 설계 패턴**으로 구현하여 검증한다.

---

## 2. 통신 무결성 — E2E Protection (End-to-End)

### 2.1 개요

현재 `payloads.py`는 JSON/CBOR 직렬화만 수행하며, 메시지 무결성 검증이 없다. E2E Protection은 송신자에서 수신자까지의 **데이터 무결성**을 보장하는 메커니즘이다.

AUTOSAR E2E Library에서 정의하는 오류 모델:

| 오류 유형 | 설명 | 감지 메커니즘 |
|-----------|------|--------------|
| Repetition | 동일 메시지 중복 수신 | Sequence Counter |
| Loss | 메시지 누락 | Sequence Counter + Timeout |
| Delay | 허용 시간 초과 수신 | Timeout Monitoring |
| Insertion | 의도하지 않은 메시지 삽입 | Data ID + CRC |
| Incorrect Sequence | 메시지 순서 뒤바뀜 | Sequence Counter |
| Corruption | 데이터 변조 | CRC |
| Asymmetric (from a replicated channel) | 이중 채널 불일치 | 비교기 (Comparator) |

### 2.2 E2E 프로파일 설계

AUTOSAR E2E Profile 참고하여, Zenoh 메시지에 적용할 E2E 헤더를 정의한다.

#### 2.2.1 E2E 헤더 구조

```
┌──────────────────────────────────────────────────────────┐
│                    E2E Protected Message                  │
├──────────┬──────────┬──────────┬──────────┬──────────────┤
│ Data ID  │ Sequence │ Alive    │ Length   │ CRC-32       │
│ (16 bit) │ Counter  │ Counter  │ (16 bit) │ (32 bit)     │
│          │ (16 bit) │ (8 bit)  │          │              │
├──────────┴──────────┴──────────┴──────────┼──────────────┤
│              Payload (JSON/CBOR)           │              │
└────────────────────────────────────────────┴──────────────┘

총 E2E 오버헤드: 11 bytes
```

| 필드 | 크기 | 설명 |
|------|------|------|
| `data_id` | 16 bit | 메시지 타입 고유 ID (key expression 해시) |
| `sequence_counter` | 16 bit | 송신 순서 번호 (0~65535, wrap-around) |
| `alive_counter` | 8 bit | 주기적 alive 카운터 (0~255) |
| `length` | 16 bit | 페이로드 길이 (bytes) |
| `crc32` | 32 bit | 전체 헤더 + 페이로드의 CRC-32 |

#### 2.2.2 Data ID 매핑

Key Expression에서 Data ID로의 매핑:

```python
# Data ID 할당 규칙
# 상위 4비트: 메시지 카테고리
# 하위 12비트: zone(4) + node_id(4) + type(4)

DATA_ID_MAP = {
    # 센서 데이터 (0x1xxx)
    "vehicle/*/sensor/temperature":  0x1001,
    "vehicle/*/sensor/pressure":     0x1002,
    "vehicle/*/sensor/proximity":    0x1003,
    "vehicle/*/sensor/light":        0x1004,
    "vehicle/*/sensor/battery":      0x1005,

    # 액추에이터 명령 (0x2xxx)
    "vehicle/*/actuator/led":        0x2001,
    "vehicle/*/actuator/motor":      0x2002,
    "vehicle/*/actuator/relay":      0x2003,
    "vehicle/*/actuator/buzzer":     0x2004,
    "vehicle/*/actuator/lock":       0x2005,

    # 상태/제어 (0x3xxx)
    "vehicle/*/status":              0x3000,
    "vehicle/master/heartbeat":      0x3F01,
    "vehicle/master/diagnostics":    0x3F02,
}
```

#### 2.2.3 CRC-32 계산

```python
import struct
import binascii

def compute_e2e_crc(data_id: int, seq: int, alive: int, 
                     length: int, payload: bytes) -> int:
    """CRC-32 over E2E header fields + payload.
    
    CRC 입력: data_id(2) + seq(2) + alive(1) + length(2) + payload(N)
    CRC 다항식: IEEE 802.3 (0x04C11DB7)
    """
    header = struct.pack(">HHBH", data_id, seq, alive, length)
    return binascii.crc32(header + payload) & 0xFFFFFFFF
```

### 2.3 Sequence Counter 관리

| 파라미터 | 값 | 설명 |
|---------|-----|------|
| 범위 | 0 ~ 65535 | 16-bit wrap-around |
| 증가 | +1 per message | 송신 시마다 증가 |
| 허용 갭 (ASIL-B) | ≤ 3 | 3개 이하 누락 허용 |
| 허용 갭 (ASIL-D) | ≤ 1 | 1개 이하 누락 허용 |
| 초기 동기화 | 최초 N개 무시 | 수신 시작 시 동기화 기간 |

수신 측 검증 로직:

```
수신 seq = S_rx, 마지막 유효 seq = S_last

delta = (S_rx - S_last) mod 65536

if delta == 0:       → REPEATED (동일 메시지 중복)
if delta == 1:       → OK (정상)
if 2 ≤ delta ≤ GAP:  → OK_SOME_LOST (일부 누락, 경고)
if delta > GAP:      → ERROR (과다 누락, 안전 반응)
```

### 2.4 Timeout Monitoring

메시지 타입별 수신 데드라인:

| 메시지 타입 | 주기 (ms) | 데드라인 (ms) | ASIL | 위반 시 동작 |
|------------|----------|-------------|------|-------------|
| 센서/temperature | 1000 | 3000 | A | 경고 로그 |
| 센서/proximity | 200 | 500 | D | 즉시 Safe State |
| 액추에이터 응답 확인 | - | 1000 | C | Degraded 모드 |
| 마스터 heartbeat | 5000 | 15000 | B | 슬레이브 자율 모드 |
| 노드 liveliness | - | 30000 | A | 노드 오프라인 |

타임아웃 감시기 설계:

```
┌─────────────────────────────────────────┐
│          Timeout Monitor                 │
│                                          │
│  ┌─────────┐   message    ┌──────────┐  │
│  │ Timer   │ ←─ reset ──  │ Receiver │  │
│  │ (per    │              │          │  │
│  │  data_id)│              └──────────┘  │
│  └────┬────┘                             │
│       │ expired                          │
│       ▼                                  │
│  ┌──────────────┐                        │
│  │ Safety       │                        │
│  │ State Machine│                        │
│  └──────────────┘                        │
└─────────────────────────────────────────┘
```

### 2.5 E2E 보호 적용 위치

현재 아키텍처에서 E2E 보호 계층 삽입 위치:

```
┌────────────────────────────────────────────────────┐
│  Application Layer (scenario_runner, node_manager)  │
├────────────────────────────────────────────────────┤
│  ★ E2E Protection Layer (NEW)                       │
│    - encode: payload → E2E header + payload + CRC  │
│    - decode: verify CRC, seq, timeout → payload    │
├────────────────────────────────────────────────────┤
│  Serialization Layer (payloads.py — JSON/CBOR)      │
├────────────────────────────────────────────────────┤
│  Zenoh Session Layer (zenoh_master.py)              │
├────────────────────────────────────────────────────┤
│  Transport / Network / PHY                          │
└────────────────────────────────────────────────────┘
```

### 2.6 E2E 상태 머신 (수신 측)

```
                    ┌─────────┐
                    │  INIT   │ (초기 동기화 대기)
                    └────┬────┘
                         │ N개 정상 수신
                         ▼
    timeout         ┌─────────┐         CRC 실패 / seq 이상
    ┌───────────────│  VALID  │──────────────────┐
    │               └────┬────┘                  │
    │                    │ 정상 수신              │
    │                    └──→ (VALID 유지)        │
    ▼                                            ▼
┌─────────┐                              ┌───────────┐
│ TIMEOUT │  ── 복구 수신 ──→ VALID      │  INVALID  │
└─────────┘                              └───────────┘
    │                                         │
    │ 연속 timeout                             │ 연속 실패
    ▼                                         ▼
┌──────────────────────────────────────────────────┐
│                   ERROR                           │
│         → Safety State Machine 통지               │
└──────────────────────────────────────────────────┘
```

---

## 3. 안전 상태 관리 (Safety State Machine)

### 3.1 상태 정의

```
┌──────────┐    장애 감지     ┌───────────┐    심각 장애    ┌────────────┐
│  NORMAL  │ ──────────────→ │ DEGRADED  │ ─────────────→ │ SAFE_STATE │
│          │                 │           │                │            │
│ 모든 기능│                 │ 제한 동작 │                │ 최소 안전  │
│ 정상 동작│                 │ 일부 기능 │                │ 기능만     │
└──────────┘                 └───────────┘                └────────────┘
      ▲                           │                            │
      │         복구 완료          │                            │
      └───────────────────────────┘                            │
                                                               ▼
                                                        ┌────────────┐
                                                        │FAIL_SILENT │
                                                        │            │
                                                        │ 출력 중단  │
                                                        │ 로그만 기록│
                                                        └────────────┘
```

### 3.2 상태 전이 조건

| 현재 상태 | 이벤트 | 다음 상태 | 동작 |
|-----------|--------|-----------|------|
| NORMAL | 노드 1개 통신 두절 | DEGRADED | 해당 노드 기능 비활성화, 경고 로그 |
| NORMAL | E2E CRC 실패 (단발) | NORMAL | 카운터 증가, 경고 로그 |
| NORMAL | E2E CRC 연속 3회 실패 | DEGRADED | 해당 채널 비신뢰 마킹 |
| NORMAL | PLCA beacon 소실 | DEGRADED | 버스 통신 불안정 경고 |
| DEGRADED | 장애 노드 복구 | NORMAL | 기능 재활성화, 로그 |
| DEGRADED | 추가 노드 장애 (≥50% 오프라인) | SAFE_STATE | 액추에이터 안전 위치 |
| DEGRADED | 마스터 heartbeat 타임아웃 | SAFE_STATE | 슬레이브 자율 모드 |
| DEGRADED | ASIL-D 센서 타임아웃 | SAFE_STATE | 즉시 안전 동작 |
| SAFE_STATE | 전체 복구 확인 | NORMAL | 수동 복구 승인 필요 |
| SAFE_STATE | 복구 불가 (60초) | FAIL_SILENT | 모든 출력 차단 |
| FAIL_SILENT | 시스템 재시작 | NORMAL | 전체 초기화 |

### 3.3 안전 동작 정의 (Safe Actions)

각 액추에이터 타입별 안전 상태:

| 액추에이터 | 안전 상태 (SAFE_STATE) | 근거 |
|-----------|----------------------|------|
| LED (헤드라이트) | ON (기본 밝기) | 야간 주행 시 시인성 확보 |
| LED (인테리어) | OFF | 비안전 기능 |
| Motor (윈도우) | STOP (현재 위치 유지) | 끼임 방지 |
| Motor (미러) | STOP | 현재 위치 유지 |
| Relay | OFF (기본) | 연결된 부하에 따라 다름 |
| Buzzer | OFF | 비안전 기능 |
| Lock (도어) | LOCK (주행 중) / UNLOCK (정차) | 탈출 가능성 확보 |

### 3.4 Degraded 모드 동작 규칙

```
Degraded 모드 진입 시:
1. 장애 노드의 액추에이터 → 안전 상태로 전환
2. 정상 노드는 계속 동작
3. 장애 노드의 센서 데이터 → 마지막 유효값 사용 (유효기간 내)
4. 진단 로그에 Degraded 이벤트 기록
5. DTC 코드 저장
6. 복구 모니터링 시작 (주기적 재연결 시도)
```

---

## 4. 장애 감지 메커니즘 (Fault Detection)

### 4.1 장애 유형 분류

| 장애 유형 | 감지 방법 | 반응 시간 | FTTI |
|-----------|----------|----------|------|
| 메시지 손상 | E2E CRC 검증 | 즉시 | < 1ms |
| 메시지 누락 | Sequence Counter 갭 | 즉시 | < 1ms |
| 통신 두절 | Timeout Monitor | 데드라인 | 타입별 |
| 노드 장애 | Liveliness Token 소멸 | < 30s | Zenoh 세션 timeout |
| 버스 장애 | PLCA beacon 소실 | 폴링 주기 | < 10s |
| 마스터 행업 | Watchdog Timer | WDT 주기 | < 5s |
| 프로그램 흐름 오류 | Flow Monitoring | 체크포인트 | < 실행 주기 |

> **FTTI (Fault Tolerant Time Interval)**: 장애 발생부터 안전 상태 도달까지 허용 시간

### 4.2 Watchdog Timer

마스터 프로세스의 행업을 감지하는 소프트웨어 워치독:

```
┌────────────────────────────────────────────────┐
│               Master Application                │
│                                                  │
│  Main Loop:                                      │
│    1. process_sensors()     ← checkpoint 1       │
│    2. process_actuators()   ← checkpoint 2       │
│    3. process_queries()     ← checkpoint 3       │
│    4. collect_diagnostics() ← checkpoint 4       │
│    5. kick_watchdog()       ← 모든 체크포인트 통과 │
│                                                  │
│  Watchdog Timer: 5초                              │
│    - kick 없이 5초 경과 → systemd 재시작          │
└────────────────────────────────────────────────┘
```

systemd watchdog 통합:

```ini
# zenoh-master-app.service
[Service]
Type=notify
WatchdogSec=5
Restart=on-watchdog
RestartSec=2
```

### 4.3 Program Flow Monitoring

실행 흐름이 예상 경로를 따르는지 검증:

```python
# Flow Monitor: 각 checkpoint에 고유 ID 부여
# 실행 순서: CP1 → CP2 → CP3 → CP4 → VERIFY

EXPECTED_FLOW = [CP_SENSOR, CP_ACTUATOR, CP_QUERY, CP_DIAG]

class FlowMonitor:
    def checkpoint(self, cp_id: int):
        """기록된 checkpoint 순서가 expected_flow와 일치하는지 검증"""
        self._actual.append(cp_id)
    
    def verify_cycle(self) -> bool:
        """한 사이클 완료 시 흐름 검증"""
        ok = self._actual == EXPECTED_FLOW
        if not ok:
            # 프로그램 흐름 오류 → Safety State Machine 통지
            safety_fsm.notify_fault(FaultType.FLOW_ERROR)
        self._actual.clear()
        return ok
```

### 4.4 이중 채널 비교 (Plausibility Check)

안전 크리티컬 센서(ASIL-D)에 대한 값 검증:

```
센서값 검증 규칙:
1. Range Check: value가 물리적 유효 범위 내인지
   - temperature: -40°C ~ +150°C
   - pressure: 0 ~ 1000 kPa
   - proximity: 0 ~ 500 cm
   - battery: 0 ~ 60 V

2. Rate-of-Change Check: 변화율이 물리적으로 가능한지
   - temperature: |Δ| ≤ 10°C/s
   - pressure: |Δ| ≤ 500 kPa/s
   - proximity: |Δ| ≤ 100 cm/cycle

3. Cross-Validation: 관련 센서 간 일관성 확인
   - 예: 근접 센서 감지 + 도어 상태 센서 일치 여부
```

---

## 5. DTC (Diagnostic Trouble Code) 관리

### 5.1 DTC 코드 체계

UDS (ISO 14229) 기반 DTC 코드 할당:

```
DTC Format: 0xYYYYZZ
  YYYY = 결함 코드 (2 bytes)
  ZZ   = 결함 유형 (1 byte)

결함 유형 (ZZ):
  0x00 = No sub-type
  0x11 = Short circuit to battery
  0x12 = Short circuit to ground
  0x13 = Open circuit
  0x1F = Circuit failure
  0x29 = Signal invalid
  0x31 = No signal
  0x49 = Internal electronic failure
  0x55 = Not configured
  0x62 = Signal compare failure
  0x64 = Signal plausibility failure
  0x71 = Actuator stuck
  0x96 = Component internal failure
```

### 5.2 프로젝트 DTC 할당

| DTC | 설명 | 트리거 조건 |
|-----|------|------------|
| 0xC10000 | 10BASE-T1S 버스 통신 일반 오류 | PLCA beacon 소실 |
| 0xC10031 | 10BASE-T1S 버스 신호 없음 | 링크 다운 |
| 0xC11029 | E2E CRC 검증 실패 | CRC 불일치 |
| 0xC11129 | E2E Sequence Counter 오류 | 순서 이상 |
| 0xC11231 | E2E Timeout (센서 무응답) | 수신 데드라인 초과 |
| 0xC12049 | 마스터 내부 오류 | Watchdog 만료, 흐름 오류 |
| 0xC13064 | 센서값 유효성 검증 실패 | Range/Rate 초과 |
| 0xC14031 | 슬레이브 노드 통신 두절 | Liveliness 소멸 |
| 0xC15071 | 액추에이터 응답 없음 | 명령 후 확인 타임아웃 |

### 5.3 DTC 상태 관리

```
DTC Status Byte (ISO 14229):
  bit 0: testFailed (현재 고장)
  bit 1: testFailedThisOperationCycle
  bit 2: pendingDTC
  bit 3: confirmedDTC
  bit 4: testNotCompletedSinceLastClear
  bit 5: testFailedSinceLastClear
  bit 6: testNotCompletedThisOperationCycle
  bit 7: warningIndicatorRequested

상태 전이:
  고장 감지 → pendingDTC set
  동일 고장 2 사이클 연속 → confirmedDTC set
  고장 해소 40 사이클 연속 → confirmedDTC clear (aging)
  진단 클리어 요청 → 전체 초기화
```

### 5.4 DTC 저장

```
저장 위치: /var/lib/zenoh-master/dtc_store.json
최대 저장 수: 256 DTC
보존 정책: 비휘발성 (시스템 재시작 후 유지)
클리어 조건: UDS 0x14 서비스 (ClearDiagnosticInformation) 또는 수동
```

---

## 6. Safety Log (불변 로그)

### 6.1 안전 이벤트 로그 요구사항

| 요구사항 | 설명 |
|---------|------|
| 불변성 | 한번 기록된 로그는 수정/삭제 불가 |
| 순서 보장 | 단조증가 타임스탬프 + 시퀀스 번호 |
| 내구성 | 전원 차단 시에도 보존 (fsync) |
| 최소 보관 | 최근 10,000 이벤트 또는 7일 |

### 6.2 로그 구조

```json
{
  "seq": 12345,
  "ts_ms": 1713000000000,
  "monotonic_ns": 987654321000,
  "severity": "SAFETY_CRITICAL",
  "event": "E2E_CRC_FAILURE",
  "source": "vehicle/front/1/sensor/proximity",
  "details": {
    "expected_crc": "0xABCD1234",
    "actual_crc": "0xDEADBEEF",
    "data_id": "0x1003",
    "seq_counter": 4567
  },
  "safety_state": "DEGRADED",
  "dtc": "0xC11029"
}
```

### 6.3 로그 이벤트 유형

| Severity | 이벤트 | 설명 |
|----------|-------|------|
| SAFETY_CRITICAL | E2E_CRC_FAILURE | CRC 검증 실패 |
| SAFETY_CRITICAL | E2E_TIMEOUT | 수신 데드라인 초과 |
| SAFETY_CRITICAL | SAFE_STATE_ENTER | 안전 상태 진입 |
| SAFETY_CRITICAL | FAIL_SILENT_ENTER | 출력 중단 진입 |
| SAFETY_WARNING | SEQ_COUNTER_GAP | 메시지 누락 감지 |
| SAFETY_WARNING | DEGRADED_ENTER | Degraded 모드 진입 |
| SAFETY_WARNING | PLCA_BEACON_LOST | PLCA 비콘 소실 |
| SAFETY_WARNING | SENSOR_PLAUSIBILITY | 센서값 유효성 위반 |
| SAFETY_INFO | NODE_OFFLINE | 노드 오프라인 |
| SAFETY_INFO | NODE_ONLINE | 노드 온라인 복구 |
| SAFETY_INFO | NORMAL_RESTORED | 정상 상태 복구 |
| SAFETY_INFO | DTC_SET | DTC 저장 |
| SAFETY_INFO | DTC_CLEARED | DTC 클리어 |

---

## 7. 시작 시 자체 점검 (Startup Self-Test)

### 7.1 점검 항목

시스템 부팅 후, 정상 동작 진입 전 수행하는 자체 점검:

| 순서 | 점검 항목 | 합격 기준 | 실패 시 동작 |
|------|----------|----------|-------------|
| 1 | CRC 엔진 검증 | 알려진 입력에 대한 기대 CRC 일치 | 시작 불가 |
| 2 | E2E 카운터 초기화 | 모든 카운터 0으로 초기화 확인 | 시작 불가 |
| 3 | Safety State Machine 초기 상태 | NORMAL 상태 확인 | 시작 불가 |
| 4 | DTC 저장소 읽기 | 파일 접근 및 파싱 성공 | 경고 후 진행 |
| 5 | 네트워크 인터페이스 | eth1 링크 UP | DEGRADED로 시작 |
| 6 | PLCA 상태 | beacon 생성/수신 확인 | DEGRADED로 시작 |
| 7 | Zenoh 세션 | zenohd 연결 성공 | 시작 불가 |
| 8 | Watchdog 등록 | systemd notify 성공 | 경고 후 진행 |
| 9 | Safety Log 쓰기 | 테스트 이벤트 기록 및 읽기 | 시작 불가 |
| 10 | 타임스탬프 소스 | monotonic clock 유효성 | 시작 불가 |

### 7.2 점검 흐름

```
[시스템 부팅]
     │
     ▼
[Self-Test 시작]
     │
     ├── CRC 엔진 ─── PASS ──┐
     ├── E2E 초기화 ── PASS ──┤
     ├── FSM 초기 ──── PASS ──┤
     ├── DTC 저장소 ── PASS ──┤
     ├── 네트워크 ──── PASS ──┤
     ├── PLCA ──────── PASS ──┤
     ├── Zenoh 세션 ── PASS ──┤
     ├── Watchdog ──── PASS ──┤
     ├── Safety Log ── PASS ──┤
     └── 타임스탬프 ── PASS ──┤
                              │
                    ALL PASS? │
                   ┌──────────┤
                   │ YES      │ NO (critical)
                   ▼          ▼
            [NORMAL 동작]  [시작 중단]
                            "Self-test failed: {항목}"
```

---

## 8. 구현 모듈 설계

### 8.1 신규 모듈 구조

```
src/
├── common/
│   ├── e2e_protection.py      # E2E 헤더, CRC, Sequence Counter
│   └── safety_types.py        # 안전 관련 Enum, 상수
├── master/
│   ├── safety_manager.py      # Safety State Machine
│   ├── e2e_supervisor.py      # E2E 감시기 (Timeout, Seq 검증)
│   ├── dtc_manager.py         # DTC 저장/조회/클리어
│   ├── safety_log.py          # 불변 Safety Log
│   ├── self_test.py           # 시작 시 자체 점검
│   ├── watchdog.py            # SW Watchdog + systemd 통합
│   └── flow_monitor.py        # Program Flow Monitoring
```

### 8.2 모듈 간 의존성

```
                    ┌──────────────┐
                    │  main.py     │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  self_test   │ (부팅 시 1회)
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
     ┌──────────────┐ ┌────────┐ ┌──────────┐
     │zenoh_master  │ │safety  │ │watchdog  │
     │  + e2e       │ │manager │ │          │
     │  protection  │ │ (FSM)  │ │          │
     └──────┬───────┘ └───┬────┘ └──────────┘
            │             │
     ┌──────▼───────┐    │
     │e2e_supervisor│────┘ (장애 통지)
     └──────┬───────┘
            │
     ┌──────▼───────┐  ┌──────────┐
     │  dtc_manager │  │safety_log│
     └──────────────┘  └──────────┘
```

---

## 9. 테스트 요구사항

### 9.1 E2E Protection 테스트

| ID | 테스트 | 검증 내용 |
|----|--------|----------|
| FST-001 | CRC 정상 | 정상 메시지의 CRC 검증 성공 |
| FST-002 | CRC 변조 감지 | 1-bit flip → CRC 실패 감지 |
| FST-003 | Sequence 정상 | 순차 수신 시 OK 상태 |
| FST-004 | Sequence 누락 감지 | 갭 > 허용치 → ERROR |
| FST-005 | Sequence 중복 감지 | delta = 0 → REPEATED |
| FST-006 | Timeout 감지 | 데드라인 초과 → TIMEOUT 상태 |
| FST-007 | Data ID 불일치 | 잘못된 data_id → 거부 |
| FST-008 | Wrap-around | seq 65535 → 0 정상 처리 |

### 9.2 Safety State Machine 테스트

| ID | 테스트 | 검증 내용 |
|----|--------|----------|
| FST-010 | NORMAL → DEGRADED | 노드 장애 시 전이 확인 |
| FST-011 | DEGRADED → NORMAL | 복구 시 전이 확인 |
| FST-012 | DEGRADED → SAFE_STATE | 다중 장애 시 전이 확인 |
| FST-013 | SAFE_STATE 액추에이터 | 안전 위치 동작 확인 |
| FST-014 | FAIL_SILENT 출력 차단 | 모든 publish 차단 확인 |
| FST-015 | 부팅 Self-Test | 전 항목 PASS/FAIL 확인 |

### 9.3 장애 주입 테스트 (Fault Injection)

| ID | 주입 장애 | 기대 동작 |
|----|----------|----------|
| FIT-001 | 네트워크 인터페이스 down | DEGRADED 진입, 재연결 시도 |
| FIT-002 | 슬레이브 프로세스 kill | Liveliness 소멸, NODE_OFFLINE 로그 |
| FIT-003 | 페이로드 바이트 변조 | E2E CRC 실패, 메시지 거부 |
| FIT-004 | 메시지 지연 주입 | Timeout 감지, 경고 또는 SAFE_STATE |
| FIT-005 | Zenohd 프로세스 kill | 세션 단절, SAFE_STATE, systemd 재시작 |
| FIT-006 | DTC 저장소 파일 삭제 | 자체 점검 경고, 새 파일 생성 |

---

## 10. ISO 26262 매핑

### 10.1 Part 6 (Software Level) 요구사항 대응

| ISO 26262 조항 | 요구사항 | 본 설계 대응 |
|----------------|---------|-------------|
| 6.7.4.1 | SW 안전 요구사항 도출 | 본 문서 Section 2~4 |
| 6.7.4.2 | 안전 메커니즘 설계 | E2E Protection, Safety FSM |
| 6.7.4.3 | 에러 감지 및 처리 | Timeout, CRC, Seq, Watchdog |
| 6.7.4.4 | 안전 상태 전이 | Section 3 Safety State Machine |
| 6.7.4.7 | 자체 점검 (self-test) | Section 7 Startup Self-Test |
| 6.9 | SW 단위 검증 | Section 9.1, 9.2 테스트 |
| 6.10 | SW 통합 검증 | Section 9.3 장애 주입 테스트 |

### 10.2 ASIL-D 추가 요구사항

ASIL-D가 요구하는 강화된 기법 (ISO 26262 Part 6, Table 1):

| 기법 | ASIL-D 권장 | 본 설계 적용 |
|------|------------|-------------|
| 방어적 프로그래밍 | 강력 권장 (++) | E2E 검증, Range Check |
| 입력 유효성 검사 | 강력 권장 (++) | Plausibility Check |
| 오류 감지 코드 (CRC) | 강력 권장 (++) | CRC-32 |
| 다중 채널 비교 | 권장 (+) | Cross-Validation (향후) |
| 프로그램 흐름 감시 | 강력 권장 (++) | Flow Monitor |
| Watchdog | 강력 권장 (++) | SW WDT + systemd |
| 안전 상태 전이 | 강력 권장 (++) | Safety FSM |

---

## 11. 참고 자료

| 표준/문서 | 범위 |
|----------|------|
| ISO 26262:2018 Part 4 | 시스템 수준 제품 개발 |
| ISO 26262:2018 Part 5 | 하드웨어 수준 제품 개발 |
| ISO 26262:2018 Part 6 | 소프트웨어 수준 제품 개발 |
| AUTOSAR E2E Protocol Specification | E2E 보호 프로파일 (Profile 1~7) |
| AUTOSAR Specification of SW-C End-to-End Communication Protection Library | E2E 라이브러리 API |
| ISO 14229 (UDS) | 통합 진단 서비스 |
| IEC 61508 | 전기/전자/프로그래머블 기능 안전 (상위 표준) |
