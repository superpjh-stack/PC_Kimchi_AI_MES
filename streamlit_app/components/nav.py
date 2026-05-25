"""
꽃순이김치 MES — 탭 활성화 헬퍼
session_state의 _nav_tab 값을 읽어 JavaScript로 해당 탭을 클릭한다.
"""
from __future__ import annotations
import streamlit as st
import streamlit.components.v1 as components


def activate_tab() -> None:
    """
    session_state에 '_nav_tab'이 있으면 해당 인덱스의 탭을 JS로 활성화.
    st.tabs() 호출 직후에 이 함수를 호출할 것.

    사용 예:
        tabs = st.tabs(["탭1", "탭2", "탭3"])
        activate_tab()   # ← 사이드바에서 탭 인덱스가 지정된 경우 자동 전환
    """
    tab_idx = st.session_state.pop("_nav_tab", None)
    if tab_idx is None or tab_idx == 0:
        return  # 기본 탭(0)은 이미 선택되어 있으므로 JS 불필요

    components.html(
        f"""
        <script>
        (function() {{
            var idx = {tab_idx};
            function clickTab() {{
                var tabs = window.parent.document.querySelectorAll('[data-baseweb="tab"]');
                // Filter to get only top-level tabs (avoid nested tabs)
                if (tabs.length > idx) {{
                    tabs[idx].click();
                    return true;
                }}
                return false;
            }}
            // Retry with delays to handle DOM rendering lag
            if (!clickTab()) {{
                setTimeout(function() {{
                    if (!clickTab()) {{
                        setTimeout(clickTab, 400);
                    }}
                }}, 150);
            }}
        }})();
        </script>
        """,
        height=0,
        scrolling=False,
    )
