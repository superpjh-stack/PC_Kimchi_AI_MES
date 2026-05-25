# =====================================================================
# 꽃순이김치 제조AI MES — FastAPI + Streamlit 공용 이미지
# 프로젝트: SF26179540 / 로뎀솔루션 주식회사
# docker-compose 의 api / ui 서비스가 동일 이미지를 공유하고
# command 로 실행 대상(uvicorn / streamlit)을 분기한다.
# =====================================================================
FROM python:3.11-slim

# 빌드 도구 (xgboost / prophet / asyncpg 빌드 의존성)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저 설치 (레이어 캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# 애플리케이션 소스 복사
COPY . .

# 컨테이너 기본 포트 (api: 8000 / ui: 8501)
EXPOSE 8000 8501

# 기본 실행 (compose 에서 command 로 오버라이드)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
