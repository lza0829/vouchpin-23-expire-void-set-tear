from __future__ import annotations
import os
import sqlite3
from app.config import DB_PATH

# 写锁等待上限（秒）。扫描与钉扎交错时，后来者先等待；超时即失败并由
# 服务层转成 409，绝不带着未提交的扫描中间态继续钉扎。
LOCK_TIMEOUT_SECONDS = float(os.environ.get("SQLITE_LOCK_TIMEOUT", "5.0"))

SCHEMA = '''
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaigns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  face_value REAL NOT NULL,
  min_spend REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS coupon_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type TEXT NOT NULL,
  coupon_code TEXT NOT NULL,
  campaign_code TEXT NOT NULL,
  amount REAL NOT NULL DEFAULT 0,
  business_day TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS redeem_facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  coupon_code TEXT NOT NULL UNIQUE,
  campaign_code TEXT NOT NULL,
  amount REAL NOT NULL,
  business_day TEXT NOT NULL,
  event_id INTEGER NOT NULL,
  batch_id INTEGER,
  status TEXT NOT NULL DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS redeem_batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  business_day TEXT NOT NULL,
  status TEXT NOT NULL,
  fact_count INTEGER NOT NULL DEFAULT 0,
  total_amount REAL NOT NULL DEFAULT 0,
  sealed_at TEXT,
  note TEXT NOT NULL DEFAULT '',
  expire_scan_id INTEGER,
  scan_scanned_at TEXT,
  scan_voided_count INTEGER
);
CREATE TABLE IF NOT EXISTS expire_scans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  business_day TEXT NOT NULL,
  scanned_at TEXT NOT NULL,
  issued_count INTEGER NOT NULL DEFAULT 0,
  voided_count INTEGER NOT NULL DEFAULT 0,
  covered_event_id INTEGER NOT NULL DEFAULT 0,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS expire_scan_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_id INTEGER NOT NULL,
  coupon_code TEXT NOT NULL,
  campaign_code TEXT NOT NULL,
  void_event_id INTEGER NOT NULL
);
'''

# 批快照新增列（老库迁移用）：钉扎批绑定 expire_scan_id 与扫描摘要
_BATCH_NEW_COLUMNS = {
    "expire_scan_id": "expire_scan_id INTEGER",
    "scan_scanned_at": "scan_scanned_at TEXT",
    "scan_voided_count": "scan_voided_count INTEGER",
}


def connect(immediate: bool = False) -> sqlite3.Connection:
    # timeout：写锁竞争（如扫描与钉扎交错）时先等待，超时再报错，
    # 由调用方转成 409「请等待或重试」，避免静默读到扫描中间态。
    conn = sqlite3.connect(DB_PATH, timeout=LOCK_TIMEOUT_SECONDS, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if immediate:
        conn.execute("BEGIN IMMEDIATE")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        for col, ddl in _BATCH_NEW_COLUMNS.items():
            _ensure_column(conn, "redeem_batches", col, ddl)
        conn.commit()
    finally:
        conn.close()
