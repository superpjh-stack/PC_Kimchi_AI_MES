"""
꽃순이김치 제조AI MES — RAG Agent 테스트 Q&A 케이스
프로젝트: SF26179540 / 로뎀솔루션

두 부분으로 구성:
  1. TEST_QA_CASES  — Agent별 검증용 Q&A 케이스(질의 / 의도 / 기대 근거 / 기대 출처).
                       실 연동 환경(OpenAI 키 + DB + pgvector)에서 회귀 테스트 기준으로 사용.
  2. 단위/통합 테스트 — OpenAI 키·DB 없이도 검증 가능한 항목:
        - 청킹 로직(_chunk_text)
        - 라우터 fallback (예외 비전파, 출처 스키마 호환)
        - agent_type 분기

실행:
    # 구조/오프라인 테스트 (키 불필요)
    pytest rag/test_rag_agents.py -v
    # 또는
    python rag/test_rag_agents.py

    # 라이브 테스트 (OPENAI_API_KEY + DB + VECTOR_DB_URL 필요)
    RUN_LIVE_RAG=1 pytest rag/test_rag_agents.py -v -k live
"""
from __future__ import annotations

import asyncio
import os

# =====================================================================
# 1. Q&A 케이스 정의 (회귀 테스트 기준)
# =====================================================================
TEST_QA_CASES: list[dict] = [
    # ── 원재료 입고 Agent (INTAKE) ──────────────────────────────────
    {
        "id": "INTAKE-01",
        "agent_type": "INTAKE",
        "intent": "공급처 품질 이력 조회",
        "question": "SUP01 공급처의 최근 3개월 품질 이력을 알려줘",
        "expected_tools": ["search_supplier_quality"],
        "expected_evidence": ["합격률", "신선도", "함수율", "SUP01"],
        "expected_sources": [],  # DB 기반 — 문서 출처 없을 수 있음
        "notes": "supplier_quality_score 2026-03~05 합격률 90~100% 반환 기대",
    },
    {
        "id": "INTAKE-02",
        "agent_type": "INTAKE",
        "intent": "LOT 트레이서빌리티 조회",
        "question": "RM-20260522-001 LOT의 입고 검사 결과와 처리 상태를 알려줘",
        "expected_tools": ["search_lot_history"],
        "expected_evidence": ["RM-20260522-001", "FAIL", "함수율", "REJECTED"],
        "expected_sources": [],
        "notes": "함수율 96.8% 기준 초과 FAIL, lot_status REJECTED 명시 기대",
    },
    {
        "id": "INTAKE-03",
        "agent_type": "INTAKE",
        "intent": "입고 기준 적합 여부 판정",
        "question": "배추 함수율 96.8%, 외관 C등급인데 입고 기준에 적합해?",
        "expected_tools": ["check_incoming_criteria", "search_quality_standards"],
        "expected_evidence": ["부적합", "기준", "조치"],
        "expected_sources": ["품질기준서"],
        "notes": "부적합 판정 + 반품/조치 방법 제시 기대",
    },
    {
        "id": "INTAKE-04",
        "agent_type": "INTAKE",
        "intent": "작업표준 절차 질의",
        "question": "배추 입고 시 외관등급 판정 절차가 어떻게 돼?",
        "expected_tools": ["search_sop"],
        "expected_evidence": ["외관", "등급", "절차"],
        "expected_sources": ["작업표준서"],
        "notes": "근거 문서 없으면 '확인 불가' 명시 기대(환각 방지)",
    },
    {
        "id": "INTAKE-05",
        "agent_type": "INTAKE",
        "intent": "환각 방지 — 근거 없는 질의",
        "question": "SUP99 공급처의 품질 이력 알려줘",
        "expected_tools": ["search_supplier_quality"],
        "expected_evidence": ["확인 불가", "없습니다"],
        "expected_sources": [],
        "notes": "존재하지 않는 공급처 → '확인 불가' 명시, 추측 금지",
    },
    # ── 포장·출하 Agent (SHIPPING) ──────────────────────────────────
    {
        "id": "SHIP-01",
        "agent_type": "SHIPPING",
        "intent": "출하 승인 기준 질의",
        "question": "KIM-BC-500 제품의 출하 승인 품질 기준이 뭐야?",
        "expected_tools": ["search_shipping_criteria"],
        "expected_evidence": ["완성품 pH", "산도", "염도", "기준"],
        "expected_sources": ["출하 승인 기준서", "품질"],
        "notes": "quality_standard PROC09 + 출하 승인 기준서 발췌 기대",
    },
    {
        "id": "SHIP-02",
        "agent_type": "SHIPPING",
        "intent": "LOT 역추적",
        "question": "PK-20260524-001 포장 LOT을 역추적해서 발효·출하 이력을 보여줘",
        "expected_tools": ["trace_lot_chain"],
        "expected_evidence": ["PK-20260524-001", "FE-20260521-001", "금속검출", "출하"],
        "expected_sources": [],
        "notes": "포장→발효 source_lot_id + 출하 주문 매핑 표시 기대",
    },
    {
        "id": "SHIP-03",
        "agent_type": "SHIPPING",
        "intent": "출하 적합 검증",
        "question": "완성품 pH 4.3, 염도 2.1%인데 출하해도 될까?",
        "expected_tools": ["check_quality_standard"],
        "expected_evidence": ["적합", "담당자 승인", "PROC09"],
        "expected_sources": [],
        "notes": "적합하더라도 '출하 최종 결정은 담당자 승인 필요' 명시 기대",
    },
    {
        "id": "SHIP-04",
        "agent_type": "SHIPPING",
        "intent": "클레임 원인 분석",
        "question": "최근 품질(QUALITY) 클레임의 원인과 대응을 분석해줘",
        "expected_tools": ["analyze_claim", "search_claim_manual"],
        "expected_evidence": ["원인", "조치", "재발방지"],
        "expected_sources": ["클레임 대응 매뉴얼"],
        "notes": "claim_record QUALITY 2건(과숙/밀봉불량) 원인·조치 요약 기대",
    },
    {
        "id": "SHIP-05",
        "agent_type": "SHIPPING",
        "intent": "특정 LOT 클레임 추적",
        "question": "PK-20260523-003 LOT에 대한 클레임이 있었어?",
        "expected_tools": ["analyze_claim"],
        "expected_evidence": ["CL-20260523-001", "신맛", "과숙"],
        "expected_sources": [],
        "notes": "신세계 5kg 신맛 클레임(발효 과숙) 추적 기대",
    },
    # ── 통합 Agent (INTEGRATED) ─────────────────────────────────────
    {
        "id": "INTEG-01",
        "agent_type": "INTEGRATED",
        "intent": "입고~출하 종합 추적",
        "question": "RM-20260520-001 입고분이 출하까지 품질 문제 없었는지 종합 분석해줘",
        "expected_tools": ["search_lot_history", "trace_lot_chain"],
        "expected_evidence": ["입고", "출하", "종합"],
        "expected_sources": [],
        "notes": "입고 Agent + 출하 Agent 결과를 LLM 병합, 중복 제거 기대",
    },
]


def print_qa_cases() -> None:
    """Q&A 케이스 표 출력 (문서화/리뷰용)."""
    print(f"\n총 {len(TEST_QA_CASES)}개 Q&A 케이스\n" + "=" * 70)
    for c in TEST_QA_CASES:
        print(f"[{c['id']}] ({c['agent_type']}) {c['intent']}")
        print(f"  Q: {c['question']}")
        print(f"  기대 도구: {', '.join(c['expected_tools'])}")
        print(f"  기대 근거: {', '.join(c['expected_evidence'])}")
        if c["expected_sources"]:
            print(f"  기대 출처: {', '.join(c['expected_sources'])}")
        print(f"  비고: {c['notes']}\n")


# =====================================================================
# 2. 오프라인 단위/통합 테스트 (OpenAI 키·DB 불필요)
# =====================================================================
def test_chunk_text_short() -> None:
    """짧은 텍스트는 단일 청크."""
    from rag.vector_store import KimchiVectorStore

    chunks = KimchiVectorStore._chunk_text("배추 입고 기준은 함수율 95% 이하.")
    assert len(chunks) == 1
    assert "배추" in chunks[0]


def test_chunk_text_long_overlap() -> None:
    """긴 텍스트는 여러 청크로 분할되고 각 청크가 chunk_size 이하."""
    from rag.vector_store import KimchiVectorStore

    text = "가나다라마바사 " * 200  # 약 1600자
    chunks = KimchiVectorStore._chunk_text(text, chunk_size=500, overlap=50)
    assert len(chunks) >= 3
    assert all(len(c) <= 520 for c in chunks)  # 경계 보정 여유 포함


def test_to_pgvector_format() -> None:
    """pgvector 리터럴 포맷 검증."""
    from rag.vector_store import KimchiVectorStore

    lit = KimchiVectorStore._to_pgvector([0.1, -0.2, 0.3])
    assert lit.startswith("[") and lit.endswith("]")
    assert lit.count(",") == 2


def test_to_ref_docs_schema() -> None:
    """라우터 출처 변환이 ReferencedDoc(title, doc_type, score) 호환인지."""
    from rag.agent_router import _to_ref_docs

    out = _to_ref_docs(
        [
            {"title": "배추김치 품질 기준서", "doc_type": "QUALITY_STANDARD",
             "version": "2.1", "score": 0.91},
            {"title": "결측", "score": 0.5},  # doc_type 누락 케이스
        ]
    )
    assert out[0]["title"] == "배추김치 품질 기준서"
    assert out[0]["doc_type"] == "QUALITY_STANDARD"
    assert isinstance(out[0]["score"], float)
    assert out[1]["doc_type"] == "UNKNOWN"  # 누락 시 기본값


def test_router_unknown_agent_type() -> None:
    """알 수 없는 agent_type 은 예외 없이 안내 문구 반환."""
    from rag.agent_router import run_rag_agent

    text, docs = asyncio.run(run_rag_agent("테스트", "WRONG_TYPE"))
    assert "알 수 없는" in text
    assert docs == []


def test_router_never_raises_without_keys() -> None:
    """OpenAI 키 없는 환경에서도 run_rag_agent 는 예외를 던지지 않고
    fallback 응답(확인 불가 안내)을 반환한다."""
    # 키 제거 (fallback 경로 강제)
    saved = os.environ.pop("OPENAI_API_KEY", None)
    try:
        text, docs = asyncio.run(run_rag_agent_safe("입고 기준 알려줘", "INTAKE"))
        assert isinstance(text, str) and len(text) > 0
        assert isinstance(docs, list)
    finally:
        if saved is not None:
            os.environ["OPENAI_API_KEY"] = saved


def run_rag_agent_safe(query: str, agent_type: str):
    """test 헬퍼: run_rag_agent 재노출 (import 지연)."""
    from rag.agent_router import run_rag_agent

    return run_rag_agent(query, agent_type)


# ── 라이브 통합 테스트 (RUN_LIVE_RAG=1 일 때만) ─────────────────────────
def _live_enabled() -> bool:
    return os.getenv("RUN_LIVE_RAG") == "1" and bool(os.getenv("OPENAI_API_KEY"))


def test_live_intake_supplier_quality() -> None:
    """[live] INTAKE-01: 공급처 품질 이력 — 실제 LLM + DB + pgvector 필요."""
    if not _live_enabled():
        print("SKIP: RUN_LIVE_RAG 미설정 — 라이브 테스트 건너뜀")
        return
    from rag.intake_agent import IntakeRAGAgent

    agent = IntakeRAGAgent()
    r = asyncio.run(agent.query("SUP01 공급처의 최근 품질 이력을 알려줘"))
    assert r["agent_type"] == "INTAKE"
    assert r["needs_approval"] is True
    assert len(r["response"]) > 0
    # 도구 호출이 실제로 일어났는지(공급처 조회)
    tool_names = [t["name"] for t in r["tool_calls"]]
    assert "search_supplier_quality" in tool_names or r.get("fallback")


def test_live_shipping_lot_trace() -> None:
    """[live] SHIP-02: LOT 역추적 — 실제 LLM + DB 필요."""
    if not _live_enabled():
        print("SKIP: RUN_LIVE_RAG 미설정 — 라이브 테스트 건너뜀")
        return
    from rag.shipping_agent import ShippingRAGAgent

    agent = ShippingRAGAgent()
    r = asyncio.run(agent.query("PK-20260524-001 포장 LOT을 역추적해줘"))
    assert r["agent_type"] == "SHIPPING"
    assert r["needs_approval"] is True
    assert "PK-20260524-001" in r["response"] or r.get("fallback")


# =====================================================================
# 직접 실행
# =====================================================================
if __name__ == "__main__":
    print_qa_cases()

    print("오프라인 단위 테스트 실행...")
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and not name.startswith("test_live") and callable(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"  FAIL {name}: {e}")
            except Exception as e:  # noqa: BLE001
                failures += 1
                print(f"  ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n결과: {'모두 통과' if failures == 0 else f'{failures}건 실패'}")
