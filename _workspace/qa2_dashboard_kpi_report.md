# QA-2 검증 보고서 — 대시보드 / KPI / AI Agent

- 담당: QA-2
- 일자: 2026-05-23
- 검증 대상: Home.py, 01_AI대시보드.py, 07_KPI관리.py, 10_AI_Agent통합관리.py
- 공통 의존 모듈: streamlit_app/components/styles.py (apply_styles, metric_card, status_badge, section_header 모두 정의 확인)

> 참고: 환경에서 Bash/PowerShell 실행 권한이 거부되어 `py_compile` 자동 컴파일 검증은 수행하지 못했으며, 4개 파일 전체를 Read 정적 분석으로 검증함. 문법 오류는 발견되지 않음.

---

## 1. Home.py — PASS

| 검증 항목 | 결과 |
|---|---|
| import 순서 (sys/os → sys.path.insert(dirname) → styles → streamlit) | Pass |
| set_page_config 위치 (import 직후, apply_styles 전) | Pass (L8) |
| apply_styles() 첫 렌더링 호출 | Pass (L9) |
| 로그인 폼 (사용자 ID / 비밀번호 / 역할 선택) | Pass (L41-45) |
| session_state["logged_in"] 처리 + 라우팅 | Pass (L12, L47-54, L159-162) |
| 로그인 후 시스템 현황 카드 4개 | Pass (생산량/발효 LOT/이상발효/출하, L104-112) |
| st.columns 언패킹 | Pass (모든 columns 변수 언패킹) |
| status_badge / unsafe_allow_html 사용 | Pass (badge는 CSS 클래스 인라인 사용) |

- 비고: Home.py는 Plotly 차트가 없는 진입/로그인 화면이므로 다크 테마 Figure 기준은 N/A.
- 발견 문제: 없음

## 2. 01_AI대시보드.py — PASS

| 검증 항목 | 결과 |
|---|---|
| import 순서 (sys.path.insert(join(dirname,'..')) → styles → streamlit → plotly → pandas → numpy) | Pass |
| set_page_config 위치 | Pass (L11) |
| apply_styles() | Pass (L12) |
| np.random.seed(42) (mock 생성 전) | Pass (L14) |
| Plotly 다크 테마 (template/paper_bgcolor/plot_bgcolor #162035) | Pass (DARK dict L17-23, style_fig 일괄 적용) |
| use_container_width=True (모든 plotly_chart) | Pass (6개 차트 전부) |
| st.columns 언패킹 | Pass |
| 상단 KPI 4개 (생산량/불량률/예측정확도/MAE) | Pass (L57-65) |
| 탭 4개 (생산현황/품질현황/발효상태/출하현황) | Pass (L69) |
| 발효상태 탭 이상 LOT st.error() | Pass (L187, FERM-2026-0523) |
| 탭별 최소 1개 Plotly 차트 | Pass (Tab1 2개, Tab2 2개, Tab3 1개, Tab4 2개) |
| status_badge HTML 렌더링 | Pass (badge_table L37, to_html escape=False + markdown unsafe_allow_html) |

- 발견 문제: 없음

## 3. 07_KPI관리.py — PASS

| 검증 항목 | 결과 |
|---|---|
| import 순서 | Pass |
| set_page_config 위치 | Pass (L11) |
| apply_styles() | Pass (L12) |
| np.random.seed(42) | Pass (L14) |
| Plotly 다크 테마 | Pass (DARK dict + style_fig) |
| use_container_width=True | Pass (5개 차트 전부) |
| st.columns 언패킹 | Pass |
| 상단 KPI 달성 카드 4개 | Pass (L42-50) |
| 탭 2개 (생산성 KPI / 품질 KPI) | Pass (L54) |
| AI 모델 성능 지표 테이블 (XGBoost/LSTM/SVR/이상발효 탐지) | Pass (L136-153, XGBoost 분류+Recall, SVR R², LSTM MAE, 이상발효 탐지 정확도 모두 포함) |
| status_badge HTML 렌더링 | Pass (KPI 이력 L95, 모델 테이블 L145) |

- 검토 메모: L145 `status_badge(x).replace("PASS", "✅ PASS")` — status_badge("PASS")는 `<span class="badge-ok">PASS</span>` 반환, replace 결과 `<span class="badge-ok">✅ PASS</span>`로 정상 동작 확인.
- 발견 문제: 없음

## 4. 10_AI_Agent통합관리.py — PASS

| 검증 항목 | 결과 |
|---|---|
| import 순서 | Pass |
| set_page_config 위치 | Pass (L11) |
| apply_styles() | Pass (L12) |
| np.random.seed(42) | Pass (L14) |
| st.columns 언패킹 | Pass |
| 탭 3개 (통합 AI 질의 / 생산·품질 분석 / 알림 및 추천) | Pass (L84) |
| 채팅 인터페이스 (session_state 기반) | Pass (ai_history L24-25, push_chat L76-81, 렌더링 L123-135, 폼 입력 L139-147, 초기화 L150-152) |
| 예시 질문 버튼 3개 | Pass (L101-111, MOCK_ANSWERS 3건과 매핑) |
| status_badge HTML 렌더링 | Pass (알림 테이블 심각도/처리상태 L213-214) |
| 출처(source) 표기 + 담당자 승인 안내 | Pass (chat-source, L247 st.info) |

- 비고: 이 페이지는 Plotly 차트를 사용하지 않으므로 다크 테마 Figure / use_container_width 차트 기준은 N/A. 버튼·폼의 use_container_width=True는 적용됨.
- 발견 문제: 없음

---

## 종합 결과

| 파일 | 상태 |
|---|---|
| Home.py | PASS |
| pages/01_AI대시보드.py | PASS |
| pages/07_KPI관리.py | PASS |
| pages/10_AI_Agent통합관리.py | PASS |

- 발견된 문제: 없음
- 수정 내역: 없음 (수정 불필요)
- 공통 모듈 styles.py: 4개 함수(apply_styles, metric_card, status_badge, section_header) 정상 정의, import 경로 일치 확인.

### 결론
4개 파일 모두 코드 구조(A), 기능 완성도(B) 기준을 충족하며 문법/구조 결함이 없어 수정 없이 PASS. 정적 분석 기준 검증 완료.
