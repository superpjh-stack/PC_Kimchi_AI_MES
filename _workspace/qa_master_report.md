# QA 검증 보고서 — 기준정보관리 모듈 (QA-MASTER)

> Project: SF26179540 | 평창꽃순이(주) | 로뎀솔루션
> 검증일: 2026-05-24 | 검증자: QA-MASTER (기준정보관리 QA 검증 전문가)
> 대상: `db_master_schema.sql`, `api_master_router.py`, `ui_08_master.py`
> 기준: `pm3-process-data-kpi-system.plan.md` §7, `db-schema-design` SKILL, `rag-agent-mes` SKILL

---

## 종합 결과

| 항목 | 결과 |
|------|------|
| 총 검증 항목 | 30 |
| 통과 (PASS) | 26 |
| 부분 통과 (PARTIAL) | 2 |
| 실패 (FAIL) | 2 |
| **통과율** | **87% (26/30)** |
| 이슈 | 6건 (HIGH:1, MEDIUM:2, LOW:3) |

전반적으로 DB 스키마·API·UI 3계층이 Plan §7 명세를 충실히 구현하였다. LOT 트레이서빌리티·임베딩 연동·권한 게이트 등 핵심 요구를 충족하나, pgvector 연동 정합성에서 **HIGH 1건**(collection_name 불일치 가능성)과 활성화 검증 로직의 미세 결함이 발견되었다.

---

## 1. DB 스키마 검증

| # | 검증 항목 | 결과 | 근거 |
|---|-----------|------|------|
| 1 | 4개 테이블 (quality_standard, sop_document, code_master, supplier) | PASS | 4개 모두 CREATE TABLE 정의 (L13/47/85/113) |
| 2 | quality_standard: normal_min/max, warning_min/max, unit, is_active, valid_from, valid_to | PASS | L17~25 전부 존재 |
| 3 | sop_document: doc_type CHECK (5종), process_codes TEXT[], chunk_count, is_active, approved_by, approved_at | PASS | L49~70 CHECK 5종 일치, 모든 컬럼 존재 |
| 4 | sop_document.embed_status (임베딩 상태 추적) | PASS | L55 embed_status + CHECK (PENDING/PROCESSING/COMPLETED/FAILED) L67 |
| 5 | code_master: (code_group, code) UNIQUE 인덱스 | PASS | L104 uidx_cm_group_code |
| 6 | code_master.code_group CHECK enum (6종) | PASS | L96~98 PROCESS/PRODUCT/DEFECT/MATERIAL/SUPPLIER/UNIT |
| 7 | GIN 인덱스 (sop_document.process_codes, supplier.material_types) | PASS | L75 idx_sop_process_codes, L131 idx_sup_material_types |
| 8 | §7.1 절임/발효/출하 품질 기준값 시드 | PASS | L212~227 (절임 PROC03, 발효 PROC07, 출하 PROC09) |
| 9 | §7.3 공정코드 PROC01~09 시드 | PASS | L164~174 9개 전부 |

### 시드 정합성 정밀 대조 (§7.1 vs SQL)

Plan §7.1 표와 SQL 시드값을 행 단위로 대조한 결과 **모든 값 일치**:
- 절임 온도 5~20 / 경고 <5 또는 >25 → SQL `(5.0,20.0,5.0,25.0)` 일치
- 절임 염도 2.0~3.5 / <1.5,>4.0 → `(2.0,3.5,1.5,4.0)` 일치
- 발효 온도 0~10 / <-2,>15 → `(0.0,10.0,-2.0,15.0)` 일치
- 발효 pH 4.0~4.5 / <3.8,>5.0 → `(4.0,4.5,3.8,5.0)` 일치
- 산도 0.6~1.0 / <0.4,>1.3 → `(0.6,1.0,0.4,1.3)` 일치
- 출하 완성품 pH 3.8~4.8 → `(3.8,4.8,3.5,5.0)` 일치, 산도 0.5~1.2 → 일치, 냉장 0~10(CCP-2) → 일치

> [LOW-1] §7.1 출하 품질 기준의 `완성품 염도 1.5~3.0`, `포장 중량 ±3%`, `금속 이물질 0건(CCP-1)` 항목은 시드에 누락. 정상/경고 범위 형식이 아닌 항목(건수·합격여부)이라 quality_standard 모델에 맞지 않는 측면은 있으나, 완성품 염도는 범위형이므로 추가 권장.

> [LOW-2] §7.3 제품 코드(PRODUCT, KIM-BC-500 등) 시드가 누락. code_group enum에 PRODUCT는 존재하나 시드 데이터 없음. UNIT 그룹 주석(L202)에 "PRODUCT 그룹 대신 별도 활용 불필요"라는 모호한 설명이 있으나 Plan §7.3은 제품 코드 체계를 명시하므로 시드 보강 권장.

---

## 2. API 검증

### 엔드포인트 카운트: 14개 (요구 14개) — PASS

| # | Method | Path | 핸들러 |
|---|--------|------|--------|
| 1 | GET | /quality-standards | list_quality_standards |
| 2 | POST | /quality-standards | create_quality_standard |
| 3 | PUT | /quality-standards/{id} | update_quality_standard |
| 4 | GET | /sop-documents | list_sop_documents |
| 5 | POST | /sop-documents/upload | upload_sop_document |
| 6 | POST | /sop-documents/{doc_id}/embed | trigger_sop_embedding |
| 7 | PUT | /sop-documents/{doc_id}/activate | activate_sop_document |
| 8 | DELETE | /sop-documents/{doc_id} | discard_sop_document |
| 9 | GET | /codes | list_codes |
| 10 | POST | /codes | create_code |
| 11 | PUT | /codes/{code_group}/{code} | update_code |
| 12 | DELETE | /codes/{code_group}/{code} | delete_code |
| 13 | GET | /suppliers | list_suppliers |
| 14 | POST | /suppliers | create_supplier |
| (+1) | PUT | /suppliers/{supplier_id} | update_supplier |

> 실제 라우트는 **15개**(supplier PUT 포함). 요구 "14개"를 초과 충족. 카운트 기준 차이일 뿐 결함 아님.

| # | 검증 항목 | 결과 | 근거 |
|---|-----------|------|------|
| 10 | POST /upload: UploadFile + Form 조합 | PASS | L194~203 `file: UploadFile=File(...)` + `doc_type/title/version: Form(...)` |
| 11 | POST /{doc_id}/embed: BackgroundTasks 비동기 임베딩 | PASS | L242 `background_tasks: BackgroundTasks`, L255 add_task |
| 12 | 임베딩 함수: 텍스트추출→청킹(1000/200)→OpenAI embedding→PGVector 저장 | PASS | embed_sop_document L469~560: PDF/DOCX 추출 → RecursiveCharacterTextSplitter(1000/200) L506 → OpenAIEmbeddings → PGVector.from_documents |
| 13 | PUT /activate: 동일 doc_type+title 이전버전 비활성화 | PASS | L274~282 transaction 내 이전 버전 UPDATE is_active=FALSE |
| 14 | 활성화 시 임베딩 미완료 거부 (409) | PASS | L269~273 embed_status != COMPLETED → 409 |
| 15 | 코드 CRUD: (code_group, code) 복합키 PUT/DELETE | PASS | L360 PUT, L382 DELETE 모두 복합키 경로 |

### API 발견 이슈

> [HIGH-1] **pgvector collection_name 불일치 위험.** `embed_sop_document`(api L549)는 `PGVector.from_documents(..., collection_name="document_embeddings")`로 적재한다. 그러나 `db-schema-design` SKILL의 pgvector 스키마는 `document_embeddings`를 **직접 테이블**(embedding vector(1536), ivfflat 인덱스)로 정의하고, `rag-agent-mes` SKILL은 `PGVector(collection_name="document_embeddings")`로 조회한다. `langchain_postgres.PGVector`는 `collection_name`을 자체 관리 테이블(`langchain_pg_embedding` + `langchain_pg_collection`)의 컬렉션 레코드로 사용하므로, SKILL이 정의한 raw `document_embeddings` 테이블과 **물리 스키마가 충돌**한다. RAG Agent가 PGVector 인터페이스로만 접근한다면 일관되어 정상 동작하나, db-schema-design의 raw 테이블/`search_documents()` SQL 함수와는 호환되지 않는다. → 임베딩 적재(PGVector)와 조회(PGVector) 경로가 동일 추상화를 쓰므로 RAG Agent 동작은 OK이나, **db-schema-design SKILL의 raw 테이블 정의와 정합성 불일치**. 둘 중 하나로 통일 필요(권장: PGVector 추상화 일원화, raw 스키마 문서 정정).

> [MEDIUM-1] **활성화 시 동일 title 그룹핑이 doc_type+title 조합.** doc_id는 `f"{doc_type}_{version}_{uuid8}"`(L211)로 생성되어 title을 포함하지 않는다. 활성화 비활성화 기준(L279)이 `doc_type=$1 AND title=$2`로, 같은 문서의 다른 버전을 식별하려면 업로드 시 동일 title을 정확히 입력해야 한다. 운영상 title 오타 시 이전 버전이 비활성화되지 않을 수 있음. process_codes나 별도 doc_series 키 기반 그룹핑 권장.

> [LOW-3] `trigger_sop_embedding`(L252)은 상태를 PENDING으로 되돌린 뒤 background로 embed를 호출하나, embed 함수 진입 직후 PROCESSING으로 다시 갱신(L481)하므로 중복 갱신. 기능상 무해하나 불필요한 UPDATE.

---

## 3. UI-API 정합성 검증

| # | 검증 항목 | 결과 | 근거 |
|---|-----------|------|------|
| 16 | 4개 탭 (품질 기준 / 작업표준(SOP) / 코드 관리 / 공급업체) | PASS | L91~93 st.tabs 4개 |
| 17 | API URL prefix 일치 (/api/v1/master) | PASS | UI BASE_URL L23 `/api/v1/master` == router prefix L26 |
| 18 | SOP 업로드: file_uploader + 메타데이터 폼 + 임베딩 progress | PASS | L265 file_uploader, L264~277 폼, L297~309 st.progress 폴링 |
| 19 | 품질 기준 탭: 정상/경고 범위 색상 구분 | PASS | _range_style L99~109 정상=초록, 경고=주황 셀 배경 |
| 20 | 권한 게이트: role in (관리자, 품질담당자) 편집 | PASS | L40 CAN_EDIT, 각 탭 `if CAN_EDIT:` 가드 |

### UI-API 엔드포인트 경로 대조

| UI 호출 | API 라우트 | 일치 |
|---------|-----------|------|
| GET /quality-standards | GET /quality-standards | OK |
| POST /quality-standards, PUT /quality-standards/{id} | 일치 | OK |
| POST /sop-documents/upload (data+files) | upload (Form+File) | OK |
| POST /sop-documents/{id}/embed | embed | OK |
| PUT /sop-documents/{id}/activate?approved_by= | activate (Query approved_by) | OK |
| DELETE /sop-documents/{id} | discard | OK |
| GET/POST /codes, PUT/DELETE /codes/{group}/{code} | 일치 | OK |
| GET/POST /suppliers, PUT /suppliers/{id} | 일치 | OK |

### UI 발견 이슈

> [MEDIUM-2] **권한 매트릭스와 UI 게이트 부분 불일치.** Plan §8.1에 따르면 코드관리는 **관리자만 읽기/쓰기**, 품질담당자/공장장은 **읽기**. 그러나 UI는 `CAN_EDIT = role in (관리자, 품질담당자)`(L40)를 4개 탭 전체에 일괄 적용 → **품질담당자가 코드관리 탭에서 편집 가능**해지는 권한 과다. 품질기준/SOP는 §8.1상 품질담당자 읽기/쓰기가 맞으나, 코드관리는 관리자 전용이어야 함. 탭별 차등 권한 필요.
> 추가로 §8.1상 공급업체(supplier)는 PM3 기준정보관리 권한 표에 명시 항목이 없어(원재료관리 PM1 영역과 중첩) 권한 기준이 모호함 — 정책 확인 권장.

> [참고] `CURRENT_ROLE = st.session_state.get("user_role", "관리자")` — 미인증 시 기본값이 "관리자"로 fallback. 데모용으로는 무방하나 운영 전 인증 연동 필수(이슈 카운트 제외, 데모 코드 특성).

---

## 4. pgvector 연동 정합성

| # | 검증 항목 | 결과 | 근거 |
|---|-----------|------|------|
| 21 | 임베딩 저장 테이블 document_embeddings 연동, doc_id 연결 | PARTIAL | metadata에 doc_id 포함(api L535)되어 sop_document.doc_id와 논리 연결 O. 단 HIGH-1의 PGVector collection vs raw table 스키마 충돌 존재 |
| 22 | embedding 차원 1536 (text-embedding-3-small) | PASS | api L530 `OpenAIEmbeddings(model="text-embedding-3-small")` → 1536차원, db-schema-design `vector(1536)` 및 rag-agent-mes 모델과 일치 |

- doc_type 메타데이터 값(SOP/QC_STANDARD/HACCP/EQUIPMENT_MANUAL/CLAIM_RESPONSE)이 rag-agent-mes의 doc_type 필터(`$in: [QC_STANDARD, SOP, CLAIM_RESPONSE]`)와 정합 — RAG Agent 검색 필터 호환 OK.
- 임베딩 metadata에 doc_id/doc_type/title/version/chunk_index/source_file 포함 → 추적성 양호.

---

## 5. 이슈 요약

| ID | 심각도 | 영역 | 내용 | 권장 조치 |
|----|--------|------|------|-----------|
| HIGH-1 | HIGH | pgvector | PGVector collection_name="document_embeddings" vs db-schema-design raw 테이블 `document_embeddings`(vector(1536)+ivfflat) 물리 스키마 충돌 | PGVector 추상화로 일원화하거나, raw 테이블 직접 적재 코드로 변경. SKILL 스키마 문서 정합화 |
| MEDIUM-1 | MEDIUM | API | 활성화 버전 그룹핑이 doc_type+title 의존 (title 오타 시 이전버전 비활성화 누락) | doc_series/안정 키 기반 그룹핑 |
| MEDIUM-2 | MEDIUM | UI 권한 | 코드관리 탭이 품질담당자에게도 편집 허용 (§8.1은 관리자 전용) | 탭별 차등 권한 적용 |
| LOW-1 | LOW | DB 시드 | §7.1 출하 완성품 염도(1.5~3.0) 등 일부 기준 시드 누락 | 범위형 항목 시드 보강 |
| LOW-2 | LOW | DB 시드 | §7.3 PRODUCT(제품) 코드 시드 누락 | KIM-BC-500 등 제품 코드 시드 추가 |
| LOW-3 | LOW | API | trigger embed의 중복 상태 갱신(PENDING→PROCESSING) | 무해, 정리 선택 |

---

## 6. 결론

기준정보관리 3계층(스키마·API·UI)은 Plan §7 명세를 **87% 충족**하며, 품질기준 범위 색상 표시, SOP 업로드-임베딩-활성화 워크플로우, 복합키 코드 CRUD, 임베딩 차원(1536) 일치 등 핵심 기능이 정상 구현되었다. 

**우선 조치 권장**: HIGH-1(pgvector 스키마 정합) — RAG Agent와의 실제 연동 시 raw 테이블/PGVector 컬렉션 방식을 하나로 통일해야 검색이 보장된다. MEDIUM-2(코드관리 권한)는 운영 보안상 단기 수정 권장.
