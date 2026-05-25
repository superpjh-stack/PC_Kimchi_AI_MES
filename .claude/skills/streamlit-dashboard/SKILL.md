---
name: streamlit-dashboard
description: 꽃순이김치 MES Streamlit 대시보드 및 UI 개발 스킬. 생산/품질/발효/출하 모니터링 화면, KPI 시각화, 현장 POP/Smart Pad UI, AI Agent 채팅 인터페이스 개발 시 반드시 이 스킬을 사용하라. 트리거: Streamlit, 대시보드, UI 화면, 페이지 개발, 차트, 시각화, 모니터링 화면, KPI 화면, Smart Pad, 현황판.
---

# MES Streamlit 대시보드 개발 스킬

## 프로젝트 구조

```
app/
├── main.py               -- 앱 진입점, 사이드바 네비게이션
├── pages/
│   ├── 01_dashboard.py   -- AI 대시보드 (생산/품질/발효/출하 현황)
│   ├── 02_intake.py      -- 원재료관리
│   ├── 03_fermentation.py -- 숙성발효관리
│   ├── 04_shipping.py    -- 포장출하관리
│   ├── 05_process.py     -- 공정관리
│   ├── 06_data.py        -- 데이터관리
│   ├── 07_kpi.py         -- KPI관리
│   └── 08_master.py      -- 기준정보관리
├── components/
│   ├── lot_selector.py   -- LOT ID 선택 컴포넌트
│   ├── kpi_cards.py      -- KPI 카드 컴포넌트
│   ├── fermentation_chart.py -- 발효 시계열 차트
│   └── ai_chat.py        -- AI Agent 채팅 인터페이스
└── utils/
    ├── api_client.py     -- FastAPI 클라이언트
    └── chart_helpers.py  -- Plotly 차트 헬퍼
```

## 목업 참고
`docs/02-design/mockups/*.html` 파일을 화면 설계 기준으로 사용한다.

---

## 공통 패턴

### API 클라이언트
```python
# utils/api_client.py
import httpx
from functools import lru_cache

BASE_URL = "http://localhost:8000/api/v1"

@lru_cache(maxsize=None)
def get_client():
    return httpx.Client(base_url=BASE_URL, timeout=30.0)

def fetch_lot_list(module: str, date: str = None) -> list:
    params = {"date": date} if date else {}
    r = get_client().get(f"/{module}/lots", params=params)
    r.raise_for_status()
    return r.json()

def fetch_fermentation_status(lot_id: str) -> dict:
    r = get_client().get(f"/fermentation/{lot_id}/status")
    r.raise_for_status()
    return r.json()
```

### LOT 선택기 컴포넌트
```python
# components/lot_selector.py
import streamlit as st
from utils.api_client import fetch_lot_list

def lot_selector(module: str, label: str = "LOT 선택") -> str | None:
    lots = fetch_lot_list(module)
    lot_ids = [lot["lot_id"] for lot in lots]
    selected = st.selectbox(label, options=["선택하세요"] + lot_ids)
    if selected != "선택하세요":
        st.session_state["selected_lot_id"] = selected
        return selected
    return None
```

### KPI 카드 컴포넌트
```python
# components/kpi_cards.py
import streamlit as st

def kpi_card(label: str, value: float, target: float, unit: str, higher_is_better: bool = True):
    delta = value - target
    delta_pct = (delta / target) * 100
    color = "normal" if (delta >= 0) == higher_is_better else "inverse"
    st.metric(
        label=label,
        value=f"{value:,.1f} {unit}",
        delta=f"{delta_pct:+.1f}% (목표: {target:,.1f})",
        delta_color=color
    )

def render_kpi_row(kpi_data: dict):
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        kpi_card("시간당 생산량", kpi_data["hourly_production_kg"], 3000, "kg/h")
    with col2:
        kpi_card("완제품 불량률", kpi_data["defect_rate"] * 100, 1.0, "%", higher_is_better=False)
    with col3:
        kpi_card("발효 예측 정확도", kpi_data["fermentation_accuracy"] * 100, 80, "%")
    with col4:
        kpi_card("발효 완료 예측 MAE", kpi_data["fermentation_time_mae"], 2.0, "시간", higher_is_better=False)
```

---

## 주요 화면 구현 패턴

### AI 대시보드 (pages/01_dashboard.py)
```python
import streamlit as st
import plotly.graph_objects as go
from components.kpi_cards import render_kpi_row
from utils.api_client import get_client

st.set_page_config(page_title="AI 대시보드", layout="wide")
st.title("꽃순이김치 제조AI 스마트공장 대시보드")

# KPI 현황
kpi_data = get_client().get("/kpi/today").json()
render_kpi_row(kpi_data)

st.divider()
col1, col2 = st.columns(2)

with col1:
    st.subheader("발효 상태 현황")
    fermentation_data = get_client().get("/fermentation/active").json()
    for lot in fermentation_data:
        status = lot["ml_quality_prediction"]
        color = {"정상": "🟢", "주의": "🟡", "이상": "🔴"}.get(status, "⚪")
        st.write(f"{color} {lot['fermentation_lot_id']} — {status} (완료 예정: {lot['predicted_end_time']})")

with col2:
    st.subheader("생산량 추이 (최근 7일)")
    production_data = get_client().get("/kpi/weekly").json()
    fig = go.Figure(go.Bar(x=[d["kpi_date"] for d in production_data],
                            y=[d["hourly_production_kg"] for d in production_data]))
    fig.add_hline(y=3000, line_dash="dash", line_color="red", annotation_text="목표 3,000 kg/h")
    st.plotly_chart(fig, use_container_width=True)

# 자동 갱신
if st.button("🔄 새로고침"):
    st.rerun()
```

### 숙성발효관리 (pages/03_fermentation.py)
```python
import streamlit as st
import plotly.graph_objects as go
from components.lot_selector import lot_selector
from utils.api_client import fetch_fermentation_status, get_client

st.title("숙성발효관리")
tabs = st.tabs(["발효상태 모니터링", "품질예측 결과", "발효완료 예측", "이상발효 알림", "ML 분석"])

with tabs[0]:
    lot_id = lot_selector("fermentation", "발효 LOT 선택")
    if lot_id:
        status = fetch_fermentation_status(lot_id)
        ml_status = status.get("ml_quality_prediction", "미예측")
        if ml_status == "이상":
            st.error(f"⚠️ 이상발효 감지! LOT {lot_id} — 즉시 확인 필요")
        elif ml_status == "주의":
            st.warning(f"⚠️ 주의 상태 — LOT {lot_id}")
        else:
            st.success(f"✅ 정상 발효 진행 중 — LOT {lot_id}")

        # 시계열 차트
        ts_data = get_client().get(f"/fermentation/{lot_id}/timeseries").json()
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=[d["recorded_at"] for d in ts_data],
                                  y=[d["temperature"] for d in ts_data], name="온도"))
        fig.add_trace(go.Scatter(x=[d["recorded_at"] for d in ts_data],
                                  y=[d["acidity"] for d in ts_data], name="산도", yaxis="y2"))
        fig.update_layout(yaxis2=dict(overlaying="y", side="right"))
        st.plotly_chart(fig, use_container_width=True)
```

---

## 실시간 갱신 전략

```python
# 발효 상태는 30초마다 자동 갱신
import time

if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = time.time()

if time.time() - st.session_state.last_refresh > 30:
    st.session_state.last_refresh = time.time()
    st.rerun()
```

---

## 개발 원칙
1. `st.session_state["selected_lot_id"]`로 LOT ID 선택 상태를 전체 페이지에서 유지한다
2. 이상발효 알림은 `st.error()`로 즉시 표시하고 사이드바에 배지를 표시한다
3. 모든 API 호출은 `try/except`로 감싸고 실패 시 `st.warning()` 표시한다
4. 차트는 Plotly를 기본으로 사용하고 `use_container_width=True`를 항상 적용한다
5. Smart Pad 화면은 터치 친화적으로 버튼 크기를 크게 설정한다
