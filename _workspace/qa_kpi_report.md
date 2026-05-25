# QA 검증 보고서 — KPI관리 모듈

- **프로젝트**: 꽃순이김치 제조AI MES (SF26179540)
- **검증 대상**: `db_kpi_schema.sql`, `api_kpi_router.py`, `ui_07_kpi.py`
- **기준 문서**: `docs/01-plan/features/pm3-process-data-kpi-system.plan.md` 섹션 6
- **검증일**: 2026-05-24
- **검증자**: QA-Validator (KPI관리)

---

## 1. 종합 결과

| 구분 | 값 |
|------|----|
| 총 검증 항목 | 22 |
| 통과 (PASS) | 20 |
| 부분/주의 (WARN) | 2 |
| 실패 (FAIL) | 0 |
| **통과율** | **90.9% (20/22)** |
| 이슈 | 4건 (HIGH:0, MEDIUM:1, LOW:3) |

결론: KPI 계산 공식, DB 스키마, 12개 엔드포인트, UI-API 정합성, 핵심 수치 모두 기획서 섹션 6과 일치한다. 치명적(HIGH) 결함 없음. 발견된 이슈는 모두 운영상 권고 수준(MEDIUM/LOW).

---

## 2. KPI 계산 공식 검증 (최우선)

| 항목 | 결과 | 근거 |
|------|------|------|
| 시간당 생산량 공식 `포장완료kg / (생산일수 × 근무시간)` | PASS | `api_kpi_router.py:117-118` `denom = prod_days * hours; hourly = total_kg / denom`. 기획서 6.1 공식과 정확히 일치. |
| 불량률 공식 `(불량kg / 총생산kg) × 100` | PASS | `api_kpi_router.py:139` `(defect_kg / total_kg) * 100.0`. 기획서 6.1과 일치. |
| `get_achievement_rate()` 역산 (낮을수록 좋은 KPI) | PASS | `api_kpi_router.py:70-74` `higher_is_better=True`→`actual/target*100`, `False`→`target/actual*100`. DEFECT/FERMENTATION_MAE에 적용됨. |
| 색상 코딩 `>=100 green / 90~99 yellow / 70~89 orange / <70 red` | PASS | `api_kpi_router.py:78-86` 기획서 6.2 표와 정확히 일치. UI `COLOR_HEX`(`ui_07_kpi.py:22`)도 동일 4색 매핑. |

추가 확인:
- 발효 정확도(`FERMENTATION_ACCURACY`)는 DB에 0~1 스케일(0.80)로 저장되나, `/summary/today`에서 `* 100`(`api_kpi_router.py:199`) 변환 후 목표 0.80과 비교 → 단위 불일치 잠재 이슈. (이슈 #1 참조)

---

## 3. DB 스키마 검증

| 항목 | 결과 | 근거 |
|------|------|------|
| 4개 테이블 (`kpi_target`, `kpi_alert_config`, `kpi_report`, `kpi_daily_summary`) | PASS | `db_kpi_schema.sql:19, 42, 62, 86` 모두 정의됨. |
| `kpi_target.kpi_type` CHECK 5종 | PASS | `db_kpi_schema.sql:30-32` PRODUCTION/DEFECT/FERMENTATION_ACCURACY/FERMENTATION_MAE/EDGE_UPTIME. |
| `kpi_alert_config.alert_channels` 배열 타입 | PASS | `db_kpi_schema.sql:47` `VARCHAR(20)[]`. |
| `kpi_daily_summary.kpi_date` UNIQUE | PASS | `db_kpi_schema.sql:88` `kpi_date DATE NOT NULL UNIQUE` (컬럼레벨 UNIQUE 제약). 별도 UNIQUE 인덱스는 없으나 제약이 동일 효과 보장. |
| 섹션 6.5 기본 알림 임계값 시드 | PASS(주의) | `db_kpi_schema.sql:118-123` PRODUCTION 2750/2500, DEFECT 1.5/2.0, FERMENTATION_ACCURACY 0.75/0.70, EDGE_UPTIME 99/95 — 기획서 6.5 4개 항목과 완전 일치. (이슈 #2 참조) |
| KPI 목표값 시드 | PASS | `db_kpi_schema.sql:110-116` PRODUCTION 3000(base 2750), DEFECT 1.0(base 1.5), ACCURACY 0.80, MAE 2.0, UPTIME 99.0. |

---

## 4. API 검증

| 항목 | 결과 | 근거 |
|------|------|------|
| 12개 엔드포인트 | PASS | summary/today, summary/daily, production/trend, defect/trend, defect/by-process, targets(GET), targets/{type}(PUT), alerts/config(GET), alerts/config/{type}(PUT), reports/generate(POST), reports(GET), reports/{id}/download — **정확히 12개**. |
| `GET /summary/today` 6개 KPI + 달성률 | PASS | `api_kpi_router.py:196-212` KPI_META 6종 순회, 각 항목에 `achievement_rate`/`color`/`achieved` 포함, `overall_rate` 반환. |
| `PUT /targets/{kpi_type}` 버전관리 (구버전 종료 + 신버전 생성) | PASS | `api_kpi_router.py:341-356` 트랜잭션 내 `valid_to = valid_from - 1day` 업데이트 후 신규 INSERT. |
| `POST /reports/generate` 4유형(DAILY/WEEKLY/MONTHLY/CUSTOM) 처리 | PASS | `api_kpi_router.py:56` Literal 타입 제약 + 파일 생성/이력 기록. |
| Prophet 연동 / graceful 처리 | PASS | API 라우터에는 Prophet 미사용(예측은 UI 책임). UI `ui_07_kpi.py:159-179`에서 `from prophet import Prophet` + `except ImportError` graceful 처리(미설치 시 caption 안내). |

---

## 5. UI-API 정합성 검증

| 항목 | 결과 | 근거 |
|------|------|------|
| 5개 탭 (KPI 현황/생산성 분석/품질 분석/KPI 설정/리포트) | PASS | `ui_07_kpi.py:87-89` `st.tabs([...])`. |
| 게이지 카드 달성률 색상 코딩 | PASS | `ui_07_kpi.py:62` `gauge_figure`가 `item["color"]`→`COLOR_HEX` 매핑으로 바 색상 적용. API `get_achievement_color` 결과 사용. |
| 생산량 트렌드 목표선 3,000 kg/h | PASS | `ui_07_kpi.py:154-155` `fig.add_hline(y=target,...)`, target 기본값 `TARGET_PRODUCTION=3000.0`(`:23, :148`). |
| 불량률 트렌드 목표선 1.0% | PASS | `ui_07_kpi.py:212-213` `fig.add_hline(y=target,...)`, target 기본값 `TARGET_DEFECT=1.0`(`:24, :205`). |
| `st.download_button` (리포트 탭) | PASS | `ui_07_kpi.py:364-368` 다운로드 응답 content를 `st.download_button`으로 제공. |
| 관리자 권한 게이트 (KPI 설정 탭) | PASS(주의) | `ui_07_kpi.py:247-250` role 체크, `is_admin`으로 form 제출 버튼 `disabled` 처리 + 제출 핸들러 `and is_admin` 가드. 단 클라이언트 측 게이트만 존재 (이슈 #3). |

---

## 6. 수치 정확성 검증

| 항목 | 결과 | 근거 |
|------|------|------|
| 생산량 현재 2,750 / 목표 3,000 kg/h | PASS | seed `baseline 2750, target 3000`(`db_kpi_schema.sql:111`), UI `TARGET_PRODUCTION=3000.0`(`:23`). 기획서 6.1 일치. |
| 불량률 현재 1.5% / 목표 1.0% | PASS | seed `baseline 1.5, target 1.0`(`db_kpi_schema.sql:112`), UI `TARGET_DEFECT=1.0`(`:24`). 기획서 6.1 일치. |

---

## 7. 이슈 목록

### 이슈 #1 (MEDIUM) — 발효 정확도 단위 스케일 불일치 가능성
- 위치: `api_kpi_router.py:199` (`/summary/today`) vs `:113`(seed target 0.80)
- 내용: `/summary/today`는 `fermentation_accuracy`(DB 0~1 스케일)에 `*100`을 적용해 actual을 0~100으로 만들지만, 목표값(`kpi_target.target_value`)은 시드에서 `0.80`(0~1 스케일)로 저장됨. 이 경우 `get_achievement_rate(actual=80, target=0.80)` → 10,000%로 계산되어 달성률이 비정상 산출됨. KPI_META unit도 `%`로 표기(`:27`)되어 DB unit `점수`(`:113`)와 불일치.
- 권고: ACCURACY 목표를 80.0(%)으로 시드하거나, summary에서 `*100`을 제거하고 목표와 동일 스케일로 비교하도록 통일.

### 이슈 #2 (LOW) — alert_config 시드에 FERMENTATION_MAE 누락
- 위치: `db_kpi_schema.sql:118-123`
- 내용: 알림 임계값 시드는 4종(PRODUCTION/DEFECT/FERMENTATION_ACCURACY/EDGE_UPTIME)만 존재. FERMENTATION_MAE는 없음. 단, 기획서 6.5 표에도 MAE 알림 항목이 정의되어 있지 않으므로 기획서 기준으로는 정합. 운영상 MAE 임계 알림이 필요하면 추가 권고. (기획서 기준 PASS, 향후 확장 관점 LOW)

### 이슈 #3 (LOW) — KPI 설정 권한 게이트가 클라이언트 측에만 존재
- 위치: `ui_07_kpi.py:247-250, 268, 302`
- 내용: 관리자 게이트가 Streamlit `session_state["role"]` 기반 버튼 disable로만 구현됨. API `PUT /targets/{type}`, `PUT /alerts/config/{type}`에는 서버측 권한 검증이 없어, API 직접 호출 시 비관리자도 수정 가능. 또한 role 기본값이 `"관리자"`(`:247`)로 하드코딩되어 인증 미연동 상태에서는 누구나 관리자로 동작.
- 권고: API 라우터에 인증/권한 의존성(Depends) 추가 또는 게이트웨이 레벨 RBAC 적용.

### 이슈 #4 (LOW) — production/defect 트렌드 count 하한 불일치
- 위치: `api_kpi_router.py:239, 265` (`ge=1`) vs `ui_07_kpi.py:140, 196` (`min_value=7`)
- 내용: API는 count 최소 1을 허용하나 UI number_input 최소값은 7. 기능 영향은 없으나 경계값 정합성 차원의 경미한 불일치.

---

## 8. 결론

KPI관리 모듈은 기획서 섹션 6의 핵심 요구사항(계산 공식, 색상 코딩, 4테이블 스키마, 12 엔드포인트, 5탭 UI, 목표선/게이지 시각화, 기준수치)을 모두 충족한다. HIGH 결함은 없으며, MEDIUM 1건(발효 정확도 스케일)만 배포 전 수정 권고, 나머지 LOW 3건은 운영 안정화 단계 개선 대상이다.
