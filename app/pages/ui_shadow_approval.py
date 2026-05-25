"""
꽃순이김치 제조AI MES — Shadow Mode 승인 대시보드 (app/pages/ui_shadow_approval.py)
프로젝트: SF26179540 / 로뎀솔루션

현장 작업자 / 관리자가 AI 추천을 검토하고 승인·거절하는 화면.

CLAUDE.md 원칙:
    "AI는 조회·분석·추천·경고. 작업자 승인 후 공정 반영 (파일럿 검증 단계)"

streamlit-dashboard 스킬 원칙:
    - 모든 API 호출은 try/except 로 감싸고 실패 시 st.warning() + Mock 폴백
    - 차트는 Plotly, use_container_width=True
    - 승인 대기열은 자동 갱신 가능

탭 구성:
    1. 승인 대기 목록  — AI 추천 카드 + 신뢰도 게이지 + 승인/거절 + 만료 카운트다운
    2. 승인 이력       — 기간/승인자/유형 필터, 승인율, 처리시간 분포
    3. Shadow Mode 설정 — ON/OFF 토글, 자동승인 임계값(미래), 만료시간

API: http://localhost:8000/api/v1/approval  (app/api/approval_router.py)
실행: streamlit run app/pages/ui_shadow_approval.py
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="AI 추천 승인 | 꽃순이김치 MES", page_icon="✅", layout="wide")

API_BASE = "http://localhost:8000/api/v1/approval"

# ---------------------------------------------------------------------------
# 도메인 상수 (approval_router.py 와 동기화)
# ---------------------------------------------------------------------------
ITEM_TYPE_LABEL = {
    "FERMENTATION_CONDITION": "절임/발효 조건 변경",
    "SHIPPING_APPROVAL": "출하 승인",
    "QUALITY_OVERRIDE": "품질 기준 예외",
    "LOT_STATUS_CHANGE": "LOT 상태 변경",
}
MODULE_ICON = {"FERMENTATION": "🫙", "SHIPPING": "📦", "INTAKE": "🥬"}
STATUS_BADGE = {
    "PENDING": ("⏳ 대기", "#f59e0b"),
    "APPROVED": ("✓ 승인", "#10b981"),
    "REJECTED": ("✕ 거절", "#ef4444"),
    "EXPIRED": ("⌛ 만료", "#64748b"),
}


# ---------------------------------------------------------------------------
# API 헬퍼 — 모든 호출 try/except, 실패 시 st.warning + 기본값/Mock
# ---------------------------------------------------------------------------
def api_get(path: str, params: dict | None = None, default=None):
    try:
        r = httpx.get(f"{API_BASE}{path}", params=params or {}, timeout=10.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        st.session_state["_api_down"] = True
        st.warning(f"API 조회 실패 ({path}): {e} — Mock 데이터로 표시합니다.")
        return default


def api_post(path: str, json: dict | None = None):
    try:
        r = httpx.post(f"{API_BASE}{path}", json=json or {}, timeout=10.0)
        r.raise_for_status()
        return r.json(), None
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:  # noqa: BLE001
            detail = e.response.text
        return None, f"{e.response.status_code}: {detail}"
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def api_put(path: str, json: dict | None = None):
    try:
        r = httpx.put(f"{API_BASE}{path}", json=json or {}, timeout=10.0)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


# ---------------------------------------------------------------------------
# Mock 데이터 (API 미가동 시 화면 검증용)
# ---------------------------------------------------------------------------
def _mock_items() -> list[dict]:
    now = datetime.now(timezone.utc)
    return [
        {
            "item_id": 101,
            "item_type": "FERMENTATION_CONDITION",
            "title": "FE-20260524-007 발효 온도 +1.5℃ 상향 추천",
            "ai_recommendation": "최근 24h 산도 정체 — 발효 촉진 위해 발효실 온도 18.5→20.0℃ 권장.",
            "current_state": {"temp": 18.5, "acidity": 0.42, "elapsed_h": 26.3},
            "proposed_change": {"temp": 20.0},
            "confidence": 0.88,
            "lot_id": "FE-20260524-007",
            "source_module": "FERMENTATION",
            "status": "PENDING",
            "requested_by": "ML_ENGINE",
            "expires_at": (now + timedelta(hours=21)).isoformat(),
            "created_at": (now - timedelta(hours=3)).isoformat(),
        },
        {
            "item_id": 102,
            "item_type": "SHIPPING_APPROVAL",
            "title": "SHP-20260524-031 출하 승인 검토",
            "ai_recommendation": "품질검사 전 항목 PASS, 클레임 이력 없음 — 출하 승인 가능.",
            "current_state": {"inspection": "PASS", "claim_history": 0},
            "proposed_change": {"approve_shipping": True},
            "confidence": 0.94,
            "lot_id": "SHP-20260524-031",
            "source_module": "SHIPPING",
            "status": "PENDING",
            "requested_by": "SHIPPING_AGENT",
            "expires_at": (now + timedelta(hours=8)).isoformat(),
            "created_at": (now - timedelta(hours=1)).isoformat(),
        },
        {
            "item_id": 103,
            "item_type": "QUALITY_OVERRIDE",
            "title": "FE-20260524-005 이상발효 의심 — 품질 예외 검토",
            "ai_recommendation": "온도 24.1℃ 임계 초과 감지. 폐기 또는 재처리 결정 필요.",
            "current_state": {"temp": 24.1, "quality_class": "ABNORMAL"},
            "proposed_change": {"action": "HOLD_FOR_REVIEW"},
            "confidence": 0.91,
            "lot_id": "FE-20260524-005",
            "source_module": "FERMENTATION",
            "status": "PENDING",
            "requested_by": "ML_ENGINE",
            "expires_at": (now + timedelta(hours=2)).isoformat(),
            "created_at": (now - timedelta(hours=22)).isoformat(),
        },
    ]


def _mock_history() -> list[dict]:
    now = datetime.now(timezone.utc)
    base = []
    samples = [
        ("APPROVED", "FERMENTATION_CONDITION", "공장장", 0.89, 12),
        ("REJECTED", "QUALITY_OVERRIDE", "공장장", 0.71, 35),
        ("APPROVED", "SHIPPING_APPROVAL", "관리자", 0.95, 6),
        ("APPROVED", "LOT_STATUS_CHANGE", "품질담당자", 0.83, 18),
        ("EXPIRED", "FERMENTATION_CONDITION", None, 0.66, None),
    ]
    for i, (status, itype, approver, conf, mins) in enumerate(samples):
        base.append({
            "item_id": 90 + i,
            "item_type": itype,
            "title": f"{itype} 이력 #{90+i}",
            "ai_recommendation": "...",
            "confidence": conf,
            "status": status,
            "approved_by": approver,
            "approved_at": (now - timedelta(days=i)).isoformat() if status != "EXPIRED" else None,
            "created_at": (now - timedelta(days=i, minutes=mins or 0)).isoformat(),
            "rejection_reason": "작업자 판단상 조건 변경 불필요" if status == "REJECTED" else None,
            "_handle_minutes": mins,
        })
    return base


# ---------------------------------------------------------------------------
# 시각화 헬퍼
# ---------------------------------------------------------------------------
def confidence_gauge(value: float | None, key: str):
    """신뢰도 게이지 (0~100%)."""
    pct = round((value or 0) * 100, 1)
    color = "#10b981" if pct >= 85 else "#f59e0b" if pct >= 70 else "#ef4444"
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=pct,
        number={"suffix": "%", "font": {"size": 22, "color": "#e2e8f0"}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": "#94a3b8"},
            "bar": {"color": color},
            "bgcolor": "#162035",
            "bordercolor": "#1e3a5f",
            "steps": [
                {"range": [0, 70], "color": "rgba(239,68,68,.15)"},
                {"range": [70, 85], "color": "rgba(245,158,11,.15)"},
                {"range": [85, 100], "color": "rgba(16,185,129,.15)"},
            ],
        },
    ))
    fig.update_layout(
        height=160, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#e2e8f0"),
    )
    st.plotly_chart(fig, use_container_width=True, key=key)


def _countdown(expires_at: str | None) -> tuple[str, str]:
    """만료까지 남은 시간 문자열 + 색상."""
    if not expires_at:
        return "—", "#94a3b8"
    try:
        exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = exp - now
        if delta.total_seconds() <= 0:
            return "만료됨", "#ef4444"
        h = int(delta.total_seconds() // 3600)
        m = int((delta.total_seconds() % 3600) // 60)
        color = "#ef4444" if h < 3 else "#f59e0b" if h < 8 else "#94a3b8"
        return f"{h}시간 {m}분 남음", color
    except Exception:  # noqa: BLE001
        return "—", "#94a3b8"


# ---------------------------------------------------------------------------
# 상단 헤더 — Shadow Mode 상태
# ---------------------------------------------------------------------------
st.markdown(
    "<style>[data-testid='stAppViewContainer']{background:#0a1628;}</style>",
    unsafe_allow_html=True,
)
st.title("✅ AI 추천 승인 (Shadow Mode)")
st.caption("AI 추천 → 사람 승인 → 공정 반영 · 꽃순이김치 MES 시범운영")

shadow = api_get("/shadow-mode", default={"enabled": True, "mode": "SHADOW"})
shadow_on = bool(shadow.get("enabled", True)) if shadow else True

hc1, hc2, hc3 = st.columns([2, 2, 2])
with hc1:
    badge = "🟢 Shadow Mode 활성" if shadow_on else "⚫ Shadow Mode 비활성(자동 반영)"
    st.markdown(f"### {badge}")
with hc2:
    st.markdown(f"**모드**: {shadow.get('mode', 'SHADOW') if shadow else 'SHADOW'}")
with hc3:
    if st.button("🔄 새로고침", use_container_width=True):
        st.rerun()

st.divider()

tab1, tab2, tab3 = st.tabs(["📋 승인 대기 목록", "📜 승인 이력", "⚙️ Shadow Mode 설정"])


# =====================================================================
# 탭 1 — 승인 대기 목록
# =====================================================================
with tab1:
    fc1, fc2, fc3 = st.columns([2, 2, 2])
    with fc1:
        f_type = st.selectbox(
            "유형 필터", ["전체"] + list(ITEM_TYPE_LABEL.keys()),
            format_func=lambda x: "전체" if x == "전체" else ITEM_TYPE_LABEL[x],
        )
    with fc2:
        f_lot = st.text_input("LOT ID 필터", placeholder="예: FE-20260524-007")
    with fc3:
        approver = st.text_input("처리자(승인/거절 시 기록)", value="공장장")

    params: dict = {"status": "PENDING"}
    if f_type != "전체":
        params["item_type"] = f_type
    if f_lot.strip():
        params["lot_id"] = f_lot.strip()

    items = api_get("/items", params=params, default=None)
    if items is None:  # API down → mock
        items = [
            it for it in _mock_items()
            if (f_type == "전체" or it["item_type"] == f_type)
            and (not f_lot.strip() or it.get("lot_id") == f_lot.strip())
        ]

    st.markdown(f"**승인 대기: {len(items)}건**")

    if not items:
        st.info("승인 대기 중인 AI 추천이 없습니다.")

    for it in items:
        with st.container(border=True):
            cl, cr = st.columns([3, 1])
            with cl:
                micon = MODULE_ICON.get(it.get("source_module"), "🤖")
                tlabel = ITEM_TYPE_LABEL.get(it["item_type"], it["item_type"])
                st.markdown(f"#### {micon} {it['title']}")
                st.markdown(
                    f"`{tlabel}`  ·  LOT: **{it.get('lot_id') or '-'}**  "
                    f"·  요청: {it.get('requested_by') or 'AI'}"
                )
                st.markdown(f"**🤖 AI 추천:** {it['ai_recommendation']}")
                ec1, ec2 = st.columns(2)
                with ec1:
                    st.markdown("**현재 상태**")
                    st.json(it.get("current_state") or {}, expanded=False)
                with ec2:
                    st.markdown("**제안 변경**")
                    st.json(it.get("proposed_change") or {}, expanded=False)
                cd_text, cd_color = _countdown(it.get("expires_at"))
                st.markdown(
                    f"<span style='color:{cd_color}'>⌛ {cd_text}</span>",
                    unsafe_allow_html=True,
                )
            with cr:
                confidence_gauge(it.get("confidence"), key=f"gauge_{it['item_id']}")
                st.caption("AI 신뢰도")

            ac1, ac2 = st.columns(2)
            with ac1:
                if st.button("✓ 승인", key=f"approve_{it['item_id']}",
                             use_container_width=True, type="primary"):
                    if not approver.strip():
                        st.warning("처리자를 입력하세요.")
                    else:
                        res, err = api_post(
                            f"/items/{it['item_id']}/approve",
                            {"approved_by": approver.strip(),
                             "approval_note": "현장 검토 후 승인"},
                        )
                        if err:
                            st.error(f"승인 실패 — {err}")
                        else:
                            st.success(f"승인 완료 (item {it['item_id']})")
                            st.rerun()
            with ac2:
                with st.popover("✕ 거절", use_container_width=True):
                    reason = st.text_area(
                        "거절 사유 (필수)", key=f"reason_{it['item_id']}",
                        placeholder="예: 현 발효 상태 양호, 조건 변경 불필요",
                    )
                    if st.button("거절 확정", key=f"reject_btn_{it['item_id']}"):
                        if not reason.strip():
                            st.warning("거절 사유는 필수입니다.")
                        elif not approver.strip():
                            st.warning("처리자를 입력하세요.")
                        else:
                            res, err = api_post(
                                f"/items/{it['item_id']}/reject",
                                {"approved_by": approver.strip(),
                                 "rejection_reason": reason.strip()},
                            )
                            if err:
                                st.error(f"거절 실패 — {err}")
                            else:
                                st.success(f"거절 완료 (item {it['item_id']})")
                                st.rerun()


# =====================================================================
# 탭 2 — 승인 이력
# =====================================================================
with tab2:
    hc1, hc2, hc3 = st.columns(3)
    with hc1:
        days = st.slider("조회 기간(일)", 1, 180, 90)
    with hc2:
        h_approver = st.text_input("승인자 필터", key="hist_approver")
    with hc3:
        h_type = st.selectbox(
            "유형", ["전체"] + list(ITEM_TYPE_LABEL.keys()),
            format_func=lambda x: "전체" if x == "전체" else ITEM_TYPE_LABEL[x],
            key="hist_type",
        )

    date_from = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    hparams: dict = {"date_from": date_from, "limit": 1000}
    if h_approver.strip():
        hparams["approver"] = h_approver.strip()
    if h_type != "전체":
        hparams["item_type"] = h_type

    history = api_get("/history", params=hparams, default=None)
    stats = api_get("/stats", params={"days": days}, default=None)

    if history is None:
        history = _mock_history()
    if stats is None:
        approved = sum(1 for h in history if h["status"] == "APPROVED")
        rejected = sum(1 for h in history if h["status"] == "REJECTED")
        decided = approved + rejected
        stats = {
            "totals": {
                "total": len(history), "approved": approved, "rejected": rejected,
                "expired": sum(1 for h in history if h["status"] == "EXPIRED"),
            },
            "approval_rate": round(approved / decided, 4) if decided else None,
            "avg_handle_minutes": 17.8,
        }

    totals = stats.get("totals", {}) if stats else {}
    rate = stats.get("approval_rate") if stats else None
    avg_min = stats.get("avg_handle_minutes") if stats else None

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("총 처리", totals.get("total", 0))
    m2.metric("승인율", f"{rate*100:.1f}%" if rate is not None else "—")
    m3.metric("평균 처리시간", f"{avg_min:.1f}분" if avg_min is not None else "—")
    m4.metric("만료", totals.get("expired", 0))

    # 상태별 분포 막대
    if history:
        df = pd.DataFrame(history)
        status_counts = df["status"].value_counts().reindex(
            ["APPROVED", "REJECTED", "EXPIRED", "PENDING"]).dropna()
        fig = go.Figure(go.Bar(
            x=[STATUS_BADGE.get(s, (s, "#888"))[0] for s in status_counts.index],
            y=status_counts.values,
            marker_color=[STATUS_BADGE.get(s, (s, "#888"))[1] for s in status_counts.index],
        ))
        fig.update_layout(
            title="처리 상태 분포", height=300, template="plotly_dark",
            paper_bgcolor="#162035", plot_bgcolor="#162035",
            margin=dict(l=40, r=20, t=40, b=40), font=dict(color="#e2e8f0"),
        )
        st.plotly_chart(fig, use_container_width=True)

        show_cols = [c for c in
                     ["item_id", "item_type", "title", "status", "confidence",
                      "approved_by", "approved_at", "rejection_reason"]
                     if c in df.columns]
        st.dataframe(df[show_cols], use_container_width=True, hide_index=True)


# =====================================================================
# 탭 3 — Shadow Mode 설정 (ADMIN)
# =====================================================================
with tab3:
    st.markdown("#### ⚙️ Shadow Mode 설정 (ADMIN 전용)")
    st.caption("시범운영(3개월) 동안 Shadow Mode 는 항상 ON 을 권장합니다.")

    new_state = st.toggle(
        "Shadow Mode 활성화 (AI 추천 → 사람 승인 → 공정 반영)",
        value=shadow_on,
    )
    if new_state != shadow_on:
        if st.button("설정 적용", type="primary"):
            res, err = api_put("/shadow-mode", {"enabled": new_state})
            if err:
                st.error(f"설정 변경 실패 — {err}")
            else:
                st.success(res.get("message", "변경 완료"))
                st.rerun()

    st.divider()
    st.markdown("**자동 승인 임계값 (미래 기능)**")
    st.slider(
        "신뢰도 ≥ 임계값 자동 승인", 90, 100, 99,
        help="시범운영 종료 후 활성화 예정 — 현재는 모든 추천 수동 승인",
        disabled=True,
    )
    st.markdown("**승인 만료 시간**")
    st.number_input(
        "미처리 항목 자동 만료(시간)", min_value=1, max_value=168, value=24,
        help="만료 시간은 항목 등록 시 expires_in_hours 로 설정됩니다.",
        disabled=True,
    )

    st.divider()
    st.markdown("**유형별 승인 권한**")
    authority = (shadow or {}).get("approval_authority") or {
        "FERMENTATION_CONDITION": ["PLANT_MANAGER", "MANAGER", "ADMIN"],
        "SHIPPING_APPROVAL": ["PLANT_MANAGER", "MANAGER", "ADMIN"],
        "QUALITY_OVERRIDE": ["PLANT_MANAGER", "ADMIN"],
        "LOT_STATUS_CHANGE": ["QC", "MANAGER", "ADMIN"],
    }
    auth_df = pd.DataFrame(
        [{"유형": ITEM_TYPE_LABEL.get(k, k), "승인 권한": ", ".join(v)}
         for k, v in authority.items()]
    )
    st.dataframe(auth_df, use_container_width=True, hide_index=True)
