# 원재료관리 & 포장출하관리 모듈 기획 문서

> **Summary**: 꽃순이김치 제조AI MES — 원재료 입고 AI Agent와 포장/출하 AI Agent를 중심으로 한 두 핵심 모듈의 상세 기획
>
> **Author**: PM2 (담당: 원재료관리, 포장출하관리)
> **Created**: 2026-05-23
> **Last Modified**: 2026-05-23
> **Status**: Draft
> **Project**: SF26179540 | 꽃순이김치 제조AI 스마트공장 | 로뎀솔루션

---

## 목차

1. [모듈별 기능 구조 (3단계 메뉴 트리)](#1-모듈별-기능-구조)
2. [화면 목록](#2-화면-목록)
3. [상세 기능 명세](#3-상세-기능-명세)
4. [LOT 추적 흐름도](#4-lot-추적-흐름도)
5. [RAG AI Agent 상세 명세](#5-rag-ai-agent-상세-명세)
6. [SmartPad 전용 화면 명세](#6-smartpad-전용-화면-명세)
7. [사용자 스토리](#7-사용자-스토리)
8. [데이터 요구사항](#8-데이터-요구사항)
9. [클레임 처리 프로세스](#9-클레임-처리-프로세스)
10. [HACCP 연계 체크포인트](#10-haccp-연계-체크포인트)

---

## 1. 모듈별 기능 구조

### 1.1 원재료관리 모듈 — 3단계 메뉴 트리

```
원재료관리
├── 1-1. 입고관리
│   ├── 1-1-1. 입고 등록
│   ├── 1-1-2. 입고 목록 조회
│   ├── 1-1-3. 입고 검사 결과 입력
│   └── 1-1-4. 입고 승인 처리
├── 1-2. 원재료 이력조회
│   ├── 1-2-1. LOT별 이력 조회
│   ├── 1-2-2. 원재료 추적 이력
│   └── 1-2-3. 기간별 이력 통계
├── 1-3. 선별 데이터관리
│   ├── 1-3-1. 선별 결과 입력
│   ├── 1-3-2. 선별 등급 현황
│   └── 1-3-3. 불합격 원재료 처리
├── 1-4. 공급처 품질분석
│   ├── 1-4-1. 공급처별 품질 현황
│   ├── 1-4-2. 공급처 품질 트렌드
│   ├── 1-4-3. 공급처 평가 관리
│   └── 1-4-4. 공급처 비교 분석
└── 1-5. 입고 AI Agent
    ├── 1-5-1. AI 질의응답 (SmartPad / Web)
    ├── 1-5-2. AI 분석 결과 조회
    └── 1-5-3. AI 질의 이력 관리
```

### 1.2 포장출하관리 모듈 — 3단계 메뉴 트리

```
포장출하관리
├── 2-1. 포장실적관리
│   ├── 2-1-1. 포장 실적 등록
│   ├── 2-1-2. 포장 실적 조회
│   ├── 2-1-3. 자동중량검사 결과 연동
│   └── 2-1-4. 포장 LOT 생성
├── 2-2. 출하관리
│   ├── 2-2-1. 출하 계획 조회
│   ├── 2-2-2. 출하 승인 처리
│   ├── 2-2-3. 출하 실적 등록
│   └── 2-2-4. 냉장 운송 온도 관리
├── 2-3. LOT추적
│   ├── 2-3-1. 정방향 추적 (입고→출하)
│   ├── 2-3-2. 역방향 추적 (출하→입고)
│   └── 2-3-3. LOT 추적 이력 출력
├── 2-4. 검사결과관리
│   ├── 2-4-1. 출하 검사 결과 입력
│   ├── 2-4-2. 검사 항목별 현황
│   └── 2-4-3. 불합격 제품 처리
├── 2-5. 클레임분석
│   ├── 2-5-1. 클레임 접수 등록
│   ├── 2-5-2. 클레임 원인 분석
│   ├── 2-5-3. 클레임 처리 현황
│   └── 2-5-4. 클레임 통계 분석
└── 2-6. 출하 AI Agent
    ├── 2-6-1. AI 질의응답 (SmartPad / Web)
    ├── 2-6-2. AI 출하 승인 검토
    └── 2-6-3. AI 질의 이력 관리
```

---

## 2. 화면 목록

### 2.1 원재료관리 — Web 관리자 화면

| 화면 ID | 화면명 | 유형 | 주요 사용자 |
|---------|--------|------|------------|
| SCR-RM-01 | 입고 등록 | 입력 폼 | 입고 담당자 |
| SCR-RM-02 | 입고 목록 조회 | 그리드 + 검색 | 입고 담당자, 품질관리자 |
| SCR-RM-03 | 입고 검사 결과 입력 | 입력 폼 | 품질관리자 |
| SCR-RM-04 | 입고 승인 처리 | 승인 워크플로우 | 공장장, 품질관리자 |
| SCR-RM-05 | LOT별 이력 조회 | 타임라인 뷰 | 품질관리자, 공장장 |
| SCR-RM-06 | 원재료 추적 이력 | 트리/플로우 뷰 | 품질관리자 |
| SCR-RM-07 | 기간별 이력 통계 | 차트 대시보드 | 공장장 |
| SCR-RM-08 | 선별 결과 입력 | 입력 폼 | 현장 작업자 |
| SCR-RM-09 | 선별 등급 현황 | 차트 + 그리드 | 품질관리자 |
| SCR-RM-10 | 불합격 원재료 처리 | 처리 폼 | 품질관리자 |
| SCR-RM-11 | 공급처별 품질 현황 | 대시보드 | 공장장, 품질관리자 |
| SCR-RM-12 | 공급처 품질 트렌드 | 꺾은선 차트 | 공장장 |
| SCR-RM-13 | 공급처 평가 관리 | 평가 폼 + 그리드 | 공장장 |
| SCR-RM-14 | 공급처 비교 분석 | 레이더/바 차트 | 공장장 |
| SCR-RM-15 | 입고 AI Agent (Web) | 채팅 인터페이스 | 품질관리자, 공장장 |
| SCR-RM-16 | AI 분석 결과 조회 | 결과 카드 + 차트 | 품질관리자 |
| SCR-RM-17 | AI 질의 이력 관리 | 로그 그리드 | 관리자 |

### 2.2 원재료관리 — SmartPad 전용 화면 (입고 공정)

| 화면 ID | 화면명 | 유형 | 특이사항 |
|---------|--------|------|---------|
| SPD-RM-01 | 입고 데이터 입력 | 대형 버튼 + 숫자패드 | 장갑 착용 환경 |
| SPD-RM-02 | LOT 바코드 스캔 | 카메라/스캔 뷰 | QR/바코드 스캔 |
| SPD-RM-03 | 입고 검사 체크리스트 | 체크박스 리스트 | HACCP 연동 |
| SPD-RM-04 | AI Agent 채팅 | 음성입력 + 텍스트 | TTS/STT 지원 |
| SPD-RM-05 | 입고 완료 확인 | 확인 화면 | 서명/지문 확인 |

### 2.3 포장출하관리 — Web 관리자 화면

| 화면 ID | 화면명 | 유형 | 주요 사용자 |
|---------|--------|------|------------|
| SCR-PS-01 | 포장 실적 등록 | 입력 폼 | 포장 담당자 |
| SCR-PS-02 | 포장 실적 조회 | 그리드 + 검색 | 공장장, 품질관리자 |
| SCR-PS-03 | 자동중량검사 결과 | 실시간 모니터링 | 포장 담당자 |
| SCR-PS-04 | 포장 LOT 생성 | 폼 + 자동생성 | 포장 담당자 |
| SCR-PS-05 | 출하 계획 조회 | 캘린더 + 그리드 | 출하 담당자 |
| SCR-PS-06 | 출하 승인 처리 | 승인 워크플로우 | 공장장 |
| SCR-PS-07 | 출하 실적 등록 | 입력 폼 | 출하 담당자 |
| SCR-PS-08 | 냉장 운송 온도 관리 | 온도 모니터링 | 출하 담당자 |
| SCR-PS-09 | 정방향 LOT 추적 | 플로우 다이어그램 | 품질관리자, 공장장 |
| SCR-PS-10 | 역방향 LOT 추적 | 역방향 플로우 | 품질관리자, 공장장 |
| SCR-PS-11 | LOT 추적 이력 출력 | PDF 출력 | 품질관리자 |
| SCR-PS-12 | 출하 검사 결과 입력 | 입력 폼 | 품질관리자 |
| SCR-PS-13 | 검사 항목별 현황 | 차트 + 그리드 | 품질관리자 |
| SCR-PS-14 | 불합격 제품 처리 | 처리 폼 | 품질관리자 |
| SCR-PS-15 | 클레임 접수 등록 | 입력 폼 | CS 담당자 |
| SCR-PS-16 | 클레임 원인 분석 | AI 분석 결과 카드 | 품질관리자 |
| SCR-PS-17 | 클레임 처리 현황 | 상태 트래킹 | 공장장 |
| SCR-PS-18 | 클레임 통계 분석 | 차트 대시보드 | 공장장 |
| SCR-PS-19 | 출하 AI Agent (Web) | 채팅 인터페이스 | 품질관리자, 공장장 |
| SCR-PS-20 | AI 출하 승인 검토 | 검토 카드 | 공장장 |
| SCR-PS-21 | AI 질의 이력 관리 | 로그 그리드 | 관리자 |

### 2.4 포장출하관리 — SmartPad 전용 화면 (출하 공정)

| 화면 ID | 화면명 | 유형 | 특이사항 |
|---------|--------|------|---------|
| SPD-PS-01 | 포장 실적 입력 | 대형 버튼 + 숫자패드 | 장갑 착용 환경 |
| SPD-PS-02 | 중량 검사 결과 확인 | 실시간 알림 | 자동중량검사기 연동 |
| SPD-PS-03 | 출하 검사 체크리스트 | 체크박스 리스트 | HACCP CCP 연동 |
| SPD-PS-04 | AI Agent 채팅 | 음성입력 + 텍스트 | TTS/STT 지원 |
| SPD-PS-05 | 출하 승인 확인 | 확인 화면 | 공장장 최종 승인 |

---

## 3. 상세 기능 명세

### 3.1 입고관리

#### 3.1.1 입고 등록 (SCR-RM-01 / SPD-RM-01)

**기능 개요**
원재료(배추, 부재료) 입고 시 LOT를 생성하고 기본 정보를 시스템에 등록한다. 입고 공정 SmartPad와 Web 관리자 화면에서 모두 접근 가능하다.

**입력 데이터 항목**

| 항목 | 필드명 | 데이터타입 | 필수 | 설명 |
|------|--------|-----------|------|------|
| 입고일시 | intake_datetime | TIMESTAMP | Y | 기본값: 현재시각 |
| 공급처코드 | supplier_code | VARCHAR(20) | Y | 등록된 공급처 선택 |
| 원재료 품목코드 | material_code | VARCHAR(20) | Y | 배추/부재료 구분 |
| 원산지 | origin | VARCHAR(50) | Y | 강원도 평창 등 |
| 차량번호 | vehicle_no | VARCHAR(20) | N | 운반 차량 |
| 입고 수량 | intake_qty | DECIMAL(10,2) | Y | 단위: kg |
| 포장 단위 | package_unit | VARCHAR(20) | Y | 망/박스/kg |
| 포장 수량 | package_count | INTEGER | Y | 포장 수량 |
| 배추 크기 등급 | cabbage_size_grade | VARCHAR(10) | N | S/M/L/XL |
| 외관 등급 | appearance_grade | VARCHAR(10) | Y | A/B/C/D |
| 함수율 (%) | moisture_content | DECIMAL(5,2) | N | 품질 예측 입력값 |
| 중량 (측정값) | measured_weight | DECIMAL(10,2) | N | 계량 측정값 |
| 비고 | remark | TEXT | N | 특이사항 |

**출력/표시 내용**
- 자동 생성된 입고LOT 번호 (형식: `RM-YYYYMMDD-NNN`)
- 공급처 기본 정보 (이전 입고 이력, 평균 품질 점수)
- 입고 검사 대기 상태로 전환 확인 메시지
- AI Agent 품질 기준 비교 결과 (자동 트리거)

**RAG AI Agent 연계 방식**
- 입고 등록 완료 시 자동으로 입고 AI Agent 호출
- 입력된 공급처 + 원재료 + 외관등급 + 함수율 데이터를 컨텍스트로 전달
- Vector DB에서 품질 기준서 관련 청크 검색 후 기준 적합 여부 판단
- 결과를 화면 하단 "AI 검토 의견" 카드로 표시

**비즈니스 로직**
1. 공급처 코드 선택 시 공급처 이력 DB에서 최근 3회 입고 품질 점수 자동 조회
2. 입고 수량 = 포장 단위 × 포장 수량 (자동 계산, 수동 조정 가능)
3. 외관 등급 D는 입고 보류 처리 (공장장 승인 필요)
4. 입고 등록 완료 시 다음 공정(절임)에 LOT 전달 예약
5. 부재료(양념류)는 배추와 별도 LOT 체계 적용

**유효성 검사 규칙**
- 입고 수량 > 0 (필수)
- 함수율: 0 ~ 100% 범위
- 외관 등급: A/B/C/D 중 하나
- 공급처코드: 기준정보에 등록된 코드만 허용
- 동일 차량번호 + 동일 일자 중복 입고 시 경고 표시 (등록은 허용)

---

#### 3.1.2 입고 목록 조회 (SCR-RM-02)

**기능 개요**
등록된 입고 내역을 다양한 조건으로 검색하고 현황을 파악한다.

**입력 데이터 항목 (검색 조건)**

| 항목 | 필드명 | 설명 |
|------|--------|------|
| 조회 기간 | date_from / date_to | 입고일 기준, 기본: 당일 |
| 공급처 | supplier_code | 전체/개별 선택 |
| 원재료 품목 | material_code | 배추/부재료 |
| 입고 상태 | intake_status | 검사대기/검사중/합격/불합격/보류 |
| LOT 번호 | lot_no | 직접 입력 |
| 외관 등급 | appearance_grade | A/B/C/D/전체 |

**출력/표시 내용**
- 입고 목록 그리드 (페이지당 20건)
- 요약 통계: 총 입고량(kg), 합격률(%), 공급처별 건수
- 상태별 색상 구분 (합격: 녹색, 불합격: 빨간색, 보류: 노란색)
- Excel 다운로드 기능

**비즈니스 로직**
- 기본 정렬: 입고일시 내림차순
- 상태 = "보류"인 건은 상단 고정 표시

---

#### 3.1.3 입고 검사 결과 입력 (SCR-RM-03 / SPD-RM-03)

**기능 개요**
입고된 원재료에 대한 품질 검사(관능검사, 이화학검사)를 수행하고 결과를 입력한다.

**입력 데이터 항목**

| 항목 | 필드명 | 데이터타입 | 필수 | 설명 |
|------|--------|-----------|------|------|
| 입고LOT | intake_lot_no | VARCHAR(30) | Y | 연결된 입고 LOT |
| 검사일시 | inspection_datetime | TIMESTAMP | Y | 기본값: 현재시각 |
| 검사자 | inspector_id | VARCHAR(20) | Y | 로그인 사용자 |
| 외관 상태 | visual_status | VARCHAR(10) | Y | 정상/이상 |
| 이물질 여부 | foreign_matter | BOOLEAN | Y | 없음/있음 |
| 부패 여부 | decay_status | BOOLEAN | Y | 없음/있음 |
| 잔류농약 결과 | pesticide_result | VARCHAR(10) | N | 적합/부적합 |
| 염도 (사전) | salinity_before | DECIMAL(4,2) | N | % 단위 |
| pH (사전) | ph_before | DECIMAL(4,2) | N | |
| 검사 총평 | inspection_summary | TEXT | N | 자유 기술 |
| 합격 여부 | pass_fail | VARCHAR(10) | Y | 합격/불합격/조건부합격 |
| HACCP 체크리스트 | haccp_checklist | JSON | Y | CCP 항목별 점검 결과 |

**출력/표시 내용**
- 입고 시 등록된 기본 정보 자동 표시 (공급처, 원재료, 등급 등)
- HACCP CCP 체크리스트 (품목별 맞춤 항목 자동 생성)
- 품질 기준서 기반 판단 가이드 (AI Agent 연계)
- 검사 완료 후 합격/불합격 상태 자동 반영

**RAG AI Agent 연계 방식**
- 검사 항목 입력 시작 시 AI Agent 호출
- "이 원재료의 검사 기준은?" 자동 질의 → 품질 기준서 청크 반환
- 이상 항목(이물질 있음, 부패 있음) 입력 시 "대응 가이드" 자동 표시

**비즈니스 로직**
1. 이물질 있음 또는 부패 있음 선택 시 → 합격 여부 자동 "불합격" 고정
2. 잔류농약 부적합 → 공장장 알림 즉시 발송
3. 조건부합격: 검사 총평 필수 입력, 공장장 승인 필요
4. 검사 결과 저장 시 AI 모델(ML Engine)에 입고 데이터 전송 트리거

**유효성 검사 규칙**
- HACCP 체크리스트 모든 항목 완료 필수
- 불합격/조건부합격 시 검사 총평 필수 입력
- 검사자 ID = 로그인 사용자 (변경 불가)

---

#### 3.1.4 입고 승인 처리 (SCR-RM-04)

**기능 개요**
품질관리자의 검사 결과를 바탕으로 공장장이 최종 입고 승인/반려를 처리한다.

**입력 데이터 항목**

| 항목 | 필드명 | 설명 |
|------|--------|------|
| 대상 LOT | intake_lot_no | 승인 대상 LOT |
| 승인 여부 | approval_status | 승인/반려/보류연장 |
| 승인 의견 | approval_comment | 자유 기술 |
| 조건부 조치사항 | condition_actions | 조건부합격 시 조치 내용 |

**출력/표시 내용**
- 검사 결과 요약 카드
- AI Agent 품질 기준 비교 의견
- 공급처 최근 3개월 품질 이력 차트
- 승인 처리 완료 시 절임 공정 자동 통보

**비즈니스 로직**
1. 승인 권한: 공장장 또는 위임된 품질관리자
2. 반려 처리 시 공급처에 반품 요청 알림 발송
3. 승인 완료 시 절임LOT 생성 준비 상태로 전환

---

### 3.2 원재료 이력조회

#### 3.2.1 LOT별 이력 조회 (SCR-RM-05)

**기능 개요**
특정 입고LOT의 전체 공정 이력을 타임라인으로 표시한다.

**입력 데이터 항목**
- 입고LOT 번호 (직접 입력 또는 바코드 스캔)
- 또는 기간 + 공급처 조합 검색

**출력/표시 내용**
- 타임라인: 입고 → 검사 → 승인 → 절임 → 발효 → 포장 → 출하 단계별 표시
- 각 단계별 담당자, 처리일시, 핵심 품질 수치
- 현재 재공 위치 표시 (어느 공정에 있는지)
- 이상 발생 이력 빨간색 강조
- PDF/Excel 내보내기

**비즈니스 로직**
- LOT 연계: 입고LOT → 절임LOT → 발효LOT → 포장LOT → 출하LOT 자동 연결
- 연계 LOT가 복수인 경우 (분할 처리) 트리 구조로 표시

---

### 3.3 선별 데이터관리

#### 3.3.1 선별 결과 입력 (SCR-RM-08)

**기능 개요**
입고 후 절단/전처리 이전 선별 공정에서 원재료 등급을 재분류하고 결과를 입력한다.

**입력 데이터 항목**

| 항목 | 필드명 | 데이터타입 | 필수 |
|------|--------|-----------|------|
| 입고LOT | intake_lot_no | VARCHAR(30) | Y |
| 선별일시 | sorting_datetime | TIMESTAMP | Y |
| 선별 담당자 | sorter_id | VARCHAR(20) | Y |
| 선별 결과 | sorting_grade | VARCHAR(10) | Y | A등급 수량/B등급 수량/C등급 수량/폐기량 |
| A등급 중량(kg) | grade_a_weight | DECIMAL(10,2) | Y |
| B등급 중량(kg) | grade_b_weight | DECIMAL(10,2) | Y |
| C등급 중량(kg) | grade_c_weight | DECIMAL(10,2) | Y |
| 폐기 중량(kg) | waste_weight | DECIMAL(10,2) | Y |
| 폐기 사유 | waste_reason | TEXT | N |

**출력/표시 내용**
- 선별 결과 등급별 비율 도넛 차트
- 공급처별 선별 불량률 누적 현황
- 폐기율 기준 초과 시 경고 표시

**비즈니스 로직**
- A등급 + B등급 + C등급 + 폐기량 = 입고 중량 (±2% 허용)
- 폐기율 5% 초과 시 해당 공급처 품질 경고 등록
- C등급 이하 → 절임 공정 투입 시 별도 LOT 관리

---

### 3.4 공급처 품질분석

#### 3.4.1 공급처별 품질 현황 (SCR-RM-11)

**기능 개요**
등록된 공급처별 입고 품질 KPI를 대시보드 형태로 표시한다.

**출력/표시 내용**
- 공급처별 합격률 막대 차트 (최근 3개월)
- 공급처별 외관 등급 분포 차트
- 함수율 평균 및 표준편차
- 공급처 종합 품질 점수 (100점 환산)
- 월별 트렌드 변화 화살표 표시

**비즈니스 로직**
품질 점수 계산식:
- 합격률 × 40점 + 외관등급 평균 × 30점 + 선별 불량률 역수 × 20점 + 납기 준수율 × 10점

---

#### 3.4.2 공급처 평가 관리 (SCR-RM-13)

**기능 개요**
분기별 공급처 공식 평가를 수행하고 등급(A/B/C/D)을 결정한다.

**입력 데이터 항목**

| 항목 | 설명 |
|------|------|
| 평가 기간 | 분기 선택 |
| 공급처 | 평가 대상 |
| 품질 점수 | 시스템 자동 계산값 (조정 가능) |
| 납기 점수 | 수동 입력 |
| 가격 경쟁력 | 수동 입력 |
| 협력도 | 수동 입력 |
| 종합 등급 | A/B/C/D 자동 산정 (수동 조정 가능) |
| 평가 의견 | 자유 기술 |

**비즈니스 로직**
- D등급 공급처: 다음 분기 입고 보류 후 공장장 판단
- 2분기 연속 C등급: 공장장 경고 알림

---

### 3.5 포장실적관리

#### 3.5.1 포장 실적 등록 (SCR-PS-01 / SPD-PS-01)

**기능 개요**
포장 공정에서 완성된 제품의 포장 실적을 LOT 단위로 등록한다.

**입력 데이터 항목**

| 항목 | 필드명 | 데이터타입 | 필수 | 설명 |
|------|--------|-----------|------|------|
| 발효LOT | ferment_lot_no | VARCHAR(30) | Y | 연결된 발효 LOT |
| 포장일시 | packing_datetime | TIMESTAMP | Y | 기본값: 현재시각 |
| 제품코드 | product_code | VARCHAR(20) | Y | 제품 종류 |
| 포장 규격 | package_spec | VARCHAR(20) | Y | 1kg/2kg/5kg 등 |
| 포장 수량 | packed_count | INTEGER | Y | 단위: 개 |
| 총 중량 | total_weight | DECIMAL(10,2) | Y | 단위: kg |
| 포장 LOT | packing_lot_no | VARCHAR(30) | Y | 자동 생성 |
| 금속검출 결과 | metal_detect_result | VARCHAR(10) | Y | 합격/불합격 |
| 포장 담당자 | packer_id | VARCHAR(20) | Y | 로그인 사용자 |
| 유통기한 | expiry_date | DATE | Y | 자동 계산 (생산일+30일 기본) |
| 냉장 보관 온도 | storage_temp | DECIMAL(4,1) | N | 포장실 온도 (단위: ℃) |

**출력/표시 내용**
- 포장 LOT 번호 자동 생성 (형식: `PK-YYYYMMDD-NNN`)
- 금속검출기 실시간 연동 결과 표시
- 자동중량검사기 데이터 자동 반영
- 발효 품질 정보 (연계된 발효LOT의 AI 예측 결과 요약)

**RAG AI Agent 연계 방식**
- 금속검출 불합격 발생 시 AI Agent 자동 호출
- "금속검출 불합격 시 처리 절차" 자동 질의 → 작업표준서 청크 반환

**비즈니스 로직**
1. 포장LOT = 발효LOT + 제품코드 + 포장규격 조합
2. 유통기한: 김치 종류별 기준 자동 적용 (기준정보 관리에서 설정)
3. 금속검출 불합격 시 해당 발효LOT 전체 재검사 필수
4. 자동중량검사기 NG(중량 미달/초과) 발생 시 실시간 알림

**유효성 검사 규칙**
- 총 중량 = 포장 규격 × 포장 수량 (±5% 허용)
- 발효LOT는 "발효 완료 + 품질 합격" 상태여야 함
- 금속검출 불합격 시 포장 실적 등록 불가 (재검사 후 등록)

---

### 3.6 출하관리

#### 3.6.1 출하 승인 처리 (SCR-PS-06 / SPD-PS-05)

**기능 개요**
포장 완료된 제품의 출하 가능 여부를 최종 심사하고 승인한다.

**입력 데이터 항목**

| 항목 | 필드명 | 설명 |
|------|--------|------|
| 포장LOT | packing_lot_no | 출하 대상 LOT |
| 출하 예정일 | ship_plan_date | 출하 예정 날짜 |
| 납품처 | customer_code | 납품처 코드 |
| 운송 차량 | transport_vehicle | 냉장 차량 번호 |
| 출하 검사 결과 | final_inspection | 합격/불합격/조건부 |
| 승인 여부 | approval_status | 승인/보류/반려 |
| AI 검토 결과 | ai_review_result | AI Agent 출하 검토 의견 (참고) |
| 승인자 의견 | approver_comment | 공장장 의견 |

**출력/표시 내용**
- 포장 LOT 상세 정보 (제품코드, 규격, 수량, 유통기한)
- 발효 공정 품질 예측 결과 요약
- AI Agent 출하 승인 검토 의견 카드
- LOT 전체 이력 요약 (입고→출하 핵심 품질 지표)
- 출하 후 냉장 운송 요건 안내

**RAG AI Agent 연계 방식**
- 출하 승인 화면 진입 시 AI Agent 자동 실행
- 해당 LOT의 발효 품질 데이터 + 출하 검사 결과를 컨텍스트로 전달
- "출하 승인 기준 대비 현재 LOT 상태" 검토 요청
- Vector DB에서 출하 승인 기준서 + HACCP CCP 문서 검색
- 검토 결과: 승인권고 / 조건부권고 / 보류권고 중 하나로 표시
- 인간 승인자(공장장)가 AI 의견 참고 후 최종 결정 (AI는 결정권 없음)

**비즈니스 로직**
1. 출하 승인 권한: 공장장 (위임 불가, 보안 정책)
2. AI 검토 의견은 참고 자료이며 법적 효력 없음
3. 출하 승인 완료 시 ERP/기존MES에 출하 데이터 전송
4. 냉장 운송 온도 요건: 0~4℃ (기준정보에서 설정)
5. 승인 후 출하LOT 생성 (형식: `SH-YYYYMMDD-NNN`)

**유효성 검사 규칙**
- 포장LOT 상태 = "포장 완료 + 금속검출 합격" 필수
- 유통기한이 출하일 + 7일 미만 시 경고 표시
- 최종 검사 합격 상태 필수 (불합격 상태에서 승인 버튼 비활성화)

---

### 3.7 LOT 추적

#### 3.7.1 정방향 추적 (입고→출하) (SCR-PS-09)

**기능 개요**
특정 입고LOT가 어떤 제품으로 생산되어 어디로 출하되었는지 전 구간을 추적한다.

**입력 데이터 항목**
- 입고LOT 번호 (또는 공급처 + 입고일 조합)

**출력/표시 내용**
- 공정별 플로우 다이어그램: 입고LOT → 절임LOT → 발효LOT → 포장LOT → 출하LOT
- 각 단계별 품질 수치 및 이상 이력
- 최종 납품처 및 출하일 표시
- 현재 재공 위치 (미출하 상태인 경우)

---

#### 3.7.2 역방향 추적 (출하→입고) (SCR-PS-10)

**기능 개요**
클레임 발생 시 출하LOT를 기준으로 원재료 입고까지 역추적한다.

**입력 데이터 항목**
- 출하LOT 번호 또는 클레임 번호

**출력/표시 내용**
- 역방향 플로우: 출하LOT → 포장LOT → 발효LOT → 절임LOT → 입고LOT
- 원재료 공급처, 입고일, 외관등급, 함수율
- 발효 공정 온도/산도/시간 이력
- 각 공정 담당자 정보
- 클레임 원인 추정 AI 분석 결과

**RAG AI Agent 연계 방식**
- 역방향 추적 실행 시 AI Agent 자동 호출
- "이 LOT의 클레임 원인 분석" 자동 질의
- Vector DB에서 클레임 대응 매뉴얼 + 발효 기준서 검색
- 추적된 공정 데이터 이상 구간 자동 탐지 및 원인 추정

---

### 3.8 클레임분석

#### 3.8.1 클레임 접수 등록 (SCR-PS-15)

**기능 개요**
고객 클레임을 시스템에 등록하고 LOT 역추적을 시작한다.

**입력 데이터 항목**

| 항목 | 필드명 | 데이터타입 | 필수 | 설명 |
|------|--------|-----------|------|------|
| 클레임 접수일 | claim_date | DATE | Y | |
| 고객명 | customer_name | VARCHAR(100) | Y | |
| 연락처 | contact | VARCHAR(30) | Y | |
| 클레임 유형 | claim_type | VARCHAR(30) | Y | 맛/위생/포장/중량/기타 |
| 출하LOT | shipment_lot_no | VARCHAR(30) | Y | |
| 제품 코드 | product_code | VARCHAR(20) | Y | |
| 클레임 내용 | claim_content | TEXT | Y | |
| 증거 첨부 | evidence_files | FILE | N | 사진 등 |
| 긴급도 | urgency | VARCHAR(10) | Y | 즉시/일반/낮음 |

**출력/표시 내용**
- 클레임 번호 자동 생성 (형식: `CL-YYYYMMDD-NNN`)
- 역방향 LOT 추적 자동 실행
- AI Agent 원인 분석 결과 카드
- 대응 가이드 (AI Agent 제공)

**비즈니스 로직**
1. 클레임 접수 즉시 공장장 + 품질관리자 알림 발송
2. 긴급도 = "즉시" 시 SMS/카카오 알림 추가
3. LOT 역추적 자동 실행 후 공정별 이상 여부 자동 표시

---

### 3.9 검사결과관리

#### 3.9.1 출하 검사 결과 입력 (SCR-PS-12 / SPD-PS-03)

**기능 개요**
출하 전 최종 품질 검사 결과를 입력한다.

**입력 데이터 항목**

| 항목 | 필드명 | 데이터타입 | 필수 | 설명 |
|------|--------|-----------|------|------|
| 포장LOT | packing_lot_no | VARCHAR(30) | Y | |
| 검사일시 | inspection_datetime | TIMESTAMP | Y | |
| 검사자 | inspector_id | VARCHAR(20) | Y | |
| 관능검사 — 색 | sensory_color | VARCHAR(10) | Y | 적합/부적합 |
| 관능검사 — 향 | sensory_smell | VARCHAR(10) | Y | 적합/부적합 |
| 관능검사 — 맛 | sensory_taste | VARCHAR(10) | Y | 적합/부적합 |
| 관능검사 — 조직감 | sensory_texture | VARCHAR(10) | Y | 적합/부적합 |
| pH | ph_value | DECIMAL(4,2) | Y | |
| 산도 (%) | acidity | DECIMAL(5,3) | Y | |
| 염도 (%) | salinity | DECIMAL(4,2) | Y | |
| 미생물 검사 결과 | microbial_result | VARCHAR(10) | N | 적합/부적합 |
| HACCP 체크리스트 | haccp_checklist | JSON | Y | |
| 합격 여부 | pass_fail | VARCHAR(10) | Y | |

**비즈니스 로직**
- 합격 기준: pH 4.0~4.6, 산도 0.5~1.5%, 염도 1.5~3.0% (기준정보에서 관리)
- 기준 벗어난 수치 입력 시 자동 색상 경고 (빨간색)
- 합격 시 "출하 승인 대기" 상태로 자동 전환

---

## 4. LOT 추적 흐름도

### 4.1 전체 LOT 흐름

```
[입고 단계]
공급처 → 입고 등록 → 입고 검사 → 입고 승인
       → 입고LOT 생성 (RM-YYYYMMDD-NNN)
              │
              ▼
[선별/전처리 단계]
입고LOT → 선별 결과 입력 → 등급 분류 (A/B/C/폐기)
              │ (A등급, B등급 투입)
              ▼
[절임 단계] ← (절임/발효 관리 모듈 — PM3 담당)
입고LOT → 절임LOT 생성 (CU-YYYYMMDD-NNN)
(절임 온도, 염도, 시간 기록)
              │
              ▼
[발효 단계] ← (절임/발효 관리 모듈 — PM3 담당)
절임LOT → 발효LOT 생성 (FM-YYYYMMDD-NNN)
(발효 온도, 산도, 숙성시간, AI 품질 예측)
              │
              ▼
[금속검출 단계]
발효LOT → 금속검출 검사
              │
              ▼
[포장 단계]
발효LOT → 포장 실적 등록 → 자동중량검사 → 포장LOT 생성 (PK-YYYYMMDD-NNN)
              │
              ▼
[출하 단계]
포장LOT → 출하 검사 → AI Agent 검토 → 공장장 승인 → 출하LOT 생성 (SH-YYYYMMDD-NNN)
              │
              ▼
납품처 도착 → 냉장 온도 이력 기록
```

### 4.2 LOT 분할 규칙

```
상황: 하나의 입고LOT가 여러 절임 배치로 분할될 때

입고LOT: RM-20260523-001
├── 절임LOT: CU-20260523-001 (입고LOT의 60% 투입)
└── 절임LOT: CU-20260523-002 (입고LOT의 40% 투입)
    ├── 발효LOT: FM-20260523-001
    └── 발효LOT: FM-20260523-002
```

### 4.3 LOT 연계 테이블 (lot_traceability)

```sql
-- LOT 연계 추적 테이블
lot_traceability (
  id              BIGSERIAL PRIMARY KEY,
  parent_lot_no   VARCHAR(30) NOT NULL,  -- 상위 공정 LOT
  child_lot_no    VARCHAR(30) NOT NULL,  -- 하위 공정 LOT
  lot_type        VARCHAR(20) NOT NULL,  -- INTAKE/SORTING/CURING/FERMENT/PACKING/SHIPMENT
  split_ratio     DECIMAL(5,4),          -- 분할 비율 (0.0~1.0)
  created_at      TIMESTAMP DEFAULT NOW()
)
```

### 4.4 역추적 흐름 (클레임 대응)

```
클레임 접수 → 출하LOT 확인
        ↓
출하LOT → 포장LOT (패키지 구성 확인)
        ↓
포장LOT → 발효LOT (발효 조건 — 온도/산도/시간 이상 여부)
        ↓
발효LOT → 절임LOT (절임 조건 — 염도/온도/시간 이상 여부)
        ↓
절임LOT → 입고LOT (원재료 공급처, 외관등급, 함수율)
        ↓
원인 추정 AI 분석 결과 도출 (RAG Agent)
```

---

## 5. RAG AI Agent 상세 명세

### 5.1 입고 AI Agent

#### 5.1.1 시스템 아키텍처

```
[SmartPad / Web 사용자 입력]
        ↓
[FastAPI → LangGraph Workflow]
        ↓
[LLM (OpenAI GPT-4o 또는 Claude)]
        ↓
    ┌───────────────────────────────┐
    │ Tool 1: pgvector 문서 검색     │  ← 품질 기준서, SOP, HACCP 문서
    │ Tool 2: PostgreSQL 데이터 조회  │  ← 공급처 이력, LOT 데이터
    │ Tool 3: 경고 알림 발송         │  ← 이상 시 공장장 알림
    └───────────────────────────────┘
        ↓
[답변 생성 + 신뢰도 점수 + 출처 표시]
        ↓
[사용자 화면 출력 + 이력 저장]
```

#### 5.1.2 입고 AI Agent 질문 시나리오 목록 (10개)

| 번호 | 질문 유형 | 예시 질문 | 조회 소스 | 기대 답변 유형 |
|------|----------|----------|---------|--------------|
| Q01 | 품질 기준 조회 | "오늘 입고된 배추 함수율 기준이 몇 %야?" | 품질 기준서 (pgvector) | 수치 + 기준 근거 |
| Q02 | 공급처 이력 조회 | "강원팜 지난 3개월 합격률 어때?" | 공급처 품질 이력 (PostgreSQL) | 통계 + 트렌드 |
| Q03 | 입고 기준 적합 여부 | "오늘 RM-20260523-001 LOT 입고 기준에 맞아?" | LOT 데이터 + 품질 기준서 | 적합/부적합 + 사유 |
| Q04 | 이상 원재료 대응 | "외관등급 D인 배추 들어왔는데 어떻게 해야 해?" | 불량 대응 매뉴얼 (pgvector) | 단계별 처리 절차 |
| Q05 | HACCP 체크 항목 | "배추 입고 시 HACCP 체크해야 할 항목이 뭐야?" | HACCP CCP 관리 문서 (pgvector) | 체크리스트 |
| Q06 | LOT 추적 조회 | "입고LOT RM-20260520-003 지금 어느 공정에 있어?" | LOT 추적 테이블 (PostgreSQL) | 현재 공정 상태 |
| Q07 | 공급처 비교 | "강원팜이랑 한국농산 중 어디가 품질 더 좋아?" | 공급처 품질 데이터 (PostgreSQL) | 비교 분석 |
| Q08 | 작업 절차 안내 | "원재료 입고 절차 처음부터 알려줘" | 작업표준서 SOP (pgvector) | 단계별 가이드 |
| Q09 | 잔류농약 대응 | "잔류농약 검사 부적합 나왔어, 어떻게 해?" | 불량 대응 매뉴얼 (pgvector) | 즉시 조치 절차 |
| Q10 | 함수율 영향 분석 | "함수율이 높으면 절임/발효에 어떤 영향이 있어?" | 절임/발효 기준서 (pgvector) | 영향 설명 + 주의사항 |

#### 5.1.3 Vector DB 문서 목록 및 임베딩 전략 (입고 Agent)

| 문서명 | 파일 유형 | 청크 크기 | 오버랩 | 임베딩 모델 | 업데이트 주기 |
|--------|---------|---------|--------|-----------|------------|
| 배추 입고 품질 기준서 | PDF/Word | 512 token | 50 token | text-embedding-3-small | 연 2회 |
| 원재료 입고 SOP | PDF/Word | 512 token | 50 token | text-embedding-3-small | 분기 1회 |
| HACCP CCP 관리 문서 (입고) | PDF/Excel | 256 token | 30 token | text-embedding-3-small | 변경 시 즉시 |
| 공급처 평가 기준서 | PDF/Word | 512 token | 50 token | text-embedding-3-small | 연 1회 |
| 불량 대응 매뉴얼 (입고) | PDF/Word | 256 token | 30 token | text-embedding-3-small | 변경 시 즉시 |
| 잔류농약 대응 절차서 | PDF | 256 token | 30 token | text-embedding-3-small | 변경 시 즉시 |
| 절임/발효 기준서 (입고 연계) | PDF/Word | 512 token | 50 token | text-embedding-3-small | 분기 1회 |

**임베딩 전략 상세**
- 문서 전처리: 표/이미지 → 텍스트 변환, 헤더/푸터 제거
- 청크 분할: RecursiveCharacterTextSplitter (문단 우선 분할)
- 메타데이터 저장: 문서명, 버전, 발행일, 공정 단계, 페이지 번호
- 검색 전략: Hybrid Search (Dense + Sparse, RRF 방식 결합)
- 검색 결과: Top-5 청크 반환, 유사도 점수 0.7 미만 필터링

---

### 5.2 출하 AI Agent

#### 5.2.1 출하 AI Agent 질문 시나리오 목록 (10개)

| 번호 | 질문 유형 | 예시 질문 | 조회 소스 | 기대 답변 유형 |
|------|----------|----------|---------|--------------|
| Q01 | 출하 승인 기준 | "포장LOT PK-20260523-001 출하해도 돼?" | 출하 기준서 + LOT 품질 데이터 | 승인가능/불가 + 사유 |
| Q02 | LOT 추적 | "출하LOT SH-20260520-002 어디로 갔어?" | 출하 이력 (PostgreSQL) | 납품처 + 출하일 |
| Q03 | 클레임 원인 분석 | "클레임CL-20260522-001 원인이 뭐야?" | 클레임 대응 매뉴얼 + LOT 이력 | 추정 원인 + 근거 |
| Q04 | 불량 대응 가이드 | "산도 기준 초과 제품 어떻게 처리해?" | 불량 대응 매뉴얼 (pgvector) | 단계별 처리 절차 |
| Q05 | 출하 검사 항목 | "출하 전 최종 검사 항목이 뭐야?" | HACCP CCP + 출하 기준서 | 체크리스트 |
| Q06 | 냉장 온도 기준 | "냉장 운송 온도 기준이 몇 도야?" | 품질 기준서 (pgvector) | 온도 범위 + 근거 |
| Q07 | 클레임 대응 절차 | "고객이 맛 클레임 냈어, 어떻게 처리해?" | 클레임 대응 매뉴얼 (pgvector) | 단계별 대응 가이드 |
| Q08 | 발효 품질 조회 | "FM-20260522-003 발효LOT 품질 상태 어때?" | 발효 품질 데이터 (PostgreSQL) | 품질 수치 + AI 예측 결과 |
| Q09 | 출하 이력 통계 | "이번 달 출하 불량률이 몇 %야?" | 출하/검사 데이터 (PostgreSQL) | 통계 수치 + 트렌드 |
| Q10 | HACCP 위반 대응 | "CCP 기준 벗어난 제품 출하 요청 왔는데?" | HACCP CCP 관리 문서 (pgvector) | 출하 금지 근거 + 처리 절차 |

#### 5.2.2 Vector DB 문서 목록 및 임베딩 전략 (출하 Agent)

| 문서명 | 파일 유형 | 청크 크기 | 오버랩 | 임베딩 모델 | 업데이트 주기 |
|--------|---------|---------|--------|-----------|------------|
| 출하 품질 기준서 | PDF/Word | 512 token | 50 token | text-embedding-3-small | 분기 1회 |
| 포장/출하 SOP | PDF/Word | 512 token | 50 token | text-embedding-3-small | 분기 1회 |
| HACCP CCP 관리 문서 (출하) | PDF/Excel | 256 token | 30 token | text-embedding-3-small | 변경 시 즉시 |
| 불량 대응 매뉴얼 (출하) | PDF/Word | 256 token | 30 token | text-embedding-3-small | 변경 시 즉시 |
| 클레임 대응 매뉴얼 | PDF/Word | 256 token | 30 token | text-embedding-3-small | 변경 시 즉시 |
| 냉장 운송 기준서 | PDF | 256 token | 30 token | text-embedding-3-small | 연 1회 |
| 절임/발효 기준서 (출하 연계) | PDF/Word | 512 token | 50 token | text-embedding-3-small | 분기 1회 |

---

### 5.3 답변 생성 로직

#### 5.3.1 LangGraph 워크플로우

```
[사용자 질문]
    ↓
[의도 분류 노드]
  - 정형 데이터 조회 (DB Query)
  - 비정형 문서 검색 (RAG)
  - 복합 (DB + RAG)
    ↓
[병렬 실행]
  ├── [pgvector 문서 검색] → 관련 청크 Top-5 반환
  └── [PostgreSQL 데이터 조회] → 정형 데이터 반환
    ↓
[컨텍스트 통합 노드]
  - 문서 청크 + 정형 데이터 결합
  - 충돌/모순 탐지
    ↓
[LLM 답변 생성 노드]
  - System Prompt: 김치 제조 전문 AI Agent 역할 정의
  - Context: 검색된 청크 + 데이터
  - User Query: 사용자 질문
    ↓
[출처 추출 노드]
  - 답변에 사용된 문서명, 버전, 페이지 추출
    ↓
[신뢰도 산정 노드]
  - 검색 유사도 점수 기반 신뢰도 계산
    ↓
[최종 출력]
```

#### 5.3.2 System Prompt 구조 (입고 Agent)

```
당신은 평창꽃순이(주) 김치 공장의 원재료 입고 전문 AI 어시스턴트입니다.

역할:
- 원재료 입고 품질 기준 안내
- 공급처 품질 이력 분석
- HACCP 체크포인트 가이드
- 이상 원재료 처리 절차 안내
- LOT 이력 조회 지원

답변 규칙:
1. 반드시 제공된 문서와 데이터에 근거하여 답변
2. 추측이나 가정은 명확히 "추정:" 으로 표시
3. 안전/HACCP 관련 사항은 항상 보수적으로 판단
4. 답변 끝에 반드시 출처 문서 명시
5. 한국어로 답변, 전문 용어는 괄호에 설명 추가
6. AI 의견은 참고용이며 최종 결정은 담당자가 함을 고지

오늘 날짜: {current_date}
현재 사용자: {user_name} ({user_role})
```

---

### 5.4 신뢰도 표시 방식

| 신뢰도 구간 | 표시 색상 | 표시 텍스트 | 권장 행동 |
|-----------|---------|----------|---------|
| 90% 이상 | 초록색 | "높은 신뢰도" | 참고하여 결정 |
| 70~89% | 파란색 | "보통 신뢰도" | 내용 검토 후 결정 |
| 50~69% | 노란색 | "낮은 신뢰도" | 추가 확인 권장 |
| 50% 미만 | 회색 | "근거 불충분" | 전문가 직접 확인 |

신뢰도 계산:
```
신뢰도 = (검색 문서 최고 유사도 × 0.6) + (출처 문서 최신성 점수 × 0.2) + (정형 데이터 존재 여부 × 0.2)
```

---

### 5.5 히스토리 관리

**저장 테이블: ai_query_history**

```sql
ai_query_history (
  id              BIGSERIAL PRIMARY KEY,
  agent_type      VARCHAR(20),      -- INTAKE / SHIPMENT
  user_id         VARCHAR(20),
  user_role       VARCHAR(20),
  device_type     VARCHAR(20),      -- WEB / SMARTPAD
  lot_no          VARCHAR(30),      -- 연관 LOT (있는 경우)
  question        TEXT,
  answer          TEXT,
  source_docs     JSONB,            -- [{doc_name, version, page, similarity}]
  confidence_score DECIMAL(4,3),
  feedback        VARCHAR(10),      -- HELPFUL / NOT_HELPFUL / NULL
  session_id      UUID,
  created_at      TIMESTAMP DEFAULT NOW()
)
```

**히스토리 활용**
- 사용자별 최근 10개 질문 자동 표시 (재질의 편의)
- 동일 질문 패턴 분석 → FAQ 자동 생성 (월 1회 배치)
- 부정적 피드백 누적 시 문서 업데이트 알림

---

## 6. SmartPad 전용 화면 명세

### 6.1 SmartPad 공통 설계 원칙

- 화면 해상도: 최소 10인치 이상 태블릿 기준
- 버튼 크기: 최소 60px 높이 (장갑 착용 환경)
- 글자 크기: 최소 18px
- 색상 대비: WCAG AA 기준 이상
- 네트워크 불안정 대비: 오프라인 임시 저장 기능 (로컬 캐시)
- 언어: 한국어, 폰트 명확도 우선

### 6.2 입고 SmartPad 화면 흐름

```
[로그인 화면]
    ↓ (PIN 또는 바코드 스캔)
[메인 메뉴 — 입고 SmartPad]
    ├── [오늘 입고 현황] — 건수, 상태 요약
    ├── [입고 등록] → SPD-RM-01
    ├── [검사 체크리스트] → SPD-RM-03
    └── [AI Agent] → SPD-RM-04
            ↓
[입고 등록 화면 (SPD-RM-01)]
    1단계: 공급처 선택 (버튼 그리드)
    2단계: LOT 바코드 스캔 (SPD-RM-02) 또는 수동 입력
    3단계: 입고량 숫자패드 입력
    4단계: 외관등급 선택 (A/B/C/D 대형 버튼)
    5단계: 함수율 입력 (있는 경우)
            ↓
[검사 체크리스트 (SPD-RM-03)]
    - HACCP CCP 항목 체크박스 (전체 표시)
    - 이물질/부패 여부 토글 버튼
    - 합격/불합격 최종 선택
    - "AI에게 물어보기" 플로팅 버튼
            ↓
[입고 완료 확인 (SPD-RM-05)]
    - 입력 내용 요약 표시
    - AI Agent 검토 의견 표시
    - 확인/수정 버튼
    - 확인 시 LOT 생성 완료 메시지
```

#### 6.2.1 입고 SmartPad 입력 필드 상세 (SPD-RM-01)

| 단계 | 필드 | UI 컴포넌트 | 입력 방식 |
|------|------|-----------|---------|
| 1 | 공급처 | 버튼 그리드 (6개) | 터치 |
| 2 | LOT 바코드 | 카메라 뷰 | 스캔 또는 수동 |
| 3 | 입고량 (kg) | 숫자패드 | 터치 |
| 3 | 포장 수량 | 숫자패드 | 터치 |
| 4 | 외관 등급 | A/B/C/D 대형 버튼 | 터치 |
| 5 | 함수율 | 슬라이더 + 숫자패드 | 터치 |
| - | 비고 | 음성 입력 → 텍스트 | STT |

#### 6.2.2 입고 SmartPad AI Agent 화면 (SPD-RM-04)

**화면 구성**
- 상단: 현재 LOT 컨텍스트 표시 (LOT 번호, 공급처, 현재 단계)
- 중앙: 채팅 버블 (Q&A 히스토리)
- 하단: 입력 영역 (음성 버튼 + 텍스트 입력)
- 좌측: 자주 쓰는 질문 바로가기 버튼 5개

**자주 쓰는 질문 (Quick Access)**
1. "이 배추 입고 기준에 맞아?"
2. "지금 체크해야 할 HACCP 항목?"
3. "이 공급처 최근 품질 어때?"
4. "외관등급 [D] 배추 처리 방법?"
5. "오늘 입고 절차 안내해줘"

---

### 6.3 출하 SmartPad 화면 흐름

```
[로그인 화면]
    ↓ (PIN 또는 바코드 스캔)
[메인 메뉴 — 출하 SmartPad]
    ├── [오늘 출하 현황] — 건수, 승인 상태
    ├── [포장 실적 입력] → SPD-PS-01
    ├── [출하 검사 체크리스트] → SPD-PS-03
    ├── [출하 승인 확인] → SPD-PS-05
    └── [AI Agent] → SPD-PS-04
            ↓
[포장 실적 입력 화면 (SPD-PS-01)]
    1단계: 발효LOT 바코드 스캔
    2단계: 제품 규격 선택 (1kg/2kg/5kg 대형 버튼)
    3단계: 포장 수량 숫자패드 입력
    4단계: 금속검출 결과 확인 (자동 연동)
            ↓
[중량 검사 결과 확인 (SPD-PS-02)]
    - 자동중량검사기 실시간 데이터 표시
    - NG 발생 시 빨간 경고 화면
    - OK/NG 현황 막대 표시
            ↓
[출하 검사 체크리스트 (SPD-PS-03)]
    - HACCP CCP 출하 체크 항목
    - 관능검사 항목 (색/향/맛/조직감)
    - pH/산도/염도 수치 입력
    - "AI에게 물어보기" 플로팅 버튼
            ↓
[출하 승인 확인 화면 (SPD-PS-05)]
    - 포장LOT 상세 정보
    - AI Agent 출하 검토 의견
    - 공장장 최종 승인 버튼 (생체인증/PIN)
    - 승인 완료 시 출하LOT 번호 표시
```

#### 6.3.1 출하 SmartPad 확인 절차 상세 (SPD-PS-05)

```
출하 승인 확인 절차:
Step 1. AI Agent 출하 검토 의견 확인 (필수 읽기, 스크롤 확인)
Step 2. 검사 결과 체크리스트 완료 확인 (미완료 항목 표시)
Step 3. 납품처/출하 차량 정보 최종 확인
Step 4. 공장장 PIN 입력 또는 생체인증
Step 5. 출하 승인 완료 → 출하LOT 번호 생성
Step 6. 운전기사에게 출하 확인서 QR 출력 (선택)
```

---

## 7. 사용자 스토리

### 7.1 현장 작업자 (입고 담당) 관점

**US-001**: 입고 데이터 빠른 입력
```
As a: 입고 공정 현장 작업자
I want to: SmartPad로 입고 데이터를 빠르게 입력하고 싶다
So that: 입고 처리 시간을 줄이고 실수를 방지할 수 있다

Acceptance Criteria:
- SmartPad에서 공급처 선택부터 LOT 생성까지 3분 이내 완료
- 바코드 스캔으로 공급처/LOT 정보 자동 입력
- 장갑 착용 상태에서도 모든 버튼 조작 가능
- 입력 오류 시 명확한 에러 메시지 표시
```

**US-002**: AI Agent 자연어 질의
```
As a: 입고 공정 현장 작업자
I want to: 궁금한 것을 자연어로 AI에게 물어보고 싶다
So that: 매뉴얼을 찾지 않고도 빠르게 처리 방법을 알 수 있다

Acceptance Criteria:
- "이 배추 입고해도 돼?" 수준의 자연어 질문 처리 가능
- 답변 생성 시간 5초 이내
- 음성 입력 지원 (STT)
- 답변에 출처 문서 표시
- 신뢰도가 낮을 때 경고 표시
```

**US-003**: HACCP 체크리스트
```
As a: 입고 공정 현장 작업자
I want to: HACCP 체크리스트를 빠짐없이 작성하고 싶다
So that: 위생 기준을 준수하고 감사 대응을 할 수 있다

Acceptance Criteria:
- 원재료 품목별 맞춤 체크리스트 자동 생성
- 미완료 항목 있으면 입고 완료 처리 불가
- 체크 완료 시 디지털 서명 저장
```

---

### 7.2 품질 관리자 관점

**US-004**: 공급처 품질 분석
```
As a: 품질관리자
I want to: 공급처별 품질 트렌드를 분석하고 싶다
So that: 품질이 저하되는 공급처를 사전에 파악할 수 있다

Acceptance Criteria:
- 공급처별 합격률, 외관등급 분포, 함수율 평균 차트 제공
- 최근 3개월 트렌드 꺾은선 그래프
- 품질 점수 하락 추세 시 자동 경고 알림
- AI Agent에게 "공급처 X 최근 품질 어때?" 자연어 조회 가능
```

**US-005**: 클레임 원인 역추적
```
As a: 품질관리자
I want to: 클레임 발생 시 원인을 빠르게 추적하고 싶다
So that: 재발 방지 조치를 신속하게 할 수 있다

Acceptance Criteria:
- 출하LOT 입력 시 입고LOT까지 역방향 추적 자동 실행
- 각 공정별 이상 여부 자동 표시
- AI Agent의 클레임 원인 추정 의견 제공 (출처 근거 포함)
- LOT 추적 결과 PDF 출력 기능
```

**US-006**: 출하 전 품질 검사
```
As a: 품질관리자
I want to: 출하 전 최종 검사 체크리스트를 체계적으로 수행하고 싶다
So that: 기준 미달 제품이 출하되는 것을 방지할 수 있다

Acceptance Criteria:
- HACCP CCP 출하 체크 항목 디지털 체크리스트
- pH/산도/염도 입력 시 기준 벗어나면 즉시 색상 경고
- 미합격 항목 있으면 출하 승인 버튼 비활성화
```

---

### 7.3 공장장 관점

**US-007**: 출하 최종 승인
```
As a: 공장장
I want to: AI Agent의 출하 검토 의견을 참고하여 최종 승인을 내리고 싶다
So that: 품질 기준에 맞는 제품만 출하되도록 통제할 수 있다

Acceptance Criteria:
- AI Agent 출하 검토 의견이 승인 화면에 항상 표시
- AI 의견 = 참고용, 최종 결정권은 공장장에게 있음을 UI에서 명시
- SmartPad에서도 공장장 승인 처리 가능 (PIN/생체인증)
- 승인/반려 이력 모두 기록 (추적 가능)
```

**US-008**: 원재료 현황 대시보드
```
As a: 공장장
I want to: 오늘 입고 현황과 품질 상태를 한눈에 파악하고 싶다
So that: 공장 운영 상황을 신속하게 판단할 수 있다

Acceptance Criteria:
- 오늘 입고 건수, 합격률, 보류 건수 요약 카드
- 공급처별 입고 현황 차트
- 경보 발생 시 대시보드 상단에 빨간 배너 표시
- 모바일에서도 접근 가능
```

**US-009**: 입고 이상 즉시 알림
```
As a: 공장장
I want to: 입고 이상 상황이 발생하면 즉시 알림을 받고 싶다
So that: 현장에 없어도 빠르게 대응할 수 있다

Acceptance Criteria:
- 잔류농약 부적합 → 5분 이내 카카오/SMS 알림
- 외관등급 D 입고 → 시스템 알림 + 이메일
- 알림 내용에 LOT 번호, 공급처, 이슈 요약 포함
```

---

## 8. 데이터 요구사항

### 8.1 원재료관리 핵심 테이블

#### 8.1.1 suppliers (공급처 기본 정보)
```sql
suppliers (
  supplier_code     VARCHAR(20) PRIMARY KEY,  -- 공급처 코드
  supplier_name     VARCHAR(100) NOT NULL,     -- 공급처명
  contact_name      VARCHAR(50),               -- 담당자명
  contact_phone     VARCHAR(30),               -- 연락처
  address           TEXT,                      -- 주소
  business_no       VARCHAR(20),               -- 사업자번호
  supplier_grade    CHAR(1),                   -- 평가 등급 (A/B/C/D)
  is_active         BOOLEAN DEFAULT TRUE,       -- 활성 여부
  registered_at     TIMESTAMP DEFAULT NOW(),
  updated_at        TIMESTAMP
)
```

#### 8.1.2 raw_material_lots (입고 LOT)
```sql
raw_material_lots (
  intake_lot_no       VARCHAR(30) PRIMARY KEY,  -- 입고LOT (RM-YYYYMMDD-NNN)
  supplier_code       VARCHAR(20) REFERENCES suppliers,
  material_code       VARCHAR(20) NOT NULL,     -- 원재료 품목코드
  intake_datetime     TIMESTAMP NOT NULL,
  origin              VARCHAR(50),              -- 원산지
  vehicle_no          VARCHAR(20),
  intake_qty          DECIMAL(10,2) NOT NULL,   -- 입고 중량 (kg)
  package_unit        VARCHAR(20),
  package_count       INTEGER,
  cabbage_size_grade  VARCHAR(10),              -- S/M/L/XL
  appearance_grade    CHAR(1),                  -- A/B/C/D
  moisture_content    DECIMAL(5,2),             -- 함수율 (%)
  measured_weight     DECIMAL(10,2),
  intake_status       VARCHAR(20) DEFAULT '검사대기',
  remark              TEXT,
  created_by          VARCHAR(20),
  created_at          TIMESTAMP DEFAULT NOW()
)
```

#### 8.1.3 intake_inspections (입고 검사 결과)
```sql
intake_inspections (
  inspection_id       BIGSERIAL PRIMARY KEY,
  intake_lot_no       VARCHAR(30) REFERENCES raw_material_lots,
  inspection_datetime TIMESTAMP NOT NULL,
  inspector_id        VARCHAR(20) NOT NULL,
  visual_status       VARCHAR(10),
  foreign_matter      BOOLEAN,
  decay_status        BOOLEAN,
  pesticide_result    VARCHAR(10),
  salinity_before     DECIMAL(4,2),
  ph_before           DECIMAL(4,2),
  inspection_summary  TEXT,
  pass_fail           VARCHAR(20) NOT NULL,   -- 합격/불합격/조건부합격
  haccp_checklist     JSONB,
  created_at          TIMESTAMP DEFAULT NOW()
)
```

#### 8.1.4 supplier_quality_scores (공급처 품질 점수)
```sql
supplier_quality_scores (
  score_id          BIGSERIAL PRIMARY KEY,
  supplier_code     VARCHAR(20) REFERENCES suppliers,
  evaluation_year   INTEGER,
  evaluation_quarter INTEGER,              -- 1/2/3/4
  pass_rate         DECIMAL(5,4),          -- 합격률
  avg_appearance    DECIMAL(4,2),          -- 외관등급 평균 점수
  sort_defect_rate  DECIMAL(5,4),          -- 선별 불량률
  delivery_rate     DECIMAL(5,4),          -- 납기 준수율
  quality_score     DECIMAL(6,2),          -- 종합 품질 점수
  overall_grade     CHAR(1),               -- A/B/C/D
  evaluator_id      VARCHAR(20),
  eval_comment      TEXT,
  created_at        TIMESTAMP DEFAULT NOW()
)
```

---

### 8.2 포장출하관리 핵심 테이블

#### 8.2.1 packing_lots (포장 LOT)
```sql
packing_lots (
  packing_lot_no    VARCHAR(30) PRIMARY KEY,  -- 포장LOT (PK-YYYYMMDD-NNN)
  ferment_lot_no    VARCHAR(30) NOT NULL,      -- 연결 발효LOT
  product_code      VARCHAR(20) NOT NULL,
  package_spec      VARCHAR(20) NOT NULL,      -- 1kg/2kg/5kg 등
  packed_count      INTEGER NOT NULL,
  total_weight      DECIMAL(10,2) NOT NULL,
  metal_detect_result VARCHAR(10),             -- 합격/불합격
  storage_temp      DECIMAL(4,1),
  expiry_date       DATE NOT NULL,
  packer_id         VARCHAR(20),
  packing_datetime  TIMESTAMP,
  packing_status    VARCHAR(20) DEFAULT '포장완료',
  created_at        TIMESTAMP DEFAULT NOW()
)
```

#### 8.2.2 shipment_lots (출하 LOT)
```sql
shipment_lots (
  shipment_lot_no   VARCHAR(30) PRIMARY KEY,  -- 출하LOT (SH-YYYYMMDD-NNN)
  packing_lot_no    VARCHAR(30) REFERENCES packing_lots,
  customer_code     VARCHAR(20),
  ship_plan_date    DATE,
  ship_actual_date  DATE,
  transport_vehicle VARCHAR(20),
  transport_temp    DECIMAL(4,1),             -- 냉장 운송 온도
  final_inspection  VARCHAR(10),              -- 합격/불합격
  approval_status   VARCHAR(20),              -- 승인/보류/반려
  approver_id       VARCHAR(20),
  approval_datetime TIMESTAMP,
  ai_review_summary TEXT,                     -- AI Agent 검토 요약
  approver_comment  TEXT,
  created_at        TIMESTAMP DEFAULT NOW()
)
```

#### 8.2.3 claims (클레임)
```sql
claims (
  claim_no          VARCHAR(30) PRIMARY KEY,  -- 클레임 번호 (CL-YYYYMMDD-NNN)
  claim_date        DATE NOT NULL,
  customer_name     VARCHAR(100),
  contact           VARCHAR(30),
  claim_type        VARCHAR(30),              -- 맛/위생/포장/중량/기타
  shipment_lot_no   VARCHAR(30) REFERENCES shipment_lots,
  product_code      VARCHAR(20),
  claim_content     TEXT,
  evidence_files    JSONB,                    -- 첨부 파일 경로 목록
  urgency           VARCHAR(10),              -- 즉시/일반/낮음
  claim_status      VARCHAR(20) DEFAULT '접수',
  ai_cause_analysis TEXT,                    -- AI Agent 원인 분석 결과
  root_cause        TEXT,                    -- 확정 원인
  action_taken      TEXT,                    -- 처리 내용
  closed_date       DATE,
  handler_id        VARCHAR(20),
  created_at        TIMESTAMP DEFAULT NOW()
)
```

#### 8.2.4 lot_traceability (LOT 연계 추적)
```sql
lot_traceability (
  id              BIGSERIAL PRIMARY KEY,
  parent_lot_no   VARCHAR(30) NOT NULL,
  child_lot_no    VARCHAR(30) NOT NULL,
  lot_type        VARCHAR(20) NOT NULL,       -- INTAKE/SORTING/CURING/FERMENT/PACKING/SHIPMENT
  split_ratio     DECIMAL(5,4),
  created_at      TIMESTAMP DEFAULT NOW(),
  UNIQUE (parent_lot_no, child_lot_no)
)
-- 인덱스: parent_lot_no, child_lot_no 각각 생성
```

#### 8.2.5 final_inspections (출하 검사 결과)
```sql
final_inspections (
  inspection_id       BIGSERIAL PRIMARY KEY,
  packing_lot_no      VARCHAR(30) REFERENCES packing_lots,
  inspection_datetime TIMESTAMP NOT NULL,
  inspector_id        VARCHAR(20) NOT NULL,
  sensory_color       VARCHAR(10),
  sensory_smell       VARCHAR(10),
  sensory_taste       VARCHAR(10),
  sensory_texture     VARCHAR(10),
  ph_value            DECIMAL(4,2),
  acidity             DECIMAL(5,3),
  salinity            DECIMAL(4,2),
  microbial_result    VARCHAR(10),
  haccp_checklist     JSONB,
  pass_fail           VARCHAR(20) NOT NULL,
  created_at          TIMESTAMP DEFAULT NOW()
)
```

---

### 8.3 AI Agent 관련 테이블

#### 8.3.1 ai_query_history (AI 질의 이력)
```sql
ai_query_history (
  id                BIGSERIAL PRIMARY KEY,
  agent_type        VARCHAR(20) NOT NULL,   -- INTAKE / SHIPMENT
  user_id           VARCHAR(20),
  user_role         VARCHAR(20),
  device_type       VARCHAR(20),            -- WEB / SMARTPAD
  lot_no            VARCHAR(30),
  question          TEXT NOT NULL,
  answer            TEXT,
  source_docs       JSONB,                  -- [{doc_name, version, page, similarity}]
  confidence_score  DECIMAL(4,3),
  feedback          VARCHAR(20),            -- HELPFUL / NOT_HELPFUL / NULL
  session_id        UUID,
  response_time_ms  INTEGER,                -- 응답 시간 (ms)
  created_at        TIMESTAMP DEFAULT NOW()
)
```

#### 8.3.2 vector_documents (Vector DB 문서 메타데이터)
```sql
-- pgvector DB에 관리 (임베딩 벡터 포함)
vector_documents (
  doc_id          BIGSERIAL PRIMARY KEY,
  doc_name        VARCHAR(200) NOT NULL,
  doc_type        VARCHAR(50),              -- SOP/QUALITY_STANDARD/HACCP/MANUAL 등
  process_stage   VARCHAR(50),              -- INTAKE/SHIPMENT/ALL 등
  version         VARCHAR(20),
  effective_date  DATE,
  chunk_count     INTEGER,
  embedding_model VARCHAR(100),
  is_active       BOOLEAN DEFAULT TRUE,
  uploaded_by     VARCHAR(20),
  uploaded_at     TIMESTAMP DEFAULT NOW()
)
```

---

## 9. 클레임 처리 프로세스

### 9.1 클레임 처리 단계별 흐름

```
[1단계: 클레임 접수]
고객 연락 → CS 담당자가 클레임 접수 등록 (SCR-PS-15)
  - 클레임 번호 자동 생성
  - 긴급도 설정
  - 즉시 공장장 + 품질관리자 알림 발송
        ↓
[2단계: 초기 대응] (접수 후 2시간 이내)
공장장/품질관리자 확인 → 고객에게 접수 확인 연락
  - 출하LOT 확인
  - 해당 LOT 동일 배치 제품 추가 출하 임시 보류 (필요 시)
        ↓
[3단계: LOT 역추적 + AI 원인 분석]
시스템 자동 실행:
  출하LOT → 포장LOT → 발효LOT → 절임LOT → 입고LOT 역추적
AI Agent 자동 호출:
  - 각 공정 데이터 이상 여부 분석
  - Vector DB에서 유사 클레임 패턴 검색
  - 원인 추정 의견 생성 (근거 출처 포함)
        ↓
[4단계: 현장 조사] (접수 후 24시간 이내)
품질관리자가 AI 분석 결과 검토:
  - 의심 공정 현장 확인
  - 잔여 재고 샘플링 검사 (동일 LOT)
  - 추가 증거 수집 (사진, 측정값)
        ↓
[5단계: 원인 확정 + 처리 결정]
품질관리자 + 공장장 협의:
  - 원인 확정 (입고 품질 / 절임 조건 / 발효 이상 / 포장 불량 / 운송 중 이상)
  - 처리 방향 결정 (교환/환불/할인 보상/기타)
  - 재발 방지 조치 수립
        ↓
[6단계: 고객 대응] (접수 후 48~72시간 이내)
  - 고객에게 원인 설명 및 처리 결과 안내
  - 교환/환불 등 실행
  - 재발 방지 조치 공유
        ↓
[7단계: 클레임 종결 + 데이터 축적]
  - 클레임 상태 "종결" 처리
  - 원인, 조치 내용 시스템 저장
  - 월별 클레임 통계 분석에 반영
  - 필요 시 공급처 품질 점수 하향 조정
  - 필요 시 Vector DB 대응 매뉴얼 업데이트
```

### 9.2 클레임 유형별 처리 기준

| 클레임 유형 | 일반 처리 기준 | 역추적 핵심 공정 | 재발 방지 |
|-----------|-------------|---------------|---------|
| 맛 이상 | 발효 조건 이상 우선 확인 | 발효LOT 온도/산도 이력 | 발효 기준 준수 강화 |
| 위생 문제 | HACCP 기록 즉시 확인 | 전 공정 HACCP 체크 이력 | HACCP 절차 강화 |
| 중량 미달 | 자동중량검사 기록 확인 | 포장LOT 중량 데이터 | 중량검사기 검교정 |
| 포장 불량 | 포장 공정 담당자 확인 | 포장LOT 담당자 및 설비 | 포장 설비 점검 |
| 이물질 | 금속검출 기록 + 전 공정 이물질 확인 | 전 공정 이물질 체크 이력 | 이물질 관리 강화 |

---

## 10. HACCP 연계 체크포인트

### 10.1 원재료 입고 HACCP CCP

| CCP 번호 | 위해 요소 | 관리 기준 | 모니터링 방법 | 시스템 연계 |
|---------|---------|---------|------------|-----------|
| CCP-RM-01 | 잔류농약 | 농약 허용 기준 이하 | 입고 시 검사 결과 입력 | 부적합 시 공장장 즉시 알림 |
| CCP-RM-02 | 이물질 혼입 | 이물질 없음 | 시각적 검사 + 체크리스트 | 이물질 있음 선택 시 입고 자동 보류 |
| CCP-RM-03 | 부패/변질 | 부패 없음 | 관능검사 + 체크리스트 | 부패 있음 선택 시 불합격 자동 처리 |
| CCP-RM-04 | 미생물 오염 | 대장균군 기준 이하 | 정기 미생물 검사 | 검사 결과 DB 연동 |

### 10.2 포장/출하 HACCP CCP

| CCP 번호 | 위해 요소 | 관리 기준 | 모니터링 방법 | 시스템 연계 |
|---------|---------|---------|------------|-----------|
| CCP-PS-01 | 금속 이물질 | 금속검출기 통과 | 자동 금속검출기 연동 | 불합격 시 포장 실적 등록 차단 |
| CCP-PS-02 | 중량 미달 | 포장 규격 중량 ±5% | 자동중량검사기 연동 | NG 시 실시간 알림 |
| CCP-PS-03 | pH/산도 기준 | pH 4.0~4.6, 산도 0.5~1.5% | 출하 검사 수치 입력 | 기준 이탈 시 색상 경고 + 출하 차단 |
| CCP-PS-04 | 냉장 온도 | 포장실 온도 10℃ 이하 | 자동 온도 센서 연동 | 기준 이탈 시 즉시 알림 |
| CCP-PS-05 | 운송 냉장 온도 | 0~4℃ | 운송 온도 이력 입력 | 기준 이탈 차량 출하 차단 |

### 10.3 HACCP 체크리스트 디지털 관리 규칙

1. **체크리스트 완료 필수**: 미완료 항목 있으면 다음 단계 진행 불가
2. **디지털 서명 저장**: 체크리스트 완료 시 작업자 ID + 일시 자동 기록
3. **변경 불가 원칙**: 저장된 HACCP 기록은 수정 불가 (정정 시 재기록 + 사유 필수)
4. **보존 기간**: HACCP 기록 최소 3년 보존 (법적 요건)
5. **감사 추적**: 모든 HACCP 기록 조회/다운로드 이력 로그
6. **이상 발생 자동 에스컬레이션**:
   - CCP 위반 발생 → 담당자 즉시 알림
   - 미조치 15분 경과 → 공장장 자동 알림
   - 미조치 30분 경과 → 품질관리자 자동 알림

### 10.4 HACCP 문서 Vector DB 임베딩 관리

- HACCP CCP 관리 계획서 개정 시 즉시 재임베딩 수행
- 구 버전 문서 비활성화 (is_active = FALSE), 기록은 유지
- AI Agent가 HACCP 관련 질문 답변 시 항상 현행 버전 문서 우선 사용
- HACCP 관련 답변에는 반드시 문서 버전 및 발행일 표시

---

## 버전 이력

| 버전 | 날짜 | 변경 내용 | 작성자 |
|------|------|---------|-------|
| 1.0 | 2026-05-23 | 최초 작성 | PM2 |

## 관련 문서
- CLAUDE.md: 시스템 전체 아키텍처
- 담당 모듈: 원재료관리(모듈 1), 포장출하관리(모듈 2)
- 연계 모듈: 숙성발효관리(PM3 담당), AI 대시보드(PM1 담당)
