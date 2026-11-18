from __future__ import annotations
import sqlite3
from typing import Any


def list_events(conn: sqlite3.Connection, business_day: str | None = None) -> list[dict[str, Any]]:
    if business_day:
        rows = conn.execute(
            "SELECT * FROM coupon_events WHERE business_day=? ORDER BY id",
            (business_day,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM coupon_events ORDER BY id DESC LIMIT 200").fetchall()
    return [dict(r) for r in rows]


def void_coupon_codes(conn: sqlite3.Connection, business_day: str) -> list[str]:
    """该业务日已作废券码（事件流为准，去重升序）。

    「作废」的唯一权威记录是事件流中的 void 事件；扫描清单、事实状态、
    总览过期计数都必须能回溯到这份记录。
    """
    rows = conn.execute(
        """
        SELECT DISTINCT coupon_code FROM coupon_events
        WHERE business_day=? AND event_type='void'
        ORDER BY coupon_code
        """,
        (business_day,),
    ).fetchall()
    return [str(r["coupon_code"]) for r in rows]


def has_void_event(conn: sqlite3.Connection, coupon_code: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM coupon_events WHERE coupon_code=? AND event_type='void' LIMIT 1",
        (coupon_code,),
    ).fetchone()
    return row is not None


def insert_event(conn: sqlite3.Connection, **fields: Any) -> int:
    cur = conn.execute(
        "INSERT INTO coupon_events(event_type, coupon_code, campaign_code, amount, business_day, occurred_at, note) VALUES(?,?,?,?,?,?,?)",
        (
            fields["event_type"],
            fields["coupon_code"],
            fields["campaign_code"],
            float(fields.get("amount") or 0),
            fields["business_day"],
            fields["occurred_at"],
            fields.get("note") or "",
        ),
    )
    return int(cur.lastrowid)
