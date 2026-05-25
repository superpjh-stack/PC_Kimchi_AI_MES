"""
꽃순이김치 제조AI MES — RAG Agent 통합 라우터
프로젝트: SF26179540 (평창꽃순이(주)농업회사법인) / 로뎀솔루션

역할:
    _workspace/api_agent_router.py 의 _rag_stub() 을 실제 LangChain/LangGraph
    Agent 호출로 교체하는 어댑터.

    INTAKE     → IntakeRAGAgent   (원재료 입고)
    SHIPPING   → ShippingRAGAgent (포장·출하)
    INTEGRATED → 두 Agent 결과를 LLM으로 병합

기존 stub 시그니처:
    async def _rag_stub(query, agent_type) -> tuple[str, list[dict]]

교체 방법 (api_agent_router.py):
    # 상단 임포트
    from rag.agent_router import run_rag_agent

    # POST /query 핸들러 내부 (210줄 부근)
    # 변경 전:
    #     response_text, ref_docs = await _rag_stub(data.query, data.agent_type)
    # 변경 후:
    response_text, ref_docs = await run_rag_agent(
        data.query, data.agent_type, session_id
    )

반환 ref_docs 항목 스키마는 ReferencedDoc(title, doc_type, score)와 호환된다.
(version 키가 추가로 포함될 수 있으나 Pydantic 모델 구성 시 무시됨)

설계 원칙:
    - run_rag_agent 는 절대 예외를 밖으로 던지지 않는다.
      (api_agent_router 가 502를 내지 않도록 내부에서 fallback 처리)
    - 응답에는 항상 출처가 포함되거나 "확인 불가"가 명시된다(환각 방지).
"""
from __future__ import annotations

import logging
import os
from typing import Any

from rag.intake_agent import intake_agent
from rag.shipping_agent import shipping_agent

logger = logging.getLogger("rag.agent_router")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def _to_ref_docs(referenced_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Agent 참조 문서 → api_agent_router ReferencedDoc 호환 dict 목록.

    ReferencedDoc(title: str, doc_type: str, score: float) 필수 3키 보장.
    """
    out: list[dict[str, Any]] = []
    for d in referenced_docs or []:
        out.append(
            {
                "title": d.get("title", "unknown"),
                "doc_type": d.get("doc_type", "") or "UNKNOWN",
                "score": float(d.get("score", 0.0) or 0.0),
            }
        )
    return out


async def _merge_results(
    i_result: dict[str, Any],
    s_result: dict[str, Any],
    query: str,
) -> dict[str, Any]:
    """INTEGRATED: 입고·출하 Agent 결과를 LLM으로 통합.

    LLM 실패 시 두 응답을 단순 연결한 fallback을 반환한다.
    """
    merged_docs = (i_result.get("referenced_docs") or []) + (
        s_result.get("referenced_docs") or []
    )
    intake_text = i_result.get("response", "")
    shipping_text = s_result.get("response", "")

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0)
        sys = (
            "당신은 꽃순이김치 공장의 통합 AI 어시스턴트입니다. "
            "원재료 입고 Agent와 포장·출하 Agent의 두 답변을 종합하여 "
            "사용자 질문에 대한 하나의 일관된 한국어 답변을 작성하세요. "
            "중복은 제거하고, LOT ID·측정값·출처는 보존하며, 근거가 없으면 "
            "'확인 불가'라고 명시하세요. 출하/입고 최종 결정은 담당자 승인이 "
            "필요한 의사결정 지원임을 전제로 합니다."
        )
        user = (
            f"[사용자 질문]\n{query}\n\n"
            f"[원재료 입고 Agent 답변]\n{intake_text}\n\n"
            f"[포장·출하 Agent 답변]\n{shipping_text}"
        )
        resp = await llm.ainvoke(
            [SystemMessage(content=sys), HumanMessage(content=user)]
        )
        merged_text = (
            resp.content if isinstance(resp.content, str) else str(resp.content)
        )
    except Exception as e:  # noqa: BLE001
        logger.error("[AgentRouter] INTEGRATED 병합 실패 — 단순 연결: %s", e)
        merged_text = (
            "[통합 Agent] 두 전문 Agent의 답변을 종합합니다.\n\n"
            f"■ 원재료 입고 관점\n{intake_text}\n\n"
            f"■ 포장·출하 관점\n{shipping_text}"
        )

    return {
        "agent_type": "INTEGRATED",
        "response": merged_text,
        "referenced_docs": merged_docs,
        "needs_approval": True,
    }


async def run_rag_agent(
    query: str,
    agent_type: str,
    session_id: str | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """api_agent_router._rag_stub 대체 함수.

    Args:
        query: 사용자 자연어 질의
        agent_type: INTAKE / SHIPPING / INTEGRATED
        session_id: 대화 세션 (없으면 Agent가 자동 생성)

    Returns:
        (response_text, referenced_docs)
        referenced_docs 항목: {title, doc_type, score} (ReferencedDoc 호환)

    예외를 던지지 않는다. 실패 시에도 안내 문구 + 빈 출처를 반환한다.
    """
    try:
        if agent_type == "INTAKE":
            result = await intake_agent.query(query, session_id)
        elif agent_type == "SHIPPING":
            result = await shipping_agent.query(query, session_id)
        elif agent_type == "INTEGRATED":
            i_result = await intake_agent.query(query, session_id)
            s_result = await shipping_agent.query(query, session_id)
            result = await _merge_results(i_result, s_result, query)
        else:
            return (
                f"알 수 없는 agent_type '{agent_type}'. "
                "INTAKE / SHIPPING / INTEGRATED 중 하나여야 합니다.",
                [],
            )
    except Exception as e:  # noqa: BLE001 — 라우터는 절대 예외 전파 금지
        logger.exception("[AgentRouter] run_rag_agent 실패: %s", e)
        return (
            "[AI Agent 오류] 질의 처리 중 문제가 발생했습니다. "
            "잠시 후 다시 시도하거나 담당자에게 문의하세요. (확인 불가)",
            [],
        )

    return result.get("response", ""), _to_ref_docs(result.get("referenced_docs"))


async def run_rag_agent_full(
    query: str,
    agent_type: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """전체 메타데이터(tool_calls, response_time_ms, needs_approval 포함) 반환 버전.

    Streamlit/대시보드에서 도구 호출 이력·승인 게이트 표시가 필요할 때 사용.
    """
    if agent_type == "INTAKE":
        return await intake_agent.query(query, session_id)
    if agent_type == "SHIPPING":
        return await shipping_agent.query(query, session_id)
    if agent_type == "INTEGRATED":
        i_result = await intake_agent.query(query, session_id)
        s_result = await shipping_agent.query(query, session_id)
        merged = await _merge_results(i_result, s_result, query)
        merged["tool_calls"] = (i_result.get("tool_calls") or []) + (
            s_result.get("tool_calls") or []
        )
        merged["response_time_ms"] = (i_result.get("response_time_ms") or 0) + (
            s_result.get("response_time_ms") or 0
        )
        merged["session_id"] = session_id or i_result.get("session_id")
        return merged
    return {
        "agent_type": agent_type,
        "response": f"알 수 없는 agent_type '{agent_type}'.",
        "referenced_docs": [],
        "tool_calls": [],
        "response_time_ms": 0,
        "needs_approval": True,
    }


if __name__ == "__main__":
    import asyncio
    import json

    async def _demo() -> None:
        for at, q in [
            ("INTAKE", "SUP01 공급처 최근 품질 이력은?"),
            ("SHIPPING", "PK-20260524-001 출하 승인 가능한지 검토해줘"),
            ("INTEGRATED", "RM-20260520-001 입고분이 출하까지 문제 없었는지 종합해줘"),
        ]:
            text, docs = await run_rag_agent(q, at)
            print(f"\n=== {at} ===\n{text}\n출처: {json.dumps(docs, ensure_ascii=False)}")

    asyncio.run(_demo())
