"""
꽃순이김치 제조AI MES — 숙성발효관리 화면 (pages/03_fermentation.py)
프로젝트: SF26179540 / 로뎀솔루션

streamlit-dashboard 스킬 원칙:
  - 모든 API 호출은 try/except 로 감싸고 실패 시 st.warning()
  - 차트는 Plotly, use_container_width=True
  - 발효상태는 @st.fragment(run_every=30) 자동 갱신

탭 구성:
  1. 발효상태 모니터링  2. 품질예측결과   3. 발효완료예측
  4. 이상발효알림       5. ML 분석        6. 영향요인 분석
  7. 공정조건 분석

API: http://localhost:8000/api/v1/fermentation  (api_fermentation_router.py)
"""
from __future__ import annotations

from datetime import datetime

import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="숙성발효관리 | 꽃순이김치 MES", page_icon="🫙", layout="wide")

API_BASE = "http://localhost:8000/api/v1/fermentation"

# ---------------------------------------------------------------------------
# 센서 임계값 상수 (api_fermentation_router.py 와 동기화)
# ---------------------------------------------------------------------------
TEMP_WARNING = 20.0
TEMP_CRITICAL = 25.0
TEMP_LOW_WARNING = 8.0
ACIDITY_MIN = 0.40
ACIDITY_MAX = 0.90
SALINITY_MIN = 1.8
SALINITY_MAX = 3.2
PH_MIN = 4.0
PH_MAX = 6.5

# AI 성능 목표 (CLAUDE.md §AI 모듈)
TARGET_QUALITY_ACC = 0.80
TARGET_COMPLETION_MAE = 2.0
TARGET_ANOMALY_ACC = 0.85
TARGET_R2 = 0.85

# 품질 등급별 색상/아이콘 일관성
QUALITY_ICON = {"NORMAL": "🟢", "CAUTION": "🟡", "ABNORMAL": "🔴", None: "⚪", "": "⚪"}
QUALITY_COLOR = {"NORMAL": "#16a34a", "CAUTION": "#eab308", "ABNORMAL": "#dc2626"}
QUALITY_LABEL = {"NORMAL": "정상", "CAUTION": "주의", "ABNORMAL": "이상"}
SEVERITY_BADGE = {"CRITICAL": "🔴 CRITICAL", "WARNING": "🟡 WARNING"}
MODEL_LABEL = {
    "XGBOOST": "XGBoost (품질분류)",
    "RANDOM_FOREST": "Random Forest (요인분석)",
    "SVR": "SVR (산도/숙성도 회귀)",
    "LSTM": "LSTM (완료시점 예측)",
}


# ---------------------------------------------------------------------------
# API 헬퍼 — 모든 호출 try/except, 실패 시 st.warning + 기본값
# ---------------------------------------------------------------------------
def api_get(path: str, params: dict | None = None, default=None):
    try:
        r = httpx.get(f"{API_BASE}{path}", params=params or {}, timeout=10.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        st.warning(f"API 조회 실패 ({path}): {e}")
        return default


def api_post(path: str, json: dict, params: dict | None = None):
    try:
        r = httpx.post(f"{API_BASE}{path}", json=json, params=params or {}, timeout=10.0)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        try:
            body = e.response.json()
            detail = body.get("detail", str(e))
            if isinstance(detail, list):
                detail = "; ".join(
                    f"{'.'.join(str(x) for x in d.get('loc', []))}: {d.get('msg','')}"
                    for d in detail
                )
        except Exception:
            detail = str(e)
        st.error(f"🚫 API 오류 ({path} · {e.response.status_code}): {detail}")
        return None
    except Exception as e:  # noqa: BLE001
        st.warning(f"API 등록 실패 ({path}): {e}")
        return None


def api_patch(path: str, json: dict):
    try:
        r = httpx.patch(f"{API_BASE}{path}", json=json, timeout=10.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        st.warning(f"API 처리 실패 ({path}): {e}")
        return None


def temp_level(temp: float | None) -> str:
    """온도 게이지 색상 결정용 레벨."""
    if temp is None:
        return "UNKNOWN"
    if temp >= TEMP_CRITICAL or temp <= TEMP_LOW_WARNING:
        return "CRITICAL"
    if temp >= TEMP_WARNING:
        return "WARNING"
    return "NORMAL"


def fmt_dt(value) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%m-%d %H:%M")
    except Exception:
        return str(value)


def lot_selectbox(label: str, key: str, statuses: list[str] | None = None) -> str | None:
    """발효 LOT 선택 박스 (목록 API 기반)."""
    params: dict = {"limit": 100}
    lots = api_get("/lots", params=params, default=[]) or []
    if statuses:
        lots = [x for x in lots if x.get("lot_status") in statuses]
    ids = [x["lot_id"] for x in lots]
    if not ids:
        st.info("표시할 발효 LOT 이 없습니다.")
        return None
    return st.selectbox(label, ids, key=key)


# ===========================================================================
st.title("🫙 숙성발효관리")

# 상단 요약 메트릭
summary = api_get("/summary/today", default={}) or {}
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("발효중", summary.get("fermenting", 0))
m2.metric("완료", summary.get("completed", 0))
m3.metric("이상", summary.get("abnormal", 0))
avg_q = summary.get("avg_quality_score")
m4.metric("평균 품질점수", f"{avg_q:.3f}" if avg_q is not None else "-")
m5.metric(
    "미해소 알림",
    summary.get("open_alert_critical", 0) + summary.get("open_alert_warning", 0),
    delta=f"CRIT {summary.get('open_alert_critical', 0)}",
    delta_color="inverse",
)

tabs = st.tabs([
    "발효상태 모니터링", "품질예측결과", "발효완료예측", "이상발효알림",
    "ML 분석", "영향요인 분석", "공정조건 분석",
])


# ===========================================================================
# 탭 1: 발효상태 모니터링 — 30초 자동 갱신
# ===========================================================================
def _temp_gauge(temp: float | None, target: float | None) -> go.Figure:
    lvl = temp_level(temp)
    color = {"NORMAL": "#16a34a", "WARNING": "#eab308",
             "CRITICAL": "#dc2626", "UNKNOWN": "#9ca3af"}[lvl]
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=temp if temp is not None else 0,
        number={"suffix": " ℃"},
        gauge={
            "axis": {"range": [0, 30]},
            "bar": {"color": color},
            "steps": [
                {"range": [0, TEMP_LOW_WARNING], "color": "#dbeafe"},
                {"range": [TEMP_LOW_WARNING, TEMP_WARNING], "color": "#dcfce7"},
                {"range": [TEMP_WARNING, TEMP_CRITICAL], "color": "#fef9c3"},
                {"range": [TEMP_CRITICAL, 30], "color": "#fee2e2"},
            ],
            "threshold": {"line": {"color": "red", "width": 3}, "value": target or TEMP_CRITICAL},
        },
    ))
    fig.update_layout(height=180, margin=dict(l=10, r=10, t=20, b=10))
    return fig


@st.fragment(run_every=30)
def render_monitor():
    data = api_get("/monitor/realtime", default={}) or {}
    lots = data.get("lots", [])
    st.caption(f"⏱ 30초 자동 갱신 · 발효중 {data.get('active_count', 0)}건 · "
               f"마지막 갱신 {datetime.now():%H:%M:%S}")
    if not lots:
        st.info("현재 발효중인 LOT 이 없습니다.")
        return
    cols = st.columns(min(3, len(lots)))
    for i, lot in enumerate(lots):
        with cols[i % len(cols)]:
            cls = lot.get("quality_class")
            icon = QUALITY_ICON.get(cls, "⚪")
            with st.container(border=True):
                st.markdown(f"**{icon} {lot['lot_id']}**  ·  발효실 {lot.get('room_id', '-')}")
                st.caption(
                    f"경과 {lot.get('elapsed_hours', '-')}h · "
                    f"목표 {lot.get('fermentation_temp_target', '-')}℃ · "
                    f"품질 {QUALITY_LABEL.get(cls, '미예측')}"
                )
                st.plotly_chart(
                    _temp_gauge(lot.get("temperature"), lot.get("fermentation_temp_target")),
                    use_container_width=True,
                    key=f"gauge_{lot['lot_id']}",
                )
                s1, s2, s3 = st.columns(3)
                s1.metric("산도(%)", f"{lot.get('acidity', 0):.2f}" if lot.get("acidity") is not None else "-")
                s2.metric("pH", f"{lot.get('ph', 0):.2f}" if lot.get("ph") is not None else "-")
                s3.metric("염도(%)", f"{lot.get('salinity', 0):.2f}" if lot.get("salinity") is not None else "-")
                if temp_level(lot.get("temperature")) == "CRITICAL":
                    st.error("⚠️ 온도 위험 임계 초과/미달")
                elif temp_level(lot.get("temperature")) == "WARNING":
                    st.warning("주의 임계 도달")


with tabs[0]:
    st.subheader("발효상태 실시간 모니터링")
    render_monitor()


# ===========================================================================
# 탭 2: 품질예측결과
# ===========================================================================
with tabs[1]:
    st.subheader("품질예측결과")
    lot_id = lot_selectbox("발효 LOT 선택", key="pred_lot")
    if lot_id:
        data = api_get(f"/predictions/{lot_id}/latest", default={}) or {}
        models = data.get("models", {})
        if not models:
            st.info("해당 LOT 의 예측 결과가 없습니다.")
        else:
            c = st.columns(3)
            # XGBoost / RF — 등급
            xgb = models.get("XGBOOST") or models.get("RANDOM_FOREST")
            with c[0]:
                st.markdown("**XGBoost 품질분류**")
                if xgb and xgb.get("quality_class"):
                    cls = xgb["quality_class"]
                    st.markdown(f"### {QUALITY_ICON.get(cls)} {QUALITY_LABEL.get(cls, cls)}")
                    st.metric("확신도", f"{(xgb.get('quality_score') or 0):.2%}")
                else:
                    st.caption("분류 결과 없음")
            # SVR — 산도/숙성도
            svr = models.get("SVR")
            with c[1]:
                st.markdown("**SVR 회귀**")
                if svr:
                    st.metric("예측 산도", f"{svr.get('predicted_acidity', 0):.3f}" if svr.get("predicted_acidity") is not None else "-")
                    st.metric("예측 숙성도", f"{svr.get('predicted_ripeness', 0):.3f}" if svr.get("predicted_ripeness") is not None else "-")
                    if svr.get("r2_score") is not None:
                        st.caption(f"R² = {svr['r2_score']:.3f} (목표 ≥ {TARGET_R2})")
                else:
                    st.caption("회귀 결과 없음")
            # LSTM — 완료 예측
            lstm = models.get("LSTM")
            with c[2]:
                st.markdown("**LSTM 완료예측**")
                if lstm:
                    st.metric("완료 예측", fmt_dt(lstm.get("predicted_completion_time")))
                    mae = lstm.get("completion_mae_hours")
                    st.metric("MAE(h)", f"{mae:.2f}" if mae is not None else "-",
                              delta="목표 달성" if (mae is not None and mae <= TARGET_COMPLETION_MAE) else None)
                else:
                    st.caption("시계열 결과 없음")

        hist = api_get("/predictions", params={"lot_id": lot_id, "limit": 50}, default=[]) or []
        if hist:
            df = pd.DataFrame(hist)
            st.markdown("**예측 이력**")
            show_cols = [c for c in ["predicted_at", "model_type", "quality_class",
                                     "quality_score", "predicted_acidity",
                                     "predicted_ripeness", "model_version"] if c in df.columns]
            st.dataframe(df[show_cols], use_container_width=True, hide_index=True)


# ===========================================================================
# 탭 3: 발효완료예측
# ===========================================================================
with tabs[2]:
    st.subheader("발효완료예측 (LSTM)")
    preds = api_get("/predictions", params={"model_type": "LSTM", "limit": 50}, default=[]) or []
    preds = [p for p in preds if p.get("predicted_completion_time")]
    if not preds:
        st.info("완료 예측 데이터가 없습니다.")
    else:
        df = pd.DataFrame(preds)
        df["completion"] = pd.to_datetime(df["predicted_completion_time"], errors="coerce", utc=True)
        df = df.sort_values("completion")
        fig = px.scatter(
            df, x="completion", y="lot_id", size="completion_mae_hours",
            color="completion_mae_hours", color_continuous_scale="RdYlGn_r",
            labels={"completion": "완료 예측 시각", "lot_id": "발효 LOT",
                    "completion_mae_hours": "MAE(h)"},
            title="LOT별 발효 완료 예측 타임라인",
        )
        fig.add_vline(x=datetime.now().timestamp() * 1000, line_dash="dash",
                      line_color="gray", annotation_text="현재")
        fig.update_layout(height=380)
        st.plotly_chart(fig, use_container_width=True)

        mae_avg = df["completion_mae_hours"].mean()
        cc1, cc2 = st.columns(2)
        cc1.metric("평균 완료시점 MAE(h)", f"{mae_avg:.2f}",
                   delta=f"목표 ≤ {TARGET_COMPLETION_MAE}",
                   delta_color="normal" if mae_avg <= TARGET_COMPLETION_MAE else "inverse")
        within = (df["completion_mae_hours"] <= TARGET_COMPLETION_MAE).mean() * 100
        cc2.metric("목표 MAE 달성률", f"{within:.0f}%")
        st.dataframe(
            df[["lot_id", "predicted_completion_time", "completion_mae_hours", "predicted_at"]],
            use_container_width=True, hide_index=True,
        )


# ===========================================================================
# 탭 4: 이상발효알림
# ===========================================================================
with tabs[3]:
    st.subheader("이상발효알림")
    fc1, fc2 = st.columns([1, 1])
    sev_filter = fc1.selectbox("심각도", ["전체", "CRITICAL", "WARNING"], key="anom_sev")
    show_resolved = fc2.checkbox("해소 포함", value=False)

    params: dict = {"limit": 100}
    if sev_filter != "전체":
        params["severity"] = sev_filter
    if not show_resolved:
        params["is_resolved"] = False
    alerts = api_get("/anomalies", params=params, default=[]) or []

    if not alerts:
        st.success("✅ 미해소 이상발효 알림이 없습니다.")
    else:
        for a in alerts:
            badge = SEVERITY_BADGE.get(a["severity"], a["severity"])
            resolved = a.get("is_resolved")
            with st.container(border=True):
                top = st.columns([3, 2, 1])
                top[0].markdown(f"**{badge}** · {a['lot_id']} · `{a['alert_type']}`")
                top[1].caption(f"탐지 {fmt_dt(a.get('detected_at'))}")
                if resolved:
                    top[2].success("해소됨")
                st.write(a["message"])
                if a.get("sensor_value") is not None or a.get("threshold_value") is not None:
                    st.caption(f"측정값 {a.get('sensor_value', '-')} / 기준값 {a.get('threshold_value', '-')}")
                if not resolved:
                    with st.expander("해소 처리"):
                        rb = st.text_input("처리자", key=f"rb_{a['alert_id']}")
                        act = st.text_area("조치 내용", key=f"act_{a['alert_id']}")
                        if st.button("해소 처리", key=f"btn_{a['alert_id']}"):
                            if not rb:
                                st.warning("처리자를 입력하세요.")
                            else:
                                res = api_patch(f"/anomalies/{a['alert_id']}/resolve",
                                                {"resolved_by": rb, "action_taken": act})
                                if res:
                                    st.success("해소 처리 완료")
                                    st.rerun()

        # 알림 추세 chart
        df = pd.DataFrame(alerts)
        if "detected_at" in df.columns:
            df["d"] = pd.to_datetime(df["detected_at"], errors="coerce", utc=True).dt.date
            trend = df.groupby(["d", "severity"]).size().reset_index(name="count")
            fig = px.bar(trend, x="d", y="count", color="severity",
                         color_discrete_map={"CRITICAL": "#dc2626", "WARNING": "#eab308"},
                         title="일자별 이상발효 알림 추세")
            fig.update_layout(height=320)
            st.plotly_chart(fig, use_container_width=True)


# ===========================================================================
# 탭 5: ML 분석
# ===========================================================================
with tabs[4]:
    st.subheader("ML 분석 — 예측 성능 트렌드")
    preds = api_get("/predictions", params={"limit": 200}, default=[]) or []
    if not preds:
        st.info("예측 데이터가 없습니다.")
    else:
        df = pd.DataFrame(preds)
        df["predicted_at"] = pd.to_datetime(df["predicted_at"], errors="coerce", utc=True)

        # 모델별 quality_score 시계열
        score_df = df[df["quality_score"].notna()] if "quality_score" in df.columns else pd.DataFrame()
        if not score_df.empty:
            fig = px.line(
                score_df.sort_values("predicted_at"),
                x="predicted_at", y="quality_score", color="model_type", markers=True,
                labels={"predicted_at": "예측시각", "quality_score": "품질 확신도"},
                title="모델별 품질 예측 확신도 트렌드",
            )
            fig.add_hline(y=TARGET_QUALITY_ACC, line_dash="dash", line_color="green",
                          annotation_text=f"목표 정확도 {TARGET_QUALITY_ACC:.0%}")
            fig.update_layout(height=340, yaxis_range=[0, 1])
            st.plotly_chart(fig, use_container_width=True)

        # R² 추세
        r2_df = df[df["r2_score"].notna()] if "r2_score" in df.columns else pd.DataFrame()
        if not r2_df.empty:
            fig2 = px.line(
                r2_df.sort_values("predicted_at"),
                x="predicted_at", y="r2_score", color="model_type", markers=True,
                labels={"predicted_at": "예측시각", "r2_score": "R² 점수"},
                title="회귀 R² 점수 추세",
            )
            fig2.add_hline(y=TARGET_R2, line_dash="dash", line_color="green",
                           annotation_text=f"목표 R² {TARGET_R2}")
            fig2.update_layout(height=340, yaxis_range=[0, 1])
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.caption("R² 점수를 가진 회귀(SVR) 예측이 없습니다.")


# ===========================================================================
# 탭 6: 영향요인 분석 (SHAP)
# ===========================================================================
with tabs[5]:
    st.subheader("영향요인 분석 (SHAP)")
    lot_id = lot_selectbox("발효 LOT 선택", key="shap_lot")
    if lot_id:
        data = api_get(f"/analysis/shap/{lot_id}", default={}) or {}
        factors = data.get("factors", [])
        if not factors:
            st.info("SHAP 분석 결과가 없습니다.")
        else:
            st.caption(f"모델: {MODEL_LABEL.get(data.get('model_type'), data.get('model_type'))} · "
                       f"예측등급: {QUALITY_ICON.get(data.get('quality_class'))} "
                       f"{QUALITY_LABEL.get(data.get('quality_class'), '-')}")
            top5 = factors[:5]
            fdf = pd.DataFrame(top5)
            fdf["color"] = fdf["direction"].map({"positive": "#dc2626", "negative": "#2563eb"})
            fig = go.Figure(go.Bar(
                x=fdf["contribution"], y=fdf["feature"], orientation="h",
                marker_color=fdf["color"],
                text=[f"{v:+.3f}" for v in fdf["contribution"]], textposition="auto",
            ))
            fig.update_layout(
                title="상위 5개 영향 요인 (SHAP 기여도)",
                xaxis_title="기여도", yaxis_title="요인",
                yaxis=dict(autorange="reversed"), height=360,
            )
            st.plotly_chart(fig, use_container_width=True)
            st.caption("🔴 긍정(품질 상승) 영향 · 🔵 부정(품질 하락) 영향")
            st.dataframe(pd.DataFrame(factors), use_container_width=True, hide_index=True)


# ===========================================================================
# 탭 7: 공정조건 분석
# ===========================================================================
with tabs[6]:
    st.subheader("공정조건 분석 — 절임 조건 vs 발효 품질")
    days = st.slider("분석 기간 (일)", 7, 90, 30, key="cond_days")
    data = api_get("/analysis/condition", params={"days": days}, default={}) or {}
    points = data.get("points", [])

    if not points:
        st.info("분석할 공정조건 데이터가 없습니다.")
    else:
        df = pd.DataFrame(points)
        df["quality_class"] = df.get("quality_class").fillna("UNKNOWN") if "quality_class" in df else "UNKNOWN"
        if "salt_density" in df and "salt_hours" in df and df["salt_density"].notna().any():
            fig = px.scatter(
                df.dropna(subset=["salt_density", "salt_hours"]),
                x="salt_density", y="salt_hours",
                color="quality_class",
                color_discrete_map={**QUALITY_COLOR, "UNKNOWN": "#9ca3af"},
                size="salt_temp" if "salt_temp" in df and df["salt_temp"].notna().any() else None,
                hover_data=["lot_id", "salt_temp"],
                labels={"salt_density": "절임 염도(%)", "salt_hours": "절임 시간(h)",
                        "quality_class": "발효 품질"},
                title="절임 염도 × 절임 시간 → 발효 품질 분포",
            )
            fig.update_layout(height=380)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("절임 조건(PROC03) 데이터가 부족하여 산점도를 그릴 수 없습니다.")

        by_q = data.get("by_quality", {})
        if by_q:
            st.markdown("**품질등급별 평균 절임 조건**")
            bq_df = pd.DataFrame([
                {"품질등급": QUALITY_LABEL.get(k, k), "LOT 수": v["count"],
                 "평균 염도(%)": v["avg_salt_density"], "평균 절임온도(℃)": v["avg_salt_temp"],
                 "평균 절임시간(h)": v["avg_salt_hours"]}
                for k, v in by_q.items()
            ])
            st.dataframe(bq_df, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### 🎯 최적 절임 조건 추천")
    recs = api_get("/recommendations/latest", params={"limit": 3}, default=[]) or []
    if not recs:
        st.info("추천 데이터가 없습니다.")
    else:
        rcols = st.columns(min(3, len(recs)))
        for i, rec in enumerate(recs):
            with rcols[i % len(rcols)]:
                with st.container(border=True):
                    pq = rec.get("predicted_quality", "-")
                    st.markdown(f"**절임 LOT {rec.get('source_lot_id', '-')}**")
                    st.caption(f"예상 품질: {pq} · 신뢰도 "
                               f"{(rec.get('confidence_score') or 0):.0%} · "
                               f"기반 {rec.get('basis_lot_count', '-')} LOT")
                    st.metric("추천 염도(%)", rec.get("rec_salt_density_pct", "-"))
                    a, b = st.columns(2)
                    a.metric("절임온도(℃)", rec.get("rec_salt_temp_c", "-"))
                    b.metric("절임시간(h)", rec.get("rec_salt_hours", "-"))
                    st.metric("발효온도(℃)", rec.get("rec_fermentation_temp_c", "-"))
                    if rec.get("notes"):
                        st.caption(f"💡 {rec['notes']}")
