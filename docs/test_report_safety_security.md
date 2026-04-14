# 기능안전 & 사이버보안 테스트 리포트

## 문서 정보

| 항목 | 내용 |
|------|------|
| 프로젝트명 | Zenoh-10BASE-T1S Automotive Master Controller Simulator |
| 문서 버전 | v2.0.0 |
| 작성일 | 2026-04-13 (v2.0 업데이트) |
| 테스트 실행 환경 | Raspberry Pi 5, Python 3.13.5, pytest 9.0.3 |
| 하드웨어 | EVB-LAN8670-USB x2, UTP cable, 10BASE-T1S PLCA |
| 관련 표준 | ISO 26262:2018 (Part 6), ISO/SAE 21434:2021 |
| 관련 문서 | functional_safety.md, cybersecurity.md |

---

## 1. 테스트 요약

| 구분 | 테스트 수 | PASS | FAIL | 비율 |
|------|----------|------|------|------|
| 단위 테스트 (Unit) | 61 | 61 | 0 | 100% |
| 기능안전 (ISO 26262) | 133 | 133 | 0 | 100% |
| 사이버보안 (ISO/SAE 21434) | 61 | 61 | 0 | 100% |
| 침투 테스트 (Penetration) | 6 | 6 | 0 | 100% |
| 시뮬레이션 테스트 (SW) | 61 | 61 | 0 | 100% |
| HW 버스 테스트 (10BASE-T1S) | 38 | 38 | 0 | 100% |
| 통합/회귀 (Integration) | 23 | 23 | 0 | 100% |
| **총계** | **383** | **383** | **0** | **100%** |

### 테스트 파일 목록 (27개)

| # | 파일 | 테스트 수 | 카테고리 |
|---|------|----------|---------|
| 1 | test_key_expressions.py | 18 | Unit |
| 2 | test_models.py | 14 | Unit |
| 3 | test_payloads.py | 12 | Unit |
| 4 | test_network_setup.py | 7 | Unit |
| 5 | test_scenario_runner.py | 10 | Unit |
| 6 | test_e2e_protection.py | 28 | Safety |
| 7 | test_safety_manager.py | 15 | Safety |
| 8 | test_e2e_supervisor.py | 13 | Safety |
| 9 | test_dtc_manager.py | 12 | Safety |
| 10 | test_flow_monitor.py | 9 | Safety |
| 11 | test_safety_foundation.py | 36 | Safety |
| 12 | test_self_test.py | 10 | Safety |
| 13 | test_safety_integration.py | 10 | Safety/Integration |
| 14 | test_secoc.py | 12 | Security |
| 15 | test_ids_engine.py | 13 | Security |
| 16 | test_acl_manager.py | 12 | Security |
| 17 | test_security_foundation.py | 24 | Security |
| 18 | test_security_integration.py | 11 | Security/Integration |
| 19 | test_penetration.py | 6 | Penetration |
| 20 | test_sim_safety.py | 22 | Simulation |
| 21 | test_sim_security.py | 15 | Simulation |
| 22 | test_sim_fault_injection.py | 13 | Simulation |
| 23 | test_sim_e2e_scenario.py | 11 | Simulation |
| 24 | test_hw_bypass.py | 15 | HW Bus |
| 25 | test_hw_safety_security.py | 17 | HW Bus (Safety+Security) |
| 26 | test_interop_hw.py | 6 | HW Bus (Python↔C) |
| 27 | test_integration_bypass.py | 12 | Integration (TCP loopback) |

---

## 2. 기능안전 테스트 상세 (ISO 26262)

### 2.1 E2E Protection (통신 무결성) — 28 테스트

| Spec ID | 테스트 | 모듈 | 결과 |
|---------|--------|------|------|
| FST-001 | CRC 정상 검증 | test_e2e_protection::TestE2ECRC::test_crc_valid_message | PASS |
| FST-002 | CRC 1-bit flip 감지 | test_e2e_protection::TestE2ECRC::test_crc_bit_flip_detected | PASS |
| — | CRC 결정론적 | test_e2e_protection::TestE2ECRC::test_crc_deterministic | PASS |
| — | 빈 페이로드 CRC | test_e2e_protection::TestE2ECRC::test_crc_empty_payload | PASS |
| — | Data ID별 CRC 차이 | test_e2e_protection::TestE2ECRC::test_crc_different_data_id | PASS |
| — | 헤더 크기 11바이트 | test_e2e_protection::TestE2EHeader::test_header_size_11_bytes | PASS |
| — | 헤더 라운드트립 | test_e2e_protection::TestE2EHeader::test_encode_decode_roundtrip | PASS |
| — | 짧은 데이터 ValueError | test_e2e_protection::TestE2EHeader::test_from_bytes_short_data_raises | PASS |
| — | 추가 바이트 무시 | test_e2e_protection::TestE2EHeader::test_from_bytes_extra_data_ignored | PASS |
| FST-007 | Data ID 불일치 거부 | test_e2e_protection::TestE2EHeader::test_data_id_mismatch_rejected | PASS |
| — | 카운터 초기값 0 | test_e2e_protection::TestSequenceCounter::test_counter_starts_at_zero | PASS |
| — | 카운터 증가 | test_e2e_protection::TestSequenceCounter::test_counter_increments | PASS |
| FST-008 | seq 65535→0 래핑 | test_e2e_protection::TestSequenceCounter::test_seq_wraps_at_65535 | PASS |
| — | alive 255→0 래핑 | test_e2e_protection::TestSequenceCounter::test_alive_wraps_at_255 | PASS |
| FST-003 | 순차 수신 OK | test_e2e_protection::TestSequenceChecker::test_sequential_ok | PASS |
| FST-004 | gap > max → ERROR | test_e2e_protection::TestSequenceChecker::test_gap_exceeded_error | PASS |
| FST-005 | delta=0 → REPEATED | test_e2e_protection::TestSequenceChecker::test_duplicate_detected | PASS |
| FST-008 | 래핑 후 정상 | test_e2e_protection::TestSequenceChecker::test_wrap_around_65535_to_0 | PASS |
| — | 허용 갭 내 OK_SOME_LOST | test_e2e_protection::TestSequenceChecker::test_gap_within_tolerance_ok_some_lost | PASS |
| — | ASIL-D gap=1 | test_e2e_protection::TestSequenceChecker::test_asil_d_gap_1 | PASS |
| — | 센서 키 해석 | test_e2e_protection::TestDataIDMapping::test_resolve_sensor_keys | PASS |
| — | 액추에이터 키 해석 | test_e2e_protection::TestDataIDMapping::test_resolve_actuator_keys | PASS |
| — | 상태 키 해석 | test_e2e_protection::TestDataIDMapping::test_resolve_status_key | PASS |
| — | 마스터 하트비트 해석 | test_e2e_protection::TestDataIDMapping::test_resolve_master_heartbeat | PASS |
| — | 미등록 키 ValueError | test_e2e_protection::TestDataIDMapping::test_resolve_unknown_key_raises | PASS |
| — | 인코드→디코드→검증 | test_e2e_protection::TestE2EEncodeDecode::test_encode_decode_verify | PASS |
| — | 변조 페이로드 검증 실패 | test_e2e_protection::TestE2EEncodeDecode::test_corrupted_payload_fails_verify | PASS |
| — | 연속 인코딩 seq 증가 | test_e2e_protection::TestE2EEncodeDecode::test_sequential_encoding_increments_seq | PASS |

### 2.2 Safety State Machine (안전 상태 관리) — 15 테스트

| Spec ID | 테스트 | 결과 |
|---------|--------|------|
| — | 초기 상태 NORMAL | PASS |
| FST-010 | NORMAL→DEGRADED (노드 장애) | PASS |
| FST-011 | DEGRADED→NORMAL (복구) | PASS |
| FST-012 | DEGRADED→SAFE_STATE (≥50% 오프라인) | PASS |
| FST-013 | SAFE_STATE 액추에이터 안전 동작 | PASS |
| FST-014 | FAIL_SILENT 출력 차단 | PASS |
| — | 단일 CRC 실패 시 NORMAL 유지 | PASS |
| — | 3회 연속 CRC → DEGRADED | PASS |
| — | 상태 변경 콜백 | PASS |
| — | FAIL_SILENT→NORMAL 리셋만 가능 | PASS |
| — | ASIL-D 타임아웃 → SAFE_STATE | PASS |
| — | 전이 시 Safety Log 기록 | PASS |
| — | 장애 시 DTC 저장 | PASS |
| — | PLCA beacon 소실 → DEGRADED | PASS |
| — | Watchdog 만료 → SAFE_STATE | PASS |

### 2.3 DTC Manager (진단 코드 관리) — 12 테스트

| Spec ID | 테스트 | 결과 |
|---------|--------|------|
| — | 첫 발생 → pending DTC | PASS |
| — | 2회 → confirmed DTC | PASS |
| — | 단일 DTC 삭제 | PASS |
| — | 전체 DTC 삭제 | PASS |
| — | ISO 14229 상태 바이트 비트 | PASS |
| — | 40 사이클 에이징 → confirmed 해제 | PASS |
| — | 재시작 후 영속성 | PASS |
| FIT-006 | 파일 미존재 시 새로 생성 | PASS |
| — | 최대 256개 DTC | PASS |
| — | 전체 DTC 조회 | PASS |
| — | freeze frame 저장 | PASS |
| — | 미존재 DTC 삭제 → false | PASS |

### 2.4 E2E Supervisor (E2E 감시) — 13 테스트

| Spec ID | 테스트 | 결과 |
|---------|--------|------|
| — | 유효 메시지 → VALID | PASS |
| — | N개 유효 후 VALID 도달 | PASS |
| — | CRC 실패 → INVALID | PASS |
| — | CRC 실패 → SafetyManager 통지 | PASS |
| — | Seq 오류 → SafetyManager 통지 | PASS |
| — | INIT→VALID 전이 | PASS |
| FST-006 | 데드라인 초과 → TIMEOUT | PASS |
| — | TIMEOUT 후 복구 → VALID | PASS |
| — | 3회 연속 실패 → ERROR | PASS |
| — | CRC 실패 시 DTC 0xC11029 | PASS |
| — | 타임아웃 시 DTC 0xC11231 | PASS |
| — | 채널별 독립 동작 | PASS |
| — | 채널 통계 조회 | PASS |

### 2.5 Flow Monitor (흐름 감시) — 9 테스트

| 테스트 | 결과 |
|--------|------|
| 정상 순서 통과 | PASS |
| 순서 오류 실패 | PASS |
| 누락 체크포인트 실패 | PASS |
| 추가 체크포인트 실패 | PASS |
| 사이클 후 리셋 | PASS |
| 에러 콜백 호출 | PASS |
| 에러 카운트 추적 | PASS |
| 커스텀 흐름 설정 | PASS |
| reset() 후 재시작 | PASS |

### 2.6 Safety Foundation (기반 타입 + 로그 + 워치독) — 36 테스트

| 영역 | 테스트 수 | 결과 |
|------|----------|------|
| SafetyState Enum | 2 | 2 PASS |
| FaultType Enum | 1 | 1 PASS |
| E2EStatus Enum | 1 | 1 PASS |
| ASILLevel Enum | 1 | 1 PASS |
| DATA_ID_MAP | 6 | 6 PASS |
| TIMEOUT_CONFIG | 2 | 2 PASS |
| SEQUENCE_GAP_LIMITS | 3 | 3 PASS |
| SAFE_ACTIONS | 3 | 3 PASS |
| SafetyEvent 데이터클래스 | 2 | 2 PASS |
| Safety Log (불변 로그) | 7 | 7 PASS |
| Watchdog Timer | 8 | 8 PASS |

### 2.7 Self-Test (시작 시 자체 점검) — 10 테스트

| Spec ID | 테스트 | 결과 |
|---------|--------|------|
| FST-015 | 전 항목 PASS → 전체 PASS | PASS |
| — | Critical 실패 → 전체 FAIL | PASS |
| — | Non-critical 실패 → 전체 PASS | PASS |
| — | CRC 엔진 점검 | PASS |
| — | E2E 카운터 초기화 점검 | PASS |
| — | FSM 초기 상태 점검 | PASS |
| — | Safety Log 쓰기 점검 | PASS |
| — | 타임스탬프 소스 점검 | PASS |
| — | 점검 결과 Safety Log 기록 | PASS |
| — | 10개 항목 결과 반환 | PASS |

### 2.8 Safety Integration (통합) — 10 테스트

| Spec ID | 테스트 | 결과 |
|---------|--------|------|
| — | E2E JSON 라운드트립 | PASS |
| — | E2E CBOR 라운드트립 | PASS |
| — | E2E CRC 불일치 감지 | PASS |
| — | 기존 encode/decode 호환성 | PASS |
| — | 시퀀스 카운터 증가 확인 | PASS |
| FIT-001 | 노드 오프라인 → DEGRADED + DTC | PASS |
| FIT-003 | 변조 페이로드 → E2E 거부 | PASS |
| — | 전체 Safety 스택 시작 | PASS |
| — | 다중 장애 에스컬레이션 | PASS |
| — | 복구 사이클 완료 | PASS |

---

## 3. 사이버보안 테스트 상세 (ISO/SAE 21434)

### 3.1 SecOC 메시지 인증 (HMAC + Freshness) — 12 테스트

| Spec ID | 테스트 | 결과 |
|---------|--------|------|
| — | Freshness 인코드/디코드 라운드트립 | PASS |
| — | Freshness 비교 연산자 | PASS |
| CST-004 | 유효 MAC 검증 성공 | PASS |
| CST-005 | 변조 MAC 거부 | PASS |
| — | 다른 키 → 다른 MAC | PASS |
| — | MAC 128비트(16바이트) 트런케이션 | PASS |
| — | SecOC 인코드/디코드 라운드트립 | PASS |
| — | SecOC 오버헤드 24바이트 | PASS |
| CST-006 | 리플레이 거부 (Freshness 실패) | PASS |
| — | 잘못된 키 → 디코드 실패 | PASS |
| — | Freshness 윈도우 초과 → 거부 | PASS |
| — | 짧은 메시지 → invalid 반환 | PASS |

### 3.2 IDS Engine (침입 탐지) — 13 테스트

| Spec ID | 테스트 | 결과 |
|---------|--------|------|
| — | Rate Limiter 속도 측정 | PASS |
| — | Rate Limiter 누적 | PASS |
| CST-023 | 정상 트래픽 → 알럿 없음 (FP=0) | PASS |
| IDS-003 | MAC 실패 → CRITICAL 알럿 | PASS |
| IDS-004 | 리플레이 감지 → HIGH 알럿 | PASS |
| CST-020 | Rate 경고 임계값 초과 → 알럿 | PASS |
| IDS-001 | 비인가 publish 감지 | PASS |
| IDS-007 | 슬레이브→마스터 키 publish 감지 | PASS |
| IDS-006 | 비정상 페이로드 크기 (>4KB) | PASS |
| IDS-010 | CRC+MAC 동시 실패 → CRITICAL | PASS |
| IDS-008 | ≥3 노드 동시 오프라인 | PASS |
| — | 알럿 → Security Log 기록 | PASS |
| — | 인가된 접근 → 알럿 없음 | PASS |

### 3.3 ACL Manager (접근 제어) — 12 테스트

| Spec ID | 테스트 | 결과 |
|---------|--------|------|
| CST-010 | 허가 접근 성공 | PASS |
| CST-011 | 비허가 접근 차단 | PASS |
| CST-012 | 슬레이브 → 마스터 publish 차단 | PASS |
| CST-013 | 크로스 노드 publish 차단 | PASS |
| — | Coordinator 전체 접근 | PASS |
| — | Mixed 노드 센서+액추에이터 | PASS |
| — | Diagnostic 읽기 전용 | PASS |
| — | zenohd ACL config 생성 | PASS |
| — | 위반 로깅 | PASS |
| — | 미등록 노드 거부 | PASS |
| — | 하트비트 구독 허용 | PASS |
| — | 정책 조회 | PASS |

### 3.4 Security Foundation (보안 기반) — 24 테스트

| 영역 | 테스트 수 | 결과 |
|------|----------|------|
| AlertSeverity Enum | 1 | PASS |
| SecurityEventType Enum | 1 | PASS |
| IDSRuleID Enum (10개 규칙) | 1 | PASS |
| NodeSecurityRole (5개 역할) | 1 | PASS |
| RATE_LIMITS 상수 | 1 | PASS |
| FRESHNESS_WINDOW (5000ms) | 1 | PASS |
| MAX_PAYLOAD_SIZE (4096B) | 1 | PASS |
| SecurityEvent 라운드트립 | 1 | PASS |
| IDSAlert 직렬화 | 1 | PASS |
| Security Log 쓰기/읽기 | 1 | PASS |
| 체인 해시 무결성 | 1 | PASS |
| 체인 해시 변조 감지 | 1 | PASS |
| 체인 해시 삭제 감지 | 1 | PASS |
| Safety Log와 분리 | 1 | PASS |
| 재시작 후 영속성 | 1 | PASS |
| HKDF-SHA256 결정론적 | 1 | PASS |
| 다른 info → 다른 키 | 1 | PASS |
| 노드별 고유 키 파생 | 1 | PASS |
| 브로드캐스트 키 파생 | 1 | PASS |
| 키 파일 권한 0600 | 1 | PASS |
| 키 로테이션 | 1 | PASS |
| 마스터 키 저장/로드 | 1 | PASS |
| 마스터 키 파일 권한 | 1 | PASS |
| 온디맨드 키 파생 | 1 | PASS |

### 3.5 Security Integration + Cert Provisioner — 11 테스트

| 테스트 | 결과 |
|--------|------|
| 전체 스택 라운드트립 (App→SecOC→E2E→...→E2E→SecOC→App) | PASS |
| 잘못된 키 → MAC 실패 | PASS |
| 데이터 변조 → MAC+CRC 실패 | PASS |
| 혼합 이벤트 후 체인 유효 | PASS |
| ACL config 노드 등록 일치 | PASS |
| 파생 키로 SecOC 동작 | PASS |
| 다른 노드 키 디코드 불가 | PASS |
| CA 인증서 생성 | PASS |
| 디바이스 인증서 생성+서명 | PASS |
| 유효 인증서 검증 성공 | PASS |
| 다른 CA 인증서 검증 실패 | PASS |

### 3.6 Penetration Tests (침투 테스트) — 6 테스트

| Spec ID | 시나리오 | 공격 기법 | 방어 메커니즘 | 결과 |
|---------|---------|----------|-------------|------|
| PT-001 | 위조 센서 메시지 | 공격자 키로 MAC 생성 | SecOC HMAC 검증 실패 | **BLOCKED** |
| PT-002 | 위조 액추에이터 명령 | 잘못된 키 + 비인가 접근 | MAC 실패 + IDS-003 알럿 | **BLOCKED** |
| PT-003 | 리플레이 공격 | 과거 유효 메시지 재전송 | Freshness Value 거부 | **BLOCKED** |
| PT-005 | Flooding (DoS) | 대량 메시지 전송 | Rate Limiting + IDS-002 | **DETECTED** |
| — | 비인가 키 표현식 접근 | 마스터 명령 키 publish | ACL + IDS-001 CRITICAL | **BLOCKED** |
| — | 복합 공격 (4종 동시) | MAC+CRC+대형+마스터 키 | IDS-003,006,007,010 동시 탐지 | **BLOCKED** |

---

## 4. 요구사항-테스트 추적 매트릭스 (RTM)

### 4.1 기능안전 (functional_safety.md Section 9)

| Spec ID | 요구사항 | 테스트 함수 | 상태 |
|---------|---------|-----------|------|
| FST-001 | CRC 정상 검증 | test_e2e_protection::test_crc_valid_message | ✅ |
| FST-002 | CRC 변조 감지 | test_e2e_protection::test_crc_bit_flip_detected | ✅ |
| FST-003 | Sequence 정상 | test_e2e_protection::test_sequential_ok | ✅ |
| FST-004 | Sequence 누락 감지 | test_e2e_protection::test_gap_exceeded_error | ✅ |
| FST-005 | Sequence 중복 감지 | test_e2e_protection::test_duplicate_detected | ✅ |
| FST-006 | Timeout 감지 | test_e2e_supervisor::test_e2e_state_timeout | ✅ |
| FST-007 | Data ID 불일치 | test_e2e_protection::test_data_id_mismatch_rejected | ✅ |
| FST-008 | Wrap-around | test_e2e_protection::test_wrap_around_65535_to_0 | ✅ |
| FST-010 | NORMAL→DEGRADED | test_safety_manager::test_normal_to_degraded_on_node_fault | ✅ |
| FST-011 | DEGRADED→NORMAL | test_safety_manager::test_degraded_to_normal_on_recovery | ✅ |
| FST-012 | DEGRADED→SAFE_STATE | test_safety_manager::test_degraded_to_safe_state_on_multi_fault | ✅ |
| FST-013 | SAFE_STATE 액추에이터 | test_safety_manager::test_safe_state_actuator_actions | ✅ |
| FST-014 | FAIL_SILENT 출력 차단 | test_safety_manager::test_fail_silent_blocks_output | ✅ |
| FST-015 | Self-Test 전 항목 | test_self_test::test_all_pass_returns_true | ✅ |

### 4.2 장애 주입 (functional_safety.md Section 9.3)

| Spec ID | 주입 장애 | 테스트 함수 | 상태 |
|---------|----------|-----------|------|
| FIT-001 | 네트워크 인터페이스 다운 | test_safety_integration::test_node_offline_triggers_degraded | ✅ |
| FIT-003 | 페이로드 바이트 변조 | test_safety_integration::test_corrupted_payload_rejected_by_e2e | ✅ |
| FIT-006 | DTC 저장소 파일 삭제 | test_dtc_manager::test_missing_file_creates_new | ✅ |
| FIT-002 | 슬레이브 프로세스 kill | — (하드웨어 테스트에서 수행) | ⏳ |
| FIT-004 | 메시지 지연 주입 | test_e2e_supervisor::test_e2e_state_timeout | ✅ |
| FIT-005 | Zenohd 프로세스 kill | — (하드웨어 테스트에서 수행) | ⏳ |

### 4.3 사이버보안 (cybersecurity.md Section 10)

| Spec ID | 요구사항 | 테스트 함수 | 상태 |
|---------|---------|-----------|------|
| CST-004 | HMAC 정상 검증 | test_secoc::test_mac_valid_verification | ✅ |
| CST-005 | HMAC 변조 감지 | test_secoc::test_mac_tampered_rejected | ✅ |
| CST-006 | 리플레이 차단 | test_secoc::test_replay_rejected | ✅ |
| CST-010 | ACL 허용 | test_acl_manager::test_allowed_access_succeeds | ✅ |
| CST-011 | ACL 차단 | test_acl_manager::test_denied_access_blocked | ✅ |
| CST-012 | 권한 상승 방지 | test_acl_manager::test_slave_cannot_publish_master_key | ✅ |
| CST-013 | 크로스 노드 차단 | test_acl_manager::test_cross_node_publish_blocked | ✅ |
| CST-020 | Flooding 감지 | test_ids_engine::test_rate_limit_warning | ✅ |
| CST-021 | 비인가 publish 감지 | test_ids_engine::test_unauthorized_publish_detected | ✅ |
| CST-023 | 정상 트래픽 무오탐 | test_ids_engine::test_normal_traffic_no_alerts | ✅ |
| CST-001 | TLS 핸드셰이크 | — (TLS 활성화 후 HW 테스트) | ⏳ |
| CST-002 | 인증서 없는 연결 거부 | — (TLS 활성화 후 HW 테스트) | ⏳ |
| CST-003 | 만료 인증서 거부 | — (TLS 활성화 후 HW 테스트) | ⏳ |
| CST-007 | TLS 성능 영향 | — (TLS 활성화 후 HW 테스트) | ⏳ |

### 4.4 침투 테스트 (cybersecurity.md Section 10.4)

| Spec ID | 시나리오 | 테스트 함수 | 상태 |
|---------|---------|-----------|------|
| PT-001 | 위조 센서 메시지 | test_penetration::test_spoofed_sensor_message_rejected | ✅ |
| PT-002 | 위조 액추에이터 명령 | test_penetration::test_spoofed_actuator_command_rejected | ✅ |
| PT-003 | 리플레이 공격 | test_penetration::test_replay_old_command_rejected | ✅ |
| PT-004 | 비인가 노드 접속 | — (mTLS Python SDK 제한) | ⏳ |
| PT-005 | Flooding 공격 | test_penetration::test_flooding_rate_limited | ✅ |
| PT-006 | MITM 공격 | — (물리적 탭 필요) | ⏳ |

---

## 5. 시뮬레이션 테스트 상세 (4종, 61 테스트)

소프트웨어 레벨에서 실제 모듈(SafetyManager, IDSEngine, SecOC 등)을 직접 호출하여
다중 노드 시나리오를 검증합니다. CI/CD 회귀 테스트용.

### 5.1 Safety 시뮬레이션 — 22 테스트 (test_sim_safety.py)

| Test ID | 시나리오 | 결과 |
|---------|---------|------|
| SIM-S1a | E2E 센서 메시지 라운드트립 | PASS |
| SIM-S1b | 10개 메시지 시퀀스 추적 | PASS |
| SIM-S1c | 멀티 센서 독립 카운터 | PASS |
| SIM-S2 | CRC 3회 연속 실패 → DEGRADED | PASS |
| SIM-S3 | ≥50% 노드 오프라인 → SAFE_STATE | PASS |
| SIM-S4a | ASIL-D 타임아웃 → SAFE_STATE | PASS |
| SIM-S4b | Watchdog 만료 → SAFE_STATE | PASS |
| SIM-S4c | Flow 오류 → SAFE_STATE | PASS |
| SIM-S5 | DEGRADED → 복구 → NORMAL | PASS |
| SIM-S6a | 전체 에스컬레이션 → FAIL_SILENT | PASS |
| SIM-S6b | FAIL_SILENT → 리셋 → NORMAL | PASS |
| SIM-S7 | E2E Supervisor 멀티 채널 | PASS |
| SIM-S8a | 시퀀스 갭 감지 (허용 범위 내) | PASS |
| SIM-S8b | CRC 변조 감지 | PASS |
| SIM-S9a | 정상 흐름 체크포인트 통과 | PASS |
| SIM-S9b | 잘못된 순서 감지 | PASS |
| SIM-S9c | 누락 체크포인트 감지 | PASS |
| SIM-S9d | 10 사이클 연속 정상 | PASS |
| SIM-S10a | Safe action 정의 확인 | PASS |
| SIM-S10b | FAIL_SILENT 출력 차단 | PASS |
| SIM-S10c | 장애 시 DTC 저장 | PASS |
| SIM-S10d | Safety Log 이벤트 기록 | PASS |

### 5.2 Security 시뮬레이션 — 15 테스트 (test_sim_security.py)

| Test ID | 시나리오 | 결과 |
|---------|---------|------|
| SIM-X1a | 정당 키 → MAC 검증 성공 | PASS |
| SIM-X1b | 위조 키 → MAC 거부 | PASS |
| SIM-X2a | 리플레이 공격 → Freshness 거부 | PASS |
| SIM-X2b | 노드별 키 격리 (교차 디코드 불가) | PASS |
| SIM-X3 | MAC 실패 → IDS-003 CRITICAL | PASS |
| SIM-X4 | Flooding → IDS-002 | PASS |
| SIM-X5a | 페이로드 >4KB → IDS-006 | PASS |
| SIM-X5b | Slave→Master 키 → IDS-007 | PASS |
| SIM-X6a | 비인가 키 표현식 → IDS-001 | PASS |
| SIM-X6b | ≥3 노드 동시 오프라인 → IDS-008 | PASS |
| SIM-X6c | CRC+MAC 동시 실패 → IDS-010 | PASS |
| SIM-X7a | Coordinator 전체 접근 | PASS |
| SIM-X7b | Sensor 노드 제한 접근 | PASS |
| SIM-X8 | ACL 위반 → IDS 알럿 연동 | PASS |
| SIM-X9 | 체인 해시 무결성 (혼합 이벤트) | PASS |

### 5.3 장애 주입 시뮬레이션 — 13 테스트 (test_sim_fault_injection.py)

| Test ID | 주입 시나리오 | Safety/Security 반응 | 결과 |
|---------|-------------|---------------------|------|
| SIM-F1a | 단일 노드 오프라인 | DEGRADED + DTC | PASS |
| SIM-F1b | 연쇄 노드 장애 (3개) | SAFE_STATE | PASS |
| SIM-F2a | 네트워크 단절 (타임아웃) | E2E TIMEOUT | PASS |
| SIM-F2b | PLCA beacon 소실 | DEGRADED | PASS |
| SIM-F3a | CRC 변조 5회 연속 | DEGRADED + ERROR | PASS |
| SIM-F3b | 변조 후 정상 → 복구 | VALID (카운터 리셋) | PASS |
| SIM-F4a | 시퀀스 갭 10 (max=3) | INVALID + SEQ_ERROR | PASS |
| SIM-F4b | 시퀀스 중복 (delta=0) | 무시 (에러 아님) | PASS |
| SIM-F5a | 3노드 동시 오프라인 | IDS-008 + SAFE_STATE | PASS |
| SIM-F5b | 센서 범위 이탈 | DEGRADED | PASS |
| SIM-F6 | MAC+CRC 동시 실패 | IDS-010 + DEGRADED | PASS |
| SIM-F7 | Flooding 후 노드 kill | IDS-002 + SAFE_STATE | PASS |
| SIM-F8 | 복합 장애 후 복구 | NORMAL 복귀 | PASS |

### 5.4 E2E 시나리오 시뮬레이션 — 11 테스트 (test_sim_e2e_scenario.py)

| Test ID | 시나리오 | 보호 스택 | 결과 |
|---------|---------|----------|------|
| SIM-E1a | SecOC 액추에이터 명령 라운드트립 | E2E + SecOC | PASS |
| SIM-E1b | 잘못된 키로 액추에이터 명령 거부 | SecOC HMAC | PASS |
| SIM-E2 | 센서 10개 → E2E Supervisor 검증 | E2E CRC | PASS |
| SIM-E3 | 전체 라이프사이클 (시작→운용→장애→복구) | 전체 | PASS |
| SIM-E4 | 4노드 혼합 (센서 2, 액추에이터 1, 혼합 1) | E2E | PASS |
| SIM-E5 | 전체 보안 스택: SecOC→IDS→ACL→디코드 | E2E + SecOC + ACL | PASS |
| SIM-E6 | 공격자 메시지: IDS + MAC + ACL 차단 | 전체 | PASS |
| SIM-E7 | Self-Test 10항목 전체 통과 | Safety | PASS |
| SIM-E8 | DTC 영속성 (저장→재시작→조회→삭제) | DTC | PASS |

---

## 6. 하드웨어 버스 테스트 상세 (3종, 38 테스트)

실제 10BASE-T1S 물리 버스에서 실행됩니다.
Slave는 `ns_slave` 네트워크 네임스페이스에서 `eth2`를 통해 연결합니다.

```
Slave (ns_slave/eth2, 192.168.1.2) ──→ 10BASE-T1S wire ──→ eth1 (192.168.1.1) ──→ zenohd ──→ Master (Python)
```

### 6.1 기존 HW 테스트 — 15 테스트 (test_hw_bypass.py)

| 영역 | 테스트 | 결과 |
|------|--------|------|
| 물리 계층 | eth1 인터페이스 UP | PASS |
| 물리 계층 | eth2 인터페이스 UP (ns_slave) | PASS |
| 물리 계층 | PLCA Coordinator 설정 | PASS |
| 물리 계층 | PLCA Follower 설정 | PASS |
| 물리 계층 | Ping master → slave | PASS |
| 물리 계층 | Ping slave → master | PASS |
| 물리 계층 | PLCA beacon 활성 | PASS |
| Zenoh Pub/Sub | Slave 센서 → Master 수신 | PASS |
| Zenoh Pub/Sub | Master 액추에이터 → Slave 수신 | PASS |
| Zenoh Pub/Sub | CBOR 인코딩 전송 | PASS |
| Liveliness | 노드 온라인/오프라인 감지 | PASS |
| Query/Reply | 상태 쿼리 응답 | PASS |
| Scenario | 근접→잠금 해제 시나리오 | PASS |
| Latency | Pub/Sub 레이턴시 (<15ms) | PASS |
| Wire | tshark 물리 와이어 검증 | PASS |

### 6.2 HW 안전/보안 버스 테스트 — 17 테스트 (test_hw_safety_security.py)

**데이터 경로**: `slave(eth2, ns_slave) → 10BASE-T1S wire → eth1 → zenohd → master(Python)`

#### E2E over 물리 버스 — 5 테스트

| Test ID | 시나리오 | 검증 내용 | 결과 |
|---------|---------|----------|------|
| HW-E2E-1 | Slave→Master E2E 센서 | CRC 검증, data_id=0x1001 | PASS |
| HW-E2E-2 | 10개 E2E 시퀀스 추적 | seq=[0,1,...,9], 모두 CRC 유효 | PASS |
| HW-E2E-3 | CRC 변조 메시지 | 물리 버스 통과 후 CRC=False | PASS |
| HW-E2E-4 | Master→Slave E2E 액추에이터 | Slave가 ns_slave에서 수신+검증 | PASS |
| HW-E2E-5 | E2E Supervisor 버스 메시지 | 5 msgs, 0 CRC failures, NORMAL | PASS |

#### SecOC over 물리 버스 — 4 테스트

| Test ID | 시나리오 | 검증 내용 | 결과 |
|---------|---------|----------|------|
| HW-SEC-1 | SecOC 센서 데이터 | MAC=True, CRC=True, value=27.3 | PASS |
| HW-SEC-2 | 위조 메시지 (잘못된 HMAC 키) | 물리 버스 통과 후 MAC=False | PASS |
| HW-SEC-3 | IDS 알럿 (위조 감지) | IDS-003 CRITICAL, chain valid | PASS |
| HW-SEC-4 | SecOC 10개 연속 전송 | 10/10 MAC+CRC valid | PASS |

#### Safety FSM on 물리 버스 — 3 테스트

| Test ID | 시나리오 | 결과 |
|---------|---------|------|
| HW-SAF-1 | 유효 버스 트래픽 → NORMAL 유지 | PASS |
| HW-SAF-2 | CRC 변조 5회 → DEGRADED + DTC | PASS |
| HW-SAF-3 | 라이프사이클: NORMAL→DEGRADED→NORMAL | PASS |

#### 레이턴시 측정 — 1 테스트

| Test ID | Plain 평균 | E2E 평균 | 오버헤드 | PRD 기준 |
|---------|-----------|---------|---------|---------|
| HW-LAT-1 | 1.09 ms | 0.93 ms | ~0 ms | < 15 ms ✅ |

#### TLS 연결 — 4 테스트

| Test ID | 시나리오 | 결과 |
|---------|---------|------|
| HW-TLS-1 | TLS zenohd 기동 (tls/192.168.1.1:7448) | PASS |
| HW-TLS-2 | Master TLS 클라이언트 연결 | PASS |
| HW-TLS-3 | Slave TLS 디바이스 인증서 연결 | PASS |
| HW-TLS-4 | TLS 채널 Pub/Sub 메시지 교환 | PASS |

> **TLS 참고**: TLS (서버 인증서) 연결 성공. mTLS (클라이언트 인증서 상호 인증)는
> zenoh Python SDK v1.9.0에서 `connect_certificate` 전송 제한으로 비활성화.
> Rust 클라이언트 또는 SDK 업데이트 시 활성화 예정.

### 6.3 Python↔C 크로스 언어 테스트 — 6 테스트 (test_interop_hw.py)

| 시나리오 | Master (Python) | Slave (C zenoh-pico) | 결과 |
|---------|----------------|---------------------|------|
| Pub/Sub: C → Python | subscribe | sensor_node publish 5회 | PASS |
| Pub/Sub: Python → C | publish 2회 | actuator_node subscribe | PASS |
| Query: Python → C | get() 쿼리 | sensor_node queryable | PASS |
| Liveliness | 온/오프라인 감지 | sensor_node 토큰 | PASS |
| Bidirectional | 센서 구독→액추에이터 발행 | 센서 발행→액추에이터 수신 | PASS |
| tshark | 패킷 캡처 분석 | 물리 와이어 검증 | PASS |

---

## 7. 커버리지 요약 (업데이트)

| 구분 | 명세서 ID | 구현 완료 | 미구현 | 커버리지 |
|------|----------|----------|--------|---------|
| E2E Protection (FST-001~008) | 8 | 8 | 0 | **100%** |
| Safety FSM (FST-010~015) | 6 | 6 | 0 | **100%** |
| Fault Injection (FIT-001~006) | 6 | 5 | 1 | 83% |
| Communication Security (CST-001~007) | 7 | 5 | 2 | 71% |
| Access Control (CST-010~013) | 4 | 4 | 0 | **100%** |
| IDS (CST-020~023) | 4 | 4 | 0 | **100%** |
| Penetration (PT-001~006) | 6 | 4 | 2 | 67% |
| **HW E2E over Bus** | **5** | **5** | **0** | **100%** |
| **HW SecOC over Bus** | **4** | **4** | **0** | **100%** |
| **HW Safety FSM on Bus** | **3** | **3** | **0** | **100%** |
| **HW TLS** | **4** | **4** | **0** | **100%** |
| **총계** | **57** | **52** | **5** | **91%** |

미구현 5개:
- FIT-005: zenohd 프로세스 kill 복구 (수동 테스트 필요)
- CST-002: mTLS 비인가 인증서 거부 (Python SDK 제한)
- CST-003: 만료 인증서 거부 (Python SDK 제한)
- PT-004: mTLS 비인가 노드 접속 차단
- PT-006: MITM 공격 (물리적 탭 필요)

---

## 8. 테스트 실행 방법

```bash
# ==============================
# 전체 SW 테스트 (321개, HW 불필요)
# ==============================
python3 -m pytest tests/ \
    --ignore=tests/test_hw_bypass.py \
    --ignore=tests/test_interop_hw.py \
    --ignore=tests/test_hw_safety_security.py \
    --ignore=tests/test_integration_bypass.py \
    --ignore=tests/test_scenario_runner.py -v

# ==============================
# 시뮬레이션 테스트 (61개, HW 불필요)
# ==============================
python3 -m pytest tests/test_sim_*.py -v

# ==============================
# 기능안전 테스트 (133개)
# ==============================
python3 -m pytest tests/test_safety*.py tests/test_e2e*.py \
    tests/test_dtc*.py tests/test_flow*.py tests/test_self_test.py -v

# ==============================
# 사이버보안 + 침투 테스트 (67개)
# ==============================
python3 -m pytest tests/test_security*.py tests/test_acl*.py \
    tests/test_ids*.py tests/test_secoc.py tests/test_penetration.py -v

# ==============================
# HW 버스 테스트 (38개, EVB-LAN8670-USB x2 필요)
# Prerequisites:
#   1. EVB-LAN8670-USB x2 + UTP cable
#   2. sudo ip netns add ns_slave
#      sudo ip link set eth2 netns ns_slave
#      sudo ip netns exec ns_slave ip addr add 192.168.1.2/24 dev eth2
#      sudo ip netns exec ns_slave ip link set eth2 up
#      sudo ip addr add 192.168.1.1/24 dev eth1
#   3. zenohd --listen tcp/192.168.1.1:7447
# ==============================
python3 -m pytest tests/test_hw_safety_security.py -v -s
python3 -m pytest tests/test_hw_bypass.py -v -s
python3 -m pytest tests/test_interop_hw.py -v -s

# ==============================
# HW 레이턴시 측정만
# ==============================
python3 -m pytest tests/test_hw_safety_security.py -v -s -k "latency"

# ==============================
# HW TLS 테스트만
# ==============================
python3 -m pytest tests/test_hw_safety_security.py -v -s -k "TLS"
```

---

## 9. 테스트 아키텍처 다이어그램

```
┌─────────────────────────────────────────────────────────────────┐
│                    테스트 피라미드 (383 tests)                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ▲  HW Bus Tests (38)        ← 실제 10BASE-T1S 물리 버스        │
│  │   ├─ E2E over wire (5)                                       │
│  │   ├─ SecOC over wire (4)   eth2(ns_slave) → wire → eth1      │
│  │   ├─ Safety FSM on bus (3)                                   │
│  │   ├─ TLS (4)               tls/192.168.1.1:7448              │
│  │   ├─ HW bypass (15)        Zenoh over 10BASE-T1S             │
│  │   └─ Interop C↔Python (6)  zenoh-pico ↔ eclipse-zenoh       │
│  │                                                              │
│  │  Simulation Tests (61)     ← 실제 모듈, 인메모리 시뮬레이션    │
│  │   ├─ Safety sim (22)       Safety FSM 전이, E2E 검증          │
│  │   ├─ Security sim (15)     IDS 10규칙, SecOC, ACL             │
│  │   ├─ Fault injection (13)  노드 kill, CRC 변조, Flooding      │
│  │   └─ E2E scenario (11)     전체 라이프사이클                   │
│  │                                                              │
│  │  Integration Tests (23)    ← Zenoh TCP loopback               │
│  │   ├─ Bypass (12)           127.0.0.1:7447                    │
│  │   └─ Safety+Security (11)  Full stack roundtrip               │
│  │                                                              │
│  ▼  Unit Tests (261)          ← 개별 모듈 단위 검증               │
│      ├─ Safety (133)          E2E, FSM, DTC, Flow, Watchdog     │
│      ├─ Security (61)         SecOC, IDS, ACL, KeyMgr, Log      │
│      ├─ Penetration (6)       PT-001~005                        │
│      └─ Foundation (61)       Key, Model, Payload, Network      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 10. TLS 인증서 구성

```
config/certs/
├── ca.crt                    # Root CA (ECDSA P-256, 2년)
├── ca.key                    # Root CA 개인키 (0600)
├── zenoh-node-master.crt     # Master 디바이스 인증서 (SAN: IP:192.168.1.1)
├── zenoh-node-master.key     # Master 개인키 (0600)
├── zenoh-node-1.crt          # Slave 디바이스 인증서 (SAN: IP:192.168.1.2)
├── zenoh-node-1.key          # Slave 개인키 (0600)
├── generate_ca.sh            # CA 생성 스크립트
└── generate_device_cert.sh   # 디바이스 인증서 생성 스크립트
```

인증서 체인:
```
Root CA (Zenoh-10BASE-T1S Root CA)
  ├── zenoh-node-master (CN=zenoh-node-master, SAN=IP:192.168.1.1)
  └── zenoh-node-1      (CN=zenoh-node-1,      SAN=IP:192.168.1.2)
```
