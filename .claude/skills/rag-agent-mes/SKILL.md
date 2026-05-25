---
name: rag-agent-mes
description: 꽃순이김치 MES 원재료 입고 AI Agent 및 포장·출하 AI Agent를 LangChain/LangGraph로 개발하는 스킬. pgvector 기반 표준문서 검색, 공정 데이터 조회, Agent 워크플로우 설계 시 반드시 이 스킬을 사용하라. 트리거: RAG, AI Agent, LangChain, LangGraph, 원재료 입고 Agent, 출하 Agent, pgvector 검색, 벡터 검색, 자연어 질의.
---

# MES RAG Agent 개발 스킬

## Agent 개요

| Agent | 질의 대상 | 데이터 소스 |
|-------|----------|-----------|
| 원재료 입고 Agent | 공급처 품질 이력, 입고 기준 적합성, LOT 추적 | 원재료 LOT DB + 품질기준서/공급처 평가 이력 (pgvector) |
| 포장·출하 Agent | 출하 승인 기준, LOT 추적, 클레임 원인 및 대응 | 출하 승인 DB + 품질표준서/클레임 대응 매뉴얼 (pgvector) |

---

## LangGraph 워크플로우 구조

```python
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_postgres.vectorstores import PGVector
from typing import TypedDict, Annotated
import operator

class AgentState(TypedDict):
    query: str
    lot_id: str | None
    retrieved_docs: list
    db_data: dict
    response: str
    sources: list
    needs_approval: bool  # 파일럿: 운영자 승인 필요 여부

def build_intake_agent(db_conn_str: str, vector_conn_str: str):
    """원재료 입고 Agent 워크플로우"""
    llm = ChatOpenAI(model="gpt-4o", temperature=0)
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

    vectorstore = PGVector(
        connection=vector_conn_str,
        embeddings=embeddings,
        collection_name="document_embeddings"
    )

    def retrieve_docs(state: AgentState) -> AgentState:
        """pgvector에서 관련 문서 검색"""
        docs = vectorstore.similarity_search(
            state["query"],
            k=5,
            filter={"doc_type": {"$in": ["QC_STANDARD", "SOP"]}}
        )
        return {**state, "retrieved_docs": docs}

    def query_db(state: AgentState) -> AgentState:
        """PostgreSQL에서 LOT 데이터 조회"""
        # lot_id가 있으면 해당 LOT 이력 조회
        db_data = {}
        if state.get("lot_id"):
            db_data = fetch_intake_lot_history(state["lot_id"], db_conn_str)
        return {**state, "db_data": db_data}

    def generate_response(state: AgentState) -> AgentState:
        """LLM으로 최종 응답 생성"""
        context = "\n".join([doc.page_content for doc in state["retrieved_docs"]])
        sources = [doc.metadata.get("source_file", "unknown") for doc in state["retrieved_docs"]]

        prompt = f"""당신은 꽃순이김치 원재료 입고 담당 AI 어시스턴트입니다.
아래 문서와 DB 데이터를 참고하여 질문에 답하세요.
답변이 불확실하면 "확인이 필요합니다"라고 명시하세요.

참고 문서:
{context}

DB 데이터:
{state['db_data']}

질문: {state['query']}"""

        response = llm.invoke(prompt)
        return {
            **state,
            "response": response.content,
            "sources": sources,
            "needs_approval": True  # 파일럿 단계: 모든 응답 승인 필요
        }

    graph = StateGraph(AgentState)
    graph.add_node("retrieve_docs", retrieve_docs)
    graph.add_node("query_db", query_db)
    graph.add_node("generate_response", generate_response)

    graph.set_entry_point("retrieve_docs")
    graph.add_edge("retrieve_docs", "query_db")
    graph.add_edge("query_db", "generate_response")
    graph.add_edge("generate_response", END)

    return graph.compile()
```

---

## 포장·출하 Agent 워크플로우

```python
def build_shipping_agent(db_conn_str: str, vector_conn_str: str):
    """포장·출하 Agent — 클레임 분석 + 출하 승인 기준 질의"""
    llm = ChatOpenAI(model="gpt-4o", temperature=0)
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

    vectorstore = PGVector(
        connection=vector_conn_str,
        embeddings=embeddings,
        collection_name="document_embeddings"
    )

    def retrieve_docs(state: AgentState) -> AgentState:
        docs = vectorstore.similarity_search(
            state["query"],
            k=5,
            filter={"doc_type": {"$in": ["QC_STANDARD", "CLAIM_RESPONSE", "SOP"]}}
        )
        return {**state, "retrieved_docs": docs}

    def query_shipping_db(state: AgentState) -> AgentState:
        db_data = {}
        if state.get("lot_id"):
            db_data = fetch_shipping_lot_traceability(state["lot_id"], db_conn_str)
        return {**state, "db_data": db_data}

    def generate_response(state: AgentState) -> AgentState:
        context = "\n".join([doc.page_content for doc in state["retrieved_docs"]])
        sources = [doc.metadata.get("source_file", "unknown") for doc in state["retrieved_docs"]]
        prompt = f"""당신은 꽃순이김치 포장·출하 담당 AI 어시스턴트입니다.
출처가 불명확하면 '확인 불가'라고 명시하세요.

참고 문서: {context}
DB 데이터: {state['db_data']}
질문: {state['query']}"""

        response = llm.invoke(prompt)
        return {**state, "response": response.content, "sources": sources, "needs_approval": True}

    graph = StateGraph(AgentState)
    graph.add_node("retrieve_docs", retrieve_docs)
    graph.add_node("query_db", query_shipping_db)
    graph.add_node("generate_response", generate_response)
    graph.set_entry_point("retrieve_docs")
    graph.add_edge("retrieve_docs", "query_db")
    graph.add_edge("query_db", "generate_response")
    graph.add_edge("generate_response", END)
    return graph.compile()
```

---

## DB 조회 헬퍼 함수

```python
import psycopg2
from contextlib import contextmanager

@contextmanager
def get_db(conn_str: str):
    conn = psycopg2.connect(conn_str)
    try:
        yield conn
    finally:
        conn.close()

def fetch_intake_lot_history(lot_id: str, conn_str: str) -> dict:
    """원재료 입고 LOT 이력 조회 (전 공정 연결)"""
    query = """
        SELECT rmi.*, sp.salting_lot_id, sp.actual_salinity, sp.ph_value,
               fp.fermentation_lot_id, fp.ml_quality_prediction
        FROM raw_material_intake rmi
        LEFT JOIN salting_process sp ON rmi.intake_lot_id = sp.intake_lot_id
        LEFT JOIN fermentation_process fp ON sp.salting_lot_id = fp.salting_lot_id
        WHERE rmi.intake_lot_id = %s
    """
    with get_db(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (lot_id,))
            row = cur.fetchone()
            if row:
                return dict(zip([d[0] for d in cur.description], row))
    return {}

def fetch_shipping_lot_traceability(lot_id: str, conn_str: str) -> dict:
    """출하 LOT 전 공정 추적 조회"""
    query = """
        SELECT s.*, fp.fermentation_lot_id, fp.ml_quality_prediction,
               sp.salting_lot_id, rmi.intake_lot_id, rmi.supplier_id
        FROM shipping s
        LEFT JOIN fermentation_process fp ON s.fermentation_lot_id = fp.fermentation_lot_id
        LEFT JOIN salting_process sp ON fp.salting_lot_id = sp.salting_lot_id
        LEFT JOIN raw_material_intake rmi ON sp.intake_lot_id = rmi.intake_lot_id
        WHERE s.shipping_lot_id = %s
    """
    with get_db(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (lot_id,))
            row = cur.fetchone()
            if row:
                return dict(zip([d[0] for d in cur.description], row))
    return {}
```

---

## 문서 임베딩 적재 스크립트

```python
from langchain_openai import OpenAIEmbeddings
from langchain_postgres.vectorstores import PGVector
from langchain.schema import Document

def embed_documents(docs: list[dict], vector_conn_str: str):
    """표준문서 → pgvector 임베딩 적재"""
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    documents = [
        Document(
            page_content=doc["content"],
            metadata={
                "doc_type": doc["doc_type"],
                "source_file": doc["source_file"],
                "title": doc["title"]
            }
        )
        for doc in docs
    ]
    vectorstore = PGVector.from_documents(
        documents=documents,
        embedding=embeddings,
        connection=vector_conn_str,
        collection_name="document_embeddings"
    )
    return vectorstore
```

---

## Streamlit AI Chat 컴포넌트

```python
import streamlit as st

def render_ai_agent_chat(agent, title: str):
    st.subheader(title)
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if msg.get("sources"):
                st.caption(f"출처: {', '.join(msg['sources'])}")

    if query := st.chat_input("질문을 입력하세요..."):
        st.session_state.chat_history.append({"role": "user", "content": query})
        lot_id = st.session_state.get("selected_lot_id")

        result = agent.invoke({"query": query, "lot_id": lot_id})

        if result["needs_approval"]:
            st.warning("이 응답은 운영자 승인 후 생산 계획에 반영됩니다 (파일럿 단계)")

        st.session_state.chat_history.append({
            "role": "assistant",
            "content": result["response"],
            "sources": result["sources"]
        })
        st.rerun()
```

---

## 운영 원칙
1. **파일럿 단계**: `needs_approval=True`로 모든 응답에 승인 게이트 적용
2. **환각 방지**: 문서/DB 근거가 없으면 "확인 불가" 명시
3. **출처 명시**: 모든 응답에 참조 문서명 포함
4. **doc_type 필터**: 관련 없는 문서 검색 방지를 위해 항상 필터 적용
