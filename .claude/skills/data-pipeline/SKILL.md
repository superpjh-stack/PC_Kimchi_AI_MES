---
name: data-pipeline
description: 꽃순이김치 MES IoT 센서 데이터 수집(OPC-UA/Modbus), MQTT/Kafka 스트리밍, ETL 파이프라인 개발 스킬. Edge Collector 설정, 센서 데이터 수집 코드, 전처리(노이즈/이상치/결측값), LOT 기반 데이터 적재 개발 시 반드시 이 스킬을 사용하라. 트리거: IoT, 데이터 수집, ETL, MQTT, Kafka, OPC-UA, Modbus, Edge Collector, 센서 데이터, 데이터 파이프라인.
---

# MES 데이터 파이프라인 개발 스킬

## 파이프라인 아키텍처

```
[현장 설비/센서]
    → OPC-UA / Modbus TCP/IP
    → [Edge Collector Mini PC]  (로컬 버퍼 — 네트워크 단절 시 보존)
    → MQTT Broker
    → Kafka Streaming
    → Data Lake (Raw Zone, S3 or 로컬)
    → ETL (전처리: 노이즈 제거, 이상치, 결측값)
    → PostgreSQL 운영DB (LOT 단위 집계)
```

---

## Kafka 토픽 명명 규칙

```
mes.{process}.{sensor_type}

예시:
mes.fermentation.temperature    -- 발효 온도
mes.fermentation.acidity        -- 발효 산도
mes.salting.salinity            -- 절임 염도
mes.intake.weight               -- 입고 중량
mes.environment.outdoor_temp    -- 외기 온도
```

---

## Edge Collector 수집 모듈

### OPC-UA 수집기
```python
# edge/opc_ua_collector.py
from opcua import Client
import json, time, queue, threading
from datetime import datetime

class OPCUACollector:
    def __init__(self, endpoint: str, node_ids: list[str], buffer: queue.Queue):
        self.client = Client(endpoint)
        self.node_ids = node_ids
        self.buffer = buffer

    def collect(self, lot_id: str, interval_sec: float = 60.0):
        self.client.connect()
        try:
            while True:
                timestamp = datetime.utcnow().isoformat()
                for node_id in self.node_ids:
                    node = self.client.get_node(node_id)
                    value = node.get_value()
                    self.buffer.put({
                        "lot_id": lot_id,
                        "node_id": node_id,
                        "value": value,
                        "timestamp": timestamp
                    })
                time.sleep(interval_sec)
        finally:
            self.client.disconnect()
```

### Modbus TCP 수집기
```python
# edge/modbus_collector.py
from pymodbus.client import ModbusTcpClient
import queue
from datetime import datetime

class ModbusCollector:
    def __init__(self, host: str, port: int, registers: dict, buffer: queue.Queue):
        self.client = ModbusTcpClient(host, port=port)
        self.registers = registers  # {"temperature": 100, "salinity": 101, ...}
        self.buffer = buffer

    def collect(self, lot_id: str, interval_sec: float = 60.0):
        import time
        self.client.connect()
        try:
            while True:
                timestamp = datetime.utcnow().isoformat()
                for sensor_name, address in self.registers.items():
                    result = self.client.read_holding_registers(address, count=1)
                    if not result.isError():
                        self.buffer.put({
                            "lot_id": lot_id,
                            "sensor": sensor_name,
                            "value": result.registers[0] / 100.0,  # 스케일 조정
                            "timestamp": timestamp
                        })
                time.sleep(interval_sec)
        finally:
            self.client.close()
```

---

## MQTT → Kafka 브리지

```python
# edge/mqtt_kafka_bridge.py
import paho.mqtt.client as mqtt
from kafka import KafkaProducer
import json

KAFKA_SERVERS = ["kafka:9092"]
MQTT_BROKER = "mqtt-broker"

producer = KafkaProducer(
    bootstrap_servers=KAFKA_SERVERS,
    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    key_serializer=lambda k: k.encode("utf-8")
)

def on_message(client, userdata, msg):
    data = json.loads(msg.payload)
    process = data.get("process", "unknown")
    sensor = data.get("sensor", "unknown")
    topic = f"mes.{process}.{sensor}"
    key = data.get("lot_id", "no-lot")
    producer.send(topic, key=key, value=data)
    producer.flush()

client = mqtt.Client()
client.on_message = on_message
client.connect(MQTT_BROKER, 1883, 60)
client.subscribe("mes/#")
client.loop_forever()
```

---

## ETL 전처리 파이프라인

```python
# etl/preprocessor.py
import pandas as pd
import numpy as np
from sklearn.impute import KNNImputer

class FermentationETL:

    def remove_noise(self, df: pd.DataFrame, cols: list) -> pd.DataFrame:
        """Moving Average로 노이즈 제거"""
        for col in cols:
            df[col] = df.groupby('fermentation_lot_id')[col].transform(
                lambda x: x.rolling(window=5, min_periods=1, center=True).mean()
            )
        return df

    def remove_outliers_iqr(self, df: pd.DataFrame, cols: list) -> pd.DataFrame:
        """IQR 기반 이상치 제거"""
        for col in cols:
            Q1, Q3 = df[col].quantile([0.25, 0.75])
            IQR = Q3 - Q1
            df = df[(df[col] >= Q1 - 1.5 * IQR) & (df[col] <= Q3 + 1.5 * IQR)]
        return df

    def impute_missing(self, df: pd.DataFrame, cols: list, method: str = "ffill") -> pd.DataFrame:
        """결측값 처리"""
        if method == "ffill":
            df[cols] = df.groupby('fermentation_lot_id')[cols].transform(lambda x: x.ffill())
        elif method == "knn":
            imputer = KNNImputer(n_neighbors=5)
            df[cols] = imputer.fit_transform(df[cols])
        return df

    def deduplicate(self, df: pd.DataFrame) -> pd.DataFrame:
        """LOT + Timestamp 기준 중복 제거"""
        return df.drop_duplicates(subset=['fermentation_lot_id', 'recorded_at'], keep='last')

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        sensor_cols = ['temperature', 'acidity', 'salinity', 'ripeness_score']
        df = self.deduplicate(df)
        df = self.remove_noise(df, sensor_cols)
        df = self.remove_outliers_iqr(df, sensor_cols)
        df = self.impute_missing(df, sensor_cols, method='ffill')
        return df
```

---

## PostgreSQL 적재 모듈

```python
# etl/db_loader.py
import psycopg2
from psycopg2.extras import execute_batch

def load_fermentation_timeseries(records: list[dict], conn_str: str):
    """발효 시계열 데이터 배치 적재"""
    query = """
        INSERT INTO fermentation_timeseries
            (fermentation_lot_id, recorded_at, temperature, acidity,
             salinity, ripeness_score, outdoor_temperature, outdoor_humidity)
        VALUES
            (%(fermentation_lot_id)s, %(recorded_at)s, %(temperature)s, %(acidity)s,
             %(salinity)s, %(ripeness_score)s, %(outdoor_temperature)s, %(outdoor_humidity)s)
        ON CONFLICT (fermentation_lot_id, recorded_at) DO NOTHING
    """
    with psycopg2.connect(conn_str) as conn:
        with conn.cursor() as cur:
            execute_batch(cur, query, records, page_size=1000)
        conn.commit()
```

---

## 네트워크 단절 대응 (로컬 버퍼)

```python
# edge/local_buffer.py
import sqlite3, json
from datetime import datetime

class LocalBuffer:
    """네트워크 단절 시 SQLite로 로컬 버퍼링"""

    def __init__(self, db_path: str = "edge_buffer.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS buffer (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now')),
                    synced INTEGER DEFAULT 0
                )
            """)

    def push(self, topic: str, payload: dict):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO buffer (topic, payload) VALUES (?, ?)",
                         (topic, json.dumps(payload)))

    def flush_to_kafka(self, producer):
        """네트워크 복구 후 버퍼 데이터를 Kafka로 전송"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT id, topic, payload FROM buffer WHERE synced = 0").fetchall()
            for row_id, topic, payload in rows:
                producer.send(topic, value=json.loads(payload))
                conn.execute("UPDATE buffer SET synced = 1 WHERE id = ?", (row_id,))
            conn.commit()
        producer.flush()
```

---

## LSTM 슬라이딩 윈도우 변환 (ETL → ML)

```python
# etl/window_transformer.py
import numpy as np
import pandas as pd

WINDOW_SIZE = 24  # 24시간

def transform_for_lstm(df: pd.DataFrame, feature_cols: list) -> tuple:
    """발효 시계열 → LSTM 슬라이딩 윈도우"""
    X, y, lot_ids = [], [], []
    for lot_id, group in df.groupby('fermentation_lot_id'):
        group = group.sort_values('recorded_at').reset_index(drop=True)
        if len(group) <= WINDOW_SIZE:
            continue
        values = group[feature_cols].values
        remaining = group['remaining_hours'].values
        for i in range(len(values) - WINDOW_SIZE):
            X.append(values[i:i + WINDOW_SIZE])
            y.append(remaining[i + WINDOW_SIZE])
            lot_ids.append(lot_id)
    return np.array(X), np.array(y), lot_ids
```

---

## 운영 원칙
1. Edge Collector는 Kafka 전송 실패 시 `LocalBuffer`로 로컬 저장 → 복구 후 자동 동기화
2. Kafka 토픽은 `mes.{process}.{sensor}` 규칙을 엄격히 준수
3. 모든 레코드는 (lot_id, timestamp) 복합 유니크 제약으로 중복 방지
4. ML 학습 데이터는 3개월 이상 축적 후 제공 (파일럿 조건)
