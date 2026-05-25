"""
꽃순이김치 제조AI MES — 원재료 입고 AI Agent (INTAKE)
프로젝트: SF26179540 (평창꽃순이(주)농업회사법인) / 로뎀솔루션

LangGraph StateGraph + ReAct 루프 기반 RAG Agent.
    agent_node (LLM, tool 바인딩) ──▶ tools_node (DB/Vector 조회) ──▶ agent_node ──▶ END

담당 질의 (CLAIM.md AI 모듈 / rag-agent-mes 스킬):
    - 공급처 품질 이력 조회 및 판단
    - 입고 기준 적합 여부 질의
    - LOT 기반 트레이서빌리티 조회

데이터 소스:
    - 운영DB(PostgreSQL): raw_material_lot, incoming_inspection, material_selection,
                          supplier, supplier_quality_score, quality_standard
    - Vector DB(pgvector): 품질기준서(QUALITY_STANDARD) / 작업표준서(SOP)

환경변수:
    OPENAI_API_KEY  필수 (LLM + 임베딩)
    OPENAI_MODEL    기본 gpt-4o-mini
    DATABASE_URL    운영DB DSN

설계 원칙:
    1. 모든 응답에 출처(문서명·LOT ID·측정값) 명시
    2. 근거 없으면 "확인 불가 — 추가 검사 필요" 명시 (환각 방지)
    3. 파일럿: needs_approval=True (운영자 승인 게이트)
    4. OpenAI 호출 실패 시 규칙형 fallback 응답
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

logger = logging.getLogger("rag.intake_agent")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://mesuser:mespass@db:5432/kimchi_mes",
)

SYSTEM_PROMPT = """당신은 꽃순이김치 공장의 원재료 입고 전문 AI 어시스턴트입니다.
배추 원재료의 입고 기준 적합 여부, 공급처 품질 이력, LOT 추적성을
작업표준서(SOP)와 품질기준서(QUALITY_STANDARD)를 기반으로 정확하게 답변합니다.

사용 가능한 도구:
- search_supplier_quality: 공급처 최근 N개월 품질 이력 조회
- search_lot_history: LOT 입고→검사→선별 전체 이력 조회
- search_quality_standards: 품질기준서 Vector DB 검색
- check_incoming_criteria: 입고 측정값 vs 품질기준 적합 판정
- search_sop: 작업표준서 Vector DB 검색

답변 원칙:
- 구체적인 LOT ID, 측정값, 공급처 코드를 항상 명시한다.
- 품질 기준 미달 시 조치 방법(반품/조건부합격/선별강화 등)을 제시한다.
- 도구 조회 결과에 근거가 없으면 "확인 불가 — 추가 검사가 필요합니다"라고 명시한다.
  추측으로 답하지 않는다(환각 방지).
- 참조한 문서명과 버전을 답변 끝에 [출처] 형식으로 표기한다.
- 반드시 한국어로 답변한다.
- 입고 적합/부적합 최종 판단은 담당자 승인이 필요한 의사결정 지원임을 전제한다.
"""


# =====================================================================
# Agent 상태
# =====================================================================
class IntakeState(TypedDict):
    """LangGraph 상태. messages는 누적(add_messages reducer)."""

    messages: Annotated[list, "대화 메시지 누적"]
    referenced_docs: list[dict[str, Any]]  # 누적 참조 문서
    tool_calls: list[dict[str, Any]]  # 호출 이력 로깅


# =====================================================================
# DB 풀 (운영DB) — 모듈 전역 공유
# =====================================================================
_db_pool: asyncpg.Pool | None = None


async def _get_db_pool() -> asyncpg.Pool:
    global _db_pool
    if _db_pool is None:
        _db_pool = await asyncpg.create_pool(
            dsn=DATABASE_URL, min_size=1, max_size=5, command_timeout=30
        )
        logger.info("[IntakeAgent] 운영DB 연결 풀 초기화")
    return _db_pool


# Tool 실행 중 수집한 참조 문서를 상태로 전달하기 위한 컨텍스트 버퍼.
# (LangChain @tool은 추가 인자 주입이 까다로워, 호출 단위 버퍼로 수집 후 병합)
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
    """LangChain @tool 목록 생성. vector_store/DB 풀을 클로저로 캡처."""
    from langchain_core.tools import tool

    @tool
    async def search_supplier_quality(supplier_code: str, months: int = 3) -> str:
        """공급처의 최근 N개월 품질 이력을 조회한다.
        supplier_code 예: SUP01. 합격률, 평균 신선도/함수율, 입고량을 반환한다."""
        pool = await _get_db_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT sqs.year_month, sqs.total_lots, sqs.passed_lots,
                       sqs.pass_rate_pct, sqs.avg_freshness,
                       sqs.avg_water_content_pct, sqs.total_kg,
                       s.supplier_name, s.quality_grade, s.region
                FROM supplier_quality_score sqs
                JOIN supplier s ON s.supplier_code = sqs.supplier_code
                WHERE sqs.supplier_code = $1
                ORDER BY sqs.year_month DESC
                LIMIT $2
                """,
                supplier_code,
                months,
            )
        if not rows:
            return (
                f"공급처 {supplier_code} 의 최근 {months}개월 품질 점수 기록이 "
                f"없습니다. 확인 불가 — 입고 검사 이력 직접 확인이 필요합니다."
            )
        head = rows[0]
        lines = [
            f"공급처: {head['supplier_name']} ({supplier_code}), "
            f"등급 {head['quality_grade']}, 지역 {head['region']}"
        ]
        for r in rows:
            lines.append(
                f"- {r['year_month']}: 합격률 {r['pass_rate_pct']}% "
                f"({r['passed_lots']}/{r['total_lots']} LOT), "
                f"평균 신선도 {r['avg_freshness']}, "
                f"평균 함수율 {r['avg_water_content_pct']}%, "
                f"입고 {r['total_kg']}kg"
            )
        return "\n".join(lines)

    @tool
    async def search_lot_history(lot_id: str) -> str:
        """원재료 LOT의 입고→검사→선별 전체 이력을 조회한다.
        lot_id 예: RM-20260520-001. 트레이서빌리티 추적에 사용한다."""
        pool = await _get_db_pool()
        async with pool.acquire() as conn:
            lot = await conn.fetchrow(
                """
                SELECT rml.*, s.supplier_name, s.quality_grade
                FROM raw_material_lot rml
                LEFT JOIN supplier s ON s.supplier_code = rml.supplier_code
                WHERE rml.lot_id = $1
                """,
                lot_id,
            )
            if not lot:
                return f"LOT {lot_id} 를 찾을 수 없습니다. 확인 불가."
            insp = await conn.fetch(
                """
                SELECT inspector, inspection_date, cabbage_size, weight_avg_kg,
                       appearance_grade, water_content_pct, freshness_score,
                       qc_result, rejection_reason, corrective_action
                FROM incoming_inspection
                WHERE lot_id = $1 ORDER BY inspection_date DESC
                """,
                lot_id,
            )
            sel = await conn.fetch(
                """
                SELECT selection_date, operator, input_qty_kg, selected_qty_kg,
                       reject_qty_kg, selection_rate_pct, reject_reason
                FROM material_selection
                WHERE lot_id = $1 ORDER BY selection_date DESC
                """,
                lot_id,
            )

        out = [
            f"[LOT {lot_id}] 입고일 {lot['intake_date']}, "
            f"공급처 {lot['supplier_name']}({lot['supplier_code']}), "
            f"재료 {lot['material_code']}, 원산지 {lot['origin']}, "
            f"수량 {lot['quantity_kg']}kg, 상태 {lot['lot_status']}"
        ]
        if insp:
            out.append("입고검사:")
            for i in insp:
                out.append(
                    f"  - {i['inspection_date']} 검사자 {i['inspector']}: "
                    f"외관 {i['appearance_grade']}, 함수율 {i['water_content_pct']}%, "
                    f"신선도 {i['freshness_score']}, 판정 {i['qc_result']}"
                    + (
                        f" / 사유: {i['rejection_reason']}"
                        if i["rejection_reason"]
                        else ""
                    )
                )
        else:
            out.append("입고검사: 기록 없음 (확인 불가)")
        if sel:
            out.append("선별실적:")
            for s in sel:
                out.append(
                    f"  - {s['selection_date']}: 투입 {s['input_qty_kg']}kg → "
                    f"통과 {s['selected_qty_kg']}kg "
                    f"(선별율 {s['selection_rate_pct']}%), "
                    f"제거 {s['reject_qty_kg']}kg [{s['reject_reason']}]"
                )
        return "\n".join(out)

    @tool
    async def search_quality_standards(query: str) -> str:
        """품질기준서/공급처 평가 기준서를 Vector DB에서 검색한다.
        입고 기준값, 외관 등급 기준 등 품질 관련 질의에 사용한다."""
        docs = await vector_store.similarity_search(
            query, doc_types=["QUALITY_STANDARD"], k=4, score_threshold=0.65
        )
        if not docs:
            return "관련 품질기준서를 찾지 못했습니다. 확인 불가."
        _record_docs(docs)
        return "\n\n".join(
            f"[{d['title']} v{d['version']} (유사도 {d['score']})]\n{d['content']}"
            for d in docs
        )

    @tool
    async def check_incoming_criteria(material_code: str, measurements: dict) -> str:
        """입고 측정값을 품질기준(quality_standard)과 비교해 적합 여부를 판정한다.
        material_code 예: MAT-BC. measurements 예:
        {"함수율": 96.8, "외관등급": "C"}. 정상/경고/부적합을 반환한다."""
        # 입고 공정(PROC01) 및 절임(PROC03) 기준 중 측정 항목명 매칭
        pool = await _get_db_pool()
        async with pool.acquire() as conn:
            stds = await conn.fetch(
                """
                SELECT standard_item, normal_min, normal_max,
                       warning_min, warning_max, unit
                FROM quality_standard
                WHERE is_active = TRUE
                """
            )
        std_map = {s["standard_item"]: s for s in stds}
        verdicts: list[str] = []
        for item, value in (measurements or {}).items():
            std = None
            # 측정 항목명 부분 매칭 (예: '함수율' → '절임 염도' 같은 키)
            for k, v in std_map.items():
                if item in k or k in item:
                    std = v
                    break
            if std is None:
                verdicts.append(f"- {item}={value}: 기준 미정의 (확인 불가)")
                continue
            try:
                fval = float(value)
            except (TypeError, ValueError):
                verdicts.append(f"- {item}={value}: 수치 아님 — 육안 기준 별도 확인")
                continue
            nmin, nmax = std["normal_min"], std["normal_max"]
            wmin, wmax = std["warning_min"], std["warning_max"]
            if nmin is not None and nmax is not None and nmin <= fval <= nmax:
                v = "정상"
            elif wmin is not None and wmax is not None and wmin <= fval <= wmax:
                v = "경고(조건부)"
            else:
                v = "부적합"
            verdicts.append(
                f"- {item}={value}{std['unit'] or ''}: {v} "
                f"(정상 {nmin}~{nmax}, 경고 {wmin}~{wmax})"
            )
        if not verdicts:
            return "판정할 측정값이 없습니다. 확인 불가."
        return f"[입고 기준 판정 — {material_code}]\n" + "\n".join(verdicts)

    @tool
    async def search_sop(query: str) -> str:
        """작업표준서(SOP)를 Vector DB에서 검색한다.
        입고 절차, 검사 방법, 외관등급 판정 절차 등 작업 표준 질의에 사용한다."""
        docs = await vector_store.similarity_search(
            query, doc_types=["SOP"], k=4, score_threshold=0.65
        )
        if not docs:
            return "관련 작업표준서를 찾지 못했습니다. 확인 불가."
        _record_docs(docs)
        return "\n\n".join(
            f"[{d['title']} v{d['version']} (유사도 {d['score']})]\n{d['content']}"
            for d in docs
        )

    return [
        search_supplier_quality,
        search_lot_history,
        search_quality_standards,
        check_incoming_criteria,
        search_sop,
    ]


# =====================================================================
# IntakeRAGAgent
# =====================================================================
class IntakeRAGAgent:
    """원재료 입고 RAG Agent (LangGraph)."""

    def __init__(self) -> None:
        self._graph = None
        self._vector_store: KimchiVectorStore | None = None
        self._tools = None

    async def _ensure_graph(self) -> None:
        """그래프 지연 빌드 (최초 query 시 1회)."""
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

        # add_messages reducer 적용 상태
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
        logger.info("[IntakeAgent] LangGraph 컴파일 완료 (model=%s)", OPENAI_MODEL)

    async def query(self, question: str, session_id: str | None = None) -> dict[str, Any]:
        """질의 실행.

        Returns:
            {response, referenced_docs, tool_calls, response_time_ms,
             needs_approval, agent_type, session_id}
        """
        session_id = session_id or f"intake-{uuid.uuid4().hex[:10]}"
        started = time.perf_counter()
        _doc_buffer.clear()

        try:
            await self._ensure_graph()
        except Exception as e:  # OpenAI 키 없음 / langchain 미설치 등
            logger.error("[IntakeAgent] 그래프 초기화 실패: %s", e)
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
        except Exception as e:  # LLM/Tool 런타임 실패
            logger.error("[IntakeAgent] 실행 실패: %s", e)
            return await self._fallback(question, session_id, started, str(e))

        final_msg = result["messages"][-1]
        response_text = (
            final_msg.content
            if isinstance(final_msg.content, str)
            else str(final_msg.content)
        )

        # 참조 문서 dedup (title+chunk 기준)
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
            "[IntakeAgent] 응답 완료 (%dms, tools=%d, docs=%d)",
            response_ms,
            len(tool_calls),
            len(ref_docs),
        )
        return {
            "agent_type": "INTAKE",
            "session_id": session_id,
            "response": response_text,
            "referenced_docs": ref_docs,
            "tool_calls": tool_calls,
            "response_time_ms": response_ms,
            "needs_approval": True,  # 파일럿: 운영자 승인 게이트
        }

    async def _fallback(
        self, question: str, session_id: str, started: float, err: str
    ) -> dict[str, Any]:
        """OpenAI/그래프 실패 시 규칙형 응답 (환각 방지: 확인 불가 명시)."""
        response_ms = int((time.perf_counter() - started) * 1000)
        text = (
            "[INTAKE Agent — 제한 모드] AI 엔진 연결에 실패하여 규칙형 응답을 "
            "제공합니다. 정확한 입고 기준/공급처 이력은 품질기준서 및 입고검사 "
            "기록을 직접 확인해 주세요. 확인 불가 항목은 추가 검사가 필요합니다.\n"
            f"(질의: {question})"
        )
        return {
            "agent_type": "INTAKE",
            "session_id": session_id,
            "response": text,
            "referenced_docs": [],
            "tool_calls": [],
            "response_time_ms": response_ms,
            "needs_approval": True,
            "fallback": True,
            "error": err,
        }


# 모듈 전역 인스턴스 (agent_router 에서 재사용)
intake_agent = IntakeRAGAgent()


if __name__ == "__main__":
    import asyncio

    async def _demo() -> None:
        agent = IntakeRAGAgent()
        r = await agent.query("SUP01 공급처의 최근 품질 이력을 알려줘")
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))

    asyncio.run(_demo())
