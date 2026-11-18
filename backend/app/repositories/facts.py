from __future__ import annotations
import sqlite3
from typing import Any


def list_facts(conn: sqlite3.Connection, business_day: str | None = None) -> list[dict[str, Any]]:
    if business_day:
        rows = conn.execute(
            "SELECT * FROM redeem_facts WHERE business_day=? ORDER BY id",
            (business_day,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM redeem_facts ORDER BY id DESC LIMIT 200").fetchall()
    return [dict(r) for r in rows]


def insert_fact(conn: sqlite3.Connection, **fields: Any) -> int:
    cur = conn.execute(
        "INSERT INTO redeem_facts(coupon_code, campaign_code, amount, business_day, event_id, status) VALUES(?,?,?,?,?,?)",
        (
            fields["coupon_code"],
            fields["campaign_code"],
            float(fields["amount"]),
            fields["business_day"],
            int(fields["event_id"]),
            fields.get("status") or "open",
        ),
    )
    return int(cur.lastrowid)


def get_fact(conn: sqlite3.Connection, fact_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM redeem_facts WHERE id=?", (int(fact_id),)).fetchone()
    return dict(row) if row else None


def fact_by_coupon(conn: sqlite3.Connection, coupon_code: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM redeem_facts WHERE coupon_code=?", (coupon_code,)
    ).fetchone()
    return dict(row) if row else None


def open_facts_for_day(conn: sqlite3.Connection, business_day: str) -> list[dict[str, Any]]:
    """该业务日可钉的 open 事实。

    同口径约束：券码一旦在事件流中出现 void（扫描作废或旁路作废），
    其事实即使遗留为 open 也不得进入预览 / sealed。
    """
    rows = conn.execute(
        """
        SELECT f.* FROM redeem_facts f
        WHERE f.business_day=? AND f.status='open'
          AND NOT EXISTS (
            SELECT 1 FROM coupon_events v
            WHERE v.coupon_code = f.coupon_code AND v.event_type = 'void'
          )
        ORDER BY f.id
        """,
        (business_day,),
    ).fetchall()
    return [dict(r) for r in rows]


def void_fact_codes(conn: sqlite3.Connection, business_day: str) -> set[str]:
    rows = conn.execute(
        "SELECT coupon_code FROM redeem_facts WHERE business_day=? AND status='void'",
        (business_day,),
    ).fetchall()
    return {str(r["coupon_code"]) for r in rows}


def mark_status(conn: sqlite3.Connection, fact_id: int, status: str) -> None:
    conn.execute(
        "UPDATE redeem_facts SET status=? WHERE id=?",
        (status, int(fact_id)),
    )


def mark_batched(conn: sqlite3.Connection, fact_ids: list[int], batch_id: int) -> None:
    for fid in fact_ids:
        conn.execute(
            "UPDATE redeem_facts SET status='sealed', batch_id=? WHERE id=?",
            (batch_id, fid),
        )


def day_is_sealed(conn: sqlite3.Connection, business_day: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM redeem_batches WHERE business_day=? AND status='sealed' LIMIT 1",
        (business_day,),
    ).fetchone()
    return row is not None
