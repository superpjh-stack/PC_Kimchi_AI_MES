"""
꽃순이김치 제조AI 스마트공장 MES — 사용자/시스템관리 화면 (Streamlit)
프로젝트: SF26179540 (평창꽃순이(주)농업회사법인) / 로뎀솔루션

화면(기획서 8장, 목업 07-master-system.html 기준):
  탭1 사용자 관리 : 사용자 목록 + 등록/수정 폼 + 역할 권한 매트릭스
  탭2 로그 관리   : 시스템 로그 / 사용자 활동 / AI Agent 질의 (3 서브탭)
  탭3 알림 설정   : 유형별 채널/수신자 설정 + 발송 이력
  탭4 시스템 설정 : Edge Collector 연결 상태 + 센서 매핑 + 배치 스케줄

API 연동: utils.api_client (FastAPI /api/v1/system).
모든 API 호출은 try/except 로 감싸 실패 시 st.warning 으로 안내한다.
"""
from __future__ import annotations

import datetime as dt

import httpx
import streamlit as st

# ---------------------------------------------------------------------
# API 클라이언트 (utils.api_client.get_client 와 호환)
# ---------------------------------------------------------------------
BASE_URL = "http://localhost:8000/api/v1/system"

ROLE_LABELS = {
    "ADMIN": "관리자",
    "MANAGER": "공장장",
    "QUALITY": "품질담당자",
    "OPERATOR": "현장작업자",
}
MENU_LABELS = {
    "DASHBOARD": "AI 대시보드",
    "PROCESS": "공정관리",
    "DATA": "데이터관리",
    "KPI": "KPI관리",
    "MASTER": "기준정보관리",
    "USER_SYSTEM": "사용자/시스템관리",
    "INTAKE": "원재료관리",
    "FERMENTATION": "숙성발효관리",
    "SHIPPING": "포장출하관리",
}


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=30.0)


def api_get(path: str, params: dict | None = None):
    try:
        r = _client().get(path, params=params or {})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.warning(f"조회 실패 ({path}): {e}")
        return None


def api_send(method: str, path: str, json: dict | None = None):
    try:
        r = _client().request(method, path, json=json)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"요청 실패 ({method} {path}): {e}")
        return None


# ---------------------------------------------------------------------
st.set_page_config(page_title="사용자/시스템관리", layout="wide")
st.title("사용자 / 시스템관리")
st.caption("권한·로그·알림·시스템 설정 (관리자 전용)")

tab_user, tab_log, tab_noti, tab_sys = st.tabs(
    ["사용자 관리", "로그 관리", "알림 설정", "시스템 설정"]
)


# =====================================================================
# 탭 1. 사용자 관리
# =====================================================================
with tab_user:
    st.subheader("사용자 목록")
    only_active = st.toggle("활성 사용자만 표시", value=False, key="user_active_toggle")
    params = {"is_active": "true"} if only_active else None
    users = api_get("/users", params) or []

    if users:
        table = []
        for u in users:
            roles = u.get("roles") or []
            badges = " ".join(f"`{ROLE_LABELS.get(r, r)}`" for r in roles) or "-"
            table.append({
                "ID": u["user_id"],
                "사용자명": u["username"],
                "이름": u["full_name"],
                "부서": u.get("department") or "-",
                "역할": badges,
                "상태": "활성" if u["is_active"] else "비활성",
                "마지막 로그인": u.get("last_login") or "-",
            })
        st.dataframe(table, use_container_width=True, hide_index=True)
    else:
        st.info("등록된 사용자가 없습니다.")

    st.divider()

    # 사용자 등록/수정
    roles_list = api_get("/roles") or []
    role_id_by_label = {f"{ROLE_LABELS.get(r['role_code'], r['role_name'])}": r["role_id"]
                        for r in roles_list}

    with st.expander("사용자 등록 / 수정", expanded=False):
        mode = st.radio("작업", ["신규 등록", "정보 수정", "비활성화"], horizontal=True, key="user_mode")

        if mode == "신규 등록":
            with st.form("user_create_form"):
                c1, c2 = st.columns(2)
                username = c1.text_input("사용자명 (로그인 ID)")
                full_name = c2.text_input("이름")
                email = c1.text_input("이메일")
                department = c2.text_input("부서")
                password = c1.text_input("비밀번호", type="password")
                sel_roles = st.multiselect("역할", options=list(role_id_by_label.keys()))
                if st.form_submit_button("등록", type="primary"):
                    payload = {
                        "username": username, "full_name": full_name,
                        "email": email or None, "department": department or None,
                        "password": password,
                        "role_ids": [role_id_by_label[r] for r in sel_roles],
                    }
                    if api_send("POST", "/users", payload):
                        st.success(f"사용자 '{username}' 등록 완료")
                        st.rerun()

        elif mode == "정보 수정":
            target = st.selectbox(
                "수정 대상", options=[f"{u['user_id']} - {u['full_name']}" for u in users],
                key="user_edit_target") if users else None
            if target:
                uid = int(target.split(" - ")[0])
                with st.form("user_update_form"):
                    c1, c2 = st.columns(2)
                    full_name = c1.text_input("이름")
                    email = c2.text_input("이메일")
                    department = c1.text_input("부서")
                    is_active = c2.checkbox("활성 상태", value=True)
                    new_pw = c1.text_input("새 비밀번호 (변경 시)", type="password")
                    if st.form_submit_button("수정", type="primary"):
                        payload = {"is_active": is_active}
                        if full_name:
                            payload["full_name"] = full_name
                        if email:
                            payload["email"] = email
                        if department:
                            payload["department"] = department
                        if new_pw:
                            payload["password"] = new_pw
                        if api_send("PUT", f"/users/{uid}", payload):
                            st.success("수정 완료")
                            st.rerun()

        else:  # 비활성화
            target = st.selectbox(
                "비활성화 대상", options=[f"{u['user_id']} - {u['full_name']}" for u in users],
                key="user_del_target") if users else None
            if target and st.button("비활성화 실행", type="secondary"):
                uid = int(target.split(" - ")[0])
                if api_send("DELETE", f"/users/{uid}"):
                    st.success("비활성화 완료")
                    st.rerun()

    st.divider()

    # 역할 권한 매트릭스 (메뉴 × 역할, 읽기/쓰기 체크박스 그리드)
    st.subheader("역할별 메뉴 권한 매트릭스")
    if roles_list:
        # 역할별 권한 로드
        perms_by_role: dict[int, dict[str, dict]] = {}
        for r in roles_list:
            res = api_get(f"/roles/{r['role_id']}/permissions")
            if res:
                perms_by_role[r["role_id"]] = {p["menu_code"]: p for p in res["permissions"]}

        edit_role_label = st.selectbox(
            "편집할 역할 선택",
            options=[f"{ROLE_LABELS.get(r['role_code'], r['role_name'])} ({r['role_code']})"
                     for r in roles_list],
            key="perm_role_sel")
        edit_role_code = edit_role_label.split("(")[-1].rstrip(")")
        edit_role = next(r for r in roles_list if r["role_code"] == edit_role_code)
        edit_role_id = edit_role["role_id"]
        cur_perms = perms_by_role.get(edit_role_id, {})

        st.write(f"**{ROLE_LABELS.get(edit_role_code, edit_role_code)}** 권한 설정")
        hcol = st.columns([3, 1, 1])
        hcol[0].markdown("**메뉴**")
        hcol[1].markdown("**읽기**")
        hcol[2].markdown("**쓰기**")

        new_perms = []
        for menu_code, menu_label in MENU_LABELS.items():
            cur = cur_perms.get(menu_code, {"can_read": False, "can_write": False})
            row = st.columns([3, 1, 1])
            row[0].write(menu_label)
            cr = row[1].checkbox("R", value=cur["can_read"],
                                 key=f"r_{edit_role_id}_{menu_code}", label_visibility="collapsed")
            cw = row[2].checkbox("W", value=cur["can_write"],
                                 key=f"w_{edit_role_id}_{menu_code}", label_visibility="collapsed")
            new_perms.append({"menu_code": menu_code, "can_read": cr, "can_write": cw})

        if st.button("권한 저장", type="primary", key="perm_save"):
            if api_send("PUT", f"/roles/{edit_role_id}/permissions", {"permissions": new_perms}):
                st.success("권한 매트릭스 저장 완료")
                st.rerun()
    else:
        st.info("역할 정보를 불러올 수 없습니다.")


# =====================================================================
# 탭 2. 로그 관리
# =====================================================================
with tab_log:
    auto_refresh = st.toggle("실시간 갱신 (30초)", value=False, key="log_auto_refresh")
    sub_sys, sub_act, sub_ai = st.tabs(["시스템 로그", "사용자 활동", "AI Agent 질의"])

    # --- 시스템 로그 ---
    with sub_sys:
        c1, c2, c3, c4 = st.columns(4)
        level = c1.selectbox("레벨", ["전체", "ERROR", "WARNING", "INFO", "DEBUG"], key="sys_level")
        module = c2.text_input("모듈", key="sys_module")
        start_dt = c3.date_input("시작일", value=dt.date.today() - dt.timedelta(days=7), key="sys_start")
        end_dt = c4.date_input("종료일", value=dt.date.today(), key="sys_end")
        params = {"limit": 200}
        if level != "전체":
            params["level"] = level
        if module:
            params["module"] = module
        params["start_dt"] = f"{start_dt}T00:00:00"
        params["end_dt"] = f"{end_dt}T23:59:59"
        logs = api_get("/logs/system", params) or []
        if logs:
            st.dataframe(
                [{"시각": l["log_time"], "레벨": l["log_level"], "모듈": l.get("module"),
                  "메시지": l["message"], "서버": l.get("server_id")} for l in logs],
                use_container_width=True, hide_index=True)
            st.caption(f"총 {len(logs)}건")
        else:
            st.info("로그가 없습니다.")

    # --- 사용자 활동 로그 ---
    with sub_act:
        c1, c2 = st.columns(2)
        uid = c1.text_input("사용자 ID", key="act_uid")
        action = c2.selectbox(
            "액션", ["전체", "LOGIN", "LOGOUT", "CREATE", "UPDATE", "DELETE", "VIEW"], key="act_type")
        params = {"limit": 200}
        if uid:
            params["user_id"] = uid
        if action != "전체":
            params["action_type"] = action
        logs = api_get("/logs/activity", params) or []
        if logs:
            st.dataframe(
                [{"시각": l["created_at"], "사용자": l.get("full_name") or l.get("username"),
                  "액션": l["action_type"], "리소스": l.get("resource_type"),
                  "대상ID": l.get("resource_id"), "IP": l.get("ip_address"),
                  "결과": l.get("result")} for l in logs],
                use_container_width=True, hide_index=True)
            st.caption(f"총 {len(logs)}건")
        else:
            st.info("활동 로그가 없습니다.")

    # --- AI Agent 질의 로그 (질의-응답 expander + 출처) ---
    with sub_ai:
        c1, c2 = st.columns(2)
        agent_type = c1.selectbox("Agent 유형", ["전체", "INTAKE", "SHIPPING"], key="ai_agent_type")
        uid = c2.text_input("사용자 ID", key="ai_uid")
        params = {"limit": 100}
        if agent_type != "전체":
            params["agent_type"] = agent_type
        if uid:
            params["user_id"] = uid
        logs = api_get("/logs/ai-agent", params) or []
        if logs:
            st.caption(f"총 {len(logs)}건")
            for l in logs:
                at = "원재료입고" if l["agent_type"] == "INTAKE" else "포장출하"
                title = f"[{at}] {l['query_text'][:50]} — {l.get('full_name') or '-'} ({l['created_at']})"
                with st.expander(title):
                    st.markdown(f"**질의**: {l['query_text']}")
                    st.markdown(f"**응답**: {l.get('response_text') or '(응답 없음)'}")
                    if l.get("needs_approval"):
                        st.warning("운영자 승인 필요 항목")
                    sources = l.get("sources") or []
                    if sources:
                        st.markdown("**참조 출처**")
                        for s in sources:
                            st.markdown(f"- {s.get('title', s) if isinstance(s, dict) else s}")
                    meta = []
                    if l.get("latency_ms") is not None:
                        meta.append(f"지연 {l['latency_ms']}ms")
                    if l.get("feedback"):
                        meta.append(f"피드백 {l['feedback']}")
                    if meta:
                        st.caption(" · ".join(meta))
        else:
            st.info("AI Agent 질의 로그가 없습니다.")

    if auto_refresh:
        import time
        time.sleep(30)
        st.rerun()


# =====================================================================
# 탭 3. 알림 설정
# =====================================================================
with tab_noti:
    st.subheader("알림 유형별 채널 설정")
    configs = api_get("/notifications/config") or []
    if configs:
        st.dataframe(
            [{"ID": c["config_id"], "유형": c["notification_type"], "채널": c["channel"],
              "수신자 수": len(c.get("recipients") or []),
              "활성": "O" if c["is_active"] else "X"} for c in configs],
            use_container_width=True, hide_index=True)

        # 알림 활성/비활성 직접 토글 (배치 스케줄과 동일 UX 패턴)
        st.markdown("**알림별 활성화 토글**")
        for c in configs:
            label = f"{c['notification_type']} / {c['channel']} (ID {c['config_id']})"
            new_active = st.toggle(label, value=bool(c["is_active"]),
                                   key=f"noti_toggle_{c['config_id']}")
            if new_active != c["is_active"]:
                if api_send("PUT", f"/notifications/config/{c['config_id']}",
                            {"is_active": new_active}):
                    st.toast(f"{'활성화' if new_active else '비활성화'} 완료: {label}")
                    st.rerun()
    else:
        st.info("등록된 알림 설정이 없습니다.")

    with st.expander("알림 설정 등록 / 수정"):
        noti_mode = st.radio("작업", ["신규 등록", "수정"], horizontal=True, key="noti_mode")
        if noti_mode == "신규 등록":
            with st.form("noti_create"):
                c1, c2 = st.columns(2)
                ntype = c1.selectbox("알림 유형", ["ALARM", "KPI", "SYSTEM"])
                channel = c2.selectbox("채널", ["SMS", "EMAIL", "PUSH"])
                recipients_raw = st.text_area("수신자 (줄바꿈으로 구분)")
                is_active = st.checkbox("활성화", value=True)
                if st.form_submit_button("등록", type="primary"):
                    recipients = [x.strip() for x in recipients_raw.splitlines() if x.strip()]
                    payload = {"notification_type": ntype, "channel": channel,
                               "recipients": recipients, "is_active": is_active}
                    if api_send("POST", "/notifications/config", payload):
                        st.success("알림 설정 등록 완료")
                        st.rerun()
        else:
            if configs:
                target = st.selectbox(
                    "수정 대상",
                    options=[f"{c['config_id']} - {c['notification_type']}/{c['channel']}"
                             for c in configs], key="noti_edit_target")
                cid = int(target.split(" - ")[0])
                with st.form("noti_update"):
                    channel = st.selectbox("채널", ["SMS", "EMAIL", "PUSH"], key="noti_up_ch")
                    recipients_raw = st.text_area("수신자 (줄바꿈으로 구분)", key="noti_up_rcpt")
                    is_active = st.checkbox("활성화", value=True, key="noti_up_active")
                    if st.form_submit_button("수정", type="primary"):
                        payload = {"channel": channel, "is_active": is_active}
                        recipients = [x.strip() for x in recipients_raw.splitlines() if x.strip()]
                        if recipients:
                            payload["recipients"] = recipients
                        if api_send("PUT", f"/notifications/config/{cid}", payload):
                            st.success("수정 완료")
                            st.rerun()

    st.divider()
    st.subheader("알림 발송 이력")
    c1, _ = st.columns([1, 3])
    status = c1.selectbox("상태", ["전체", "SENT", "FAILED", "PENDING"], key="noti_log_status")
    params = {"limit": 200}
    if status != "전체":
        params["status"] = status
    noti_logs = api_get("/notifications/logs", params) or []
    if noti_logs:
        st.dataframe(
            [{"발송시각": n["sent_at"], "수신처": n["recipient"], "채널": n["channel"],
              "상태": n["status"], "메시지": (n.get("message") or "")[:60]} for n in noti_logs],
            use_container_width=True, hide_index=True)
    else:
        st.info("발송 이력이 없습니다.")


# =====================================================================
# 탭 4. 시스템 설정
# =====================================================================
with tab_sys:
    # --- Edge Collector 장치 목록 + 연결 상태 ---
    st.subheader("Edge Collector 장치")
    devices = api_get("/edge-devices") or []
    if devices:
        for d in devices:
            conn_badge = "🟢 연결됨" if d.get("is_connected") else "🔴 끊김"
            cols = st.columns([3, 2, 2, 2])
            cols[0].markdown(f"**{d['device_name']}** ({d['protocol']})")
            cols[1].write(f"{d['host']}:{d['port']}")
            cols[2].write(conn_badge)
            cols[3].write(f"마지막 수신: {d.get('last_seen') or '-'}")
    else:
        st.info("등록된 Edge 장치가 없습니다.")

    with st.expander("Edge 장치 등록 / 수정"):
        edge_mode = st.radio("작업", ["신규 등록", "수정"], horizontal=True, key="edge_mode")
        if edge_mode == "신규 등록":
            with st.form("edge_create"):
                c1, c2 = st.columns(2)
                name = c1.text_input("장치명")
                protocol = c2.selectbox("프로토콜", ["OPC_UA", "MODBUS"])
                host = c1.text_input("Host/IP", value="192.168.1.100")
                port = c2.number_input("Port", value=4840, step=1)
                timeout = c1.number_input("타임아웃(초)", value=10, step=1)
                retry = c2.number_input("재연결 시도", value=3, step=1)
                if st.form_submit_button("등록", type="primary"):
                    payload = {"device_name": name, "protocol": protocol, "host": host,
                               "port": int(port), "timeout_sec": int(timeout),
                               "retry_count": int(retry), "is_active": True}
                    if api_send("POST", "/edge-devices", payload):
                        st.success("Edge 장치 등록 완료")
                        st.rerun()
        elif devices:
            target = st.selectbox(
                "수정 대상", options=[f"{d['device_id']} - {d['device_name']}" for d in devices],
                key="edge_edit_target")
            did = int(target.split(" - ")[0])
            with st.form("edge_update"):
                c1, c2 = st.columns(2)
                host = c1.text_input("Host/IP", key="edge_up_host")
                port = c2.number_input("Port", value=4840, step=1, key="edge_up_port")
                is_active = st.checkbox("활성화", value=True, key="edge_up_active")
                if st.form_submit_button("수정", type="primary"):
                    payload = {"is_active": is_active}
                    if host:
                        payload["host"] = host
                    payload["port"] = int(port)
                    if api_send("PUT", f"/edge-devices/{did}", payload):
                        st.success("수정 완료")
                        st.rerun()

    # --- 센서 매핑 ---
    if devices:
        st.divider()
        st.subheader("센서 매핑")
        dev_target = st.selectbox(
            "장치 선택", options=[f"{d['device_id']} - {d['device_name']}" for d in devices],
            key="sensor_dev_sel")
        did = int(dev_target.split(" - ")[0])
        sensors = api_get(f"/edge-devices/{did}/sensors") or []
        if sensors:
            st.dataframe(
                [{"센서ID": s["sensor_id"], "센서명": s.get("sensor_name"),
                  "DB컬럼": s["data_field"], "단위": s.get("unit"),
                  "보정계수": s.get("scale_factor"), "오프셋": s.get("offset_value"),
                  "주기(초)": s.get("interval_sec")} for s in sensors],
                use_container_width=True, hide_index=True)
        else:
            st.info("매핑된 센서가 없습니다.")

        with st.expander("센서 매핑 등록"):
            with st.form("sensor_create"):
                c1, c2 = st.columns(2)
                sid = c1.text_input("센서 ID", value="SENSOR-PROC03-TEMP-01")
                sname = c2.text_input("센서명")
                field = c1.text_input("DB 컬럼명", value="pickling_temp")
                unit = c2.text_input("단위", value="°C")
                scale = c1.number_input("보정 계수", value=1.0, step=0.1)
                offset = c2.number_input("오프셋", value=0.0, step=0.1)
                interval = st.number_input("수집 주기(초)", value=600, step=10)
                if st.form_submit_button("등록", type="primary"):
                    payload = {"sensor_id": sid, "sensor_name": sname or None,
                               "data_field": field, "unit": unit or None,
                               "scale_factor": scale, "offset_value": offset,
                               "interval_sec": int(interval)}
                    if api_send("POST", f"/edge-devices/{did}/sensors", payload):
                        st.success("센서 매핑 등록 완료")
                        st.rerun()

    # --- 배치 스케줄 ---
    st.divider()
    st.subheader("배치 스케줄")
    schedules = api_get("/batch-schedules") or []
    if schedules:
        for s in schedules:
            cols = st.columns([3, 2, 2, 1])
            cols[0].markdown(f"**{s['job_name']}**")
            cols[0].caption(s.get("description") or "")
            cols[1].code(s["cron_expression"])
            cols[2].write(f"최근: {s.get('last_run') or '-'}")
            new_active = cols[3].toggle(
                "활성", value=s["is_active"], key=f"sched_{s['schedule_id']}")
            if new_active != s["is_active"]:
                if api_send("PUT", f"/batch-schedules/{s['schedule_id']}",
                            {"is_active": new_active}):
                    st.toast(f"{s['job_name']} 상태 변경됨")
                    st.rerun()
    else:
        st.info("등록된 배치 스케줄이 없습니다.")
