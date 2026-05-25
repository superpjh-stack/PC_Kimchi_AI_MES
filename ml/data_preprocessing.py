"""
꽃순이김치 제조AI MES — 발효 품질 예측 ML 데이터 전처리 파이프라인
프로젝트: SF26179540 / 로뎀솔루션
스킬: ml-fermentation

처리 순서:
  1. PostgreSQL에서 fermentation_timeseries + fermentation_process(또는 _lot)
     + salting_process + raw_material_intake 조인
  2. 노이즈 제거: Moving Average(3포인트) + Low-pass(EWMA) Filter
  3. 이상치 제거: IQR (온도/산도/염도)
  4. 결측값 보간: Forward Fill(LOT 단위) → KNN Imputation (K=5)
  5. 파생변수: 온도변화율, pH변화율, 염도×절임시간, 함수율대비탈수율
  6. Z-score + Min-Max 스케일링
  7. LSTM용 Sliding Window 변환 (window_size=24, step=1)
  8. LOT+Timestamp 중복 제거

DB 스키마(db/init.sql) 컬럼명을 기준으로 한다:
  fermentation_timeseries(fermentation_lot_id, recorded_at, temperature,
                          acidity, salt_density, humidity)
  fermentation_process(fermentation_lot_id, salting_lot_id, start_time,
                       ferment_temp, ferment_acidity, ferment_hours,
                       ambient_temp, ambient_humidity, actual_end_time, ...)
  salting_process(salting_lot_id, intake_lot_id, salt_temp, salt_density,
                  salt_ph, salt_hours, dehydration_rate)
  raw_material_intake(intake_lot_id, weight_kg, cabbage_size,
                      appearance_grade, moisture_rate, origin)

ml-fermentation 스킬의 표준 피처 명세에 맞춰 내부 컬럼명을 정규화한다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import KNNImputer
from sklearn.preprocessing import LabelEncoder, MinMaxScaler, StandardScaler

# ---------------------------------------------------------------------------
# 로깅
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ml.preprocessing")

# ---------------------------------------------------------------------------
# 경로 상수
# ---------------------------------------------------------------------------
ML_ROOT = Path(__file__).resolve().parent
PROCESSED_DIR = ML_ROOT / "data" / "processed"
RAW_DIR = ML_ROOT / "data" / "raw"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 피처 정의 (ml-fermentation 스킬 §입력 피처 정의 동기화)
# ---------------------------------------------------------------------------
SALTING_FEATURES = ["salt_temp", "salinity", "salt_ph", "salt_hours"]
FERMENTATION_FEATURES = ["temperature", "acidity", "ripeness_score"]
ENVIRONMENT_FEATURES = ["outdoor_temperature", "outdoor_humidity"]
RAW_MATERIAL_FEATURES = [
    "cabbage_size_enc", "weight_kg", "moisture_content",
    "appearance_grade_enc", "origin_enc",
]
DERIVED_FEATURES = [
    "temp_change_rate", "ph_change_rate",
    "salinity_x_duration", "dehydration_per_moisture", "elapsed_hours",
]

ALL_FEATURES = (
    SALTING_FEATURES + FERMENTATION_FEATURES + ENVIRONMENT_FEATURES
    + RAW_MATERIAL_FEATURES + DERIVED_FEATURES
)
# LSTM 시계열 입력 피처 (window_size 길이로 잘림)
TIMESERIES_FEATURES = [
    "temperature", "acidity", "salinity",
    "ripeness_score", "outdoor_temperature", "outdoor_humidity",
    "temp_change_rate", "ph_change_rate",
]

# 품질 레이블 매핑
QUALITY_LABEL_MAP = {"NORMAL": 0, "CAUTION": 1, "ABNORMAL": 2}
QUALITY_LABEL_INV = {v: k for k, v in QUALITY_LABEL_MAP.items()}

WINDOW_SIZE = 24   # 24시간 슬라이딩 윈도우 (1시간 간격)
WINDOW_STEP = 1


def quality_label_encode(labels: pd.Series | list[str]) -> np.ndarray:
    """품질 라벨 문자열 → 정수 (NORMAL=0, CAUTION=1, ABNORMAL=2)."""
    s = pd.Series(labels).astype(str).str.upper()
    return s.map(QUALITY_LABEL_MAP).fillna(0).astype(int).to_numpy()


def quality_label_decode(codes: np.ndarray | list[int]) -> list[str]:
    """정수 라벨 → 문자열."""
    return [QUALITY_LABEL_INV.get(int(c), "NORMAL") for c in codes]


# ===========================================================================
# 1. 데이터 로더 — asyncpg 로 DB 조인 로드
# ===========================================================================
class FermentationDataLoader:
    """PostgreSQL에서 발효 시계열 + 공정 + 절임 + 원재료 데이터를 조인 로드한다.

    DSN 예) postgresql://mes:mes@db-server:5432/kimchi_mes
    """

    JOIN_QUERY = """
        SELECT
            ts.fermentation_lot_id                      AS lot_id,
            ts.recorded_at                              AS recorded_at,
            ts.temperature                              AS temperature,
            ts.acidity                                  AS acidity,
            ts.salt_density                             AS salinity,
            ts.humidity                                 AS outdoor_humidity,
            fp.start_time                               AS ferment_start,
            fp.actual_end_time                          AS ferment_end,
            fp.ferment_hours                            AS ferment_hours,
            fp.ambient_temp                             AS outdoor_temperature,
            fp.ml_quality_pred                          AS quality_label_raw,
            fp.is_abnormal                              AS is_abnormal,
            sp.salt_temp                                AS salt_temp,
            sp.salt_density                             AS salt_salinity,
            sp.salt_ph                                  AS salt_ph,
            sp.salt_hours                               AS salt_hours,
            sp.dehydration_rate                         AS dehydration_rate,
            rmi.weight_kg                               AS weight_kg,
            rmi.cabbage_size                            AS cabbage_size,
            rmi.appearance_grade                        AS appearance_grade,
            rmi.moisture_rate                           AS moisture_content,
            rmi.origin                                  AS origin
        FROM fermentation_timeseries ts
        JOIN fermentation_process fp
            ON fp.fermentation_lot_id = ts.fermentation_lot_id
        LEFT JOIN salting_process sp
            ON sp.salting_lot_id = fp.salting_lot_id
        LEFT JOIN raw_material_intake rmi
            ON rmi.intake_lot_id = sp.intake_lot_id
        WHERE ts.recorded_at >= $1
        ORDER BY ts.fermentation_lot_id, ts.recorded_at
    """

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn

    async def load(self, since: str = "2026-01-01") -> pd.DataFrame:
        """DB에서 조인 데이터를 DataFrame으로 로드한다."""
        try:
            import asyncpg  # 지연 import (합성 데이터 경로에서는 불필요)
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "asyncpg가 설치되어 있지 않습니다. `pip install asyncpg` 또는 "
                "--synthetic 모드를 사용하세요."
            ) from exc

        if not self.dsn:
            raise ValueError("DB DSN이 지정되지 않았습니다.")

        logger.info("DB 연결 및 조인 쿼리 실행 (since=%s)...", since)
        conn = await asyncpg.connect(self.dsn)
        try:
            rows = await conn.fetch(self.JOIN_QUERY, pd.Timestamp(since).to_pydatetime())
        finally:
            await conn.close()

        df = pd.DataFrame([dict(r) for r in rows])
        logger.info("DB 로드 완료: %d행 / %d개 LOT",
                    len(df), df["lot_id"].nunique() if not df.empty else 0)
        return df

    @staticmethod
    def load_parquet(path: str | Path) -> pd.DataFrame:
        """이미 추출한 raw parquet을 로드한다 (오프라인 학습용)."""
        df = pd.read_parquet(path)
        logger.info("Parquet 로드: %s (%d행)", path, len(df))
        return df


# ===========================================================================
# 2. 피처 엔지니어링 — 파생변수 생성 + 범주형 인코딩
# ===========================================================================
class FeatureEngineer:
    """원시 조인 데이터에서 파생변수를 생성하고 범주형을 인코딩한다."""

    CATEGORICAL = {
        "cabbage_size": "cabbage_size_enc",
        "appearance_grade": "appearance_grade_enc",
        "origin": "origin_enc",
    }

    def __init__(self):
        self.encoders: dict[str, LabelEncoder] = {}

    def transform(self, df: pd.DataFrame, fit: bool = True) -> pd.DataFrame:
        df = df.copy()
        df = df.sort_values(["lot_id", "recorded_at"])

        # --- ripeness_score: 산도 기반 숙성도 근사 (없으면 정규화 산도) ---
        if "ripeness_score" not in df.columns:
            # 산도 0.3~1.0 구간을 0~1 숙성도로 맵핑 (로지스틱 근사)
            df["ripeness_score"] = (
                (df["acidity"].astype(float) - 0.3) / 0.7
            ).clip(0, 1)

        # --- salinity (발효 시계열 염도) 결측 시 절임 염도로 대체 ---
        if "salinity" in df.columns and "salt_salinity" in df.columns:
            df["salinity"] = df["salinity"].fillna(df["salt_salinity"])

        # --- 경과 시간 (LOT 시작부터의 시간) ---
        if "ferment_start" in df.columns:
            start = pd.to_datetime(df["ferment_start"], errors="coerce")
            rec = pd.to_datetime(df["recorded_at"], errors="coerce")
            df["elapsed_hours"] = (rec - start).dt.total_seconds() / 3600.0
        else:
            df["elapsed_hours"] = (
                df.groupby("lot_id").cumcount().astype(float)
            )

        # --- 잔여 발효 시간 (LSTM 타겟): 종료시각 - 현재시각 ---
        if "ferment_end" in df.columns:
            end = pd.to_datetime(df["ferment_end"], errors="coerce")
            rec = pd.to_datetime(df["recorded_at"], errors="coerce")
            df["remaining_hours"] = (end - rec).dt.total_seconds() / 3600.0
            df["remaining_hours"] = df["remaining_hours"].clip(lower=0)

        # --- 파생변수: 변화율 (diff / dt) ---
        grp = df.groupby("lot_id", group_keys=False)
        dt_h = grp["elapsed_hours"].diff().replace(0, np.nan)
        df["temp_change_rate"] = grp["temperature"].diff() / dt_h
        df["ph_change_rate"] = grp["acidity"].diff() / dt_h
        df["temp_change_rate"] = df["temp_change_rate"].fillna(0.0)
        df["ph_change_rate"] = df["ph_change_rate"].fillna(0.0)

        # --- 파생변수: 염도×절임시간, 함수율대비탈수율 ---
        def _col(name: str, default: float = 0.0) -> pd.Series:
            """컬럼이 없으면 default로 채운 Series 반환 (스칼라 연산 방지)."""
            if name in df.columns:
                return pd.to_numeric(df[name], errors="coerce").fillna(default)
            return pd.Series(default, index=df.index, dtype=float)

        salt_sal = _col("salt_salinity") if "salt_salinity" in df.columns else _col("salinity")
        df["salinity_x_duration"] = salt_sal * _col("salt_hours")
        moisture = _col("moisture_content").replace(0, np.nan)
        df["dehydration_per_moisture"] = (_col("dehydration_rate") / moisture).fillna(0.0)

        # --- 범주형 인코딩 ---
        for raw_col, enc_col in self.CATEGORICAL.items():
            if raw_col not in df.columns:
                df[enc_col] = 0
                continue
            vals = df[raw_col].astype(str).fillna("UNKNOWN")
            if fit:
                le = LabelEncoder()
                df[enc_col] = le.fit_transform(vals)
                self.encoders[raw_col] = le
            else:
                le = self.encoders.get(raw_col)
                if le is None:
                    df[enc_col] = 0
                else:
                    known = set(le.classes_)
                    vals = vals.where(vals.isin(known), other=le.classes_[0])
                    df[enc_col] = le.transform(vals)

        logger.info("피처 엔지니어링 완료: 파생변수 %d개 생성", len(DERIVED_FEATURES))
        return df


# ===========================================================================
# 3. 전처리기 — 노이즈/이상치/결측/스케일링
# ===========================================================================
@dataclass
class DataPreprocessor:
    """노이즈 제거 → 이상치 제거 → 결측 보간 → 스케일링."""

    ma_window: int = 3
    ewma_alpha: float = 0.3
    iqr_factor: float = 1.5
    knn_k: int = 5
    iqr_cols: tuple = ("temperature", "acidity", "salinity")
    smooth_cols: tuple = ("temperature", "acidity", "salinity", "outdoor_humidity")
    scale_cols: list = field(default_factory=lambda: [
        "temperature", "acidity", "salinity", "ripeness_score",
        "outdoor_temperature", "outdoor_humidity",
    ])

    minmax_scaler: MinMaxScaler = field(default_factory=MinMaxScaler)
    zscore_scaler: StandardScaler = field(default_factory=StandardScaler)
    _fitted: bool = False

    # ---------------------------------------------------------------
    def denoise(self, df: pd.DataFrame) -> pd.DataFrame:
        """Moving Average(3) + Low-pass(EWMA) — LOT 단위."""
        df = df.copy()
        for col in self.smooth_cols:
            if col not in df.columns:
                continue
            grp = df.groupby("lot_id", group_keys=False)[col]
            ma = grp.transform(lambda s: s.rolling(self.ma_window, min_periods=1).mean())
            df[col] = (
                df.assign(_ma=ma)
                  .groupby("lot_id", group_keys=False)["_ma"]
                  .transform(lambda s: s.ewm(alpha=self.ewma_alpha, adjust=False).mean())
            )
        logger.info("노이즈 제거 완료 (MA=%d, EWMA alpha=%.2f)",
                    self.ma_window, self.ewma_alpha)
        return df

    # ---------------------------------------------------------------
    def remove_outliers_iqr(self, df: pd.DataFrame) -> pd.DataFrame:
        """IQR 기반 이상치 제거 (온도/산도/염도)."""
        before = len(df)
        mask = pd.Series(True, index=df.index)
        for col in self.iqr_cols:
            if col not in df.columns:
                continue
            q1, q3 = df[col].quantile([0.25, 0.75])
            iqr = q3 - q1
            lo, hi = q1 - self.iqr_factor * iqr, q3 + self.iqr_factor * iqr
            mask &= df[col].between(lo, hi) | df[col].isna()
        df = df[mask]
        logger.info("IQR 이상치 제거: %d → %d행 (%d행 제거)",
                    before, len(df), before - len(df))
        return df

    # ---------------------------------------------------------------
    def impute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Forward Fill(LOT 단위) → KNN Imputation(K)."""
        df = df.copy()
        ffill_cols = [c for c in self.scale_cols if c in df.columns]
        g = df.groupby("lot_id")[ffill_cols]
        df[ffill_cols] = g.ffill().bfill()
        # 남은 결측은 KNN
        knn_cols = [c for c in ffill_cols if df[c].isna().any()]
        if knn_cols:
            imputer = KNNImputer(n_neighbors=self.knn_k)
            df[ffill_cols] = imputer.fit_transform(df[ffill_cols])
            logger.info("KNN 결측 보간(K=%d): %d개 컬럼", self.knn_k, len(knn_cols))
        else:
            logger.info("Forward/Back Fill로 결측 해소 — KNN 생략")
        return df

    # ---------------------------------------------------------------
    def dedup(self, df: pd.DataFrame) -> pd.DataFrame:
        """LOT + Timestamp 중복 제거."""
        before = len(df)
        df = df.drop_duplicates(subset=["lot_id", "recorded_at"], keep="last")
        if before != len(df):
            logger.info("중복 제거: %d → %d행", before, len(df))
        return df

    # ---------------------------------------------------------------
    def scale(self, df: pd.DataFrame, fit: bool = True) -> pd.DataFrame:
        """Z-score 정규화 → Min-Max 스케일링 (모델 안정성)."""
        df = df.copy()
        cols = [c for c in self.scale_cols if c in df.columns]
        if not cols:
            return df
        if fit:
            z = self.zscore_scaler.fit_transform(df[cols])
            df[cols] = self.minmax_scaler.fit_transform(z)
            self._fitted = True
        else:
            if not self._fitted:
                raise RuntimeError("스케일러가 학습되지 않았습니다. fit=True로 먼저 호출하세요.")
            z = self.zscore_scaler.transform(df[cols])
            df[cols] = self.minmax_scaler.transform(z)
        logger.info("스케일링 완료 (Z-score + Min-Max): %d개 컬럼", len(cols))
        return df

    # ---------------------------------------------------------------
    def run(self, df: pd.DataFrame, fit: bool = True) -> pd.DataFrame:
        """전체 전처리 파이프라인 실행."""
        logger.info("=== 전처리 파이프라인 시작 (입력 %d행) ===", len(df))
        df = self.dedup(df)
        df = self.denoise(df)
        df = self.remove_outliers_iqr(df)
        df = self.impute(df)
        df = self.scale(df, fit=fit)
        df = df.reset_index(drop=True)
        logger.info("=== 전처리 완료 (출력 %d행) ===", len(df))
        return df


# ===========================================================================
# 4. 슬라이딩 윈도우 빌더 — LSTM 입력 (samples, window, features)
# ===========================================================================
class SlidingWindowBuilder:
    """LOT 단위 시계열을 (samples, window_size, n_features) 텐서로 변환한다."""

    def __init__(self, window_size: int = WINDOW_SIZE, step: int = WINDOW_STEP,
                 features: list[str] | None = None, target: str = "remaining_hours"):
        self.window_size = window_size
        self.step = step
        self.features = features or [f for f in TIMESERIES_FEATURES]
        self.target = target

    def build(self, df: pd.DataFrame, lot_col: str = "lot_id"
              ) -> tuple[np.ndarray, np.ndarray]:
        feats = [f for f in self.features if f in df.columns]
        if not feats:
            raise ValueError("슬라이딩 윈도우 변환에 사용할 피처가 없습니다.")
        X_list, y_list = [], []
        has_target = self.target in df.columns
        for lot_id, g in df.groupby(lot_col):
            g = g.sort_values("recorded_at")
            vals = g[feats].to_numpy(dtype=np.float32)
            tgt = g[self.target].to_numpy(dtype=np.float32) if has_target else None
            n = len(vals)
            if n <= self.window_size:
                continue
            for i in range(0, n - self.window_size, self.step):
                X_list.append(vals[i:i + self.window_size])
                if has_target:
                    y_list.append(tgt[i + self.window_size])
        X = np.asarray(X_list, dtype=np.float32)
        y = np.asarray(y_list, dtype=np.float32) if has_target else np.empty(0)
        logger.info("슬라이딩 윈도우: X%s, y%s (window=%d, %d피처)",
                    X.shape, y.shape, self.window_size, len(feats))
        return X, y


# ===========================================================================
# 5. LOT 단위 집계 — 분류/회귀 모델용 (tabular)
# ===========================================================================
def aggregate_lot_features(df: pd.DataFrame) -> pd.DataFrame:
    """시계열을 LOT 단위 집계 통계로 축약 (XGBoost/RF/SVR tabular 입력).

    각 LOT의 마지막 상태 + 통계량을 한 행으로 만든다.
    """
    rows = []
    for lot_id, g in df.groupby("lot_id"):
        g = g.sort_values("recorded_at")
        last = g.iloc[-1]
        row: dict = {"lot_id": lot_id}
        for col in ["temperature", "acidity", "salinity", "ripeness_score",
                    "outdoor_temperature", "outdoor_humidity"]:
            if col in g.columns:
                row[f"{col}"] = float(last.get(col, np.nan))
                row[f"{col}_mean"] = float(g[col].mean())
                row[f"{col}_std"] = float(g[col].std(ddof=0)) if len(g) > 1 else 0.0
                row[f"{col}_max"] = float(g[col].max())
        for col in (SALTING_FEATURES + RAW_MATERIAL_FEATURES + DERIVED_FEATURES):
            if col in g.columns:
                row[col] = float(last.get(col, np.nan)) if pd.notna(last.get(col, np.nan)) else 0.0
        # 타겟
        if "quality_label_raw" in g.columns:
            row["quality_label_raw"] = last.get("quality_label_raw")
        if "is_abnormal" in g.columns:
            row["is_abnormal"] = bool(last.get("is_abnormal", False))
        if "acidity" in g.columns:
            row["target_acidity"] = float(last.get("acidity"))
        if "ripeness_score" in g.columns:
            row["target_ripeness"] = float(last.get("ripeness_score"))
        rows.append(row)
    out = pd.DataFrame(rows).fillna(0.0)
    logger.info("LOT 단위 집계: %d개 LOT × %d피처", len(out), out.shape[1])
    return out


# ===========================================================================
# 6. 저장 헬퍼
# ===========================================================================
def save_processed(df: pd.DataFrame, name: str) -> Path:
    """전처리 결과를 Parquet으로 저장."""
    path = PROCESSED_DIR / f"{name}.parquet"
    df.to_parquet(path, index=False)
    logger.info("저장: %s (%d행)", path, len(df))
    return path


def save_arrays(X: np.ndarray, y: np.ndarray, name: str) -> Path:
    """슬라이딩 윈도우 배열을 npz로 저장."""
    path = PROCESSED_DIR / f"{name}.npz"
    np.savez_compressed(path, X=X, y=y)
    logger.info("저장: %s (X%s, y%s)", path, X.shape, y.shape)
    return path


# ===========================================================================
# 통합 파이프라인 진입점
# ===========================================================================
def build_training_datasets(df_raw: pd.DataFrame, fit: bool = True
                            ) -> dict[str, object]:
    """원시 조인 데이터 → (tabular, sliding-window) 학습 데이터셋 묶음 생성.

    반환:
      {
        "tabular": pd.DataFrame,          # XGBoost/RF/SVR 입력
        "X_seq": np.ndarray,              # LSTM 입력 (N, 24, F)
        "y_seq": np.ndarray,              # LSTM 타겟 (잔여시간)
        "engineer": FeatureEngineer,
        "preprocessor": DataPreprocessor,
      }
    """
    engineer = FeatureEngineer()
    df_feat = engineer.transform(df_raw, fit=fit)

    pre = DataPreprocessor()
    df_proc = pre.run(df_feat, fit=fit)

    # 시계열 (LSTM)
    swb = SlidingWindowBuilder()
    X_seq, y_seq = swb.build(df_proc)

    # tabular (XGBoost/RF/SVR)
    tabular = aggregate_lot_features(df_proc)

    save_processed(df_proc, "fermentation_timeseries_processed")
    save_processed(tabular, "fermentation_tabular")
    save_arrays(X_seq, y_seq, "lstm_windows")

    return {
        "tabular": tabular,
        "X_seq": X_seq,
        "y_seq": y_seq,
        "engineer": engineer,
        "preprocessor": pre,
        "processed_ts": df_proc,
    }


if __name__ == "__main__":
    # 단독 실행 시: 합성 데이터로 전처리 데모
    from fermentation_model import generate_synthetic_data  # type: ignore

    logger.info("단독 실행 — 합성 데이터로 전처리 데모")
    df_demo = generate_synthetic_data(n_lots=50, hours=48)
    datasets = build_training_datasets(df_demo, fit=True)
    logger.info("데모 완료: tabular=%s, X_seq=%s",
                datasets["tabular"].shape, datasets["X_seq"].shape)
