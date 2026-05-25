"""
꽃순이김치 제조AI MES — 발효 모델 실시간 추론 서비스
프로젝트: SF26179540 / 로뎀솔루션
스킬: ml-fermentation

저장된 모델(ml/models/*) 로드 → 실시간 추론 →
api_fermentation_router.py 의 엔드포인트로 결과 전송:
  POST /api/v1/fermentation/predictions   (XGBoost/SVR/LSTM 예측 결과)
  POST /api/v1/fermentation/anomalies     (이상발효 알림)

작업 원칙(CLAUDE.md §개발 원칙):
  - AI는 의사결정 지원(조회·분석·추천·경고)이며 직접 공정 제어를 하지 않는다.
  - 파일럿 단계에서 예측 결과는 작업자 승인 게이트를 거친다(approval_required 플래그).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from data_preprocessing import (
    DataPreprocessor,
    FeatureEngineer,
    SlidingWindowBuilder,
    TIMESERIES_FEATURES,
    aggregate_lot_features,
    quality_label_decode,
)
from fermentation_model import (
    AnomalyDetector,
    LSTMFermentationPredictor,
    RandomForestAnalyzer,
    SHAPExplainer,
    SVRQualityRegressor,
    XGBoostQualityClassifier,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ml.inference")

ML_ROOT = Path(__file__).resolve().parent
MODELS_DIR = ML_ROOT / "models"

QUALITY_CODE_TO_CLASS = {0: "NORMAL", 1: "CAUTION", 2: "ABNORMAL"}
BATCH_INTERVAL_SEC = 15 * 60   # 15분마다 배치 추론


class FermentationInferenceService:
    """모델 로드 + 실시간 예측 + MES API 적재 통합 서비스."""

    def __init__(self, db_dsn: str | None = None,
                 api_base: str = "http://localhost:8000",
                 model_version: str = "1.0.0",
                 approval_required: bool = True):
        self.db_dsn = db_dsn
        self.api_base = api_base.rstrip("/")
        self.model_version = model_version
        self.approval_required = approval_required   # 파일럿: 작업자 승인 게이트

        self.engineer = FeatureEngineer()
        self.preprocessor = DataPreprocessor()
        self.xgb: XGBoostQualityClassifier | None = None
        self.rf: RandomForestAnalyzer | None = None
        self.svr: SVRQualityRegressor | None = None
        self.lstm: LSTMFermentationPredictor | None = None
        self.anomaly: AnomalyDetector | None = None
        self.shap = SHAPExplainer()
        self._loaded = False

    # ------------------------------------------------------------------
    def load_models(self) -> None:
        """ml/models/ 에서 학습된 모델을 로드한다. 일부 누락은 경고 후 진행."""
        def _try(name, fn):
            try:
                m = fn()
                logger.info("모델 로드: %s", name)
                return m
            except Exception as exc:  # pragma: no cover
                logger.warning("모델 로드 실패(%s): %s", name, exc)
                return None

        self.xgb = _try("XGBoost", XGBoostQualityClassifier.load)
        self.rf = _try("RandomForest", RandomForestAnalyzer.load)
        self.svr = _try("SVR", SVRQualityRegressor.load)
        self.anomaly = _try("AnomalyDetector", AnomalyDetector.load)
        self.lstm = _try("LSTM", LSTMFermentationPredictor.load)
        if self.xgb is not None:
            self.shap.feature_names = self.xgb.feature_names
        # 스케일러/인코더 복원 (전처리 일관성)
        scaler_path = MODELS_DIR / "preprocess_state.pkl"
        if scaler_path.exists():
            import joblib
            state = joblib.load(scaler_path)
            self.engineer = state.get("engineer", self.engineer)
            self.preprocessor = state.get("preprocessor", self.preprocessor)
            logger.info("전처리 상태(scaler/encoder) 복원")
        self._loaded = True
        logger.info("모델 로드 완료 (version=%s)", self.model_version)

    # ------------------------------------------------------------------
    async def _fetch_recent_window(self, lot_id: str, hours: int = 24
                                   ) -> pd.DataFrame:
        """DB에서 특정 LOT의 최근 N시간 센서+공정+원재료 조인 데이터를 로드."""
        import asyncpg
        query = """
            SELECT ts.fermentation_lot_id AS lot_id, ts.recorded_at,
                   ts.temperature, ts.acidity, ts.salt_density AS salinity,
                   ts.humidity AS outdoor_humidity,
                   fp.start_time AS ferment_start, fp.actual_end_time AS ferment_end,
                   fp.ferment_hours, fp.ambient_temp AS outdoor_temperature,
                   fp.ml_quality_pred AS quality_label_raw, fp.is_abnormal,
                   sp.salt_temp, sp.salt_density AS salt_salinity, sp.salt_ph,
                   sp.salt_hours, sp.dehydration_rate,
                   rmi.weight_kg, rmi.cabbage_size, rmi.appearance_grade,
                   rmi.moisture_rate AS moisture_content, rmi.origin
            FROM fermentation_timeseries ts
            JOIN fermentation_process fp ON fp.fermentation_lot_id = ts.fermentation_lot_id
            LEFT JOIN salting_process sp ON sp.salting_lot_id = fp.salting_lot_id
            LEFT JOIN raw_material_intake rmi ON rmi.intake_lot_id = sp.intake_lot_id
            WHERE ts.fermentation_lot_id = $1
              AND ts.recorded_at >= NOW() - ($2 || ' hours')::INTERVAL
            ORDER BY ts.recorded_at
        """
        conn = await asyncpg.connect(self.db_dsn)
        try:
            rows = await conn.fetch(query, lot_id, str(hours))
        finally:
            await conn.close()
        return pd.DataFrame([dict(r) for r in rows])

    # ------------------------------------------------------------------
    def _preprocess(self, df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
        """추론용 전처리 — 학습된 인코더/스케일러로 transform(fit=False)."""
        df_feat = self.engineer.transform(df, fit=False)
        df_proc = self.preprocessor.run(df_feat, fit=False)
        tabular = aggregate_lot_features(df_proc)
        # 모델 입력 피처 정렬
        feat_names = (self.xgb.feature_names if self.xgb and self.xgb.feature_names
                      else [c for c in tabular.columns if c not in
                            ("lot_id", "quality_label_raw", "is_abnormal",
                             "target_acidity", "target_ripeness")])
        for c in feat_names:
            if c not in tabular.columns:
                tabular[c] = 0.0
        X = tabular[feat_names].to_numpy(dtype=np.float32)
        return df_proc, X

    # ------------------------------------------------------------------
    async def predict_lot_quality(self, lot_id: str) -> dict:
        """LOT 품질 종합 예측 → POST /predictions 로 모델별 결과 적재.

        절차:
          1. 최근 24h 센서 데이터 로드
          2. 전처리 (인코딩/스케일링/슬라이딩 윈도우)
          3. XGBoost → quality_class, quality_score
          4. SVR → predicted_acidity, predicted_ripeness
          5. LSTM → predicted_completion_time
          6. SHAP → shap_features
          7. 각 모델 결과를 POST /api/v1/fermentation/predictions 로 저장
        """
        if not self._loaded:
            self.load_models()

        df = await self._fetch_recent_window(lot_id, hours=24)
        if df.empty:
            logger.warning("LOT %s 최근 센서 데이터 없음 — 예측 건너뜀", lot_id)
            return {"lot_id": lot_id, "status": "no_data"}

        df_proc, X = self._preprocess(df)
        result: dict = {"lot_id": lot_id, "model_version": self.model_version,
                        "approval_required": self.approval_required, "models": {}}

        # --- XGBoost 품질 분류 ---
        if self.xgb is not None:
            proba = self.xgb.predict_proba(X)[-1]
            code = int(np.argmax(proba))
            q_class = QUALITY_CODE_TO_CLASS[code]
            q_score = float(proba[code])
            shap_out = self.shap.explain(self.xgb, X)
            result["models"]["XGBOOST"] = {
                "quality_class": q_class, "quality_score": round(q_score, 4),
                "probabilities": {QUALITY_CODE_TO_CLASS[i]: round(float(p), 4)
                                  for i, p in enumerate(proba)},
                "shap_features": shap_out["top_features"],
            }
            await self._post_prediction({
                "lot_id": lot_id, "model_type": "XGBOOST",
                "quality_class": q_class, "quality_score": round(q_score, 4),
                "shap_features": shap_out["top_features"],
                "model_version": self.model_version,
            })

        # --- SVR 회귀 (산도/숙성도) ---
        if self.svr is not None:
            pred = self.svr.predict(X)
            acidity = float(pred["acidity"][-1])
            ripeness = float(pred["ripeness"][-1])
            result["models"]["SVR"] = {
                "predicted_acidity": round(acidity, 3),
                "predicted_ripeness": round(ripeness, 3),
            }
            await self._post_prediction({
                "lot_id": lot_id, "model_type": "SVR",
                "predicted_acidity": round(acidity, 3),
                "predicted_ripeness": round(ripeness, 3),
                "model_version": self.model_version,
            })

        # --- LSTM 발효 완료 시점 ---
        if self.lstm is not None:
            swb = SlidingWindowBuilder(window_size=self.lstm.window_size)
            X_seq, _ = swb.build(df_proc)
            if len(X_seq):
                remaining_h = self.lstm.predict_completion_time(X_seq)
                completion = datetime.now(timezone.utc) + timedelta(hours=remaining_h)
                result["models"]["LSTM"] = {
                    "remaining_hours": round(remaining_h, 2),
                    "predicted_completion_time": completion.isoformat(),
                }
                await self._post_prediction({
                    "lot_id": lot_id, "model_type": "LSTM",
                    "predicted_completion_time": completion.isoformat(),
                    "model_version": self.model_version,
                })

        logger.info("LOT %s 예측 완료: %s", lot_id, list(result["models"].keys()))
        return result

    # ------------------------------------------------------------------
    async def detect_anomaly(self, lot_id: str) -> dict | None:
        """이상발효 감지 → 감지 시 POST /anomalies 로 알림 등록."""
        if not self._loaded:
            self.load_models()
        if self.anomaly is None:
            return None

        df = await self._fetch_recent_window(lot_id, hours=24)
        if df.empty:
            return None

        _, X = self._preprocess(df)
        is_anom, conf, reason = self.anomaly.detect(X[-1])
        if not is_anom:
            return None

        # 임계 기반 알림 유형/심각도 판정 (원시 센서값 기준)
        last = df.sort_values("recorded_at").iloc[-1]
        temp = float(last.get("temperature", 0))
        acidity = float(last.get("acidity", 0))
        if temp >= 25.0:
            alert_type, severity = "TEMP_HIGH", "CRITICAL"
            sensor_val, thr = temp, 25.0
            msg = f"발효실 온도 {temp:.1f}℃ 위험 임계 초과 — 이상발효 위험({reason})"
        elif acidity >= 0.9:
            alert_type, severity = "ACIDITY_DRIFT", "CRITICAL"
            sensor_val, thr = acidity, 0.9
            msg = f"산도 {acidity:.2f}% 급상승 — 과발효 진행 추정({reason})"
        elif temp >= 20.0:
            alert_type, severity = "TEMP_HIGH", "WARNING"
            sensor_val, thr = temp, 20.0
            msg = f"발효실 온도 {temp:.1f}℃ 주의 임계 초과({reason})"
        else:
            alert_type, severity = "ACIDITY_DRIFT", "WARNING"
            sensor_val, thr = acidity, None
            msg = f"이상발효 패턴 탐지 (신뢰도 {conf:.2f}, {reason})"

        payload = {
            "lot_id": lot_id, "alert_type": alert_type, "severity": severity,
            "sensor_value": round(sensor_val, 3) if sensor_val is not None else None,
            "threshold_value": thr, "message": msg,
        }
        await self._post_anomaly(payload)
        logger.warning("이상발효 감지 LOT %s | %s (%s, conf=%.2f)",
                       lot_id, alert_type, severity, conf)
        return {**payload, "confidence": conf, "approval_required": self.approval_required}

    # ------------------------------------------------------------------
    async def _post_prediction(self, payload: dict) -> None:
        """POST /api/v1/fermentation/predictions"""
        await self._post("/api/v1/fermentation/predictions", payload)

    async def _post_anomaly(self, payload: dict) -> None:
        """POST /api/v1/fermentation/anomalies"""
        await self._post("/api/v1/fermentation/anomalies", payload)

    async def _post(self, path: str, payload: dict) -> None:
        url = f"{self.api_base}{path}"
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code >= 400:
                    logger.error("POST %s 실패 [%d]: %s", path, resp.status_code, resp.text)
                else:
                    logger.info("POST %s 성공 [%d]", path, resp.status_code)
        except ImportError:
            logger.info("httpx 미설치 — DRY-RUN: POST %s payload=%s", url, payload)
        except Exception as exc:  # pragma: no cover
            logger.error("POST %s 예외: %s", path, exc)

    # ------------------------------------------------------------------
    async def _list_fermenting_lots(self) -> list[str]:
        """현재 발효중(FERMENTING) LOT ID 목록."""
        import asyncpg
        conn = await asyncpg.connect(self.db_dsn)
        try:
            rows = await conn.fetch(
                "SELECT fermentation_lot_id FROM fermentation_process "
                "WHERE actual_end_time IS NULL"
            )
        finally:
            await conn.close()
        return [r["fermentation_lot_id"] for r in rows]

    # ------------------------------------------------------------------
    async def run_batch_inference(self) -> None:
        """발효중 모든 LOT에 대해 BATCH_INTERVAL_SEC(15분)마다 배치 추론."""
        if not self._loaded:
            self.load_models()
        logger.info("배치 추론 루프 시작 (주기 %d초)", BATCH_INTERVAL_SEC)
        while True:
            try:
                lots = await self._list_fermenting_lots()
                logger.info("배치 추론 대상 LOT %d건", len(lots))
                for lot_id in lots:
                    await self.predict_lot_quality(lot_id)
                    await self.detect_anomaly(lot_id)
            except Exception as exc:  # pragma: no cover
                logger.error("배치 추론 오류: %s", exc)
            await asyncio.sleep(BATCH_INTERVAL_SEC)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import os

    dsn = os.getenv("MES_DB_DSN")
    api = os.getenv("MES_API_BASE", "http://localhost:8000")
    svc = FermentationInferenceService(db_dsn=dsn, api_base=api)
    svc.load_models()
    if dsn:
        asyncio.run(svc.run_batch_inference())
    else:
        logger.info("MES_DB_DSN 미설정 — 모델 로드만 수행하고 종료")
