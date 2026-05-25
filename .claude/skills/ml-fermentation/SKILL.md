---
name: ml-fermentation
description: 꽃순이김치 발효 공정 ML 모델 개발 스킬. XGBoost 품질 분류, LSTM 발효 완료 시점 예측, Random Forest+SHAP 요인 분석, SVR 연속값 예측, Prophet 생산량 예측 개발 및 서빙 시 반드시 이 스킬을 사용하라. 트리거: ML 모델, 발효 예측, 품질 분류, LSTM, XGBoost, SHAP, 이상발효 탐지, Prophet, 모델 학습, 모델 서빙.
---

# 발효 공정 ML 개발 스킬

## AI 성능 목표

| 모델 | 지표 | 목표 |
|------|------|------|
| XGBoost (품질 분류) | 정확도 | ≥ 80% |
| XGBoost (품질 분류) | Recall (이상 클래스) | ≥ 85% |
| SVR (회귀) | R² | ≥ 0.85 |
| LSTM (완료 예측) | MAE | ≤ 2시간 |
| 이상발효 탐지 | 탐지 정확도 | ≥ 85% |

---

## 입력 피처 정의

```python
SALTING_FEATURES = ["temperature", "salinity", "ph_value", "duration_hours"]
FERMENTATION_FEATURES = ["temperature", "acidity", "ripeness_score"]
ENVIRONMENT_FEATURES = ["outdoor_temperature", "outdoor_humidity"]
RAW_MATERIAL_FEATURES = ["cabbage_size_enc", "weight_kg", "moisture_content",
                          "appearance_grade_enc", "origin_enc"]

ALL_FEATURES = SALTING_FEATURES + FERMENTATION_FEATURES + ENVIRONMENT_FEATURES + RAW_MATERIAL_FEATURES
TIMESERIES_FEATURES = FERMENTATION_FEATURES + ENVIRONMENT_FEATURES  # LSTM용
```

---

## 모델별 구현

### 1. XGBoost — 발효 품질 분류

```python
import xgboost as xgb
from sklearn.metrics import classification_report, recall_score

def build_quality_classifier():
    return xgb.XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.1,
        use_label_encoder=False,
        eval_metric='mlogloss',
        scale_pos_weight=3  # 이상/주의 클래스 불균형 보정
    )

def evaluate_classifier(model, X_test, y_test):
    y_pred = model.predict(X_test)
    print(classification_report(y_test, y_pred, target_names=['정상', '주의', '이상']))
    recall = recall_score(y_test, y_pred, average='weighted')
    assert recall >= 0.85, f"Recall {recall:.4f} < 목표 0.85"
    return recall
```

### 2. LSTM — 발효 완료 시점 예측

```python
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout
import numpy as np

WINDOW_SIZE = 24   # 24시간 슬라이딩 윈도우 (1시간 간격)
N_FEATURES = len(TIMESERIES_FEATURES)

def build_lstm_model():
    model = Sequential([
        LSTM(128, return_sequences=True, input_shape=(WINDOW_SIZE, N_FEATURES)),
        Dropout(0.2),
        LSTM(64),
        Dropout(0.2),
        Dense(32, activation='relu'),
        Dense(1)  # 잔여 발효 시간 (시간, 회귀)
    ])
    model.compile(optimizer='adam', loss='mae', metrics=['mae'])
    return model

def create_sliding_windows(df, lot_col='fermentation_lot_id'):
    X, y = [], []
    for lot_id, group in df.groupby(lot_col):
        group = group.sort_values('recorded_at')
        values = group[TIMESERIES_FEATURES].values
        remaining = group['remaining_hours'].values
        for i in range(len(values) - WINDOW_SIZE):
            X.append(values[i:i + WINDOW_SIZE])
            y.append(remaining[i + WINDOW_SIZE])
    return np.array(X), np.array(y)

def evaluate_lstm(model, X_test, y_test):
    from sklearn.metrics import mean_absolute_error
    y_pred = model.predict(X_test).flatten()
    mae = mean_absolute_error(y_test, y_pred)
    assert mae <= 2.0, f"MAE {mae:.2f}시간 > 목표 2시간"
    return mae
```

### 3. Random Forest + SHAP — 품질 요인 분석

```python
from sklearn.ensemble import RandomForestClassifier
import shap

def build_rf_model():
    return RandomForestClassifier(
        n_estimators=200,
        max_depth=10,
        class_weight='balanced',
        random_state=42
    )

def analyze_shap(model, X_train, X_test, feature_names):
    """작업자용 품질 영향 요인 리포트 생성"""
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_test)
    shap.summary_plot(shap_values, X_test, feature_names=feature_names,
                      class_names=['정상', '주의', '이상'], show=False)
    return explainer, shap_values
```

### 4. SVR — 산도/숙성도 연속값 예측

```python
from sklearn.svm import SVR
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import r2_score

def build_svr_model():
    return Pipeline([
        ('scaler', StandardScaler()),
        ('svr', SVR(kernel='rbf', C=10, epsilon=0.01))
    ])

def evaluate_svr(model, X_test, y_test):
    y_pred = model.predict(X_test)
    r2 = r2_score(y_test, y_pred)
    assert r2 >= 0.85, f"R² {r2:.4f} < 목표 0.85"
    return r2
```

### 5. Prophet — 생산량 트렌드 예측

```python
from prophet import Prophet

def build_production_forecast(df_daily):
    """df_daily: ds(날짜), y(kg/h) 컬럼"""
    model = Prophet(
        yearly_seasonality=True,
        weekly_seasonality=True,
        daily_seasonality=False,
        seasonality_mode='multiplicative'
    )
    model.fit(df_daily)
    future = model.make_future_dataframe(periods=30)
    return model, model.predict(future)
```

---

## 데이터 전처리 파이프라인

```python
import pandas as pd
from sklearn.preprocessing import MinMaxScaler, LabelEncoder

def preprocess(df):
    # 파생변수
    df['temp_change_rate'] = df.groupby('fermentation_lot_id')['temperature'].diff()
    df['ph_change_rate'] = df.groupby('fermentation_lot_id')['acidity'].diff()
    df['salinity_x_duration'] = df['salinity'] * df['duration_hours']

    # 결측값 — Forward Fill (lot 단위)
    df = df.groupby('fermentation_lot_id', group_keys=False).apply(lambda x: x.ffill())

    # 이상치 제거 — IQR
    for col in ['temperature', 'acidity', 'salinity']:
        Q1, Q3 = df[col].quantile([0.25, 0.75])
        IQR = Q3 - Q1
        df = df[(df[col] >= Q1 - 1.5 * IQR) & (df[col] <= Q3 + 1.5 * IQR)]

    # 스케일링 — Min-Max
    scaler = MinMaxScaler()
    numeric_cols = ['temperature', 'acidity', 'salinity', 'ripeness_score',
                    'outdoor_temperature', 'outdoor_humidity']
    df[numeric_cols] = scaler.fit_transform(df[numeric_cols])

    # 범주형 인코딩
    for col in ['appearance_grade', 'origin', 'cabbage_size']:
        le = LabelEncoder()
        df[f'{col}_enc'] = le.fit_transform(df[col].astype(str))

    return df, scaler
```

---

## FastAPI 서빙 엔드포인트

```python
# app/routers/ai_prediction.py
from fastapi import APIRouter
from pydantic import BaseModel
import joblib, numpy as np

router = APIRouter(prefix="/api/v1/ai", tags=["AI Prediction"])

class QualityInput(BaseModel):
    fermentation_lot_id: str
    temperature: float; acidity: float; salinity: float
    ripeness_score: float; outdoor_temperature: float; outdoor_humidity: float

@router.post("/quality-prediction")
async def predict_quality(data: QualityInput):
    model = joblib.load("models/xgboost_quality.pkl")
    features = [[data.temperature, data.acidity, data.salinity,
                 data.ripeness_score, data.outdoor_temperature, data.outdoor_humidity]]
    pred = model.predict(features)[0]
    prob = model.predict_proba(features)[0]
    quality_map = {0: "정상", 1: "주의", 2: "이상"}
    return {
        "lot_id": data.fermentation_lot_id,
        "quality_status": quality_map[pred],
        "confidence": float(max(prob)),
        "probabilities": {quality_map[i]: float(p) for i, p in enumerate(prob)}
    }

@router.get("/completion-prediction/{lot_id}")
async def predict_completion(lot_id: str):
    """LSTM 발효 완료 시점 예측 — DB에서 최근 24시간 데이터 조회 후 예측"""
    # DB 조회 → 슬라이딩 윈도우 변환 → LSTM 예측 → 반환
    ...
```

---

## 모델 파일 구조

```
models/
├── xgboost_quality.pkl       -- 품질 분류 (XGBoost)
├── rf_feature_importance.pkl -- 요인 분석 (Random Forest)
├── svr_acidity.pkl           -- 산도 예측 (SVR)
├── svr_ripeness.pkl          -- 숙성도 예측 (SVR)
├── lstm_completion.h5        -- 발효 완료 예측 (LSTM)
├── scaler.pkl                -- 데이터 스케일러
└── training_metadata.json    -- 학습 기간, 성능 지표, 모델 버전
```
