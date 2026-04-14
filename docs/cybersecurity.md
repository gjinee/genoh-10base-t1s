# 사이버보안 설계 명세서 (Cybersecurity Specification)

## 문서 정보

| 항목 | 내용 |
|------|------|
| 프로젝트명 | Zenoh-10BASE-T1S Automotive Master Controller Simulator |
| 문서 버전 | v0.1.0 |
| 작성일 | 2026-04-13 |
| 상태 | Draft |
| 관련 표준 | ISO/SAE 21434:2021, UNECE R155/R156, AUTOSAR SecOC |
| 관련 문서 | PRD.md, functional_safety.md |

---

## 1. 개요 (Overview)

### 1.1 목적

본 문서는 10BASE-T1S Zenoh 기반 자동차 존 네트워크의 **사이버보안(Cybersecurity)** 요구사항과 설계를 정의한다. ISO/SAE 21434(자동차 사이버보안 엔지니어링)과 UNECE R155(사이버보안 형식 승인)를 기준으로, 통신 보안, 접근 제어, 침입 탐지 메커니즘을 명세한다.

### 1.2 적용 범위

| 범위 | 포함 | 제외 |
|------|------|------|
| 통신 보안 | TLS/DTLS, 메시지 인증 (MAC), 리플레이 방지 | V2X 보안, 클라우드 연동 보안 |
| 접근 제어 | 노드 인증, Key Expression ACL | 물리적 접근 통제 |
| 침입 탐지 | 네트워크 IDS, 이상 행위 감지 | 호스트 기반 IDS (HIDS) |
| 키 관리 | 인증서 수명주기, 키 저장 | HSM 하드웨어 통합 |
| 보안 업데이트 | OTA 서명 검증 | OTA 인프라 구축 |

### 1.3 규제 배경

| 규제 | 발효일 | 요구사항 |
|------|--------|---------|
| UNECE R155 | 2022-07 (신규 형식), 2024-07 (모든 신차) | CSMS(사이버보안관리시스템) 인증 |
| UNECE R156 | 2022-07 (신규 형식), 2024-07 (모든 신차) | SUMS(소프트웨어 업데이트관리시스템) 인증 |
| ISO/SAE 21434 | 2021-08 | 자동차 사이버보안 엔지니어링 프로세스 |

> **참고**: UNECE R155는 2024년 7월부터 EU에서 판매되는 **모든 신차**에 필수 적용된다. 부품(10BASE-T1S 존 컨트롤러 등)도 차량 CSMS 범위에 포함된다.

---

## 2. 위협 분석 (TARA — Threat Analysis and Risk Assessment)

### 2.1 TARA 프로세스

ISO/SAE 21434 Section 15에 따른 위협 분석:

```
자산 식별 → 위협 시나리오 → 공격 경로 분석 → 영향/실현 가능성 평가 → 위험 등급 → 대응 결정
```

### 2.2 자산 식별

| 자산 ID | 자산 | 유형 | 위치 |
|---------|------|------|------|
| A-01 | 센서 데이터 (온도, 압력, 근접) | 데이터 | Zenoh 메시지 |
| A-02 | 액추에이터 제어 명령 | 데이터 | Zenoh 메시지 |
| A-03 | 노드 상태 정보 | 데이터 | Zenoh Query/Reply |
| A-04 | Zenoh 세션 자격증명 | 자격증명 | 마스터/슬레이브 설정 |
| A-05 | PLCA 설정 (Node ID, Coordinator) | 설정 | ethtool 파라미터 |
| A-06 | DTC/진단 데이터 | 데이터 | 로컬 저장소 |
| A-07 | 펌웨어/소프트웨어 바이너리 | 소프트웨어 | 마스터/슬레이브 |
| A-08 | Zenoh Router 설정 | 설정 | master_config.json5 |

### 2.3 위협 시나리오 (STRIDE 분류)

| ID | 위협 | STRIDE | 자산 | 공격 벡터 |
|----|------|--------|------|----------|
| T-01 | 센서 데이터 위조 | Spoofing | A-01 | 버스에 위조 센서 메시지 주입 |
| T-02 | 액추에이터 명령 위조 | Spoofing | A-02 | 위조 제어 명령으로 액추에이터 오동작 |
| T-03 | 메시지 도청 | Information Disclosure | A-01~03 | 버스 트래픽 스니핑 |
| T-04 | 메시지 변조 | Tampering | A-01~03 | 전송 중 메시지 내용 수정 |
| T-05 | 리플레이 공격 | Spoofing | A-02 | 과거 유효 명령 재전송 |
| T-06 | 서비스 거부 (DoS) | Denial of Service | A-01~03 | 대량 메시지로 버스 포화 |
| T-07 | 비인가 노드 접속 | Spoofing | A-04 | 인증 없이 Zenoh 세션 수립 |
| T-08 | PLCA 설정 변조 | Tampering | A-05 | Coordinator 강탈, Node Count 변경 |
| T-09 | 펌웨어 변조 | Tampering | A-07 | 악성 펌웨어 주입 |
| T-10 | 진단 데이터 위조 | Repudiation | A-06 | DTC 삭제/변조로 사고 은폐 |
| T-11 | 권한 상승 | Elevation of Privilege | A-08 | 슬레이브가 마스터 기능 수행 |

### 2.4 위험 평가

영향도(Impact) × 실현 가능성(Feasibility) = 위험 등급(Risk Level)

| ID | 영향도 | 실현 가능성 | 위험 등급 | 대응 전략 |
|----|--------|-----------|----------|----------|
| T-01 | 높음 (안전 기능 오동작) | 중간 (물리 접근 필요) | **높음** | 메시지 인증 (MAC) |
| T-02 | 매우 높음 (물리적 위험) | 중간 | **매우 높음** | MAC + Freshness |
| T-03 | 중간 (프라이버시) | 높음 (버스 스니핑 용이) | **높음** | TLS 암호화 |
| T-04 | 높음 | 중간 | **높음** | E2E CRC + MAC |
| T-05 | 높음 | 높음 (이전 메시지 저장 용이) | **매우 높음** | Freshness Value |
| T-06 | 높음 (통신 마비) | 중간 | **높음** | Rate Limiting + IDS |
| T-07 | 높음 | 중간 (물리 접근 필요) | **높음** | mTLS 인증 |
| T-08 | 높음 (버스 제어 상실) | 낮음 (물리 접근 + 지식) | **중간** | 물리 보안 + 모니터링 |
| T-09 | 매우 높음 | 낮음 | **높음** | Secure Boot + 서명 |
| T-10 | 중간 | 중간 | **중간** | 불변 로그 + 인증 |
| T-11 | 높음 | 중간 | **높음** | ACL + 역할 기반 |

---

## 3. 통신 보안 (Communication Security)

### 3.1 전송 계층 보안 — TLS/DTLS

현재 Zenoh 세션은 평문 TCP(`tcp/127.0.0.1:7447`)를 사용한다. 보안 적용 후 구조:

```
현재:
  Master App ──tcp/127.0.0.1:7447──→ zenohd ──tcp/192.168.1.1:7447──→ Slave

보안 적용 후:
  Master App ──tcp/127.0.0.1:7447──→ zenohd ──tls/192.168.1.1:7447──→ Slave
                (로컬 loopback,                (10BASE-T1S 버스,
                 TLS 불필요)                    mTLS 적용)
```

#### 3.1.1 zenohd TLS 설정

```json5
// master_config.json5 — TLS 활성화
{
  mode: "router",
  listen: {
    endpoints: [
      "tcp/127.0.0.1:7447",          // 로컬 앱용 (loopback)
      "tls/192.168.1.1:7447"         // 슬레이브용 (10BASE-T1S)
    ]
  },
  transport: {
    link: {
      tls: {
        // 서버 인증서 (zenohd = 마스터)
        server_certificate: "/etc/zenoh/certs/master.crt",
        server_private_key: "/etc/zenoh/certs/master.key",
        // 클라이언트 인증서 검증 (mTLS)
        root_ca_certificate: "/etc/zenoh/certs/ca.crt",
        client_auth: true
      }
    }
  }
}
```

#### 3.1.2 zenoh-pico TLS 빌드

```bash
# zenoh-pico TLS 지원 빌드 (Mbed TLS 사용)
cmake .. \
  -DCMAKE_BUILD_TYPE=Release \
  -DZ_FEATURE_LINK_TLS=ON \
  -DZ_FEATURE_LINK_TCP=ON \
  -DZENOH_PICO_TLS_BACKEND=MBEDTLS
```

#### 3.1.3 TLS 파라미터

| 파라미터 | 값 | 근거 |
|---------|-----|------|
| 프로토콜 | TLS 1.3 | 최신 보안, 핸드셰이크 간소화 |
| 암호 스위트 | TLS_AES_128_GCM_SHA256 | MCU 리소스 고려, AEAD |
| 인증서 형식 | X.509 v3 | 표준 PKI |
| 키 알고리즘 | ECDSA P-256 | MCU 성능 최적화 (RSA 대비 빠름) |
| 인증서 유효기간 | 2년 (CA), 1년 (디바이스) | 차량 수명주기 고려 |
| OCSP/CRL | 오프라인 CRL 사용 | 차량 네트워크는 오프라인 가능 |

#### 3.1.4 성능 영향

10BASE-T1S (10 Mbps) 환경에서 TLS 오버헤드:

| 항목 | 오버헤드 | 비고 |
|------|---------|------|
| TLS 핸드셰이크 | ~2KB (ECDSA P-256) | 세션 수립 시 1회 |
| TLS 레코드 헤더 | 5 bytes/record | 매 전송 |
| AES-128-GCM | 16 bytes (auth tag) + 12 bytes (IV) | 매 전송 |
| 핸드셰이크 지연 | ~50ms (10Mbps 기준) | 세션 수립 시 1회 |
| 데이터 전송 지연 | < 1ms 추가 | AES-128-GCM HW 가속 시 |

> **10Mbps 대역폭 영향**: TLS 레코드 오버헤드(~33 bytes/message)는 Zenoh 메시지(평균 50~100 bytes payload) 대비 약 33~66% 증가. 그러나 10Mbps 대역폭에서 8노드 × 10 msg/s = 80 msg/s 기준으로 총 ~10.6 KB/s로, 대역폭의 약 0.08%만 사용하므로 충분하다.

### 3.2 메시지 인증 — HMAC / CMAC

TLS가 전송 계층 보안을 제공하지만, **애플리케이션 레벨** 메시지 인증이 추가로 필요한 이유:

- TLS는 hop-by-hop 보호 (zenohd 라우터에서 복호화됨)
- 라우터 내부 또는 로컬 프로세스 간 변조 방지
- E2E(송신자→수신자) 무결성 보장

#### 3.2.1 SecOC 기반 메시지 인증 구조

AUTOSAR SecOC(Secure Onboard Communication) 프로파일 참고:

```
┌──────────────────────────────────────────────────────────────┐
│                 SecOC Protected Message                        │
├──────────┬──────────────────┬──────────────┬─────────────────┤
│ E2E HDR  │    Payload       │ Freshness    │   MAC           │
│ (11 B)   │  (JSON/CBOR)     │ Value (8 B)  │ (16 B truncated)│
├──────────┴──────────────────┴──────────────┼─────────────────┤
│          Authenticated Data                 │  Auth Tag       │
└─────────────────────────────────────────────┴─────────────────┘

MAC 계산 입력: E2E Header + Payload + Freshness Value
MAC 알고리즘: HMAC-SHA256 (truncated to 128 bits)
총 SecOC 오버헤드: 24 bytes (Freshness 8B + MAC 16B)
```

#### 3.2.2 MAC 키 관리

| 항목 | 설명 |
|------|------|
| 키 유형 | 대칭키 (HMAC-SHA256) |
| 키 길이 | 256 bits |
| 키 저장 | 보안 파일 (chmod 600) / 향후 HSM |
| 키 분배 | 초기 프로비저닝 시 인증서와 함께 배포 |
| 키 갱신 | 6개월 주기 또는 보안 이벤트 발생 시 |
| 키 ID | node_id 기반 (마스터: 0, 슬레이브: 1~7) |

키 분리 정책:

```
Master-Slave 1 통신 키: K_01 = KDF(Master_Key, "node_01")
Master-Slave 2 통신 키: K_02 = KDF(Master_Key, "node_02")
...
브로드캐스트 키: K_BC = KDF(Master_Key, "broadcast")

KDF = HKDF-SHA256(salt=vehicle_id, ikm=Master_Key, info=context)
```

### 3.3 리플레이 방지 — Freshness Value

과거 유효 메시지를 재전송하는 리플레이 공격 방지:

#### 3.3.1 Freshness Value 구조

```
Freshness Value (64 bits):
┌─────────────────────────┬──────────────────┐
│  Timestamp (48 bits)    │ Counter (16 bits) │
│  ms since epoch         │ per-timestamp     │
└─────────────────────────┴──────────────────┘
```

| 필드 | 크기 | 설명 |
|------|------|------|
| Timestamp | 48 bit | 밀리초 단위 시각 (약 8900년 범위) |
| Counter | 16 bit | 동일 밀리초 내 순서 번호 |

#### 3.3.2 검증 로직

```
수신 측 Freshness 검증:

1. FV_rx = 수신 메시지의 Freshness Value
2. FV_last = 마지막 유효 수신 Freshness Value
3. T_now = 현재 시각 (ms)

검증:
  if FV_rx.timestamp ≤ FV_last.timestamp 
     AND FV_rx.counter ≤ FV_last.counter:
    → REJECT (리플레이)

  if |FV_rx.timestamp - T_now| > FRESHNESS_WINDOW:
    → REJECT (시간 편차 과다)

  otherwise:
    → ACCEPT, FV_last = FV_rx

FRESHNESS_WINDOW: 5000 ms (시간 동기화 오차 허용)
```

#### 3.3.3 시간 동기화

10BASE-T1S 네트워크에서의 시간 동기화:

| 방법 | 정확도 | 구현 복잡도 | 적용 |
|------|--------|-----------|------|
| NTP (로컬) | ~1ms | 낮음 | 시뮬레이터 (현재) |
| PTP (IEEE 1588) | < 1μs | 높음 | 양산 (향후) |
| Zenoh 타임스탬프 | HLC 기반 | 내장 | 보조 수단 |

---

## 4. 접근 제어 (Access Control)

### 4.1 노드 인증 체계

```
┌──────────────────────────────────────────────────────┐
│                    PKI 구조                            │
│                                                        │
│  ┌──────────┐                                          │
│  │ Root CA  │ ── 자체 서명, 오프라인 보관                │
│  └────┬─────┘                                          │
│       │ 서명                                           │
│  ┌────▼─────────────┐                                  │
│  │ Vehicle Sub-CA   │ ── 차량별 중간 CA                 │
│  └────┬─────────────┘                                  │
│       │ 서명                                           │
│  ┌────▼────┐  ┌──────────┐  ┌──────────┐              │
│  │ Master  │  │ Slave 1  │  │ Slave N  │  ── 디바이스 │
│  │ Cert    │  │ Cert     │  │ Cert     │     인증서   │
│  └─────────┘  └──────────┘  └──────────┘              │
└──────────────────────────────────────────────────────┘
```

인증서 Subject 형식:

```
CN = zenoh-node-{node_id}
O  = {vehicle_manufacturer}
OU = zone-controller
SAN = IP:192.168.1.{node_id+1}
```

### 4.2 Zenoh ACL (Access Control List)

zenohd 라우터에서 Key Expression 기반 접근 제어:

#### 4.2.1 ACL 정책 설계

```json5
// master_config.json5 — ACL 설정
{
  access_control: {
    enabled: true,
    default_permission: "deny",  // 화이트리스트 방식
    rules: [
      // 마스터 앱 (로컬) — 전체 접근
      {
        id: "master_app",
        interfaces: ["tcp/127.0.0.1"],
        permission: "allow",
        key_exprs: ["vehicle/**"],
        actions: ["put", "get", "declare_subscriber", "declare_queryable"]
      },

      // Slave Node 1 (front_left) — 자기 zone만
      {
        id: "slave_node_1",
        cert_common_name: "zenoh-node-1",
        permission: "allow",
        key_exprs: [
          "vehicle/front_left/1/sensor/*",     // 자기 센서 publish
          "vehicle/front_left/1/status",       // 자기 상태 queryable
          "vehicle/front_left/1/alive",        // 자기 liveliness
          "vehicle/front_left/1/actuator/*",   // 자기 액추에이터 subscribe
          "vehicle/master/heartbeat",          // 마스터 heartbeat subscribe
          "vehicle/master/command"             // 브로드캐스트 명령 subscribe
        ],
        actions: ["put", "declare_subscriber", "declare_queryable"]
      },

      // Slave Node 2 (front_right) — 자기 zone만
      {
        id: "slave_node_2",
        cert_common_name: "zenoh-node-2",
        permission: "allow",
        key_exprs: [
          "vehicle/front_right/2/sensor/*",
          "vehicle/front_right/2/status",
          "vehicle/front_right/2/alive",
          "vehicle/front_right/2/actuator/*",
          "vehicle/master/heartbeat",
          "vehicle/master/command"
        ],
        actions: ["put", "declare_subscriber", "declare_queryable"]
      }

      // ... 노드 3~7도 동일 패턴
    ]
  }
}
```

#### 4.2.2 ACL 위반 처리

| ACL 위반 유형 | 동작 |
|-------------|------|
| 비인가 key expression publish | 메시지 차단, IDS 경고 |
| 비인가 subscribe 시도 | 구독 거부, IDS 경고 |
| 비인가 query | 쿼리 거부, IDS 경고 |
| 인증서 없는 연결 | 연결 거부 |
| 만료 인증서 | 연결 거부, 로그 |

### 4.3 역할 기반 접근 제어 (RBAC)

| 역할 | 노드 | 허용 동작 |
|------|------|----------|
| COORDINATOR | 마스터 (Node 0) | 전체 key expression read/write, ACL 관리 |
| SENSOR_NODE | 센서 슬레이브 | 자기 센서 publish, 상태 queryable |
| ACTUATOR_NODE | 액추에이터 슬레이브 | 자기 액추에이터 subscribe, 확인 publish |
| MIXED_NODE | 센서+액추에이터 | SENSOR + ACTUATOR 합산 |
| DIAGNOSTIC | 진단 도구 | 읽기 전용 (모든 key expression subscribe) |

---

## 5. 침입 탐지 시스템 (IDS)

### 5.1 네트워크 기반 IDS 설계

```
┌─────────────────────────────────────────────────────┐
│                  IDS Engine                           │
│                                                       │
│  ┌────────────┐  ┌────────────┐  ┌────────────────┐ │
│  │ Rule-Based │  │ Rate       │  │ Anomaly        │ │
│  │ Detection  │  │ Limiter    │  │ Detection      │ │
│  └─────┬──────┘  └─────┬──────┘  └──────┬─────────┘ │
│        │               │                │            │
│        └───────────────┼────────────────┘            │
│                        ▼                              │
│                 ┌──────────────┐                      │
│                 │ Alert Manager│                      │
│                 └──────┬───────┘                      │
│                        │                              │
│              ┌─────────┼──────────┐                   │
│              ▼         ▼          ▼                   │
│         ┌───────┐ ┌────────┐ ┌────────┐              │
│         │ Log   │ │ Safety │ │ Block  │              │
│         │       │ │ FSM    │ │ Source │              │
│         └───────┘ └────────┘ └────────┘              │
└─────────────────────────────────────────────────────┘
```

### 5.2 탐지 규칙

#### 5.2.1 Rate Limiting

노드별 메시지 전송률 제한:

| 메시지 타입 | 정상 범위 | 경고 임계값 | 차단 임계값 |
|------------|----------|-----------|-----------|
| 센서 데이터 (per node) | 1~10 msg/s | > 50 msg/s | > 100 msg/s |
| 액추에이터 명령 | 0~5 msg/s | > 20 msg/s | > 50 msg/s |
| Query 요청 | 0~2 msg/s | > 10 msg/s | > 20 msg/s |
| 전체 버스 트래픽 | < 100 msg/s | > 500 msg/s | > 1000 msg/s |

#### 5.2.2 Rule-Based Detection

| 규칙 ID | 조건 | 심각도 | 동작 |
|---------|------|--------|------|
| IDS-001 | 비인가 key expression publish | CRITICAL | 차단 + 경고 |
| IDS-002 | 메시지 rate 초과 (flooding) | HIGH | 속도 제한 + 경고 |
| IDS-003 | MAC 검증 실패 | CRITICAL | 메시지 거부 + 경고 |
| IDS-004 | 리플레이 감지 (Freshness 실패) | HIGH | 메시지 거부 + 경고 |
| IDS-005 | 인증서 없는 연결 시도 | MEDIUM | 연결 거부 + 로그 |
| IDS-006 | 비정상 페이로드 크기 (> 4KB) | MEDIUM | 메시지 거부 + 경고 |
| IDS-007 | 슬레이브가 마스터 key expression publish | CRITICAL | 차단 + 즉시 경고 |
| IDS-008 | 동시 다수 노드 오프라인 (≥3) | HIGH | 버스 공격 의심 경고 |
| IDS-009 | 비정상 시간대 통신 (차량 정차 중) | LOW | 로그 |
| IDS-010 | CRC + MAC 동시 실패 | CRITICAL | SAFE_STATE 진입 |

#### 5.2.3 Anomaly Detection

통계 기반 이상 행위 감지:

```
학습 기간: 최초 1000 메시지 (baseline)

모니터링 지표:
1. 메시지 간격 분포 (평균, 표준편차)
   - |interval - μ| > 3σ → 이상
   
2. 페이로드 크기 분포
   - |size - μ| > 3σ → 이상
   
3. 센서값 변화 패턴
   - 갑작스러운 값 점프 (물리적 불가능)
   
4. 통신 패턴
   - 평소 없던 key expression 사용
   - 평소 없던 시간대 통신
```

### 5.3 IDS 경고 구조

```json
{
  "alert_id": "IDS-2026041300001",
  "ts_ms": 1713000000000,
  "rule_id": "IDS-001",
  "severity": "CRITICAL",
  "source_node": "zenoh-node-3",
  "source_ip": "192.168.1.4",
  "description": "Unauthorized publish to vehicle/master/command",
  "evidence": {
    "key_expr": "vehicle/master/command",
    "payload_size": 45,
    "expected_publisher": "master_only"
  },
  "action_taken": "message_blocked",
  "related_dtc": "0xC20029"
}
```

---

## 6. 보안 부팅 및 소프트웨어 업데이트

### 6.1 Secure Boot Chain

```
┌───────────┐     검증      ┌───────────┐     검증      ┌───────────┐
│ Root of   │ ──────────→  │ Bootloader│ ──────────→  │ OS Kernel │
│ Trust     │              │ (signed)  │              │ (signed)  │
│ (eFuse)   │              │           │              │           │
└───────────┘              └───────────┘              └───────────┘
                                                            │ 검증
                                                            ▼
                                                     ┌───────────┐
                                                     │ zenohd    │
                                                     │ + Master  │
                                                     │ App       │
                                                     │ (signed)  │
                                                     └───────────┘
```

### 6.2 OTA 업데이트 서명

| 항목 | 설명 |
|------|------|
| 서명 알고리즘 | Ed25519 (또는 ECDSA P-256) |
| 서명 대상 | 펌웨어 이미지 전체 |
| 검증 키 | 디바이스에 사전 배포된 공개키 |
| 업데이트 형식 | 헤더(버전+서명+해시) + 이미지 |
| 롤백 보호 | 버전 카운터 (anti-rollback) |
| A/B 파티션 | 실패 시 이전 버전으로 복구 |

### 6.3 업데이트 흐름

```
[OTA 서버] ── 서명된 이미지 ──→ [마스터]
                                   │
                          1. 서명 검증 (Ed25519)
                          2. 해시 검증 (SHA-256)
                          3. 버전 확인 (anti-rollback)
                          4. B 파티션에 쓰기
                          5. 재부팅 → B 파티션으로 시작
                          6. Self-test PASS → B를 활성으로 확정
                          7. Self-test FAIL → A 파티션으로 롤백
```

---

## 7. 키 관리 (Key Management)

### 7.1 키 수명주기

```
생성 → 분배 → 저장 → 사용 → 갱신 → 폐기

┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐
│ 생성 │ →  │ 분배 │ →  │ 저장 │ →  │ 사용 │ →  │ 갱신 │ →  │ 폐기 │
│      │    │      │    │      │    │      │    │      │    │      │
│오프라│    │보안  │    │파일/ │    │TLS/  │    │주기적│    │안전  │
│인 CA │    │채널  │    │HSM   │    │MAC   │    │재발급│    │삭제  │
└──────┘    └──────┘    └──────┘    └──────┘    └──────┘    └──────┘
```

### 7.2 키 유형 및 관리

| 키 유형 | 용도 | 저장 위치 | 갱신 주기 |
|---------|------|----------|----------|
| Root CA 비밀키 | CA 인증서 서명 | 오프라인 HSM | 5년 |
| Vehicle Sub-CA 비밀키 | 디바이스 인증서 발급 | 보안 서버 | 2년 |
| 디바이스 비밀키 (TLS) | mTLS 인증 | 노드 로컬 | 1년 |
| HMAC 대칭키 (SecOC) | 메시지 인증 | 노드 로컬 | 6개월 |
| OTA 서명 키 | 펌웨어 서명 | 빌드 서버 HSM | 2년 |

### 7.3 키 저장 보안

시뮬레이터 환경 (Raspberry Pi):

```
/etc/zenoh/certs/
├── ca.crt                    # Root CA 공개 인증서 (644)
├── master.crt                # 마스터 인증서 (644)
├── master.key                # 마스터 비밀키 (600, root only)
├── hmac_keys/
│   ├── node_01.key           # Slave 1 HMAC 키 (600)
│   ├── node_02.key           # Slave 2 HMAC 키 (600)
│   └── broadcast.key         # 브로드캐스트 HMAC 키 (600)
└── crl/
    └── revoked.crl           # 인증서 폐기 목록 (644)
```

> **양산 환경**: Raspberry Pi의 파일시스템 대신 **HSM(Hardware Security Module)** 또는 **TPM 2.0**을 사용하여 비밀키를 보호한다. ARM TrustZone 또는 OP-TEE Secure World에 키를 격리할 수 있다.

---

## 8. 보안 이벤트 로그

### 8.1 로그 구조

기능안전 Safety Log와 별도의 보안 이벤트 로그:

```json
{
  "seq": 5678,
  "ts_ms": 1713000000000,
  "severity": "CRITICAL",
  "category": "INTRUSION_DETECTION",
  "event": "UNAUTHORIZED_PUBLISH",
  "source": {
    "node_id": "zenoh-node-3",
    "ip": "192.168.1.4",
    "cert_cn": "zenoh-node-3"
  },
  "target": {
    "key_expr": "vehicle/master/command"
  },
  "action": "BLOCKED",
  "ids_rule": "IDS-001"
}
```

### 8.2 로그 보호

| 요구사항 | 구현 |
|---------|------|
| 무결성 | 로그 체인 해시 (각 항목이 이전 해시 포함) |
| 비부인 | 마스터 서명 (Ed25519) |
| 보존 | 최소 30일 보관 |
| 전송 | 향후 SIEM 연동 (syslog/JSON over TLS) |

체인 해시 구조:

```
Log[n].chain_hash = SHA-256(Log[n-1].chain_hash + Log[n].content)

→ 중간 항목 삭제/변조 시 체인 단절로 감지
```

---

## 9. 구현 모듈 설계

### 9.1 신규 모듈 구조

```
src/
├── common/
│   └── security_types.py      # 보안 관련 Enum, 상수
├── master/
│   ├── secoc.py               # SecOC 메시지 인증 (HMAC + Freshness)
│   ├── ids_engine.py          # 침입 탐지 엔진
│   ├── acl_manager.py         # ACL 정책 관리 (zenohd 설정 생성)
│   ├── key_manager.py         # 키/인증서 수명주기 관리
│   ├── security_log.py        # 보안 이벤트 로그 (체인 해시)
│   └── cert_provisioner.py    # 인증서 생성/배포 도구
config/
│   ├── master_config_tls.json5  # TLS 적용 zenohd 설정
│   ├── acl_policy.json5         # ACL 정책 정의
│   └── certs/                   # 인증서 템플릿 및 스크립트
│       ├── generate_ca.sh
│       ├── generate_device_cert.sh
│       └── openssl.cnf
```

### 9.2 보호 계층 통합 (전체 스택)

```
┌─────────────────────────────────────────────────────────┐
│  Application (scenario_runner, node_manager)              │
├─────────────────────────────────────────────────────────┤
│  ★ IDS Engine (ids_engine.py) — 이상 감지               │
├─────────────────────────────────────────────────────────┤
│  ★ SecOC Layer (secoc.py) — HMAC + Freshness            │
├─────────────────────────────────────────────────────────┤
│  ★ E2E Protection (e2e_protection.py) — CRC + Seq       │
├─────────────────────────────────────────────────────────┤
│  Serialization (payloads.py) — JSON/CBOR                 │
├─────────────────────────────────────────────────────────┤
│  Zenoh Session (zenoh_master.py) — ★ ACL 적용           │
├─────────────────────────────────────────────────────────┤
│  ★ TLS/mTLS (zenohd config) — 전송 암호화               │
├─────────────────────────────────────────────────────────┤
│  10BASE-T1S PHY (PLCA)                                   │
└─────────────────────────────────────────────────────────┘

★ = 보안 레이어 (신규)
```

---

## 10. 테스트 요구사항

### 10.1 통신 보안 테스트

| ID | 테스트 | 검증 내용 |
|----|--------|----------|
| CST-001 | TLS 핸드셰이크 | mTLS 인증 성공 |
| CST-002 | 인증서 없는 연결 거부 | 비인증 클라이언트 차단 |
| CST-003 | 만료 인증서 거부 | 유효기간 초과 인증서 차단 |
| CST-004 | HMAC 정상 검증 | 유효 MAC의 메시지 수신 성공 |
| CST-005 | HMAC 변조 감지 | 변조 MAC → 메시지 거부 |
| CST-006 | 리플레이 차단 | 과거 Freshness → 메시지 거부 |
| CST-007 | TLS 성능 영향 | 지연 < 15ms (PRD NFR-001 유지) |

### 10.2 접근 제어 테스트

| ID | 테스트 | 검증 내용 |
|----|--------|----------|
| CST-010 | ACL 허용 | 허가된 key expression 접근 성공 |
| CST-011 | ACL 차단 | 비허가 key expression 접근 차단 |
| CST-012 | 권한 상승 방지 | 슬레이브가 마스터 key expression publish 차단 |
| CST-013 | 크로스 노드 차단 | Node 1이 Node 2 key expression publish 차단 |

### 10.3 IDS 테스트

| ID | 테스트 | 검증 내용 |
|----|--------|----------|
| CST-020 | Flooding 감지 | Rate 초과 시 경고 발생 |
| CST-021 | 비인가 publish 감지 | IDS 경고 + 차단 |
| CST-022 | MAC 실패 연속 경고 | N회 연속 실패 → CRITICAL 경고 |
| CST-023 | 정상 트래픽 무오탐 | 정상 동작 시 경고 없음 (FP=0) |

### 10.4 침투 테스트 시나리오

| ID | 시나리오 | 목표 | 기대 결과 |
|----|---------|------|----------|
| PT-001 | 위조 센서 메시지 주입 | T-01 검증 | MAC 실패로 거부 |
| PT-002 | 위조 액추에이터 명령 | T-02 검증 | MAC + ACL로 차단 |
| PT-003 | 과거 명령 리플레이 | T-05 검증 | Freshness 실패로 거부 |
| PT-004 | 비인가 노드 접속 | T-07 검증 | mTLS 인증 실패 |
| PT-005 | 버스 flooding 공격 | T-06 검증 | Rate limit + IDS 경고 |
| PT-006 | MITM (중간자 공격) | T-04 검증 | TLS 인증서 검증 실패 |

---

## 11. ISO/SAE 21434 매핑

### 11.1 사이버보안 엔지니어링 활동 대응

| ISO/SAE 21434 조항 | 활동 | 본 설계 대응 |
|-------------------|------|-------------|
| 8 (위협 분석) | TARA | Section 2 위협 분석 |
| 9 (사이버보안 개념) | 보안 목표/요구사항 도출 | Section 3~7 설계 |
| 10 (제품 개발) | 보안 기능 구현 | Section 9 구현 모듈 |
| 11 (사이버보안 검증) | 테스트/침투 테스트 | Section 10 테스트 |
| 12 (생산) | 보안 프로비저닝 | Section 7 키 관리 |
| 13 (운영/유지보수) | 모니터링, 업데이트 | Section 5 IDS, Section 6 OTA |
| 14 (폐기) | 키/데이터 삭제 | Section 7.1 폐기 |

### 11.2 UNECE R155 Annex 5 위협 대응

| R155 위협 카테고리 | 위협 | 본 설계 대응 |
|-------------------|------|-------------|
| 차량 통신 채널 위협 | 메시지 스푸핑 | TLS + SecOC + ACL |
| 차량 통신 채널 위협 | 중간자 공격 | mTLS 상호 인증 |
| 차량 업데이트 위협 | 악성 업데이트 | Secure Boot + OTA 서명 |
| 데이터/코드 위협 | 무단 접근 | ACL + 역할 기반 접근 제어 |
| 기타 취약점 | 서비스 거부 | Rate Limiting + IDS |

---

## 12. 구현 로드맵

### Phase 1: 기본 보안 (즉시)

```
├── Zenoh TLS/mTLS 활성화
│   ├── 자체 서명 CA 및 인증서 생성 스크립트
│   ├── zenohd TLS 설정 (master_config_tls.json5)
│   └── zenoh-pico TLS 빌드 및 연결 테스트
├── 기본 ACL 설정
│   └── 노드별 key expression 접근 제한
└── 보안 로그 기초
    └── 인증 실패/ACL 위반 로그
```

### Phase 2: 메시지 인증 (중기)

```
├── SecOC 모듈 구현
│   ├── HMAC-SHA256 메시지 인증
│   ├── Freshness Value 리플레이 방지
│   └── 키 분배 메커니즘
├── IDS 엔진 구현
│   ├── Rate Limiting
│   ├── Rule-Based 감지
│   └── 경고 관리
└── 보안 이벤트 로그 (체인 해시)
```

### Phase 3: 양산 수준 (장기)

```
├── HSM/TPM 통합
├── PTP 시간 동기화
├── Secure Boot Chain
├── OTA 서명 검증
├── 침투 테스트 (전문 업체)
└── ISO/SAE 21434 인증 문서화
```

---

## 13. 참고 자료

| 표준/문서 | 범위 |
|----------|------|
| ISO/SAE 21434:2021 | 자동차 사이버보안 엔지니어링 |
| UNECE R155 (WP.29) | 사이버보안 형식 승인 규정 |
| UNECE R156 (WP.29) | 소프트웨어 업데이트 관리 규정 |
| AUTOSAR SecOC | Secure Onboard Communication 사양 |
| AUTOSAR IdsM | 침입 탐지 시스템 관리자 사양 |
| NIST SP 800-57 | 키 관리 권장사항 |
| SAE J3061 | 사이버 물리 차량 시스템 사이버보안 가이드북 |
| Zenoh Security Documentation | Zenoh TLS/ACL 설정 가이드 |
