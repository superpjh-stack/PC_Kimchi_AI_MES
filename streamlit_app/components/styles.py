"""
꽃순이김치 MES — 디자인 시스템 (Claude Design 핸드오프: 라이트/한지 테마)

색상 토큰, 전역 CSS, 그리고 페이지에서 재사용하는 Python 헬퍼를 제공한다.
- apply_styles()            : 전역 CSS 주입 (모든 페이지에서 호출)
- render_stat_card()        : KPI/통계 카드
- render_badge()            : 상태 배지 (HTML 문자열 반환)
- render_alert()            : 알림 배너
- render_card_header()      : 카드 헤더 (제목 + 서브타이틀)
- style_plotly()            : Plotly figure 라이트 테마 적용 (공통)
하위 호환 헬퍼: metric_card(), status_badge(), section_header()
"""
import streamlit as st

# ----------------------------------------------------------------------------
# 디자인 토큰 (styles.css 핸드오프 기준)
# ----------------------------------------------------------------------------
COLORS = {
    "bg": "#F4EFE6",            # 메인 배경 (한지/종이)
    "card": "#FFFFFF",          # 카드 배경
    "card_2": "#F9F7F4",        # 카드 내부 섹션 배경
    "sidebar": "#181410",       # 사이드바 (다크)
    "accent": "#C53D2E",        # 김치 레드
    "accent_deep": "#9A2A1F",
    "accent_soft": "#FCE5E1",
    "ink_1": "#29261b",         # 기본 텍스트
    "ink_2": "#4A4640",
    "ink_3": "#7B7670",
    "ink_4": "#A8A39E",
    "line": "rgba(0,0,0,.09)",  # 테두리
    "sidebar_ink_1": "#F2EDE8",
    "sidebar_ink_3": "#8A857F",
    "sidebar_line": "rgba(255,255,255,.08)",
    "green": "#4C9B52",
    "olive": "#7A8C3C",
    "orange": "#D97A2B",
    "red": "#C53D2E",
    "celadon": "#3F8C9C",
}

# Plotly 차트 공통 색상 (라이트 테마)
PLOTLY_BG = "#FFFFFF"
PLOT_GRID = "rgba(0,0,0,.08)"
COLORWAY = ["#C53D2E", "#3F8C9C", "#4C9B52", "#D97A2B", "#7A8C3C", "#9A2A1F"]

BASE_CSS = """
<style>
/* ===== 전역 폰트 — 한국어 시스템 폰트 우선, CDN 없이 안정적 렌더링 ===== */
/* ⚠ * 셀렉터에 !important를 쓰면 Streamlit Material Symbols 아이콘 폰트가 깨짐
   → html, body 상속으로 처리하고, 아이콘 폰트 클래스는 명시적으로 복원 */
html, body {
    font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', '맑은 고딕',
                 -apple-system, BlinkMacSystemFont, 'Segoe UI',
                 system-ui, sans-serif !important;
}
/* Streamlit 주요 콘텐츠 요소에 한국어 폰트 적용 */
p, h1, h2, h3, h4, h5, h6, label, li, td, th,
div[data-testid], section[data-testid],
.stMarkdown, .stText, .stAlert,
.stButton > button, .stTextInput input,
.stSelectbox, .stNumberInput input, .stTextArea textarea {
    font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', '맑은 고딕',
                 -apple-system, BlinkMacSystemFont, 'Segoe UI',
                 system-ui, sans-serif !important;
}
/* Material Symbols / Material Icons 아이콘 폰트 복원 — 절대 덮어쓰지 않음 */
.material-symbols-rounded,
.material-symbols-outlined,
.material-symbols-sharp,
.material-icons,
[class^="material-symbols"],
[class*=" material-symbols"],
[class*="material-icon"] {
    font-family: 'Material Symbols Rounded', 'Material Symbols Outlined',
                 'Material Icons', sans-serif !important;
}

/* ===== 메인 배경 / 레이아웃 ===== */
[data-testid="stAppViewContainer"] { background: #F4EFE6 !important; }
[data-testid="stAppViewContainer"] > .main { background: #F4EFE6 !important; }
[data-testid="stHeader"] { background: #F4EFE6 !important; border-bottom: 1px solid rgba(0,0,0,.06); }
.main .block-container { max-width: 100% !important; padding: 20px 28px !important; }
section.main > div { background: transparent !important; }

/* ===== 기본 Streamlit 사이드바 내비게이션 숨기기 ===== */
[data-testid="stSidebarNav"] { display: none !important; }
[data-testid="stSidebarNavItems"] { display: none !important; }
[data-testid="stSidebarNavLink"] { display: none !important; }

/* ===== 사이드바 — 배경/글자 색을 CSS로 직접 강제 (config.toml 재시작과 무관) ===== */
/* 사이드바 배경: 외부 컨테이너와 알려진 내부 컨테이너 전부 #181410으로 고정 */
[data-testid="stSidebar"],
[data-testid="stSidebar"] > div,
[data-testid="stSidebar"] > div > div,
[data-testid="stSidebar"] section,
[data-testid="stSidebarContent"],
[data-testid="stSidebar"] [data-testid="stVerticalBlock"],
[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] {
    background: #181410 !important;
    background-color: #181410 !important;
}
[data-testid="stSidebar"] { border-right: 1px solid rgba(255,255,255,.08) !important; }

/* 사이드바 내 모든 글자를 밝게 — 배경이 다크(#181410)이므로 안전 */
[data-testid="stSidebar"] p     { color: #C9C3BC !important; }
[data-testid="stSidebar"] span  { color: #C9C3BC !important; }
[data-testid="stSidebar"] label { color: #C9C3BC !important; }
[data-testid="stSidebar"] div   { color: #C9C3BC !important; }
[data-testid="stSidebar"] a     { color: #C9C3BC !important; }
[data-testid="stSidebar"] summary { color: #C9C3BC !important; }

/* ===== 메인 콘텐츠 영역 expander: secondaryBgColor=#181410 이라 어두워짐 → 흰색 복원 ===== */
.main [data-testid="stExpander"] > div,
[data-testid="stMain"] [data-testid="stExpander"] > div,
section.main [data-testid="stExpander"] > div {
    background: #FFFFFF !important;
}
.main details,
[data-testid="stMain"] details,
section.main details {
    background: #FFFFFF !important;
    border-radius: 8px !important;
    border: 1px solid rgba(0,0,0,.09) !important;
}
.main details > summary,
[data-testid="stMain"] details > summary,
section.main details > summary {
    color: #29261b !important;
    background: #F9F7F4 !important;
}
.main details > summary:hover,
[data-testid="stMain"] details > summary:hover {
    background: #F4EFE6 !important;
}

/* ── 사이드바 브랜드 마크 ── */
.sb-brand {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px 4px 12px 4px;
}
.sb-brand-mark {
    width: 36px; height: 36px;
    background: #C53D2E;
    border-radius: 8px;
    display: grid; place-items: center;
    font-size: 18px; font-weight: 700; color: #F4EFE6;
    font-family: 'Noto Serif KR', serif;
    flex-shrink: 0;
}
.sb-brand-name { font-size: 14px; font-weight: 600; color: #F2EDE8 !important; line-height: 1.3; }
.sb-brand-sub  { font-size: 10px; color: #8A857F !important; margin-top: 2px; letter-spacing: .3px; }

/* ── 구분선 ── */
.sb-divider { border: none; border-top: 1px solid rgba(255,255,255,.08); margin: 4px 0 10px 0; }

/* ── Expander (메뉴 그룹) ── */
[data-testid="stSidebar"] details > summary {
    font-size: 13px !important;
    font-weight: 500 !important;
    padding: 7px 6px !important;
    border-radius: 6px !important;
    color: #F2EDE8 !important;
    background: transparent !important;
}
[data-testid="stSidebar"] details > summary:hover {
    background: rgba(255,255,255,.06) !important;
    color: #FFFFFF !important;
}
[data-testid="stSidebar"] details[open] > summary {
    color: #E8A89F !important;
    background: rgba(197,61,46,.16) !important;
}
[data-testid="stSidebar"] details {
    border: none !important;
    background: transparent !important;
    margin-bottom: 2px !important;
}
/* Streamlit expander 내부 content 영역 */
[data-testid="stSidebar"] [data-testid="stExpander"] > div {
    background: transparent !important;
    border: none !important;
}

/* ── 사이드바 page_link ── */
[data-testid="stSidebar"] [data-testid="stPageLink"] a { color: #C9C3BC !important; font-size: 13px !important; }
[data-testid="stSidebar"] [data-testid="stPageLink"] a:hover { color: #F2EDE8 !important; }

/* ── 사이드바 서브메뉴 버튼 (expander 내부) — 높은 우선순위로 오버라이드 ── */
[data-testid="stSidebar"] details .stButton > button,
[data-testid="stSidebar"] [data-testid="stExpander"] .stButton > button {
    background: transparent !important;
    border: none !important;
    border-left: 2px solid rgba(255,255,255,.12) !important;
    border-radius: 0 4px 4px 0 !important;
    color: #8A857F !important;
    font-size: 12px !important;
    font-weight: 400 !important;
    padding: 5px 8px 5px 16px !important;
    margin: 1px 0 1px 4px !important;
    text-align: left !important;
    line-height: 1.4 !important;
    min-height: 28px !important;
    height: auto !important;
    box-shadow: none !important;
    justify-content: flex-start !important;
    width: calc(100% - 4px) !important;
}
[data-testid="stSidebar"] details .stButton > button:hover,
[data-testid="stSidebar"] [data-testid="stExpander"] .stButton > button:hover {
    background: rgba(197,61,46,.12) !important;
    color: #E8A89F !important;
    border-left-color: #C53D2E !important;
    box-shadow: none !important;
}
[data-testid="stSidebar"] details .stButton > button:active,
[data-testid="stSidebar"] details .stButton > button:focus,
[data-testid="stSidebar"] [data-testid="stExpander"] .stButton > button:active,
[data-testid="stSidebar"] [data-testid="stExpander"] .stButton > button:focus {
    background: rgba(197,61,46,.18) !important;
    color: #F2EDE8 !important;
    border-left-color: #C53D2E !important;
    box-shadow: none !important;
    outline: none !important;
}

/* ── 접속자 카드 ── */
.sb-user-card {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px;
    background: rgba(255,255,255,.04);
    border: 1px solid rgba(255,255,255,.08);
    border-radius: 8px;
    margin-bottom: 8px;
}
.sb-user-avatar { font-size: 22px; flex-shrink: 0; }
.sb-user-name {
    font-size: 14px; font-weight: 600; color: #F2EDE8 !important;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.sb-user-role { font-size: 11px; margin-top: 2px; font-weight: 500; }

/* ── 사이드바 모든 버튼 (로그아웃 포함) — 기본 .stButton 오버라이드 ── */
[data-testid="stSidebar"] .stButton > button {
    background: transparent !important;
    border: 1px solid rgba(255,255,255,.14) !important;
    color: #C9C3BC !important;
    font-size: 13px !important;
    box-shadow: none !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    border-color: #C53D2E !important;
    color: #E8A89F !important;
    background: rgba(197,61,46,.10) !important;
}

/* ===== 페이지 헤더 ===== */
.page-header {
    display: flex; justify-content: space-between; align-items: flex-start;
    margin-bottom: 20px; padding-bottom: 16px;
    border-bottom: 1px solid rgba(0,0,0,.09);
}
.page-title { font-size: 22px; font-weight: 700; color: #29261b; margin: 0; }
.page-desc  { font-size: 12px; color: #7B7670; margin-top: 4px; }

/* ===== 카드 컴포넌트 ===== */
.mes-card {
    background: #FFFFFF;
    border: 1px solid rgba(0,0,0,.09);
    border-radius: 12px;
    padding: 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,.06);
    margin-bottom: 12px;
}
.mes-card-title { font-size: 14px; font-weight: 600; color: #29261b; display: flex; align-items: center; gap: 8px; }
.mes-card-sub   { font-size: 11.5px; color: #7B7670; margin-top: 2px; }

/* ===== Stat 카드 (KPI) ===== */
.stat-card {
    background: #FFFFFF;
    border: 1px solid rgba(0,0,0,.09);
    border-radius: 10px;
    padding: 14px 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,.06);
}
.stat-card-label   { font-size: 11.5px; color: #7B7670; font-weight: 500; }
.stat-card-value   { font-size: 28px; font-weight: 700; color: #29261b; line-height: 1.2; margin: 4px 0; }
.stat-card-unit    { font-size: 14px; color: #7B7670; margin-left: 3px; }
.stat-card-delta-up { color: #4C9B52; font-size: 12px; }
.stat-card-delta-dn { color: #C53D2E; font-size: 12px; }
.stat-card-sub     { font-size: 11px; color: #A8A39E; margin-top: 4px; }

/* ===== 배지 (핸드오프) ===== */
.badge { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 99px; font-size: 11px; font-weight: 600; }
.badge-green   { background: #DFF0E0; color: #2C5C2E; }
.badge-red     { background: #FCE5E1; color: #7D1C0F; }
.badge-amber   { background: #FEF3C7; color: #78350F; }
.badge-blue    { background: #E0F2F7; color: #0C4A6E; }
.badge-neutral { background: #F0EDEA; color: #4A4640; }
.badge-olive   { background: #EDF2DD; color: #3F5320; }

/* 하위 호환 배지(기존 .badge-ok/warn/error/info) → 라이트 매핑 */
.badge-ok    { background: #DFF0E0; color: #2C5C2E; border-radius: 99px; padding: 2px 8px; font-size: 11px; font-weight: 600; }
.badge-warn  { background: #FEF3C7; color: #78350F; border-radius: 99px; padding: 2px 8px; font-size: 11px; font-weight: 600; }
.badge-error { background: #FCE5E1; color: #7D1C0F; border-radius: 99px; padding: 2px 8px; font-size: 11px; font-weight: 600; }
.badge-info  { background: #E0F2F7; color: #0C4A6E; border-radius: 99px; padding: 2px 8px; font-size: 11px; font-weight: 600; }

/* ===== 테이블 (HTML mes-table) ===== */
.mes-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.mes-table th {
    background: #F9F7F4; border-bottom: 1px solid rgba(0,0,0,.09);
    padding: 8px 12px; text-align: left; font-size: 11px; font-weight: 600;
    color: #7B7670; text-transform: uppercase; letter-spacing: .04em;
}
.mes-table td { padding: 9px 12px; border-bottom: 1px solid rgba(0,0,0,.06); color: #29261b; }
.mes-table tr:hover td { background: #F9F7F4; }
.mes-table .num { font-family: 'JetBrains Mono', monospace; text-align: right; }
.mes-table .pk  { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #C53D2E; }

/* ===== 알림 배너 ===== */
.alert-err  { background: #FCE5E1; border: 1px solid #F0B4A8; color: #7D1C0F; border-radius: 8px; padding: 10px 14px; font-size: 13px; }
.alert-warn { background: #FEF3C7; border: 1px solid #F6D770; color: #78350F; border-radius: 8px; padding: 10px 14px; font-size: 13px; }
.alert-ok   { background: #DFF0E0; border: 1px solid #9FCB9C; color: #2C5C2E; border-radius: 8px; padding: 10px 14px; font-size: 13px; }
.alert-info { background: #E0F2F7; border: 1px solid #90C5D2; color: #0C4A6E; border-radius: 8px; padding: 10px 14px; font-size: 13px; }

/* ===== 섹션 헤더 ===== */
.section-header {
    font-size: 15px; font-weight: 600; color: #29261b;
    padding-bottom: 8px; border-bottom: 1px solid rgba(0,0,0,.09);
    margin-bottom: 14px; display: flex; align-items: center; gap: 6px;
}

/* ===== 탭 ===== */
[data-testid="stTabs"] > div:first-child {
    border-bottom: 1px solid rgba(0,0,0,.09) !important;
    gap: 0 !important;
}
.stTabs [data-baseweb="tab-list"] { background: transparent !important; gap: 0 !important; }
.stTabs [data-baseweb="tab"] {
    font-size: 13px !important; font-weight: 500 !important;
    color: #7B7670 !important; padding: 8px 14px !important;
    border-bottom: 2px solid transparent !important; background: transparent !important;
}
.stTabs [data-baseweb="tab"]:hover { color: #29261b !important; }
.stTabs [aria-selected="true"] {
    color: #C53D2E !important; border-bottom: 2px solid #C53D2E !important; background: transparent !important;
}

/* ===== 버튼 ===== */
.stButton > button {
    background: #FFFFFF !important;
    border: 1px solid rgba(0,0,0,.12) !important;
    color: #29261b !important;
    border-radius: 7px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    box-shadow: 0 1px 2px rgba(0,0,0,.04) !important;
}
.stButton > button:hover { border-color: #C53D2E !important; color: #C53D2E !important; }
.stButton > button[kind="primary"],
.stFormSubmitButton > button {
    background: #C53D2E !important;
    border-color: #C53D2E !important;
    color: #FFFFFF !important;
}
.stFormSubmitButton > button:hover { background: #9A2A1F !important; border-color: #9A2A1F !important; color: #FFFFFF !important; }

/* ===== 입력 요소 ===== */
.stTextInput > div > div > input,
.stNumberInput > div > div > input,
.stDateInput > div > div > input,
.stTextArea textarea {
    background: #FFFFFF !important;
    border: 1px solid rgba(0,0,0,.12) !important;
    color: #29261b !important;
    border-radius: 7px !important;
}
.stSelectbox > div > div {
    background: #FFFFFF !important;
    border: 1px solid rgba(0,0,0,.12) !important;
    color: #29261b !important;
    border-radius: 7px !important;
}
.stTextInput input::placeholder, .stTextArea textarea::placeholder { color: #A8A39E !important; }

/* ===== st.metric 오버라이드 ===== */
[data-testid="stMetric"] {
    background: #FFFFFF !important;
    border: 1px solid rgba(0,0,0,.09) !important;
    border-radius: 10px !important;
    padding: 14px 16px !important;
}
[data-testid="stMetricLabel"] { color: #7B7670 !important; font-size: 11.5px !important; }
[data-testid="stMetricValue"] { color: #29261b !important; font-size: 24px !important; font-weight: 700 !important; }

/* ===== DataFrame ===== */
[data-testid="stDataFrame"] { border: 1px solid rgba(0,0,0,.09) !important; border-radius: 8px; }

/* ===== st.alert (info/success/warning/error) 라이트 톤 ===== */
.stAlert { border-radius: 8px; }

/* ===== 구분선 ===== */
hr { border-color: rgba(0,0,0,.09); }

/* ===== AI 채팅 ===== */
.chat-user { background: #C53D2E; border-radius: 12px 12px 2px 12px; padding: 10px 14px; color: #FFFFFF; margin-left: 20%; }
.chat-ai   { background: #FFFFFF; border-radius: 12px 12px 12px 2px; padding: 10px 14px; color: #29261b; margin-right: 20%; border: 1px solid rgba(0,0,0,.09); }
.chat-source { font-size: 11px; color: #A8A39E; margin-top: 4px; }
</style>
"""


def apply_styles():
    """모든 페이지에서 호출 — 전역 라이트/한지 테마 CSS 주입"""
    st.markdown(BASE_CSS, unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# 핸드오프 헬퍼
# ----------------------------------------------------------------------------
def render_stat_card(label: str, value, unit: str = "", delta: str = "",
                     delta_up: bool = True, sub: str = ""):
    """KPI/통계 stat 카드 렌더링."""
    delta_html = ""
    if delta:
        cls = "stat-card-delta-up" if delta_up else "stat-card-delta-dn"
        arrow = "▲" if delta_up else "▼"
        delta_html = f"<div class='{cls}'>{arrow} {delta}</div>"
    unit_html = f"<span class='stat-card-unit'>{unit}</span>" if unit else ""
    sub_html = f"<div class='stat-card-sub'>{sub}</div>" if sub else ""
    st.markdown(
        f"""
        <div class="stat-card">
            <div class="stat-card-label">{label}</div>
            <div class="stat-card-value">{value}{unit_html}</div>
            {delta_html}
            {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


_BADGE_TONE = {
    "green": "badge-green", "red": "badge-red", "amber": "badge-amber",
    "blue": "badge-blue", "neutral": "badge-neutral", "olive": "badge-olive",
}


def render_badge(text: str, tone: str = "neutral") -> str:
    """배지 HTML 문자열 반환. tone: green/red/amber/blue/neutral/olive"""
    cls = _BADGE_TONE.get(tone, "badge-neutral")
    return f'<span class="badge {cls}">{text}</span>'


def render_alert(message: str, kind: str = "info"):
    """알림 배너. kind: err/warn/ok/info"""
    cls = {"err": "alert-err", "warn": "alert-warn", "ok": "alert-ok", "info": "alert-info"}.get(kind, "alert-info")
    st.markdown(f'<div class="{cls}">{message}</div>', unsafe_allow_html=True)


def render_card_header(title: str, sub: str = ""):
    """카드 헤더 (제목 + 서브타이틀)"""
    sub_html = f"<div class='mes-card-sub'>{sub}</div>" if sub else ""
    st.markdown(
        f"<div class='mes-card-title'>{title}</div>{sub_html}",
        unsafe_allow_html=True,
    )


def render_page_header(title: str, desc: str = "", right: str = ""):
    """페이지 상단 헤더 (제목/설명 + 우측 영역)"""
    desc_html = f"<div class='page-desc'>{desc}</div>" if desc else ""
    right_html = f"<div style='font-size:13px;color:#7B7670;'>{right}</div>" if right else ""
    st.markdown(
        f"""
        <div class="page-header">
            <div>
                <div class="page-title">{title}</div>
                {desc_html}
            </div>
            {right_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def style_plotly(fig, height: int = 320, legend: bool = True):
    """Plotly figure에 라이트/한지 테마 적용 (공통)."""
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor=PLOTLY_BG,
        plot_bgcolor=PLOTLY_BG,
        height=height,
        margin=dict(l=40, r=20, t=40, b=40),
        font=dict(color="#29261b", size=12,
                  family="Pretendard Variable, Pretendard, sans-serif"),
        colorway=COLORWAY,
        showlegend=legend,
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(gridcolor=PLOT_GRID, zerolinecolor=PLOT_GRID)
    fig.update_yaxes(gridcolor=PLOT_GRID, zerolinecolor=PLOT_GRID)
    return fig


# ----------------------------------------------------------------------------
# 하위 호환 헬퍼 (기존 페이지에서 사용 중 — 시그니처 유지, 라이트 테마로 표시)
# ----------------------------------------------------------------------------
def metric_card(label: str, value: str, delta: str = "", color: str = "#C53D2E", target: str = ""):
    """기존 KPI 카드 — stat-card 라이트 스타일로 렌더링 (시그니처 유지)."""
    target_html = f"<div class='stat-card-sub'>목표: {target}</div>" if target else ""
    delta_html = f"<div class='stat-card-delta-up'>{delta}</div>" if delta else ""
    st.markdown(
        f"""
        <div class="stat-card">
            <div class="stat-card-label">{label}</div>
            <div class="stat-card-value" style="color:{color};">{value}</div>
            {target_html}
            {delta_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def status_badge(status: str) -> str:
    """상태 문자열 → 라이트 배지 HTML (기존 페이지 호환)."""
    mapping = {
        "정상": render_badge("✓ 정상", "green"),
        "주의": render_badge("⚠ 주의", "amber"),
        "이상": render_badge("✕ 이상", "red"),
        "진행중": render_badge("● 진행중", "blue"),
        "완료": render_badge("✓ 완료", "green"),
        "승인": render_badge("✓ 승인", "green"),
        "대기": render_badge("⏳ 대기", "amber"),
        "반려": render_badge("✕ 반려", "red"),
        "처리중": render_badge("● 처리중", "amber"),
        "처리완료": render_badge("✓ 처리완료", "green"),
        "PASS": render_badge("PASS", "green"),
        "FAIL": render_badge("FAIL", "red"),
    }
    return mapping.get(status, render_badge(status, "blue"))


def section_header(title: str, icon: str = ""):
    st.markdown(f'<div class="section-header">{icon} {title}</div>', unsafe_allow_html=True)
