"""
꽃순이김치 제조AI MES — 발효 모델 학습 실행 스크립트 (CLI)
프로젝트: SF26179540 / 로뎀솔루션
스킬: ml-fermentation

사용법:
  python ml/train.py --model all          # 전체 모델 학습
  python ml/train.py --model xgboost      # XGBoost만
  python ml/train.py --model lstm         # LSTM만
  python ml/train.py --model svr          # SVR만
  python ml/train.py --model rf           # RandomForest만
  python ml/train.py --model anomaly      # 이상탐지만
  python ml/train.py --evaluate           # 테스트셋 평가(저장 모델 로드)
  python ml/train.py --synthetic          # 합성 데이터로 학습(실데이터 없을 때)
  python ml/train.py --model all --synthetic --n-lots 500 --hours 24

데이터 소스 우선순위:
  --synthetic 지정 시 합성 데이터
  그 외 --dsn 또는 MES_DB_DSN 환경변수로 DB 로드
  둘 다 없으면 합성 데이터로 폴백(경고)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

import joblib
import numpy as np
from sklearn.model_selection import train_test_split

from data_preprocessing import (
    FermentationDataLoader,
    SlidingWindowBuilder,
    TIMESERIES_FEATURES,
    build_training_datasets,
    quality_label_encode,
)
from fermentation_model import (
    AnomalyDetector,
    LSTMFermentationPredictor,
    QualityEnsemble,
    RandomForestAnalyzer,
    SHAPExplainer,
    SVRQualityRegressor,
    TARGETS,
    XGBoostQualityClassifier,
    generate_synthetic_data,
    maybe_smote,
    write_training_metadata,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ml.train")

ML_ROOT = Path(__file__).resolve().parent
MODELS_DIR = ML_ROOT / "models"

NON_FEATURE_COLS = {
    "lot_id", "quality_label_raw", "is_abnormal",
    "target_acidity", "target_ripeness",
}


# ===========================================================================
# 데이터 준비
# ===========================================================================
def load_raw_data(args) -> tuple["object", dict, str]:
    """원시 데이터 로드 → (df, data_period, source)."""
    import pandas as pd

    if args.synthetic:
        logger.info("합성 데이터 모드 (n_lots=%d, hours=%d)", args.n_lots, args.hours)
        df = generate_synthetic_data(n_lots=args.n_lots, hours=args.hours, seed=args.seed)
        source = "synthetic"
    else:
        dsn = args.dsn or os.getenv("MES_DB_DSN")
        if not dsn:
            logger.warning("DSN 미지정 — 합성 데이터로 폴백합니다.")
            df = generate_synthetic_data(n_lots=args.n_lots, hours=args.hours, seed=args.seed)
            source = "synthetic"
        else:
            import asyncio
            loader = FermentationDataLoader(dsn=dsn)
            df = asyncio.run(loader.load(since=args.since))
            source = "db"
            if df.empty:
                logger.warning("DB 데이터 0건 — 합성 데이터로 폴백합니다.")
                df = generate_synthetic_data(n_lots=args.n_lots, hours=args.hours, seed=args.seed)
                source = "synthetic"

    ts = pd.to_datetime(df["recorded_at"])
    data_period = {"from": str(ts.min()), "to": str(ts.max()),
                   "n_lots": int(df["lot_id"].nunique())}
    return df, data_period, source


def split_tabular(tabular):
    """tabular DataFrame → (X, y_class, y_acidity, y_ripeness, y_abnormal, feat_names)."""
    feat_names = [c for c in tabular.columns if c not in NON_FEATURE_COLS]
    X = tabular[feat_names].to_numpy(dtype=np.float32)
    y_class = quality_label_encode(tabular["quality_label_raw"]) \
        if "quality_label_raw" in tabular.columns else np.zeros(len(tabular), int)
    y_acidity = tabular.get("target_acidity",
                            tabular.get("acidity")).to_numpy(dtype=np.float32)
    y_ripeness = tabular.get("target_ripeness",
                             tabular.get("ripeness_score")).to_numpy(dtype=np.float32)
    y_abnormal = tabular["is_abnormal"].astype(int).to_numpy() \
        if "is_abnormal" in tabular.columns else (y_class == 2).astype(int)
    return X, y_class, y_acidity, y_ripeness, y_abnormal, feat_names


# ===========================================================================
# 개별 모델 학습
# ===========================================================================
def train_xgboost(X, y_class, feat_names, metrics: dict):
    Xtr, Xte, ytr, yte = train_test_split(
        X, y_class, test_size=0.2, random_state=42,
        stratify=y_class if len(np.unique(y_class)) > 1 else None)
    Xtr, ytr = maybe_smote(Xtr, ytr)
    Xtr2, Xval, ytr2, yval = train_test_split(
        Xtr, ytr, test_size=0.2, random_state=42,
        stratify=ytr if len(np.unique(ytr)) > 1 else None)

    clf = XGBoostQualityClassifier()
    clf.train(Xtr2, ytr2, Xval, yval, feature_names=feat_names)
    metrics["xgboost"] = clf.evaluate(Xte, yte)
    clf.save()
    return clf, (Xte, yte)


def train_rf(X, y_class, feat_names, metrics: dict):
    Xtr, Xte, ytr, yte = train_test_split(
        X, y_class, test_size=0.2, random_state=42,
        stratify=y_class if len(np.unique(y_class)) > 1 else None)
    Xtr, ytr = maybe_smote(Xtr, ytr)
    rf = RandomForestAnalyzer()
    rf.train(Xtr, ytr, feature_names=feat_names)
    metrics["random_forest"] = rf.evaluate(Xte, yte)
    rf.save()
    return rf, (Xte, yte)


def train_svr(X, y_acidity, y_ripeness, metrics: dict):
    Xtr, Xte, ya_tr, ya_te, yr_tr, yr_te = train_test_split(
        X, y_acidity, y_ripeness, test_size=0.2, random_state=42)
    svr = SVRQualityRegressor()
    svr.train(Xtr, ya_tr, yr_tr)
    metrics["svr"] = svr.evaluate(Xte, ya_te, yr_te)
    svr.save()
    return svr


def train_lstm(X_seq, y_seq, metrics: dict):
    if len(X_seq) < 20:
        logger.warning("LSTM 학습 데이터 부족(%d) — 건너뜀", len(X_seq))
        metrics["lstm"] = {"skipped": "insufficient_sequences"}
        return None
    Xtr, Xte, ytr, yte = train_test_split(X_seq, y_seq, test_size=0.2, random_state=42)
    Xtr2, Xval, ytr2, yval = train_test_split(Xtr, ytr, test_size=0.2, random_state=42)
    n_features = X_seq.shape[2]
    lstm = LSTMFermentationPredictor(window_size=X_seq.shape[1], n_features=n_features)
    if lstm.model is None:
        logger.warning("TensorFlow 미설치 — LSTM 학습 건너뜀")
        metrics["lstm"] = {"skipped": "tensorflow_not_installed"}
        return None
    lstm.train(Xtr2, ytr2, Xval, yval)
    metrics["lstm"] = lstm.evaluate(Xte, yte)
    lstm.save()
    return lstm


def train_anomaly(X, y_abnormal, metrics: dict):
    Xtr, Xte, ytr, yte = train_test_split(
        X, y_abnormal, test_size=0.2, random_state=42,
        stratify=y_abnormal if len(np.unique(y_abnormal)) > 1 else None)
    det = AnomalyDetector()
    det.fit(Xtr, ytr)
    metrics["anomaly"] = det.evaluate(Xte, yte)
    det.save()
    return det


# ===========================================================================
# 성능 목표 달성 리포트
# ===========================================================================
def print_target_report(metrics: dict) -> None:
    logger.info("=" * 64)
    logger.info("AI 성능 목표 달성 현황 (CLAUDE.md §AI 모듈)")
    logger.info("=" * 64)

    def line(label, value, target, met, unit=""):
        mark = "달성 [OK]" if met else "미달 [--]"
        logger.info("  %-28s %8s%s (목표 %s%s) → %s",
                    label, value, unit, target, unit, mark)

    if "xgboost" in metrics and "accuracy" in metrics["xgboost"]:
        m = metrics["xgboost"]
        line("XGBoost 품질 정확도", m["accuracy"], TARGETS["quality_accuracy"],
             m.get("target_accuracy_met"))
        line("품질 리스크 재현율", m["recall_weighted"], TARGETS["risk_recall"],
             m.get("target_recall_met"))
    if "svr" in metrics and "acidity" in metrics["svr"]:
        m = metrics["svr"]
        line("SVR 산도 R²", m["acidity"]["r2"], TARGETS["r2"],
             m["acidity"]["r2"] >= TARGETS["r2"])
        line("SVR 숙성도 R²", m["ripeness"]["r2"], TARGETS["r2"],
             m["ripeness"]["r2"] >= TARGETS["r2"])
    if "lstm" in metrics and "mae_hours" in metrics["lstm"]:
        m = metrics["lstm"]
        line("LSTM 완료시점 MAE", m["mae_hours"], TARGETS["completion_mae_hours"],
             m.get("target_mae_met"), "h")
    if "anomaly" in metrics and "accuracy" in metrics["anomaly"]:
        m = metrics["anomaly"]
        line("이상발효 탐지 정확도", m["accuracy"], TARGETS["anomaly_accuracy"],
             m.get("target_accuracy_met"))
    logger.info("=" * 64)


def save_preprocess_state(datasets) -> None:
    """추론 일관성을 위해 인코더/스케일러 상태를 저장."""
    state = {"engineer": datasets["engineer"], "preprocessor": datasets["preprocessor"]}
    path = MODELS_DIR / "preprocess_state.pkl"
    joblib.dump(state, path)
    # 표준 scaler.pkl (스킬 §모델 파일 구조)
    joblib.dump(datasets["preprocessor"], MODELS_DIR / "scaler.pkl")
    logger.info("전처리 상태 저장: %s", path)


# ===========================================================================
# 메인
# ===========================================================================
def main():
    parser = argparse.ArgumentParser(description="발효 품질 예측 모델 학습")
    parser.add_argument("--model", default="all",
                        choices=["all", "xgboost", "rf", "svr", "lstm", "anomaly"])
    parser.add_argument("--evaluate", action="store_true",
                        help="저장된 모델 로드 후 테스트셋 평가만 수행")
    parser.add_argument("--synthetic", action="store_true",
                        help="합성 데이터로 학습 (실데이터 미축적 시)")
    parser.add_argument("--dsn", default=None, help="PostgreSQL DSN (미지정 시 MES_DB_DSN)")
    parser.add_argument("--since", default="2026-01-01", help="DB 로드 시작일")
    parser.add_argument("--n-lots", type=int, default=500, help="합성 LOT 수")
    parser.add_argument("--hours", type=int, default=24, help="LOT당 시계열 시간")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model-version", default="1.0.0")
    args = parser.parse_args()

    # 데이터 로드 + 전처리
    df_raw, data_period, source = load_raw_data(args)
    logger.info("데이터 준비: source=%s, 기간=%s", source, data_period)
    datasets = build_training_datasets(df_raw, fit=True)
    tabular = datasets["tabular"]
    X_seq, y_seq = datasets["X_seq"], datasets["y_seq"]

    X, y_class, y_acidity, y_ripeness, y_abnormal, feat_names = split_tabular(tabular)
    logger.info("tabular X%s / 클래스 분포=%s / 시퀀스 X_seq%s",
                X.shape, np.bincount(y_class, minlength=3).tolist(), X_seq.shape)

    metrics: dict = {}

    # --- 평가 전용 모드 ---
    if args.evaluate:
        logger.info("평가 모드 — 저장된 모델 로드")
        try:
            clf = XGBoostQualityClassifier.load()
            Xtr, Xte, ytr, yte = train_test_split(X, y_class, test_size=0.2, random_state=42,
                                                  stratify=y_class if len(np.unique(y_class)) > 1 else None)
            metrics["xgboost"] = clf.evaluate(Xte, yte)
        except Exception as exc:
            logger.error("XGBoost 평가 실패: %s", exc)
        try:
            svr = SVRQualityRegressor.load()
            metrics["svr"] = svr.evaluate(X, y_acidity, y_ripeness)
        except Exception as exc:
            logger.error("SVR 평가 실패: %s", exc)
        print_target_report(metrics)
        return

    want = args.model
    xgb_clf = rf_model = None

    if want in ("all", "xgboost"):
        xgb_clf, _ = train_xgboost(X, y_class, feat_names, metrics)
        # SHAP 리포트 저장
        shap_exp = SHAPExplainer(feature_names=feat_names)
        report = shap_exp.report(xgb_clf, X[: min(200, len(X))])
        (MODELS_DIR / "shap_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("SHAP 리포트 저장: %s", MODELS_DIR / "shap_report.json")

    if want in ("all", "rf"):
        rf_model, _ = train_rf(X, y_class, feat_names, metrics)

    if want in ("all", "svr"):
        train_svr(X, y_acidity, y_ripeness, metrics)

    if want in ("all", "lstm"):
        train_lstm(X_seq, y_seq, metrics)

    if want in ("all", "anomaly"):
        train_anomaly(X, y_abnormal, metrics)

    # 앙상블 평가 (XGBoost + RF 모두 학습된 경우)
    if want == "all" and xgb_clf is not None and rf_model is not None:
        Xtr, Xte, ytr, yte = train_test_split(
            X, y_class, test_size=0.2, random_state=42,
            stratify=y_class if len(np.unique(y_class)) > 1 else None)
        ens = QualityEnsemble(xgb_clf, rf_model)
        metrics["ensemble"] = ens.evaluate(Xte, yte)

    # 전처리 상태 + 메타데이터 저장
    save_preprocess_state(datasets)
    write_training_metadata(
        metrics=metrics, data_period=data_period, n_samples=len(tabular),
        model_version=args.model_version, data_source=source)

    print_target_report(metrics)
    logger.info("학습 완료. 모델 산출물: %s", MODELS_DIR)


if __name__ == "__main__":
    main()
