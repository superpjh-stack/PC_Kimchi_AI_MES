"""
꽃순이김치 제조AI MES — 포장·출하 AI Agent (SHIPPING)
프로젝트: SF26179540 (평창꽃순이(주)농업회사법인) / 로뎀솔루션

LangGraph StateGraph + ReAct 루프 기반 RAG Agent.
    agent_node (LLM, tool 바인딩) ──▶ tools_node ──▶ agent_node ──▶ END

담당 질의 (CLAUDE.md AI 모듈 / rag-agent-mes 스킬):
    - 출하 승인 기준 질의
    - LOT 추적 및 이력 조회 (역추적: 포장→발효→절임→입고)
    - 클레임 원인 분석 및 대응 가이드

데이터 소스:
    - 운영DB(PostgreSQL): packaging_lot, packaging_inspection, shipping_order,
                          shipping_lot_mapping, claim_record, quality_standard,
                          raw_material_lot (역추적)
    - Vector DB(pgvector): 품질표준서(QUALITY_STANDARD) / 클레임 대응 매뉴얼(CLAIM)
                          / 출하 작업표준서(SOP)

환경변수:
    OPENAI_API_KEY  필수
    OPENAI_MODEL    기본 gpt-4o-mini
    DATABASE_URL    운영DB DSN

설계 원칙:
    1. 출하 최종 결정은 반드시 담당자 승인 필요 (needs_approval=True)
    2. 모든 응답에 출처(문서명·LOT ID·측정값) 명시
    3. 근거 없으면 "확인 불가" 명시 (환각 방지)
    4. OpenAI 실패 시 규칙형 fallback
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Annotated, Any, TypedDict

import asyncpg

from rag.vector_store import KimchiVectorStore, get_vector_store

logger = logging.getLogger("rag.shipping_agent")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://mesuser:mespass@db:5432/kimchi_mes",
)

SYSTEM_PROMPT = """당신은 꽃순이김치 공장의 포장·출하 전문 AI 어시스턴트입니다.
출하 승인 기준 확인, LOT 역추적, 클레임 원인 분석을 품질표준서(QUALITY_STANDARD)와
클레임 대응 매뉴얼(CLAIM)을 기반으로 정확하게 답변합니다.

사용 가능한 도구:
- search_shipping_criteria: 제품별 출하 승인 기준 조회 (품질기준 + Vector DB)
- trace_lot_chain: LOT 역추적 (포장→발효→절임→입고 전체 체인)
- analyze_claim: 클레임 유형별 원인 분석 + 대응 매뉴얼 검색
- search_claim_manual: 클레임 대응 매뉴얼 Vector DB 검색
- check_quality_standard: 출하 품질 기준 충족 여부 검증

답변 원칙:
- 구체적인 LOT ID(포장 PK-, 발효 FE-, 원재료 RM-), 측정값, 검사 결과를 명시한다.
- 출하 승인 기준 충족 여부를 항목별(금속검출/pH/염도/관능)로 명확히 정리한다.
- 도구 조회 결과에 근거가 없으면 "확인 불가"라고 명시한다(환각 방지).
- 참조한 문서명과 버전을 답변 끝에 [출처] 형식으로 표기한다.
- 반드시 한국어로 답변한다.

중요: 출하 최종 결정은 반드시 담당자 승인이 필요합니다.
본 답변은 의사결정 지원용이며, AI가 출하를 자동 승인하지 않습니다.
"""


class ShippingState(TypedDict):
    messages: Annotated[list, "대화 메시지 누적"]
    referenced_docs: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]


_db_pool: asyncpg.Pool | None = None


async def _get_db_pool() -> asyncpg.Pool:
    global _db_pool
    if _db_pool is None:
        _db_pool = await asyncpg.create_pool(
            dsn=DATABASE_URL, min_size=1, max_size=5, command_timeout=30
        )
        logger.info("[ShippingAgent] 운영DB 연결 풀 초기화")
    return _db_pool


_doc_buffer: list[dict[str, Any]] = []


def _record_docs(docs: list[dict[str, Any]]) -> None:
    for d in docs:
        _doc_buffer.append(
            {
                "title": d.get("title", "unknown"),
                "doc_type": d.get("doc_type", ""),
                "version": d.get("version", ""),
                "score": d.get("score", 0.0),
            }
        )


# =====================================================================
# Tools
# =====================================================================
def _build_tools(vector_store: KimchiVectorStore):
    from langchain_core.tools import tool

    @tool
    async def search_shipping_criteria(product_code: str) -> str:
        """제품별 출하 승인 기준을 조회한다 (quality_standard PROC09 + Vector DB).
        product_code 예: KIM-BC-500. 완성품 pH/산도/염도/보관온도 기준을 반환한다."""
        pool = await _get_db_pool()
        async with pool.acquire() as conn:
            stds = await conn.fetch(
                """
                SELECT standard_item, normal_min, normal_max,
                       warning_min, warning_max, unit, measurement_method
                FROM quality_standard
                WHERE process_code = 'PROC09' AND is_active = TRUE
                ORDER BY standard_item
                """
            )
        lines = [f"[출하 승인 품질 기준 — {product_code} (완성품 공정 PROC09)]"]
        if stds:
            for s in stds:
                lines.append(
                    f"- {s['standard_item']}: 정상 {s['normal_min']}~{s['normal_max']}"
                    f"{s['unit'] or ''} (경고 {s['warning_min']}~{s['warning_max']}), "
                    f"측정 {s['measurement_method']}"
                )
        else:
            lines.append("- DB 기준값 없음 (확인 불가)")

        # 출하 승인 기준서 본문 보강
        docs = await vector_store.similarity_search(
            f"{product_code} 출하 승인 기준",
            doc_types=["QUALITY_STANDARD"],
            k=3,
            score_threshold=0.62,
        )
        if docs:
            _record_docs(docs)
            lines.append("\n[출하 승인 기준서 발췌]")
            for d in docs:
                lines.append(f"- [{d['title']} v{d['version']}] {d['content'][:300]}")
        return "\n".join(lines)

    @tool
    async def trace_lot_chain(lot_id: str) -> str:
        """LOT를 역추적한다: 포장 LOT(PK-)→발효(FE-)→입고(RM-) 전체 체인.
        포장 LOT, 출하 주문번호(SO-), 발효 LOT 어느 것이든 입력 가능하다."""
        pool = await _get_db_pool()
        async with pool.acquire() as conn:
            # 1) 포장 LOT 기준 조회
            pk = await conn.fetchrow(
                """
                SELECT pl.*,
                       (SELECT json_agg(json_build_object(
                            'date', pi.inspection_date, 'ph', pi.acidity_ph,
                            'salinity', pi.salinity_pct, 'ferment', pi.fermentation_level,
                            'result', pi.qc_result, 'fail', pi.fail_reason))
                        FROM packaging_inspection pi WHERE pi.lot_id = pl.lot_id) AS inspections
                FROM packaging_lot pl
                WHERE pl.lot_id = $1
                """,
                lot_id,
            )
            order_info = await conn.fetch(
                """
                SELECT so.order_no, so.customer_name, so.order_status,
                       so.approved_by, so.approved_at, slm.allocated_units
                FROM shipping_lot_mapping slm
                JOIN shipping_order so ON so.order_id = slm.order_id
                WHERE slm.lot_id = $1
                """,
                lot_id,
            )

        if not pk:
            return (
                f"포장 LOT {lot_id} 를 찾을 수 없습니다. "
                f"발효/입고 LOT이라면 포장 LOT을 먼저 식별해 주세요. 확인 불가."
            )
        out = [
            f"[LOT 역추적] 포장 {pk['lot_id']} → 발효 source {pk['source_lot_id']}",
            f"- 포장일 {pk['packaging_date']}, 제품 {pk['product_code']}, "
            f"라인 {pk['line_no']}, 산출 {pk['output_units']}개 "
            f"(불량 {pk['defect_units']}), 금속검출 "
            f"{'통과' if pk['metal_detection'] else '미통과/검출'}, "
            f"상태 {pk['lot_status']}",
        ]
        insp = pk["inspections"]
        if insp:
            insp = json.loads(insp) if isinstance(insp, str) else insp
            out.append("- 포장검사:")
            for i in insp:
                out.append(
                    f"    {i['date']}: pH {i['ph']}, 염도 {i['salinity']}%, "
                    f"숙성 {i['ferment']}, 판정 {i['result']}"
                    + (f" / 사유 {i['fail']}" if i.get("fail") else "")
                )
        else:
            out.append("- 포장검사: 기록 없음 (확인 불가)")
        if order_info:
            out.append("- 출하 매핑:")
            for o in order_info:
                appr = (
                    f"승인 {o['approved_by']}({o['approved_at']})"
                    if o["approved_by"]
                    else "미승인"
                )
                out.append(
                    f"    {o['order_no']} {o['customer_name']} "
                    f"[{o['order_status']}] {o['allocated_units']}개, {appr}"
                )
        else:
            out.append("- 출하 매핑: 없음")
        return "\n".join(out)

    @tool
    async def analyze_claim(claim_type: str, lot_id: str = "") -> str:
        """클레임 유형별 원인을 분석한다 (claim_record 이력 + 대응 매뉴얼).
        claim_type: QUALITY/DELIVERY/FOREIGN/LABELING/OTHER.
        lot_id 지정 시 해당 LOT 클레임에 집중한다."""
        pool = await _get_db_pool()
        async with pool.acquire() as conn:
            if lot_id:
                rows = await conn.fetch(
                    """
                    SELECT claim_no, claim_date, customer_name, claim_type,
                           claim_content, severity, root_cause, corrective_action,
                           recurrence_prevention, status, lot_id
                    FROM claim_record
                    WHERE lot_id = $1
                    ORDER BY claim_date DESC
                    """,
                    lot_id,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT claim_no, claim_date, customer_name, claim_type,
                           claim_content, severity, root_cause, corrective_action,
                           recurrence_prevention, status, lot_id
                    FROM claim_record
                    WHERE claim_type = $1
                    ORDER BY claim_date DESC
                    LIMIT 10
                    """,
                    claim_type,
                )
        out: list[str] = []
        if rows:
            out.append(f"[클레임 이력 — type={claim_type} lot={lot_id or '전체'}]")
            for c in rows:
                out.append(
                    f"- {c['claim_no']} ({c['claim_date']}, {c['severity']}) "
                    f"{c['customer_name']} LOT {c['lot_id']}: {c['claim_content']}\n"
                    f"    원인: {c['root_cause'] or '분석중'}\n"
                    f"    조치: {c['corrective_action'] or '-'}\n"
                    f"    재발방지: {c['recurrence_prevention'] or '-'} [{c['status']}]"
                )
        else:
            out.append(
                f"해당 조건({claim_type}/{lot_id or '전체'})의 클레임 이력이 "
                f"없습니다. 확인 불가."
            )

        # 대응 매뉴얼 보강
        docs = await vector_store.similarity_search(
            f"{claim_type} 클레임 대응 원인 분석",
            doc_types=["CLAIM"],
            k=3,
            score_threshold=0.6,
        )
        if docs:
            _record_docs(docs)
            out.append("\n[클레임 대응 매뉴얼 발췌]")
            for d in docs:
                out.append(f"- [{d['title']} v{d['version']}] {d['content'][:300]}")
        return "\n".join(out)

    @tool
    async def search_claim_manual(query: str) -> str:
        """클레임 대응 매뉴얼을 Vector DB에서 검색한다 (doc_type=CLAIM)."""
        docs = await vector_store.similarity_search(
            query, doc_types=["CLAIM"], k=4, score_threshold=0.62
        )
        if not docs:
            return "관련 클레임 대응 매뉴얼을 찾지 못했습니다. 확인 불가."
        _record_docs(docs)
        return "\n\n".join(
            f"[{d['title']} v{d['version']} (유사도 {d['score']})]\n{d['content']}"
            for d in docs
        )

    @tool
    async def check_quality_standard(product_code: str, measurements: dict) -> str:
        """출하 품질 기준(PROC09) 충족 여부를 검증한다.
        product_code 예: KIM-BC-500. measurements 예:
        {"완성품 pH": 4.3, "완성품 염도": 2.1}. 항목별 적합/부적합을 반환한다."""
        pool = await _get_db_pool()
        async with pool.acquire() as conn:
            stds = await conn.fetch(
                """
                SELECT standard_item, normal_min, normal_max,
                       warning_min, warning_max, unit
                FROM quality_standard
                WHERE process_code = 'PROC09' AND is_active = TRUE
                """
            )
        std_map = {s["standard_item"]: s for s in stds}
        verdicts: list[str] = []
        all_pass = True
        for item, value in (measurements or {}).items():
            std = None
            for k, v in std_map.items():
                if item in k or k in item:
                    std = v
                    break
            if std is None:
                verdicts.append(f"- {item}={value}: 출하 기준 미정의 (확인 불가)")
                all_pass = False
                continue
            try:
                fval = float(value)
            except (TypeError, ValueError):
                verdicts.append(f"- {item}={value}: 수치 아님 — 별도 확인")
                continue
            nmin, nmax = std["normal_min"], std["normal_max"]
            wmin, wmax = std["warning_min"], std["warning_max"]
            if nmin is not None and nmax is not None and nmin <= fval <= nmax:
                v = "적합(정상)"
            elif wmin is not None and wmax is not None and wmin <= fval <= wmax:
                v = "경고(조건부) — 담당자 검토 필요"
                all_pass = False
            else:
                v = "부적합 — 출하 불가"
                all_pass = False
            verdicts.append(
                f"- {item}={value}{std['unit'] or ''}: {v} "
                f"(정상 {nmin}~{nmax})"
            )
        if not verdicts:
            return "검증할 측정값이 없습니다. 확인 불가."
        summary = (
            "전 항목 출하 기준 충족 (단, 최종 출하 승인은 담당자 결정 필요)"
            if all_pass
            else "일부 항목 미충족 — 출하 보류 검토 필요"
        )
        return (
            f"[출하 품질 검증 — {product_code}]\n"
            + "\n".join(verdicts)
            + f"\n판정: {summary}"
        )

    return [
        search_shipping_criteria,
        trace_lot_chain,
        analyze_claim,
        search_claim_manual,
        check_quality_standard,
    ]


# =====================================================================
# ShippingRAGAgent
# =====================================================================
class ShippingRAGAgent:
    """포장·출하 RAG Agent (LangGraph)."""

    def __init__(self) -> None:
        self._graph = None
        self._vector_store: KimchiVectorStore | None = None
        self._tools = None

    async def _ensure_graph(self) -> None:
        if self._graph is not None:
            return

        from langchain_openai import ChatOpenAI
        from langgraph.graph import StateGraph, END
        from langgraph.graph.message import add_messages
        from langgraph.prebuilt import ToolNode

        self._vector_store = await get_vector_store()
        self._tools = _build_tools(self._vector_store)

        llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0)
        llm_with_tools = llm.bind_tools(self._tools)
        tool_node = ToolNode(self._tools)

        class _State(TypedDict):
            messages: Annotated[list, add_messages]
            referenced_docs: list
            tool_calls: list

        async def agent_node(state: _State) -> dict:
            resp = await llm_with_tools.ainvoke(state["messages"])
            calls = []
            for tc in getattr(resp, "tool_calls", []) or []:
                calls.append({"name": tc["name"], "args": tc.get("args", {})})
            return {"messages": [resp], "tool_calls": calls}

        def should_continue(state: _State) -> str:
            last = state["messages"][-1]
            if getattr(last, "tool_calls", None):
                return "tools"
            return END

        graph = StateGraph(_State)
        graph.add_node("agent", agent_node)
        graph.add_node("tools", tool_node)
        graph.set_entry_point("agent")
        graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
        graph.add_edge("tools", "agent")
        self._graph = graph.compile()
        logger.info("[ShippingAgent] LangGraph 컴파일 완료 (model=%s)", OPENAI_MODEL)

    async def query(self, question: str, session_id: str | None = None) -> dict[str, Any]:
        """질의 실행. 반환 스키마는 IntakeRAGAgent.query 와 동일."""
        session_id = session_id or f"ship-{uuid.uuid4().hex[:10]}"
        started = time.perf_counter()
        _doc_buffer.clear()

        try:
            await self._ensure_graph()
        except Exception as e:
            logger.error("[ShippingAgent] 그래프 초기화 실패: %s", e)
            return await self._fallback(question, session_id, started, str(e))

        from langchain_core.messages import HumanMessage, SystemMessage

        init_state = {
            "messages": [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=question),
            ],
            "referenced_docs": [],
            "tool_calls": [],
        }

        try:
            assert self._graph is not None
            result = await self._graph.ainvoke(init_state, {"recursion_limit": 12})
        except Exception as e:
            logger.error("[ShippingAgent] 실행 실패: %s", e)
            return await self._fallback(question, session_id, started, str(e))

        final_msg = result["messages"][-1]
        response_text = (
            final_msg.content
            if isinstance(final_msg.content, str)
            else str(final_msg.content)
        )

        seen: set = set()
        ref_docs: list[dict[str, Any]] = []
        for d in _doc_buffer:
            key = (d["title"], d.get("doc_type"))
            if key in seen:
                continue
            seen.add(key)
            ref_docs.append(d)

        tool_calls = result.get("tool_calls", [])
        response_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "[ShippingAgent] 응답 완료 (%dms, tools=%d, docs=%d)",
            response_ms,
            len(tool_calls),
            len(ref_docs),
        )
        return {
            "agent_type": "SHIPPING",
            "session_id": session_id,
            "response": response_text,
            "referenced_docs": ref_docs,
            "tool_calls": tool_calls,
            "response_time_ms": response_ms,
            "needs_approval": True,  # 출하 결정은 담당자 승인 필수
        }

    async def _fallback(
        self, question: str, session_id: str, started: float, err: str
    ) -> dict[str, Any]:
        response_ms = int((time.perf_counter() - started) * 1000)
        text = (
            "[SHIPPING Agent — 제한 모드] AI 엔진 연결에 실패하여 규칙형 응답을 "
            "제공합니다. 출하 승인 기준 및 클레임 원인은 품질표준서·클레임 대응 "
            "매뉴얼과 포장검사 기록을 직접 확인해 주세요. 출하 최종 결정은 담당자 "
            "승인이 필요합니다. 확인 불가 항목은 추가 검토가 필요합니다.\n"
            f"(질의: {question})"
        )
        return {
            "agent_type": "SHIPPING",
            "session_id": session_id,
            "response": text,
            "referenced_docs": [],
            "tool_calls": [],
            "response_time_ms": response_ms,
            "needs_approval": True,
            "fallback": True,
            "error": err,
        }


shipping_agent = ShippingRAGAgent()


if __name__ == "__main__":
    import asyncio

    async def _demo() -> None:
        agent = ShippingRAGAgent()
        r = await agent.query("PK-20260524-001 출하 승인 가능한지 검토해줘")
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))

    asyncio.run(_demo())
