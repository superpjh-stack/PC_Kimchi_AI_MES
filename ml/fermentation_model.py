"""
꽃순이김치 제조AI MES — 발효 품질 예측 모델 앙상블
프로젝트: SF26179540 / 로뎀솔루션
스킬: ml-fermentation

모델 구성:
  - XGBoost            : 품질 분류 (NORMAL/CAUTION/ABNORMAL)  — 정확도 ≥80%, Recall ≥85%
  - Random Forest      : 특징 중요도 분석 (SHAP 연계)           — 설명력 확보
  - SVR                : 산도·숙성도 회귀 예측                  — R² ≥0.85
  - LSTM               : 시계열 발효 완료 시점(잔여시간) 예측    — MAE ≤2h
  - SHAPExplainer      : XGBoost + RF SHAP 영향 요인 분석
  - AnomalyDetector    : 이상발효 조기탐지 (IsolationForest + XGBoost) — 정확도 ≥85%
  - Ensemble           : XGBoost + RF 소프트 보팅

클래스 불균형(이상 샘플 희소) 대응:
  - XGBoost: scale_pos_weight
  - RandomForest: class_weight='balanced'
  - SMOTE(가용 시): 학습 데이터 오버샘플링

모델 산출물 (ml/models/):
  xgboost_quality.pkl, rf_feature_importance.pkl,
  svr_acidity.pkl, svr_ripeness.pkl, lstm_completion.h5,
  isolation_forest.pkl, scaler.pkl, training_metadata.json
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
)
from sklearn.svm import SVR

import xgboost as xgb

from data_preprocessing import (
    QUALITY_LABEL_INV,
    QUALITY_LABEL_MAP,
    quality_label_encode,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ml.model")

ML_ROOT = Path(__file__).resolve().parent
MODELS_DIR = ML_ROOT / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

CLASS_NAMES = ["정상", "주의", "이상"]   # NORMAL / CAUTION / ABNORMAL

# AI 성능 목표 (CLAUDE.md §AI 모듈)
TARGETS = {
    "quality_accuracy": 0.80,
    "risk_recall": 0.85,
    "r2": 0.85,
    "completion_mae_hours": 2.0,
    "anomaly_accuracy": 0.85,
}


# ===========================================================================
# 1. XGBoost — 발효 품질 분류
# ===========================================================================
class XGBoostQualityClassifier:
    """품질 분류 (NORMAL/CAUTION/ABNORMAL). 목표 정확도 ≥80%, Recall ≥85%."""

    def __init__(self):
        self.model = xgb.XGBClassifier(
            objective="multi:softprob",
            num_class=3,
            n_estimators=300,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=2,
            reg_lambda=1.0,
            eval_metric=["mlogloss", "merror"],
            early_stopping_rounds=20,
            random_state=42,
            n_jobs=-1,
        )
        self.feature_names: list[str] | None = None

    def _sample_weight(self, y: np.ndarray) -> np.ndarray:
        """클래스 불균형 보정 — 빈도 역수 기반 (scale_pos_weight 효과)."""
        classes, counts = np.unique(y, return_counts=True)
        freq = dict(zip(classes, counts))
        total = len(y)
        # 이상(2)/주의(1) 클래스에 추가 가중
        boost = {0: 1.0, 1: 2.0, 2: 3.0}
        return np.array([
            (total / (len(classes) * freq[c])) * boost.get(int(c), 1.0) for c in y
        ])

    def train(self, X_train, y_train, X_val, y_val,
              feature_names: list[str] | None = None):
        self.feature_names = feature_names
        sw = self._sample_weight(np.asarray(y_train))
        self.model.fit(
            X_train, y_train,
            sample_weight=sw,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )
        logger.info("XGBoost 학습 완료 (best_iteration=%s)",
                    getattr(self.model, "best_iteration", "n/a"))
        return self

    def predict(self, X) -> np.ndarray:
        return self.model.predict(X)

    def predict_proba(self, X) -> np.ndarray:
        """클래스별 확률 반환 (N, 3)."""
        return self.model.predict_proba(X)

    def evaluate(self, X_test, y_test) -> dict:
        y_pred = self.predict(X_test)
        acc = accuracy_score(y_test, y_pred)
        # 이상(ABNORMAL=2) 클래스 재현율 — 품질 리스크 재현율
        rec_abnormal = recall_score(y_test, y_pred, labels=[2], average="macro",
                                    zero_division=0)
        rec_weighted = recall_score(y_test, y_pred, average="weighted", zero_division=0)
        prec = precision_score(y_test, y_pred, average="weighted", zero_division=0)
        f1 = f1_score(y_test, y_pred, average="weighted", zero_division=0)
        cm = confusion_matrix(y_test, y_pred, labels=[0, 1, 2])
        result = {
            "accuracy": round(float(acc), 4),
            "recall_weighted": round(float(rec_weighted), 4),
            "recall_abnormal": round(float(rec_abnormal), 4),
            "precision": round(float(prec), 4),
            "f1": round(float(f1), 4),
            "confusion_matrix": cm.tolist(),
            "target_accuracy_met": bool(acc >= TARGETS["quality_accuracy"]),
            "target_recall_met": bool(rec_weighted >= TARGETS["risk_recall"]),
        }
        logger.info("XGBoost 평가 | acc=%.4f recall(가중)=%.4f recall(이상)=%.4f",
                    acc, rec_weighted, rec_abnormal)
        return result

    def save(self, path: Path | None = None) -> Path:
        path = path or MODELS_DIR / "xgboost_quality.pkl"
        joblib.dump({"model": self.model, "feature_names": self.feature_names}, path)
        logger.info("저장: %s", path)
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "XGBoostQualityClassifier":
        path = path or MODELS_DIR / "xgboost_quality.pkl"
        obj = cls()
        blob = joblib.load(path)
        obj.model = blob["model"]
        obj.feature_names = blob.get("feature_names")
        return obj


# ===========================================================================
# 2. Random Forest — 특징 중요도 / SHAP 연계
# ===========================================================================
class RandomForestAnalyzer:
    """품질 분류 + 특징 중요도 분석 (SHAP 연계용)."""

    def __init__(self):
        self.model = RandomForestClassifier(
            n_estimators=300,
            max_depth=12,
            min_samples_leaf=3,
            class_weight="balanced",   # 불균형 보정
            random_state=42,
            n_jobs=-1,
        )
        self.feature_names: list[str] | None = None

    def train(self, X_train, y_train, feature_names: list[str] | None = None):
        self.feature_names = feature_names
        self.model.fit(X_train, y_train)
        logger.info("RandomForest 학습 완료 (트리 %d개)", self.model.n_estimators)
        return self

    def predict_proba(self, X) -> np.ndarray:
        return self.model.predict_proba(X)

    def feature_importance(self) -> dict[str, float]:
        names = self.feature_names or [
            f"f{i}" for i in range(len(self.model.feature_importances_))
        ]
        imp = dict(zip(names, self.model.feature_importances_.astype(float)))
        return dict(sorted(imp.items(), key=lambda kv: kv[1], reverse=True))

    def evaluate(self, X_test, y_test) -> dict:
        y_pred = self.model.predict(X_test)
        return {
            "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
            "recall_weighted": round(
                float(recall_score(y_test, y_pred, average="weighted", zero_division=0)), 4),
            "top_features": dict(list(self.feature_importance().items())[:5]),
        }

    def save(self, path: Path | None = None) -> Path:
        path = path or MODELS_DIR / "rf_feature_importance.pkl"
        joblib.dump({"model": self.model, "feature_names": self.feature_names}, path)
        logger.info("저장: %s", path)
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "RandomForestAnalyzer":
        path = path or MODELS_DIR / "rf_feature_importance.pkl"
        obj = cls()
        blob = joblib.load(path)
        obj.model = blob["model"]
        obj.feature_names = blob.get("feature_names")
        return obj


# ===========================================================================
# 3. SVR — 산도/숙성도 연속값 예측
# ===========================================================================
class SVRQualityRegressor:
    """연속값 예측: 산도(acidity), 숙성도(ripeness). 목표 R² ≥0.85."""

    def __init__(self):
        self.acidity_model = SVR(kernel="rbf", C=100, gamma=0.01, epsilon=0.05)
        self.ripeness_model = SVR(kernel="rbf", C=100, gamma=0.01, epsilon=0.05)

    def train(self, X_train, y_acidity, y_ripeness):
        self.acidity_model.fit(X_train, y_acidity)
        self.ripeness_model.fit(X_train, y_ripeness)
        logger.info("SVR 학습 완료 (acidity / ripeness)")
        return self

    def predict(self, X) -> dict[str, np.ndarray]:
        return {
            "acidity": self.acidity_model.predict(X),
            "ripeness": self.ripeness_model.predict(X),
        }

    @staticmethod
    def _metrics(y_true, y_pred) -> dict:
        return {
            "r2": round(float(r2_score(y_true, y_pred)), 4),
            "mae": round(float(mean_absolute_error(y_true, y_pred)), 4),
            "rmse": round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 4),
        }

    def evaluate(self, X_test, y_acidity, y_ripeness) -> dict:
        pred = self.predict(X_test)
        m_ac = self._metrics(y_acidity, pred["acidity"])
        m_rp = self._metrics(y_ripeness, pred["ripeness"])
        result = {
            "acidity": m_ac,
            "ripeness": m_rp,
            "target_r2_met": bool(m_ac["r2"] >= TARGETS["r2"]
                                  and m_rp["r2"] >= TARGETS["r2"]),
        }
        logger.info("SVR 평가 | acidity R²=%.4f / ripeness R²=%.4f",
                    m_ac["r2"], m_rp["r2"])
        return result

    def save(self, dir_path: Path | None = None) -> tuple[Path, Path]:
        dir_path = dir_path or MODELS_DIR
        p1 = dir_path / "svr_acidity.pkl"
        p2 = dir_path / "svr_ripeness.pkl"
        joblib.dump(self.acidity_model, p1)
        joblib.dump(self.ripeness_model, p2)
        logger.info("저장: %s, %s", p1, p2)
        return p1, p2

    @classmethod
    def load(cls, dir_path: Path | None = None) -> "SVRQualityRegressor":
        dir_path = dir_path or MODELS_DIR
        obj = cls()
        obj.acidity_model = joblib.load(dir_path / "svr_acidity.pkl")
        obj.ripeness_model = joblib.load(dir_path / "svr_ripeness.pkl")
        return obj


# ===========================================================================
# 4. LSTM — 발효 완료 시점(잔여시간) 예측
# ===========================================================================
class LSTMFermentationPredictor:
    """시계열 → 잔여 발효 시간(시간) 회귀. 목표 MAE ≤2h."""

    def __init__(self, window_size: int = 24, n_features: int = 8):
        self.window_size = window_size
        self.n_features = n_features
        self.model = None
        self._build()

    def _build(self):
        try:
            import tensorflow as tf
            from tensorflow.keras.layers import LSTM, Dense, Dropout
            from tensorflow.keras.models import Sequential
        except ImportError as exc:  # pragma: no cover
            logger.warning("TensorFlow 미설치 — LSTM 비활성화: %s", exc)
            self.model = None
            return
        tf.random.set_seed(42)
        model = Sequential([
            LSTM(128, return_sequences=True,
                 input_shape=(self.window_size, self.n_features)),
            Dropout(0.2),
            LSTM(64),
            Dropout(0.2),
            Dense(32, activation="relu"),
            Dense(1),   # 잔여 발효 시간 (회귀)
        ])
        model.compile(optimizer="adam", loss="mae", metrics=["mae"])
        self.model = model

    def train(self, X_seq, y_hours, X_val=None, y_val=None,
              epochs: int = 60, batch_size: int = 64):
        if self.model is None:
            raise RuntimeError("TensorFlow 미설치로 LSTM 학습 불가")
        from tensorflow.keras.callbacks import EarlyStopping

        val_data = (X_val, y_val) if X_val is not None else None
        cb = [EarlyStopping(monitor="val_mae" if val_data else "mae",
                            patience=8, restore_best_weights=True)]
        history = self.model.fit(
            X_seq, y_hours,
            validation_data=val_data,
            epochs=epochs, batch_size=batch_size,
            callbacks=cb, verbose=0,
        )
        logger.info("LSTM 학습 완료 (epochs=%d, 최종 loss=%.4f)",
                    len(history.history["loss"]), history.history["loss"][-1])
        return self

    def predict(self, X_seq) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("LSTM 모델 없음")
        return self.model.predict(X_seq, verbose=0).flatten()

    def predict_completion_time(self, X_seq) -> float:
        """마지막 윈도우의 잔여시간 예측값(시간) 반환."""
        preds = self.predict(X_seq)
        return float(preds[-1]) if len(preds) else float("nan")

    def evaluate(self, X_test, y_test) -> dict:
        y_pred = self.predict(X_test)
        mae = mean_absolute_error(y_test, y_pred)
        rmse = np.sqrt(mean_squared_error(y_test, y_pred))
        result = {
            "mae_hours": round(float(mae), 3),
            "rmse_hours": round(float(rmse), 3),
            "target_mae_met": bool(mae <= TARGETS["completion_mae_hours"]),
        }
        logger.info("LSTM 평가 | MAE=%.3fh (목표 ≤%.1fh)",
                    mae, TARGETS["completion_mae_hours"])
        return result

    def save(self, path: Path | None = None) -> Path:
        path = path or MODELS_DIR / "lstm_completion.h5"
        if self.model is not None:
            self.model.save(path)
            logger.info("저장: %s", path)
        return path

    @classmethod
    def load(cls, path: Path | None = None, window_size: int = 24,
             n_features: int = 8) -> "LSTMFermentationPredictor":
        path = path or MODELS_DIR / "lstm_completion.h5"
        obj = cls.__new__(cls)
        obj.window_size = window_size
        obj.n_features = n_features
        import tensorflow as tf
        obj.model = tf.keras.models.load_model(path)
        return obj


# ===========================================================================
# 5. SHAP Explainer — XGBoost + RF 영향 요인 분석
# ===========================================================================
class SHAPExplainer:
    """트리 모델 SHAP 분석 — 작업자용 품질 영향 요인 리포트."""

    def __init__(self, feature_names: list[str] | None = None):
        self.feature_names = feature_names

    def explain(self, model, X, top_k: int = 5) -> dict:
        """shap.TreeExplainer → 상위 k개 평균 |SHAP| 기여도 반환.

        SHAP 미설치 또는 실패 시 트리 feature_importances_ 로 폴백한다.
        """
        names = self.feature_names or [f"f{i}" for i in range(np.asarray(X).shape[1])]
        try:
            import shap
            inner = getattr(model, "model", model)
            explainer = shap.TreeExplainer(inner)
            shap_values = explainer.shap_values(X)
            # 다중클래스: list[array] → 클래스 평균
            if isinstance(shap_values, list):
                arr = np.mean([np.abs(sv) for sv in shap_values], axis=0)
            else:
                arr = np.abs(shap_values)
                if arr.ndim == 3:    # (N, F, C)
                    arr = arr.mean(axis=2)
            mean_abs = arr.mean(axis=0)
            total = mean_abs.sum() or 1.0
            contrib = {n: float(v / total) for n, v in zip(names, mean_abs)}
            method = "shap"
        except Exception as exc:  # pragma: no cover
            logger.warning("SHAP 실패 → feature_importances_ 폴백: %s", exc)
            inner = getattr(model, "model", model)
            imp = getattr(inner, "feature_importances_", None)
            if imp is None:
                return {"method": "none", "top_features": {}}
            total = float(imp.sum()) or 1.0
            contrib = {n: float(v / total) for n, v in zip(names, imp)}
            method = "feature_importance"

        ranked = dict(sorted(contrib.items(), key=lambda kv: kv[1], reverse=True)[:top_k])
        ranked = {k: round(v, 4) for k, v in ranked.items()}
        logger.info("SHAP 분석(%s) 상위 요인: %s", method, list(ranked.keys()))
        return {"method": method, "top_features": ranked}

    def report(self, model, X, lot_id: str | None = None) -> dict:
        """API/리포트용 SHAP 결과 (POST /predictions shap_features 형식)."""
        out = self.explain(model, X)
        return {
            "lot_id": lot_id,
            "shap_features": out["top_features"],
            "method": out["method"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


# ===========================================================================
# 6. AnomalyDetector — 이상발효 조기탐지
# ===========================================================================
class AnomalyDetector:
    """IsolationForest(비지도) + XGBoost(지도) 앙상블. 목표 정확도 ≥85%."""

    def __init__(self, contamination: float = 0.1):
        self.iso = IsolationForest(
            n_estimators=200, contamination=contamination, random_state=42, n_jobs=-1,
        )
        self.clf = xgb.XGBClassifier(
            n_estimators=200, max_depth=5, learning_rate=0.05,
            scale_pos_weight=4,   # 이상 샘플 희소 → 가중
            eval_metric="logloss", random_state=42, n_jobs=-1,
        )
        self._clf_fitted = False

    def fit(self, X_train, y_abnormal=None):
        """X_train: tabular 피처. y_abnormal: 0/1 (있으면 지도 학습 추가)."""
        self.iso.fit(X_train)
        if y_abnormal is not None and len(np.unique(y_abnormal)) > 1:
            self.clf.fit(X_train, y_abnormal)
            self._clf_fitted = True
        logger.info("AnomalyDetector 학습 완료 (지도=%s)", self._clf_fitted)
        return self

    def detect(self, sensor_window) -> tuple[bool, float, str]:
        """(is_anomaly, confidence, reason) 반환.

        sensor_window: tabular 1행(또는 N행) 피처 배열.
        """
        X = np.atleast_2d(sensor_window)
        iso_pred = self.iso.predict(X)          # -1 이상, 1 정상
        iso_score = -self.iso.score_samples(X)  # 높을수록 이상
        is_iso_anom = (iso_pred == -1)

        if self._clf_fitted:
            proba = self.clf.predict_proba(X)[:, 1]
            ensemble = 0.5 * proba + 0.5 * _minmax(iso_score)
        else:
            ensemble = _minmax(iso_score)

        conf = float(ensemble[-1])
        is_anom = bool(is_iso_anom[-1] or conf >= 0.6)
        reason = ("지도+비지도 앙상블 이상 신호" if self._clf_fitted
                  else "IsolationForest 이상 패턴")
        return is_anom, round(conf, 4), reason

    def evaluate(self, X_test, y_abnormal) -> dict:
        flags = []
        for i in range(len(X_test)):
            is_anom, _, _ = self.detect(np.asarray(X_test)[i])
            flags.append(int(is_anom))
        acc = accuracy_score(y_abnormal, flags)
        rec = recall_score(y_abnormal, flags, zero_division=0)
        logger.info("AnomalyDetector 평가 | acc=%.4f recall=%.4f", acc, rec)
        return {
            "accuracy": round(float(acc), 4),
            "recall": round(float(rec), 4),
            "target_accuracy_met": bool(acc >= TARGETS["anomaly_accuracy"]),
        }

    def save(self, path: Path | None = None) -> Path:
        path = path or MODELS_DIR / "isolation_forest.pkl"
        joblib.dump({"iso": self.iso, "clf": self.clf if self._clf_fitted else None,
                     "clf_fitted": self._clf_fitted}, path)
        logger.info("저장: %s", path)
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "AnomalyDetector":
        path = path or MODELS_DIR / "isolation_forest.pkl"
        obj = cls()
        blob = joblib.load(path)
        obj.iso = blob["iso"]
        obj._clf_fitted = blob.get("clf_fitted", False)
        if obj._clf_fitted and blob.get("clf") is not None:
            obj.clf = blob["clf"]
        return obj


# ===========================================================================
# 7. Ensemble — XGBoost + RF 소프트 보팅
# ===========================================================================
class QualityEnsemble:
    """XGBoost + RandomForest 소프트 보팅 (가중 평균 확률)."""

    def __init__(self, xgb_model: XGBoostQualityClassifier,
                 rf_model: RandomForestAnalyzer,
                 w_xgb: float = 0.6, w_rf: float = 0.4):
        self.xgb = xgb_model
        self.rf = rf_model
        self.w_xgb = w_xgb
        self.w_rf = w_rf

    def predict_proba(self, X) -> np.ndarray:
        return self.w_xgb * self.xgb.predict_proba(X) + self.w_rf * self.rf.predict_proba(X)

    def predict(self, X) -> np.ndarray:
        return self.predict_proba(X).argmax(axis=1)

    def evaluate(self, X_test, y_test) -> dict:
        y_pred = self.predict(X_test)
        acc = accuracy_score(y_test, y_pred)
        rec = recall_score(y_test, y_pred, average="weighted", zero_division=0)
        logger.info("Ensemble 평가 | acc=%.4f recall=%.4f", acc, rec)
        return {
            "accuracy": round(float(acc), 4),
            "recall_weighted": round(float(rec), 4),
            "target_accuracy_met": bool(acc >= TARGETS["quality_accuracy"]),
        }


# ===========================================================================
# 보조 함수
# ===========================================================================
def _minmax(arr: np.ndarray) -> np.ndarray:
    arr = np.asarray(arr, dtype=float)
    lo, hi = arr.min(), arr.max()
    if hi - lo < 1e-9:
        return np.zeros_like(arr)
    return (arr - lo) / (hi - lo)


def maybe_smote(X, y):
    """SMOTE 가용 시 오버샘플링 (이상 샘플 희소 보정). 미설치 시 원본 반환."""
    try:
        from imblearn.over_sampling import SMOTE
        classes, counts = np.unique(y, return_counts=True)
        if counts.min() < 6 or len(classes) < 2:
            logger.info("SMOTE 생략 (최소 클래스 샘플 부족)")
            return X, y
        k = min(5, counts.min() - 1)
        sm = SMOTE(random_state=42, k_neighbors=k)
        X_res, y_res = sm.fit_resample(X, y)
        logger.info("SMOTE 적용: %d → %d 샘플", len(y), len(y_res))
        return X_res, y_res
    except ImportError:
        logger.info("imblearn 미설치 — SMOTE 생략 (XGBoost scale_pos_weight로 보정)")
        return X, y


def write_training_metadata(metrics: dict, data_period: dict,
                            n_samples: int, model_version: str = "1.0.0",
                            data_source: str = "db") -> Path:
    """모델 버전 + 학습 데이터 기간 + 성능을 training_metadata.json에 기록."""
    meta = {
        "model_version": model_version,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "data_source": data_source,          # db | synthetic
        "data_period": data_period,          # {"from": ..., "to": ...}
        "n_samples": n_samples,
        "ai_targets": TARGETS,
        "metrics": metrics,
        "class_mapping": QUALITY_LABEL_MAP,
        "project": "SF26179540",
    }
    path = MODELS_DIR / "training_metadata.json"
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("학습 메타데이터 저장: %s", path)
    return path


# ===========================================================================
# 합성 데이터 생성 (--synthetic) — 3개월 LOT 데이터 미축적 시 대체
# ===========================================================================
def generate_synthetic_data(n_lots: int = 500, hours: int = 24,
                            seed: int = 42) -> pd.DataFrame:
    """정상/주의/이상 발효 패턴을 수식 기반으로 생성한다.

    - 온도: N(18, 2) + 이상 LOT은 후반부 급등(과열) 패턴
    - 산도: 로지스틱 성장 곡선 (0.3 → 0.8%) / 이상 LOT은 과발효(>0.9)
    - 품질 레이블: 최종 온도/산도 임계값 기반 자동 부여
    각 LOT은 hours 길이의 1시간 간격 시계열을 갖는다.
    """
    rng = np.random.default_rng(seed)
    base_date = pd.Timestamp("2026-03-01 06:00:00")
    rows = []

    # 클래스 비율: 정상 70% / 주의 20% / 이상 10% (불균형 재현)
    classes = rng.choice([0, 1, 2], size=n_lots, p=[0.70, 0.20, 0.10])

    origins = ["강원_평창", "강원_정선", "충북_괴산", "전남_해남"]
    sizes = ["대", "중", "소"]
    grades = ["A", "B", "C"]

    for lot_idx in range(n_lots):
        cls = int(classes[lot_idx])
        lot_id = f"FE-SYN-{lot_idx:04d}"
        start = base_date + pd.Timedelta(hours=int(rng.integers(0, 24 * 80)))

        # 원재료 LOT 속성
        cabbage_size = rng.choice(sizes)
        appearance = rng.choice(grades, p=[0.5, 0.35, 0.15] if cls == 0 else [0.2, 0.4, 0.4])
        weight = float(rng.normal(1200, 150))
        moisture = float(np.clip(rng.normal(92 if cls == 0 else 88, 2), 80, 96))
        origin = rng.choice(origins)

        # 절임 조건
        salt_temp = float(rng.normal(11.5, 0.8))
        salt_density = float(rng.normal(2.8 if cls == 0 else 3.3, 0.3))
        salt_ph = float(rng.normal(6.0, 0.2))
        salt_hours = float(rng.normal(8.0, 0.7))
        dehydration = float(np.clip(rng.normal(15 if cls == 0 else 11, 2), 5, 25))

        # 총 발효 시간 (완료 시점)
        total_hours = float(rng.normal(60 if cls == 0 else 54, 6))
        end_time = start + pd.Timedelta(hours=total_hours)

        # 로지스틱 산도 성장
        t = np.arange(hours)
        midpoint = total_hours * 0.5
        rate = 0.12 if cls != 2 else 0.22   # 이상은 빠른 과발효
        ceiling = 0.82 if cls == 0 else (0.9 if cls == 1 else 1.15)
        acidity = 0.3 + (ceiling - 0.3) / (1 + np.exp(-rate * (t - midpoint)))
        acidity += rng.normal(0, 0.02, hours)

        # 온도 패턴
        if cls == 2:   # 이상: 후반 급등
            temp = rng.normal(18, 1.0, hours)
            spike = np.where(t > hours * 0.6, (t - hours * 0.6) * 0.9, 0)
            temp = temp + spike + rng.normal(0, 0.5, hours)
        elif cls == 1:  # 주의: 약한 상승
            temp = rng.normal(19, 1.5, hours) + t * 0.05
        else:           # 정상
            temp = rng.normal(13, 1.0, hours)

        humidity = np.clip(rng.normal(85, 4, hours), 60, 99)
        ambient_temp = float(rng.normal(15, 3))

        for i in range(hours):
            rec_at = start + pd.Timedelta(hours=int(i))
            rows.append({
                "lot_id": lot_id,
                "recorded_at": rec_at,
                "temperature": round(float(temp[i]), 2),
                "acidity": round(float(np.clip(acidity[i], 0.2, 1.4)), 3),
                "salinity": round(float(np.clip(rng.normal(salt_density, 0.1), 1.5, 4.0)), 2),
                "outdoor_humidity": round(float(humidity[i]), 1),
                "ferment_start": start,
                "ferment_end": end_time,
                "ferment_hours": total_hours,
                "outdoor_temperature": ambient_temp,
                "quality_label_raw": QUALITY_LABEL_INV[cls],
                "is_abnormal": cls == 2,
                "salt_temp": round(salt_temp, 2),
                "salt_salinity": round(salt_density, 2),
                "salt_ph": round(salt_ph, 2),
                "salt_hours": round(salt_hours, 2),
                "dehydration_rate": round(dehydration, 2),
                "weight_kg": round(weight, 2),
                "cabbage_size": cabbage_size,
                "appearance_grade": appearance,
                "moisture_content": round(moisture, 2),
                "origin": origin,
            })

    df = pd.DataFrame(rows)
    logger.info("합성 데이터 생성: %d개 LOT × %dh = %d행 (정상/주의/이상=%s)",
                n_lots, hours, len(df),
                np.bincount(classes, minlength=3).tolist())
    return df
