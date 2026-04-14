# 통합 요구사항 추적 매트릭스 (Unified Requirements Traceability Matrix)

## 문서 정보

| 항목 | 내용 |
|------|------|
| 프로젝트명 | Zenoh-10BASE-T1S Automotive Slave Node (SAM E70) |
| 문서 버전 | v1.0.0 |
| 작성일 | 2026-04-14 |
| 상태 | Release |
| 관련 표준 | ISO 26262:2018, ISO/SAE 21434:2021, AUTOSAR E2E/SecOC |
| 관련 문서 | safety_case.md, functional_safety.md, cybersecurity.md |
| 총 추적 항목 | 30행 |
| 총 테스트 수 | 52개 (3개 파일) |

---

## 1. 개요

### 1.1 목적

본 문서는 SAM E70 MCU 기반 Zenoh 10BASE-T1S 슬레이브 노드의 모든 안전/보안 요구사항에 대한 **양방향 추적성(Bidirectional Traceability)**을 제공한다.

- **정방향 추적(Forward Traceability)**: 위험(Hazard/Threat) → 안전 목표(Safety Goal) → 요구사항(Requirement) → 설계 모듈(Design Module) → 테스트(Test)
- **역방향 추적(Backward Traceability)**: 테스트(Test) → 요구사항(Requirement) → 위험(Hazard/Threat)

### 1.2 용어 정의

| 접두어 | 의미 | 출처 |
|--------|------|------|
| HAZ-xxx | 위험 시나리오 (Hazard) | ISO 26262 HARA |
| THR-xxx | 사이버 위협 (Threat) | ISO/SAE 21434 TARA |
| SG-xxx | 안전 목표 (Safety Goal) | ISO 26262 Part 3 |
| FSR-xxx | 기능안전 요구사항 (Functional Safety Requirement) | ISO 26262 Part 4 |
| CSR-xxx | 사이버보안 요구사항 (Cybersecurity Requirement) | ISO/SAE 21434 |
| NFR-xxx | 비기능 요구사항 (Non-Functional Requirement) | PRD |

### 1.3 테스트 파일 요약

| 파일 | 경로 | 테스트 수 | 범위 |
|------|------|----------|------|
| test_mcu_bus.py | `tests/test_mcu_bus.py` | 21 | 물리층, Zenoh 전송, 양방향 제어, 성능, 신뢰성 |
| test_mcu_safety_security.py | `tests/test_mcu_safety_security.py` | 17 | E2E Protection, SecOC, Safety FSM, 보안 성능 |
| test_mcu_advanced.py | `tests/test_mcu_advanced.py` | 14 | 퍼징, 침투 테스트, 장애 캐스케이드 |

---

## 2. 정방향 추적 매트릭스 (Forward Traceability)

### 위험/위협 → 안전 목표 → 요구사항 → 설계 모듈 → 테스트

| # | 위험/위협 ID | 위험/위협 설명 | 안전 목표 | 요구사항 ID | 요구사항 설명 | 설계 모듈 | 테스트 ID | 테스트 파일 | 결과 |
|---|-------------|---------------|----------|------------|-------------|----------|----------|------------|------|
| 1 | HAZ-002 | 헤드라이트 오프 (야간 주행 중 조명 실패) | SG-001: 메시지 무결성 보장 | FSR-001 | 모든 메시지에 E2E 헤더(11B) 포함 | e2e_protection.c | test_steering_e2e_format | test_mcu_safety_security.py | PASS |
| 2 | HAZ-004 | 데이터 손실 (센서 메시지 누락) | SG-002: 메시지 연속성 보장 | FSR-002 | Sequence Counter 연속성 검증 | e2e_protection.c | test_steering_e2e_sequence | test_mcu_safety_security.py | PASS |
| 3 | HAZ-007 | 통신 단절 (MCU-마스터 연결 끊김) | SG-003: 장애 시 안전 상태 전이 | FSR-003 | Watchdog으로 SW hang 감지 및 리셋 | watchdog.c | test_continuous_30s | test_mcu_bus.py | PASS |
| 4 | HAZ-009 | CRC 미감지 (비트 오류 통과) | SG-004: 데이터 오류 감지 | FSR-004 | CRC-32 무결성 검증 | e2e_protection.c | test_steering_crc_integrity | test_mcu_safety_security.py | PASS |
| 5 | HAZ-010 | 보안 위반 (무단 액추에이터 제어) | SG-005: 무단 접근 방지 | CSR-001 | SecOC HMAC-SHA256 인증 | secoc.c | test_steering_secoc_mac | test_mcu_safety_security.py | PASS |
| 6 | THR-001 | 스푸핑 (위조 메시지 주입) | SG-005: 무단 접근 방지 | CSR-002 | 잘못된 키 메시지 거부 | secoc.c | test_wrong_key_rejected | test_mcu_advanced.py | PASS |
| 7 | THR-005 | DoS 공격 (메시지 폭주) | SG-006: 서비스 가용성 보장 | CSR-003 | IDS Rate Limiter 동작 | ids_engine.c | test_message_flood_resilience | test_mcu_advanced.py | PASS |
| 8 | THR-003 | 리플레이 공격 (과거 메시지 재전송) | SG-005: 무단 접근 방지 | CSR-004 | SecOC Freshness 단조 증가 검증 | secoc.c | test_secoc_freshness_increment | test_mcu_safety_security.py | PASS |
| 9 | HAZ-002 | 헤드라이트 오프 (장애 후 조명 명령 불가) | SG-001: 메시지 무결성 보장 | FSR-005 | E2E 보호 하에서도 액추에이터 명령 전달 | e2e_protection.c | test_headlight_e2e_command | test_mcu_safety_security.py | PASS |
| 10 | HAZ-001 | Safety FSM 미전이 (장애 미감지) | SG-003: 장애 시 안전 상태 전이 | FSR-006 | 정상 운영 시 safety=0(NORMAL) 유지 | safety_manager.c | test_normal_state_during_operation | test_mcu_safety_security.py | PASS |
| 11 | HAZ-001 | Safety FSM 미전이 (장애 미감지) | SG-003: 장애 시 안전 상태 전이 | FSR-007 | MAC 오류 시 DEGRADED 전이 | safety_manager.c | test_degraded_after_bad_mac | test_mcu_safety_security.py | PASS |
| 12 | HAZ-003 | DTC 미기록 (장애 이력 유실) | SG-007: 진단 정보 보존 | FSR-008 | 장애 발생 시 DTC 카운터 증가 | dtc_manager.c | test_dtc_recorded_after_faults | test_mcu_advanced.py | PASS |
| 13 | HAZ-005 | 메시지 순서 혼동 (액추에이터 오동작) | SG-002: 메시지 연속성 보장 | FSR-009 | JSON 시퀀스 필드 단조 증가 | e2e_protection.c | test_steering_sequence_increment | test_mcu_bus.py | PASS |
| 14 | HAZ-006 | 데이터 범위 초과 (센서 이상값) | SG-004: 데이터 오류 감지 | FSR-010 | 센서 값 범위 검증 (x,y: 0~4095) | flow_monitor.c | test_message_integrity | test_mcu_bus.py | PASS |
| 15 | THR-002 | 데이터 위조 (Data ID 스푸핑) | SG-005: 무단 접근 방지 | CSR-005 | Data ID 불일치 메시지 거부 | secoc.c | test_spoofed_data_id | test_mcu_advanced.py | PASS |
| 16 | THR-004 | 평문 주입 (E2E/SecOC 우회) | SG-005: 무단 접근 방지 | CSR-006 | E2E/SecOC 없는 메시지 거부 | secoc.c | test_plain_json_rejected | test_mcu_advanced.py | PASS |
| 17 | THR-006 | 퍼징 공격 (랜덤 데이터 주입) | SG-006: 서비스 가용성 보장 | CSR-007 | 랜덤 바이트 입력에 대한 견고성 | ids_engine.c | test_random_bytes | test_mcu_advanced.py | PASS |
| 18 | THR-006 | 퍼징 공격 (빈 페이로드) | SG-006: 서비스 가용성 보장 | CSR-007 | 빈 페이로드 입력에 대한 견고성 | ids_engine.c | test_empty_payload | test_mcu_advanced.py | PASS |
| 19 | THR-006 | 퍼징 공격 (과대 페이로드) | SG-006: 서비스 가용성 보장 | CSR-007 | 4KB 과대 페이로드에 대한 견고성 | ids_engine.c | test_oversized_payload | test_mcu_advanced.py | PASS |
| 20 | THR-006 | 퍼징 공격 (널 바이트) | SG-006: 서비스 가용성 보장 | CSR-007 | 널 바이트 입력에 대한 견고성 | ids_engine.c | test_null_bytes | test_mcu_advanced.py | PASS |
| 21 | THR-006 | 퍼징 공격 (E2E 헤더 손상) | SG-006: 서비스 가용성 보장 | CSR-008 | 손상된 E2E 헤더에 대한 견고성 | e2e_protection.c | test_corrupted_e2e_header | test_mcu_advanced.py | PASS |
| 22 | THR-006 | 퍼징 공격 (비정상 JSON) | SG-006: 서비스 가용성 보장 | CSR-008 | 유효 E2E 내 비정상 JSON 대한 견고성 | e2e_protection.c | test_valid_e2e_wrong_json | test_mcu_advanced.py | PASS |
| 23 | HAZ-008 | 키 만료 (인증 불가) | SG-005: 무단 접근 방지 | CSR-009 | key_epoch 필드 유지 (epoch >= 1) | key_manager.c | test_key_epoch_present | test_mcu_advanced.py | PASS |
| 24 | HAZ-001 | 연속 장애 시 안전 미확보 | SG-003: 장애 시 안전 상태 전이 | FSR-011 | 복수 MAC 오류 시 DEGRADED 이상 전이 | safety_manager.c | test_multiple_bad_mac_degraded | test_mcu_advanced.py | PASS |
| 25 | HAZ-011 | 장애 후 E2E/SecOC 무효화 | SG-001: 메시지 무결성 보장 | FSR-012 | 장애 상태에서도 E2E+SecOC 유지 | e2e_protection.c, secoc.c | test_e2e_secoc_still_valid_after_faults | test_mcu_advanced.py | PASS |
| 26 | HAZ-007 | 통신 단절 후 미복구 | SG-003: 장애 시 안전 상태 전이 | FSR-013 | zenohd 재시작 후 MCU 자동 재접속 | zenoh-pico (TCP) | test_reconnect_after_zenohd_restart | test_mcu_bus.py | PASS |
| 27 | HAZ-012 | 성능 저하 (지연 시간 초과) | SG-008: 실시간성 보장 | NFR-001 | 메시지 지연 < 15 ms (PRD) | zenoh-pico, LAN8670 PHY | test_latency_under_15ms | test_mcu_bus.py | PASS |
| 28 | HAZ-012 | 성능 저하 (E2E+SecOC 오버헤드) | SG-008: 실시간성 보장 | NFR-001 | E2E+SecOC 상태에서도 지연 < 15 ms | e2e_protection.c, secoc.c | test_e2e_secoc_latency | test_mcu_safety_security.py | PASS |
| 29 | HAZ-004 | 데이터 손실 (E2E+SecOC 환경) | SG-002: 메시지 연속성 보장 | FSR-014 | E2E+SecOC 30초 연속: CRC/MAC 100%, 손실 < 1% | e2e_protection.c, secoc.c | test_e2e_continuous_30s | test_mcu_safety_security.py | PASS |
| 30 | HAZ-002 | 양방향 통신 장애 | SG-001: 메시지 무결성 보장 | FSR-015 | 빠른 액추에이터 연속 명령 중에도 스티어링 유지 | zenoh-pico (TCP) | test_bidirectional_simultaneous | test_mcu_bus.py | PASS |

---

## 3. 역방향 추적 매트릭스 (Backward Traceability)

### 테스트 → 요구사항 → 위험/위협

#### 3.1 test_mcu_bus.py (21개 테스트)

| # | 테스트 ID | 테스트 클래스 | 요구사항 | 위험/위협 |
|---|----------|-------------|---------|----------|
| 1 | test_eth1_link_up | TestPhysicalLayer | NFR-003 (물리 링크) | HAZ-007 (통신 단절) |
| 2 | test_mcu_ping | TestPhysicalLayer | NFR-004 (IP 연결성) | HAZ-007 (통신 단절) |
| 3 | test_mcu_ping_latency | TestPhysicalLayer | NFR-001 (지연 < 15 ms) | HAZ-012 (성능 저하) |
| 4 | test_zenohd_running | TestPhysicalLayer | NFR-005 (라우터 가용성) | HAZ-007 (통신 단절) |
| 5 | test_master_session_open | TestZenohTransport | NFR-006 (세션 수립) | HAZ-007 (통신 단절) |
| 6 | test_mcu_steering_publish | TestZenohTransport | FSR-001 (메시지 전달) | HAZ-004 (데이터 손실) |
| 7 | test_steering_json_format | TestZenohTransport | FSR-010 (데이터 포맷) | HAZ-006 (데이터 범위 초과) |
| 8 | test_steering_sequence_increment | TestZenohTransport | FSR-009 (시퀀스 증가) | HAZ-005 (순서 혼동) |
| 9 | test_headlight_on | TestBidirectionalControl | FSR-015 (양방향 제어) | HAZ-002 (헤드라이트 오프) |
| 10 | test_headlight_off | TestBidirectionalControl | FSR-015 (양방향 제어) | HAZ-002 (헤드라이트 오프) |
| 11 | test_hazard_on | TestBidirectionalControl | FSR-015 (양방향 제어) | HAZ-002 (액추에이터 오동작) |
| 12 | test_hazard_off | TestBidirectionalControl | FSR-015 (양방향 제어) | HAZ-002 (액추에이터 오동작) |
| 13 | test_bidirectional_simultaneous | TestBidirectionalControl | FSR-015 (동시 양방향) | HAZ-002 (양방향 장애) |
| 14 | test_steering_publish_rate | TestPerformance | NFR-002 (발행률 ~10 msg/s) | HAZ-012 (성능 저하) |
| 15 | test_zenoh_message_latency | TestPerformance | NFR-001 (전달 일관성) | HAZ-012 (성능 저하) |
| 16 | test_latency_under_15ms | TestPerformance | NFR-001 (지연 < 15 ms) | HAZ-012 (성능 저하) |
| 17 | test_actuator_response_time | TestPerformance | NFR-007 (응답 시간) | HAZ-012 (성능 저하) |
| 18 | test_continuous_30s | TestReliability | FSR-003, NFR-008 | HAZ-007 (통신 단절) |
| 19 | test_message_integrity | TestReliability | FSR-010 (값 범위) | HAZ-006 (데이터 범위 초과) |
| 20 | test_reconnect_after_zenohd_restart | TestReliability | FSR-013 (자동 재접속) | HAZ-007 (통신 단절) |
| 21 | test_angle_range_consistency | TestReliability | FSR-010 (계산 정확성) | HAZ-006 (데이터 범위 초과) |

#### 3.2 test_mcu_safety_security.py (17개 테스트)

| # | 테스트 ID | 테스트 클래스 | 요구사항 | 위험/위협 |
|---|----------|-------------|---------|----------|
| 1 | test_steering_e2e_format | TestE2EProtection | FSR-001 (E2E 헤더) | HAZ-002 (헤드라이트 오프) |
| 2 | test_steering_e2e_sequence | TestE2EProtection | FSR-002 (시퀀스 검증) | HAZ-004 (데이터 손실) |
| 3 | test_steering_crc_integrity | TestE2EProtection | FSR-004 (CRC-32) | HAZ-009 (CRC 미감지) |
| 4 | test_e2e_data_id_correct | TestE2EProtection | FSR-001 (Data ID) | HAZ-002 (메시지 혼동) |
| 5 | test_headlight_e2e_command | TestE2EProtection | FSR-005 (E2E 명령) | HAZ-002 (헤드라이트 오프) |
| 6 | test_steering_secoc_mac | TestSecOC | CSR-001 (MAC 검증) | HAZ-010 (보안 위반) |
| 7 | test_secoc_freshness_increment | TestSecOC | CSR-004 (Freshness) | THR-003 (리플레이) |
| 8 | test_secoc_message_size | TestSecOC | CSR-001 (SecOC 포맷) | HAZ-010 (보안 위반) |
| 9 | test_mac_verification_consistent | TestSecOC | CSR-001 (MAC 일관성) | HAZ-010 (보안 위반) |
| 10 | test_normal_state_during_operation | TestSafetyFSM | FSR-006 (정상 상태) | HAZ-001 (FSM 미전이) |
| 11 | test_steering_includes_safety_field | TestSafetyFSM | FSR-006 (safety 필드) | HAZ-001 (FSM 미전이) |
| 12 | test_payload_has_all_fields | TestSafetyFSM | FSR-010 (완전성) | HAZ-006 (필드 누락) |
| 13 | test_e2e_secoc_publish_rate | TestPerformanceSecure | NFR-002 (암호 성능) | HAZ-012 (성능 저하) |
| 14 | test_e2e_secoc_latency | TestPerformanceSecure | NFR-001 (암호 지연) | HAZ-012 (성능 저하) |
| 15 | test_e2e_continuous_30s | TestPerformanceSecure | FSR-014 (30초 연속) | HAZ-004 (데이터 손실) |
| 16 | test_reject_bad_mac | TestZFaultInjection | CSR-001 (MAC 거부) | THR-001 (스푸핑) |
| 17 | test_degraded_after_bad_mac | TestZFaultInjection | FSR-007 (DEGRADED 전이) | HAZ-001 (FSM 미전이) |

#### 3.3 test_mcu_advanced.py (14개 테스트)

| # | 테스트 ID | 테스트 클래스 | 요구사항 | 위험/위협 |
|---|----------|-------------|---------|----------|
| 1 | test_random_bytes | TestFuzzing | CSR-007 (입력 견고성) | THR-006 (퍼징) |
| 2 | test_empty_payload | TestFuzzing | CSR-007 (입력 견고성) | THR-006 (퍼징) |
| 3 | test_oversized_payload | TestFuzzing | CSR-007 (입력 견고성) | THR-006 (퍼징) |
| 4 | test_null_bytes | TestFuzzing | CSR-007 (입력 견고성) | THR-006 (퍼징) |
| 5 | test_corrupted_e2e_header | TestFuzzing | CSR-008 (E2E 견고성) | THR-006 (퍼징) |
| 6 | test_valid_e2e_wrong_json | TestFuzzing | CSR-008 (JSON 견고성) | THR-006 (퍼징) |
| 7 | test_plain_json_rejected | TestPenetration | CSR-006 (평문 거부) | THR-004 (평문 주입) |
| 8 | test_wrong_key_rejected | TestPenetration | CSR-002 (키 검증) | THR-001 (스푸핑) |
| 9 | test_spoofed_data_id | TestPenetration | CSR-005 (ID 검증) | THR-002 (위조) |
| 10 | test_message_flood_resilience | TestPenetration | CSR-003 (DoS 내성) | THR-005 (DoS) |
| 11 | test_multiple_bad_mac_degraded | TestZFaultCascade | FSR-011 (다중 장애) | HAZ-001 (연속 장애) |
| 12 | test_dtc_recorded_after_faults | TestZFaultCascade | FSR-008 (DTC 기록) | HAZ-003 (DTC 미기록) |
| 13 | test_key_epoch_present | TestZFaultCascade | CSR-009 (키 epoch) | HAZ-008 (키 만료) |
| 14 | test_e2e_secoc_still_valid_after_faults | TestZFaultCascade | FSR-012 (장애 후 무결성) | HAZ-011 (장애 후 무효화) |

---

## 4. 커버리지 분석

### 4.1 요구사항 커버리지

#### 기능안전 요구사항 (FSR)

| 요구사항 ID | 요구사항 설명 | 커버 테스트 수 | 테스트 파일 | 상태 |
|-------------|-------------|--------------|------------|------|
| FSR-001 | E2E 헤더 포함 (11B) | 3 | test_mcu_safety_security.py, test_mcu_bus.py | 커버됨 |
| FSR-002 | Sequence Counter 연속성 | 1 | test_mcu_safety_security.py | 커버됨 |
| FSR-003 | Watchdog으로 hang 감지/리셋 | 1 | test_mcu_bus.py | 커버됨 |
| FSR-004 | CRC-32 무결성 검증 | 1 | test_mcu_safety_security.py | 커버됨 |
| FSR-005 | E2E 보호 하 액추에이터 명령 전달 | 1 | test_mcu_safety_security.py | 커버됨 |
| FSR-006 | 정상 운영 시 safety=0 유지 | 2 | test_mcu_safety_security.py | 커버됨 |
| FSR-007 | MAC 오류 시 DEGRADED 전이 | 1 | test_mcu_safety_security.py | 커버됨 |
| FSR-008 | DTC 카운터 증가 | 1 | test_mcu_advanced.py | 커버됨 |
| FSR-009 | JSON 시퀀스 단조 증가 | 1 | test_mcu_bus.py | 커버됨 |
| FSR-010 | 센서 값 범위 검증 | 3 | test_mcu_bus.py, test_mcu_safety_security.py | 커버됨 |
| FSR-011 | 복수 MAC 오류 시 DEGRADED+ | 1 | test_mcu_advanced.py | 커버됨 |
| FSR-012 | 장애 후 E2E+SecOC 유지 | 1 | test_mcu_advanced.py | 커버됨 |
| FSR-013 | zenohd 재시작 후 자동 재접속 | 1 | test_mcu_bus.py | 커버됨 |
| FSR-014 | 30초 연속 CRC/MAC 100% | 1 | test_mcu_safety_security.py | 커버됨 |
| FSR-015 | 양방향 동시 통신 유지 | 5 | test_mcu_bus.py | 커버됨 |

**FSR 커버리지: 15/15 (100%)**

#### 사이버보안 요구사항 (CSR)

| 요구사항 ID | 요구사항 설명 | 커버 테스트 수 | 테스트 파일 | 상태 |
|-------------|-------------|--------------|------------|------|
| CSR-001 | SecOC HMAC-SHA256 인증 | 4 | test_mcu_safety_security.py | 커버됨 |
| CSR-002 | 잘못된 키 메시지 거부 | 1 | test_mcu_advanced.py | 커버됨 |
| CSR-003 | IDS Rate Limiter (DoS 내성) | 1 | test_mcu_advanced.py | 커버됨 |
| CSR-004 | Freshness Counter 단조 증가 | 1 | test_mcu_safety_security.py | 커버됨 |
| CSR-005 | Data ID 불일치 거부 | 1 | test_mcu_advanced.py | 커버됨 |
| CSR-006 | E2E/SecOC 미포함 메시지 거부 | 1 | test_mcu_advanced.py | 커버됨 |
| CSR-007 | 퍼징 입력 견고성 | 4 | test_mcu_advanced.py | 커버됨 |
| CSR-008 | 손상 E2E/비정상 JSON 견고성 | 2 | test_mcu_advanced.py | 커버됨 |
| CSR-009 | key_epoch 유지 (epoch >= 1) | 1 | test_mcu_advanced.py | 커버됨 |

**CSR 커버리지: 9/9 (100%)**

#### 비기능 요구사항 (NFR)

| 요구사항 ID | 요구사항 설명 | 커버 테스트 수 | 테스트 파일 | 상태 |
|-------------|-------------|--------------|------------|------|
| NFR-001 | 메시지 지연 < 15 ms | 3 | test_mcu_bus.py, test_mcu_safety_security.py | 커버됨 |
| NFR-002 | 발행률 ~10 msg/s | 2 | test_mcu_bus.py, test_mcu_safety_security.py | 커버됨 |
| NFR-003 | 물리 링크 UP (10 Mbps) | 1 | test_mcu_bus.py | 커버됨 |
| NFR-004 | IP 연결성 (ping) | 1 | test_mcu_bus.py | 커버됨 |
| NFR-005 | zenohd 라우터 가용성 | 1 | test_mcu_bus.py | 커버됨 |
| NFR-006 | Zenoh 세션 수립 | 1 | test_mcu_bus.py | 커버됨 |
| NFR-007 | 액추에이터 응답 시간 | 1 | test_mcu_bus.py | 커버됨 |
| NFR-008 | 30초 연속 손실 < 1% | 1 | test_mcu_bus.py | 커버됨 |

**NFR 커버리지: 8/8 (100%)**

---

### 4.2 위험/위협 커버리지

#### 위험 시나리오 (HAZ) 커버리지

| 위험 ID | 위험 설명 | 커버 테스트 수 | 상태 |
|---------|----------|--------------|------|
| HAZ-001 | Safety FSM 미전이 | 4 | 커버됨 |
| HAZ-002 | 헤드라이트 오프/액추에이터 오동작 | 7 | 커버됨 |
| HAZ-003 | DTC 미기록 | 1 | 커버됨 |
| HAZ-004 | 데이터 손실 | 3 | 커버됨 |
| HAZ-005 | 메시지 순서 혼동 | 1 | 커버됨 |
| HAZ-006 | 데이터 범위 초과 | 4 | 커버됨 |
| HAZ-007 | 통신 단절 | 5 | 커버됨 |
| HAZ-008 | 키 만료 | 1 | 커버됨 |
| HAZ-009 | CRC 미감지 | 1 | 커버됨 |
| HAZ-010 | 보안 위반 | 3 | 커버됨 |
| HAZ-011 | 장애 후 E2E/SecOC 무효화 | 1 | 커버됨 |
| HAZ-012 | 성능 저하 | 5 | 커버됨 |

**HAZ 커버리지: 12/12 (100%)**

#### 사이버 위협 (THR) 커버리지

| 위협 ID | 위협 설명 | STRIDE 분류 | 커버 테스트 수 | 상태 |
|---------|----------|------------|--------------|------|
| THR-001 | 스푸핑 (위조 메시지) | Spoofing | 2 | 커버됨 |
| THR-002 | 데이터 위조 (Data ID) | Tampering | 1 | 커버됨 |
| THR-003 | 리플레이 공격 | Spoofing | 1 | 커버됨 |
| THR-004 | 평문 주입 (우회) | Elevation of Privilege | 1 | 커버됨 |
| THR-005 | DoS 공격 | Denial of Service | 1 | 커버됨 |
| THR-006 | 퍼징 공격 | Tampering | 6 | 커버됨 |

**THR 커버리지: 6/6 (100%)**

---

### 4.3 설계 모듈 커버리지

| 설계 모듈 | 역할 | 관련 요구사항 | 커버 테스트 수 | 상태 |
|----------|------|-------------|--------------|------|
| e2e_protection.c | E2E 헤더 생성/검증 (CRC-32, Seq Counter) | FSR-001, FSR-002, FSR-004, FSR-005, FSR-009, FSR-012, FSR-014, CSR-008 | 10 | 커버됨 |
| secoc.c | SecOC HMAC-SHA256 MAC 생성/검증 | CSR-001, CSR-002, CSR-004, CSR-005, CSR-006, FSR-012 | 9 | 커버됨 |
| safety_manager.c | Safety FSM 상태 관리 (NORMAL→DEGRADED→SAFE→FAIL) | FSR-006, FSR-007, FSR-011 | 4 | 커버됨 |
| watchdog.c | HW Watchdog Timer 관리 (~2s timeout) | FSR-003 | 1 | 커버됨 |
| ids_engine.c | IDS Rate Limiter, 이상 탐지 | CSR-003, CSR-007 | 5 | 커버됨 |
| dtc_manager.c | 진단 고장 코드 기록/관리 | FSR-008 | 1 | 커버됨 |
| flow_monitor.c | 메시지 흐름 모니터링, 값 범위 검증 | FSR-010 | 3 | 커버됨 |
| key_manager.c | SecOC 키 파생/갱신 (HMAC-SHA256 epoch) | CSR-009 | 1 | 커버됨 |

**모듈 커버리지: 8/8 (100%)**

---

### 4.4 커버리지 종합

```
┌────────────────────────────────────────────────────────┐
│              커버리지 종합 요약                          │
├────────────────────────────────────────────────────────┤
│                                                        │
│  요구사항 커버리지                                      │
│  ├── FSR (기능안전)      : 15/15 (100%) ████████████  │
│  ├── CSR (사이버보안)    :  9/9  (100%) ████████████  │
│  └── NFR (비기능)        :  8/8  (100%) ████████████  │
│                                                        │
│  위험/위협 커버리지                                     │
│  ├── HAZ (위험 시나리오) : 12/12 (100%) ████████████  │
│  └── THR (사이버 위협)   :  6/6  (100%) ████████████  │
│                                                        │
│  설계 모듈 커버리지      :  8/8  (100%) ████████████  │
│                                                        │
│  테스트 파일                                           │
│  ├── test_mcu_bus.py             : 21 tests  PASS     │
│  ├── test_mcu_safety_security.py : 17 tests  PASS     │
│  └── test_mcu_advanced.py       : 14 tests  PASS     │
│  ──────────────────────────────────────────────        │
│  총합                            : 52 tests  PASS     │
│                                                        │
│  전체 커버리지: 100%                                    │
│  미커버 항목: 없음                                      │
│                                                        │
└────────────────────────────────────────────────────────┘
```

---

## 5. 추적성 갭 분석

### 5.1 식별된 갭

| # | 갭 유형 | 설명 | 심각도 | 경감 방안 | 상태 |
|---|--------|------|--------|----------|------|
| 1 | 없음 | 모든 요구사항이 테스트에 의해 커버됨 | - | - | 해당 없음 |

### 5.2 양산 전환 시 추가 추적 항목

다음 항목은 현재 프로토타입 단계에서는 범위 외이나, 양산 전환 시 추적 매트릭스에 추가되어야 한다.

| # | 요구사항 유형 | 설명 | 설계 모듈 | 현재 상태 |
|---|-------------|------|----------|----------|
| 1 | FSR-016 | HSM 기반 키 저장 | key_manager.c + HSM 드라이버 | 미구현 (SW 키 저장) |
| 2 | FSR-017 | Secure Boot 펌웨어 서명 검증 | bootloader.c | 미구현 |
| 3 | CSR-010 | mTLS 상호 인증 | zenoh-pico TLS 설정 | 미구현 (TLS 단방향) |
| 4 | FSR-018 | FMEDA 정량적 고장률 분석 | 전체 시스템 | 미수행 |
| 5 | CSR-011 | OTA 서명 검증 업데이트 | ota_manager.c | 미구현 |

---

## 6. 추적성 다이어그램

```
위험/위협                안전 목표              요구사항              설계 모듈              테스트
─────────              ─────────              ─────────              ─────────              ──────

HAZ-001 ──────────┬──► SG-003 ──────────┬──► FSR-006 ──────────► safety_manager.c ──┬──► test_normal_state_during_operation
                  │                     ├──► FSR-007 ──────────► safety_manager.c ──┼──► test_degraded_after_bad_mac
                  │                     └──► FSR-011 ──────────► safety_manager.c ──┼──► test_multiple_bad_mac_degraded
                  │                                                                 └──► test_steering_includes_safety_field
                  │
HAZ-002 ──────────┼──► SG-001 ──────────┬──► FSR-001 ──────────► e2e_protection.c ─┬──► test_steering_e2e_format
                  │                     ├──► FSR-005 ──────────► e2e_protection.c ─┼──► test_headlight_e2e_command
                  │                     └──► FSR-015 ──────────► zenoh-pico ────────┼──► test_headlight_on/off
                  │                                                                 ├──► test_hazard_on/off
                  │                                                                 └──► test_bidirectional_simultaneous
                  │
HAZ-004 ──────────┼──► SG-002 ──────────┬──► FSR-002 ──────────► e2e_protection.c ─┬──► test_steering_e2e_sequence
                  │                     ├──► FSR-009 ──────────► e2e_protection.c ─┼──► test_steering_sequence_increment
                  │                     └──► FSR-014 ──────────► e2e+secoc ─────────┴──► test_e2e_continuous_30s
                  │
HAZ-007 ──────────┼──► SG-003 ──────────┬──► FSR-003 ──────────► watchdog.c ───────┬──► test_continuous_30s
                  │                     └──► FSR-013 ──────────► zenoh-pico ────────┴──► test_reconnect_after_zenohd_restart
                  │
HAZ-009 ──────────┼──► SG-004 ──────────── ► FSR-004 ──────────► e2e_protection.c ────► test_steering_crc_integrity
                  │
HAZ-010 ──────────┼──► SG-005 ──────────── ► CSR-001 ──────────► secoc.c ──────────────► test_steering_secoc_mac
                  │
THR-001 ──────────┼──► SG-005 ──────────── ► CSR-002 ──────────► secoc.c ──────────────► test_wrong_key_rejected
                  │                                                                ────► test_reject_bad_mac
                  │
THR-003 ──────────┼──► SG-005 ──────────── ► CSR-004 ──────────► secoc.c ──────────────► test_secoc_freshness_increment
                  │
THR-005 ──────────┼──► SG-006 ──────────── ► CSR-003 ──────────► ids_engine.c ─────────► test_message_flood_resilience
                  │
THR-006 ──────────┴──► SG-006 ──────────┬─► CSR-007 ──────────► ids_engine.c ──────┬──► test_random_bytes
                                        │                                          ├──► test_empty_payload
                                        │                                          ├──► test_oversized_payload
                                        │                                          └──► test_null_bytes
                                        └─► CSR-008 ──────────► e2e_protection.c ──┬──► test_corrupted_e2e_header
                                                                                   └──► test_valid_e2e_wrong_json
```

---

## 7. 결론

본 추적 매트릭스는 SAM E70 Zenoh 10BASE-T1S 슬레이브 노드의 안전/보안 요구사항에 대한 완전한 양방향 추적성을 제공한다.

**요약**:

| 항목 | 수량 | 커버리지 |
|------|------|---------|
| 기능안전 요구사항 (FSR) | 15개 | 100% |
| 사이버보안 요구사항 (CSR) | 9개 | 100% |
| 비기능 요구사항 (NFR) | 8개 | 100% |
| 위험 시나리오 (HAZ) | 12개 | 100% |
| 사이버 위협 (THR) | 6개 | 100% |
| 설계 모듈 | 8개 | 100% |
| 테스트 | 52개 | 100% PASS |

**미커버 갭**: 없음

모든 식별된 위험 및 위협에 대해 요구사항이 할당되었고, 각 요구사항은 설계 모듈에 구현되었으며, 52개의 자동화 테스트에 의해 물리 버스(10BASE-T1S) 상에서 검증이 완료되었다.

---

**문서 이력**

| 버전 | 일자 | 작성자 | 변경 내용 |
|------|------|--------|----------|
| v1.0.0 | 2026-04-14 | Safety/Security Team | 초기 작성 — 30행 정방향 + 52개 역방향 추적 |
