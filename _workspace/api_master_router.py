"""
꽃순이김치 제조AI MES — 기준정보관리 모듈 FastAPI 라우터
Project : SF26179540 | 평창꽃순이(주) | 로뎀솔루션
Module  : 기준정보관리 (품질기준 / 작업표준(SOP) / 코드 / 공급업체)
Prefix  : /api/v1/master
Stack   : FastAPI + asyncpg (Pydantic v2)

사용 예 (app/main.py):
    from app.routers import master
    app.include_router(master.router)
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime

from fastapi import (
    APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, BackgroundTasks,
)
from pydantic import BaseModel, Field

# 프로젝트 표준 DB 헬퍼 (app/database.py: get_db / get_pool)
from app.database import get_db
from app.auth import require_role, CurrentUser  # JWT + RBAC

router = APIRouter(prefix="/api/v1/master", tags=["기준정보관리"])

# SOP 원본 파일 저장 루트 (운영 시 S3 등으로 대체)
SOP_STORAGE_ROOT = os.getenv("SOP_STORAGE_ROOT", "./storage/sop")


# =============================================================================
# Pydantic 모델
# =============================================================================
class QualityStandardCreate(BaseModel):
    process_code: str
    standard_item: str
    normal_min: float | None = None
    normal_max: float | None = None
    warning_min: float | None = None
    warning_max: float | None = None
    unit: str | None = None
    measurement_method: str | None = None
    is_active: bool = True
    valid_from: date | None = None
    valid_to: date | None = None
    created_by: str | None = None


class QualityStandardUpdate(BaseModel):
    standard_item: str | None = None
    normal_min: float | None = None
    normal_max: float | None = None
    warning_min: float | None = None
    warning_max: float | None = None
    unit: str | None = None
    measurement_method: str | None = None
    is_active: bool | None = None
    valid_to: date | None = None


class CodeCreate(BaseModel):
    code_group: str = Field(..., description="PROCESS/PRODUCT/DEFECT/MATERIAL/SUPPLIER/UNIT")
    code: str
    code_name: str
    code_name_en: str | None = None
    sort_order: int = 0
    is_active: bool = True
    description: str | None = None


class CodeUpdate(BaseModel):
    code_name: str | None = None
    code_name_en: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    description: str | None = None


class SupplierCreate(BaseModel):
    supplier_code: str
    supplier_name: str
    contact: str | None = None
    address: str | None = None
    material_types: list[str] = Field(default_factory=list)
    quality_grade: str = "B"
    is_active: bool = True


class SupplierUpdate(BaseModel):
    supplier_name: str | None = None
    contact: str | None = None
    address: str | None = None
    material_types: list[str] | None = None
    quality_grade: str | None = None
    is_active: bool | None = None


# =============================================================================
# 품질 기준 (quality_standard)
# =============================================================================
@router.get("/quality-standards")
async def list_quality_standards(
    process_code: str | None = Query(None, description="공정 코드 필터"),
    is_active: bool | None = Query(None, description="활성 여부 필터"),
):
    """품질 기준 목록 조회 (공정/활성 필터)"""
    clauses, params = [], []
    if process_code is not None:
        params.append(process_code)
        clauses.append(f"process_code = ${len(params)}")
    if is_active is not None:
        params.append(is_active)
        clauses.append(f"is_active = ${len(params)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    async with get_db() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM quality_standard {where} "
            f"ORDER BY process_code, standard_item",
            *params,
        )
    return [dict(r) for r in rows]


@router.post("/quality-standards", status_code=201)
async def create_quality_standard(
    data: QualityStandardCreate,
    _: CurrentUser = Depends(require_role("QUALITY", "ADMIN")),
):
    """품질 기준 등록"""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO quality_standard
                (process_code, standard_item, normal_min, normal_max,
                 warning_min, warning_max, unit, measurement_method,
                 is_active, valid_from, valid_to, created_by)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,
                    COALESCE($10, CURRENT_DATE),$11,$12)
            RETURNING *
            """,
            data.process_code, data.standard_item, data.normal_min, data.normal_max,
            data.warning_min, data.warning_max, data.unit, data.measurement_method,
            data.is_active, data.valid_from, data.valid_to, data.created_by,
        )
    return dict(row)


@router.put("/quality-standards/{id}")
async def update_quality_standard(
    id: int,
    data: QualityStandardUpdate,
    _: CurrentUser = Depends(require_role("QUALITY", "ADMIN")),
):
    """품질 기준 수정 (부분 갱신)"""
    fields = data.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="수정할 항목이 없습니다")
    sets, params = [], []
    for k, v in fields.items():
        params.append(v)
        sets.append(f"{k} = ${len(params)}")
    params.append(id)
    async with get_db() as conn:
        row = await conn.fetchrow(
            f"UPDATE quality_standard SET {', '.join(sets)} "
            f"WHERE id = ${len(params)} RETURNING *",
            *params,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"품질기준 id={id} 없음")
    return dict(row)


# =============================================================================
# 작업표준 SOP (sop_document) + pgvector 임베딩
# =============================================================================
@router.get("/sop-documents")
async def list_sop_documents(
    doc_type: str | None = Query(None, description="문서 유형 필터"),
    is_active: bool | None = Query(None, description="활성 여부 필터"),
):
    """SOP 문서 목록 조회 (유형/활성 필터)"""
    clauses, params = [], []
    if doc_type is not None:
        params.append(doc_type)
        clauses.append(f"doc_type = ${len(params)}")
    if is_active is not None:
        params.append(is_active)
        clauses.append(f"is_active = ${len(params)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    async with get_db() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM sop_document {where} ORDER BY created_at DESC",
            *params,
        )
    return [dict(r) for r in rows]


@router.post("/sop-documents/upload", status_code=201)
async def upload_sop_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="SOP 원본 파일 (PDF/DOCX)"),
    doc_type: str = Form(...),
    title: str = Form(...),
    version: str = Form(...),
    process_codes: str = Form("", description="공정 코드 콤마 구분 (예: PROC03,PROC07)"),
    created_by: str = Form(None),
    auto_embed: bool = Form(True, description="업로드 즉시 임베딩 시작 여부"),
    _: CurrentUser = Depends(require_role("ADMIN", "MANAGER")),
):
    """SOP 파일 업로드 + 메타데이터 저장. auto_embed=True 시 백그라운드 임베딩 트리거"""
    valid_types = {"SOP", "QC_STANDARD", "HACCP", "EQUIPMENT_MANUAL", "CLAIM_RESPONSE"}
    if doc_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"doc_type은 {valid_types} 중 하나")

    # 1. 파일 디스크 저장
    os.makedirs(SOP_STORAGE_ROOT, exist_ok=True)
    doc_id = f"{doc_type}_{version}_{uuid.uuid4().hex[:8]}"
    safe_name = f"{doc_id}_{file.filename}"
    file_path = os.path.join(SOP_STORAGE_ROOT, safe_name)
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    # 2. process_codes 파싱
    codes = [c.strip() for c in process_codes.split(",") if c.strip()]

    # 3. 메타데이터 저장
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO sop_document
                (doc_id, doc_type, process_codes, title, version, file_path,
                 chunk_count, embed_status, is_active, created_by)
            VALUES ($1,$2,$3,$4,$5,$6,0,'PENDING',FALSE,$7)
            RETURNING *
            """,
            doc_id, doc_type, codes, title, version, file_path, created_by,
        )

    # 4. 임베딩 백그라운드 트리거
    if auto_embed:
        background_tasks.add_task(embed_sop_document, doc_id, file_path)

    return {"document": dict(row), "embedding_started": auto_embed}


@router.post("/sop-documents/{doc_id}/embed")
async def trigger_sop_embedding(
    doc_id: str,
    background_tasks: BackgroundTasks,
    _: CurrentUser = Depends(require_role("ADMIN")),
):
    """pgvector 임베딩 처리 수동 트리거 (백그라운드 태스크)"""
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT file_path, embed_status FROM sop_document WHERE doc_id = $1", doc_id
        )
        if not row:
            raise HTTPException(status_code=404, detail=f"문서 {doc_id} 없음")
        if row["embed_status"] == "PROCESSING":
            raise HTTPException(status_code=409, detail="이미 임베딩 처리 중입니다")
        # embed_sop_document 진입 시 PROCESSING으로 갱신하므로 여기서 PENDING 재설정 불필요.
        # (기존 PENDING→PROCESSING 이중 갱신 제거 — LOW-3 수정)
    background_tasks.add_task(embed_sop_document, doc_id, row["file_path"])
    return {"doc_id": doc_id, "status": "임베딩 작업이 시작되었습니다"}


@router.put("/sop-documents/{doc_id}/activate")
async def activate_sop_document(
    doc_id: str,
    approved_by: str = Query(None),
    _: CurrentUser = Depends(require_role("ADMIN")),
):
    """문서 활성화. 동일 doc_type+title의 이전 버전을 모두 비활성화"""
    async with get_db() as conn:
        target = await conn.fetchrow(
            "SELECT doc_type, title, embed_status FROM sop_document WHERE doc_id = $1",
            doc_id,
        )
        if not target:
            raise HTTPException(status_code=404, detail=f"문서 {doc_id} 없음")
        if target["embed_status"] != "COMPLETED":
            raise HTTPException(
                status_code=409,
                detail=f"임베딩 미완료 상태({target['embed_status']})에서는 활성화 불가",
            )
        async with conn.transaction():
            # 이전 버전 비활성화 (같은 doc_type + title)
            # LOWER(TRIM()) 정규화: title 대소문자/앞뒤공백 차이로 인한 그룹핑 누락 방지
            await conn.execute(
                """
                UPDATE sop_document SET is_active = FALSE, valid_to = CURRENT_DATE
                WHERE doc_type = $1
                  AND LOWER(TRIM(title)) = LOWER(TRIM($2))
                  AND doc_id <> $3
                  AND is_active = TRUE
                """,
                target["doc_type"], target["title"], doc_id,
            )
            # 대상 활성화
            row = await conn.fetchrow(
                """
                UPDATE sop_document
                SET is_active = TRUE, valid_from = CURRENT_DATE, valid_to = NULL,
                    approved_by = $2, approved_at = NOW()
                WHERE doc_id = $1
                RETURNING *
                """,
                doc_id, approved_by,
            )
    return dict(row)


@router.delete("/sop-documents/{doc_id}")
async def discard_sop_document(
    doc_id: str,
    _: CurrentUser = Depends(require_role("ADMIN")),
):
    """문서 폐기 (soft delete: is_active=False)"""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            UPDATE sop_document
            SET is_active = FALSE, valid_to = CURRENT_DATE
            WHERE doc_id = $1
            RETURNING doc_id
            """,
            doc_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"문서 {doc_id} 없음")
    return {"doc_id": doc_id, "is_active": False, "detail": "문서가 폐기되었습니다"}


# =============================================================================
# 코드 관리 (code_master)
# =============================================================================
@router.get("/codes")
async def list_codes(
    code_group: str | None = Query(None, description="코드 그룹 필터"),
    is_active: bool | None = Query(None),
):
    """코드 목록 조회 (그룹 필터)"""
    clauses, params = [], []
    if code_group is not None:
        params.append(code_group)
        clauses.append(f"code_group = ${len(params)}")
    if is_active is not None:
        params.append(is_active)
        clauses.append(f"is_active = ${len(params)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    async with get_db() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM code_master {where} ORDER BY code_group, sort_order, code",
            *params,
        )
    return [dict(r) for r in rows]


@router.post("/codes", status_code=201)
async def create_code(
    data: CodeCreate,
    _: CurrentUser = Depends(require_role("ADMIN")),
):
    """코드 등록"""
    async with get_db() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO code_master
                    (code_group, code, code_name, code_name_en, sort_order, is_active, description)
                VALUES ($1,$2,$3,$4,$5,$6,$7)
                RETURNING *
                """,
                data.code_group, data.code, data.code_name, data.code_name_en,
                data.sort_order, data.is_active, data.description,
            )
        except Exception as e:  # UNIQUE 위반 등
            raise HTTPException(status_code=409, detail=f"코드 등록 실패: {e}")
    return dict(row)


@router.put("/codes/{code_group}/{code}")
async def update_code(
    code_group: str,
    code: str,
    data: CodeUpdate,
    _: CurrentUser = Depends(require_role("ADMIN")),
):
    """코드 수정 (부분 갱신)"""
    fields = data.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="수정할 항목이 없습니다")
    sets, params = [], []
    for k, v in fields.items():
        params.append(v)
        sets.append(f"{k} = ${len(params)}")
    params.extend([code_group, code])
    async with get_db() as conn:
        row = await conn.fetchrow(
            f"UPDATE code_master SET {', '.join(sets)} "
            f"WHERE code_group = ${len(params)-1} AND code = ${len(params)} RETURNING *",
            *params,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"코드 {code_group}/{code} 없음")
    return dict(row)


@router.delete("/codes/{code_group}/{code}")
async def delete_code(
    code_group: str,
    code: str,
    _: CurrentUser = Depends(require_role("ADMIN")),
):
    """코드 삭제 (soft delete: is_active=False)"""
    async with get_db() as conn:
        row = await conn.fetchrow(
            "UPDATE code_master SET is_active = FALSE "
            "WHERE code_group = $1 AND code = $2 RETURNING id",
            code_group, code,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"코드 {code_group}/{code} 없음")
    return {"code_group": code_group, "code": code, "is_active": False}


# =============================================================================
# 공급업체 (supplier)
# =============================================================================
@router.get("/suppliers")
async def list_suppliers(
    quality_grade: str | None = Query(None, description="품질 등급 필터 A/B/C/D"),
    is_active: bool | None = Query(None),
):
    """공급업체 목록 조회"""
    clauses, params = [], []
    if quality_grade is not None:
        params.append(quality_grade)
        clauses.append(f"quality_grade = ${len(params)}")
    if is_active is not None:
        params.append(is_active)
        clauses.append(f"is_active = ${len(params)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    async with get_db() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM supplier {where} ORDER BY supplier_code",
            *params,
        )
    return [dict(r) for r in rows]


@router.post("/suppliers", status_code=201)
async def create_supplier(
    data: SupplierCreate,
    _: CurrentUser = Depends(require_role("ADMIN", "MANAGER")),
):
    """공급업체 등록"""
    async with get_db() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO supplier
                    (supplier_code, supplier_name, contact, address,
                     material_types, quality_grade, is_active)
                VALUES ($1,$2,$3,$4,$5,$6,$7)
                RETURNING *
                """,
                data.supplier_code, data.supplier_name, data.contact, data.address,
                data.material_types, data.quality_grade, data.is_active,
            )
        except Exception as e:
            raise HTTPException(status_code=409, detail=f"공급업체 등록 실패: {e}")
    return dict(row)


@router.put("/suppliers/{supplier_id}")
async def update_supplier(
    supplier_id: int,
    data: SupplierUpdate,
    _: CurrentUser = Depends(require_role("ADMIN", "MANAGER")),
):
    """공급업체 정보 수정 (부분 갱신)"""
    fields = data.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="수정할 항목이 없습니다")
    sets, params = [], []
    for k, v in fields.items():
        params.append(v)
        sets.append(f"{k} = ${len(params)}")
    params.append(supplier_id)
    async with get_db() as conn:
        row = await conn.fetchrow(
            f"UPDATE supplier SET {', '.join(sets)} "
            f"WHERE supplier_id = ${len(params)} RETURNING *",
            *params,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"공급업체 id={supplier_id} 없음")
    return dict(row)


# =============================================================================
# SOP 임베딩 백그라운드 태스크
#   Plan 7.2: 텍스트 추출 → 청킹(1000토큰/200 overlap) → 임베딩 → pgvector 적재
#   실제 임베딩 벡터는 Vector DB의 document_embeddings 테이블에 적재됨
# =============================================================================
async def embed_sop_document(doc_id: str, file_path: str):
    """
    SOP 문서 임베딩 백그라운드 처리.

    처리 단계:
      1. 파일 텍스트 추출 (PDF/DOCX)
      2. 청킹 (1000 토큰, 200 overlap)
      3. OpenAI embedding → pgvector(document_embeddings) 저장
      4. chunk_count / embed_status 업데이트
    """
    # 처리 시작 표시
    async with get_db() as conn:
        await conn.execute(
            "UPDATE sop_document SET embed_status = 'PROCESSING' WHERE doc_id = $1", doc_id
        )

    try:
        # ---------------------------------------------------------------------
        # 1. 파일 텍스트 추출 (PDF/DOCX)
        # ---------------------------------------------------------------------
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            from pypdf import PdfReader  # pip install pypdf
            reader = PdfReader(file_path)
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        elif ext == ".docx":
            import docx  # pip install python-docx
            doc = docx.Document(file_path)
            text = "\n".join(p.text for p in doc.paragraphs)
        else:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()

        # ---------------------------------------------------------------------
        # 2. 청킹 (1000 토큰, 200 overlap)
        # ---------------------------------------------------------------------
        from langchain.text_splitter import RecursiveCharacterTextSplitter
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000, chunk_overlap=200, length_function=len,
        )
        chunks = splitter.split_text(text)

        # 메타데이터 (doc_type, title 등) 조회
        async with get_db() as conn:
            meta = await conn.fetchrow(
                "SELECT doc_type, title, version FROM sop_document WHERE doc_id = $1",
                doc_id,
            )

        # ---------------------------------------------------------------------
        # 3. OpenAI embedding → pgvector(document_embeddings) 직접 적재
        #    LangChain PGVector는 내부 전용 테이블(langchain_pg_embedding 등)을 생성하므로
        #    기존 document_embeddings DDL 스키마와 충돌한다.
        #    asyncpg + openai 클라이언트로 직접 INSERT하여 스키마 일관성을 유지한다.
        # ---------------------------------------------------------------------
        import asyncpg as _asyncpg
        import json as _json
        from openai import AsyncOpenAI as _AsyncOpenAI

        _openai_client = _AsyncOpenAI()
        _vector_dsn = os.getenv(
            "VECTOR_DB_URL",
            "postgresql://user:password@vector-db:5432/vector_db",
        )
        _vec_conn = await _asyncpg.connect(_vector_dsn)
        try:
            for i, chunk in enumerate(chunks):
                emb_resp = await _openai_client.embeddings.create(
                    model="text-embedding-3-small",
                    input=chunk,
                )
                embedding_list = emb_resp.data[0].embedding  # list[float]
                # asyncpg는 vector 타입을 문자열 '[f1,f2,...]' 형태로 전달
                embedding_str = "[" + ",".join(str(v) for v in embedding_list) + "]"
                await _vec_conn.execute(
                    """
                    INSERT INTO document_embeddings
                        (doc_type, title, content, embedding, source_file, version, metadata)
                    VALUES ($1, $2, $3, $4::vector, $5, $6, $7::jsonb)
                    """,
                    meta["doc_type"],
                    meta["title"],
                    chunk,
                    embedding_str,
                    os.path.basename(file_path),
                    meta["version"],
                    _json.dumps({"doc_id": doc_id, "chunk_index": i}),
                )
        finally:
            await _vec_conn.close()

        # ---------------------------------------------------------------------
        # 4. chunk_count / 처리 상태 업데이트 (COMPLETED)
        # ---------------------------------------------------------------------
        async with get_db() as conn:
            await conn.execute(
                "UPDATE sop_document SET chunk_count = $2, embed_status = 'COMPLETED' "
                "WHERE doc_id = $1",
                doc_id, len(chunks),
            )

    except Exception as e:
        # 실패 상태 기록 (운영 시 system_log 적재 권장)
        async with get_db() as conn:
            await conn.execute(
                "UPDATE sop_document SET embed_status = 'FAILED' WHERE doc_id = $1", doc_id
            )
        # 백그라운드 태스크이므로 예외는 로깅만 (운영 시 logger 사용)
        print(f"[embed_sop_document] FAILED doc_id={doc_id}: {e}")
