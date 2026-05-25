# Shadow Mode 운영 가이드

> 꽃순이김치 제조AI MES · 프로젝트 SF26179540 · 로뎀솔루션 주식회사
> 시범운영(파일럿 검증) 단계 현장 매뉴얼

## 개요

꽃순이김치 MES의 AI(발효 품질 예측, 원재료 입고/출하 Agent)는 **조회·분석·추천·경고**만 수행합니다.
AI가 생성한 추천은 **작업자/관리자의 승인을 거친 후에만** 공정에 반영됩니다.

```
AI 추천 생성  →  담당자 검토  →  승인 / 거절  →  (승인 시) 공정 반영
```

이를 **Shadow Mode**라고 하며, 시범운영 기간(3개월) 동안 항상 활성(ON) 상태로 운영합니다.

---

## 승인 프로세스

1. **AI 추천 생성** — 발효 ML 엔진 또는 RAG Agent가 추천을 생성합니다.
   (예: 발효 조건 변경, 출하 승인 가능 여부, 품질 예외 처리)
2. **승인 대기열 등록** — 추천이 `approval_item` 테이블에 `PENDING` 상태로 등록됩니다.
3. **담당자 알림** — 담당자에게 알림이 발송됩니다 (이메일/시스템 알림).
4. **추천 검토** — 담당자가 AI 추천 내용과 근거 데이터(현재 상태, 제안 변경, 신뢰도)를 확인합니다.
5. **승인 또는 거절**
   - 승인: 승인 메모 입력 (선택)
   - 거절: **거절 사유 필수 입력**
6. **공정 반영** — 승인된 항목(`APPROVED`)을 해당 모듈/배치가 폴링하여 공정 데이터에 반영합니다.

> 24시간 이내에 처리되지 않은 항목은 자동으로 **만료(EXPIRED)** 처리됩니다.

---

## 승인 항목 유형 및 권한

| 추천 유형 (item_type) | 설명 | 승인 권한 |
|----------------------|------|----------|
| `FERMENTATION_CONDITION` | 절임/발효 조건 변경 | 공장장(PLANT_MANAGER), 관리자(MANAGER) |
| `SHIPPING_APPROVAL` | 출하 최종 승인 | 공장장, 관리자 |
| `QUALITY_OVERRIDE` | 품질 기준 예외 처리 | 공장장 |
| `LOT_STATUS_CHANGE` | LOT 상태 변경 | 품질담당자(QC), 관리자 |

> ADMIN은 모든 유형을 승인할 수 있으며, Shadow Mode ON/OFF 토글 권한을 가집니다.

---

## 상태 흐름

| 상태 | 의미 |
|------|------|
| `PENDING` | 승인 대기 (신규 등록) |
| `APPROVED` | 승인 완료 → 공정 반영 대상 |
| `REJECTED` | 거절 (사유 기록됨) |
| `EXPIRED` | 24시간 미처리로 자동 만료 |

```
PENDING ──(승인)──▶ APPROVED ──▶ 공정 반영
        ──(거절)──▶ REJECTED
        ──(24h 경과)──▶ EXPIRED
```

---

## 화면 사용법 (승인 대시보드)

실행: `streamlit run app/pages/ui_shadow_approval.py`

### 1. 승인 대기 목록 탭
- 항목별 카드로 표시: AI 추천 내용 + 현재 상태 + 제안 변경 + **신뢰도 게이지(0~100%)**
- 유형 / LOT ID 필터 지원
- 만료 카운트다운 표시 (3시간 미만 시 빨강 경고)
- **승인** 버튼 / **거절** 버튼 (거절 시 사유 필수)

### 2. 승인 이력 탭
- 기간 / 승인자 / 유형 필터
- 승인율, 평균 처리시간 지표(`st.metric`)
- 처리 상태 분포 막대 차트

### 3. Shadow Mode 설정 탭 (ADMIN 전용)
- Shadow Mode ON/OFF 토글
- 자동 승인 임계값 설정 (신뢰도 ≥99% 자동 승인 — **미래 기능**, 현재 비활성)
- 승인 만료 시간 안내

---

## 환경 설정

| 항목 | 설정 |
|------|------|
| 부팅 기본값 | 환경변수 `SHADOW_MODE=true` (기본) / `false` |
| 런타임 토글 | `PUT /api/v1/approval/shadow-mode` (ADMIN) — 환경변수보다 우선 |
| 만료 시간 | 항목 등록 시 `expires_in_hours` (기본 24h, 1~168h) |

미들웨어(`app/middleware/shadow_mode.py`)가 다음 경로를 게이트 대상으로 인터셉트합니다.

- `POST /api/v1/fermentation/recommendations` (절임/발효 조건 추천)
- `PATCH /api/v1/fermentation/lots/{lot_id}/status` (발효 LOT 상태변경)
- `PATCH /api/v1/shipping/orders/{order_id}/approve` (출하 승인)
- `PATCH /api/v1/agent/query/{query_id}/approve` (AI 의사결정 승인)
- `PATCH /api/v1/agent/recommendations/{rec_id}/action` (AI 추천 처리)

Shadow Mode가 ON일 때 위 경로 응답에는 다음 헤더가 부착됩니다.

```
X-Shadow-Mode: active
X-Approval-Required: true
```

---

## 감사 추적 (Audit Trail)

모든 승인/거절은 다음을 기록합니다 — **누가, 언제, 무엇을, 왜**.

- `approved_by` — 처리자
- `approved_at` — 처리 시각
- `approval_note` — 승인 메모
- `rejection_reason` — 거절 사유 (거절 시 필수)

미들웨어는 게이트 대상 경로 접근을 모두 로깅(`mes.shadow_mode` 로거)합니다.

---

## 시범운영 기간 (3개월) 운영 지침

- Shadow Mode: **항상 ON**
- 모든 AI 추천 승인 필수 (자동 반영 금지)
- AI 정확도 vs 작업자 판단 일치율 기록 (승인율 = 승인 / (승인 + 거절))
- 평균 처리시간 모니터링 (`GET /api/v1/approval/stats`)
- 3개월 후 성과 검토 → 자동 승인 임계값 조정 검토

### KPI 연계
- 발효 품질 예측 정확도 ≥ 80%, 이상발효 조기탐지 정확도 ≥ 85% 등
  AI 성능 목표 달성 여부를 승인 이력 기반으로 검증합니다.
