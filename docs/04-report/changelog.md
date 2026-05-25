# Changelog

꽃순이김치 제조AI 스마트공장 MES (SF26179540)

## [2026-05-24] - MES 풀스택 10개 모듈 개발 완료

### Added
- 10개 MES 모듈 풀스택 구현 (DB 스키마 + FastAPI 라우터 + Streamlit UI), 총 30개 파일 / 13,971줄
- Phase 1: 공정·데이터·KPI·기준정보·시스템관리 5개 모듈
- Phase 2: AI 대시보드·원재료관리·숙성발효관리·포장출하관리·AI Agent 통합관리 5개 모듈
- LOT 기반 추적성 체인 데이터 모델 (약 45개 테이블 + 4개 뷰)
- 약 130개 REST API 엔드포인트 (10개 라우터)
- ML(XGBoost/LSTM/SHAP), RAG Agent(LangChain/LangGraph) 통합 stub

### Changed
- DB 접근을 직접 asyncpg로 통일 (ORM 추상화 미사용)
- 대시보드를 st.fragment 기반 부분 자동갱신으로 전환
- API 반환 정책 RETURNING * 제거, 오류 코드 400/422/500 분리

### Fixed
- QA 이슈 총 30건 수정 (HIGH 5 / MEDIUM 10 / LOW 15)
- KPI 척도 불일치(10,250% 버그), supplier 테이블 중복 정의, /suppliers/ranking 라우트 순서 버그, LOT 접두사 형식 불일치(FERM- → FE-) 등
