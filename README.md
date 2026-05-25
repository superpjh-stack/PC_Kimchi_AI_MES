# 꽃순이김치 제조AI MES 시스템

평창꽃순이(주)농업회사법인 제조AI 스마트공장 MES

## 실행 방법

### 1. 패키지 설치
```bash
pip install -r requirements.txt
```

### 2. Streamlit 앱 실행
```bash
cd streamlit_app
streamlit run Home.py
```

또는 프로젝트 루트에서:
```bash
streamlit run streamlit_app/Home.py
```

### 3. 브라우저 접속
http://localhost:8501

### 테스트 계정
- 관리자: admin / admin123
- 생산담당: prod01 / prod123

## 메뉴 구조
- 🏠 홈 (로그인)
- 📊 AI 대시보드
- 🥬 원재료관리
- 🫙 숙성발효관리
- 📦 포장출하관리
- ⚙️ 공정관리
- 📁 데이터관리
- 📈 KPI관리
- 🔧 기준정보관리
- 👤 시스템관리
- 🤖 AI Agent 통합관리

## DB 초기화 (PostgreSQL)
```bash
psql -U postgres -d mes_db -f db/init.sql
```

## 기술 스택
- Frontend: Streamlit + Plotly
- Backend: FastAPI (추후 연결)
- DB: PostgreSQL + pgvector
- AI: XGBoost, LSTM, LangChain/LangGraph
