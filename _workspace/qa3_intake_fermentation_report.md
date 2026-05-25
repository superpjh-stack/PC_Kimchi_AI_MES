# QA-3 검증 보고서 — 원재료관리 / 숙성발효관리

- 담당: QA-3
- 일자: 2026-05-23
- 대상 파일:
  - `streamlit_app/pages/02_원재료관리.py`
  - `streamlit_app/pages/03_숙성발효관리.py`
- 의존 모듈: `streamlit_app/components/styles.py` (apply_styles / metric_card / status_badge / section_header 모두 정상 export 확인)

> 참고: 환경에서 Bash/PowerShell 실행이 차단되어 `py_compile` 동적 검증은 수행하지 못함. 대신 전체 Read 기반 정적 검증을 수행함. 문법/구조상 컴파일 오류 요소는 발견되지 않음.

---

## A. 공통 구조 검증

| 항목 | 02_원재료관리.py | 03_숙성발효관리.py |
|------|:---:|:---:|
| import 패턴 (sys/os path insert + components.styles + st/go/px/pd/np) | PASS (L1-8) | PASS (L1-8) |
| set_page_config — import 직후 첫 st.* 호출 | PASS (L11) | PASS (L11) |
| apply_styles() — set_page_config 직후 | PASS (L12) | PASS (L12) |
| np.random.seed(42) | PASS (L14) | PASS (L14) |
| Plotly template/paper_bgcolor/plot_bgcolor=#162035 | PASS (PLOTLY_LAYOUT L27-33) | PASS (style_fig L22-35) |
| 모든 st.plotly_chart에 use_container_width=True | PASS (3/3) | PASS (전부) |
| status_badge unsafe_allow_html=True 렌더링 | PASS | PASS |

비고: 두 파일 모두 `from datetime import ...`를 추가로 import (정상). 03은 `style_fig()` 헬퍼로 다크 테마를 일괄 적용.

---

## B. 02_원재료관리.py 기능 검증

탭 5개 존재 확인 (L125-127): 입고관리 / 원재료 이력조회 / 선별 데이터관리 / 공급처 품질분석 / 입고 AI Agent

| 탭 | 요구 기능 | 상태 |
|----|-----------|:---:|
| Tab1 입고관리 | 요약 메트릭 3개(L135-141), 입고 현황 HTML 테이블+필터(L148-208), st.form 입고 등록 폼+submit(L214-228) | PASS |
| Tab2 이력조회 | LOT 검색(L242-245), 공정 타임라인(L285-308), expander 4종 상세(L314-345) | PASS |
| Tab3 선별 데이터관리 | 입력 폼(st.form, L354-365), 이력 테이블(L379), 선별률 Bar 차트(L385-400) | PASS |
| Tab4 공급처 품질분석 | 레이더 차트(L412-434), 합격률 가로 Bar(L443-460) | PASS |
| Tab5 입고 AI Agent | 채팅, session_state["intake_chat"], 예시 질문 버튼 | PASS |

추가 검증:
- `session_state["intake_chat"]` 초기화: PASS (L467-470, `if "intake_chat" not in st.session_state`)
- 예시 질문 버튼 → mock 답변 표시: PASS. 버튼 클릭 시 `clicked_q` 설정 → `MOCK_ANSWERS`에서 답변/출처 조회(L472-518) → 같은 rerun 내 채팅 루프(L522-535)에서 즉시 렌더링. 3개 예시 질문 모두 상세 답변 매핑 존재.
- 입고 등록 폼: PASS. `st.form("intake_register")` + `st.form_submit_button("입고 등록")` (L214-228), submit 시 success 메시지(L231-232).
- 대화 초기화 버튼 + st.rerun() 정상(L537-541).

---

## C. 03_숙성발효관리.py 기능 검증

탭 7개 존재 확인 (L180-188): 발효상태 모니터링 / 품질예측결과 / 발효완료예측 / 이상발효알림 / ML분석 / 영향요인 분석 / 공정조건 분석

| 탭 | 요구 기능 | 상태 |
|----|-----------|:---:|
| Tab1 발효상태 모니터링 | LOT 테이블(style.apply 강조, L209-213), selectbox(L218), 시계열 차트 3개(온도/산도/염도, L231-257) | PASS |
| Tab2 품질예측결과 | 예측 테이블(L272-276), 품질 분포 Pie(L282-289), 신뢰도 Histogram(L299-301) | PASS |
| Tab3 발효완료예측 | 잔여시간 가로 Bar+오차(L311-322), MAE Line+목표선 hline(L328-337) | PASS |
| Tab4 이상발효알림 | st.error() 카드(L345-351), 알림 이력 테이블(L363-367) | PASS |
| Tab5 ML분석 | 성능 카드 2종(L377-405), 학습 손실곡선(L414-420), Confusion Matrix Heatmap(L430-441) | PASS |
| Tab6 영향요인 분석 | SHAP Bar 10개 피처(L449-463), 설명 텍스트(L465-468), 산점도(L477-482) | PASS |
| Tab7 공정조건 분석 | 산점도 3종(L512-525), 최적 절임조건 추천 카드(L528-534) | PASS |

추가 검증:
- FERM-2026-0523 이상 LOT → st.error() 표시: PASS. Tab1에서 선택 시 조건부 st.error(L221-225, selectbox 기본 index가 ABNORMAL_LOT), Tab4에서 상시 st.error 알림 카드(L345-351).
- SHAP 피처 중요도 10개 포함: PASS. 발효온도/절임염도/절임시간/pH변화율/외기온도/배추등급/함수율/원산지/절임온도/외기습도 = 10개(L449-454).
- Confusion Matrix 구현 방식: PASS. `go.Heatmap` 사용(L430-439), 3x3 라벨(정상/주의/이상), texttemplate로 셀 값 표시.

---

## D. 발견 및 수정된 문제

발견된 문제 없음. 두 파일 모두 import 경로, set_page_config 위치, use_container_width, status_badge 렌더링, session_state 초기화, st.form 패턴, 차트 구현이 모두 기준을 충족함. 미완성(pass-only) 함수, 괄호/들여쓰기 불일치, 누락된 use_container_width 등 수정 대상 결함 없음. **Edit 수정 미발생.**

---

## E. 최종 상태

| 파일 | 결과 |
|------|:---:|
| 02_원재료관리.py | 검증 통과 (수정 불필요) |
| 03_숙성발효관리.py | 검증 통과 (수정 불필요) |

- 공통 구조 7개 항목: 양 파일 전부 PASS
- 02 탭 5개 기능: 전부 PASS
- 03 탭 7개 기능: 전부 PASS
- 의존 모듈 styles.py: 필요한 4개 함수 + chat CSS 클래스 정상 제공

종합: 두 페이지는 검증 기준을 모두 충족하며 코드 결함이 발견되지 않음. 별도 수정 없이 검증 완료.
