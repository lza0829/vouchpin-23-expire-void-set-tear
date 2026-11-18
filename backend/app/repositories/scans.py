from __future__ import annotations
import sqlite3
from typing import Any


def issued_unredeemed(conn: sqlite3.Connection, business_day: str) -> list[dict[str, Any]]:
    """该业务日发放未核集合：当日发放、且至今未核销、未作废的券。"""
    rows = conn.execute(
        """
        SELECT i.coupon_code AS coupon_code, i.campaign_code AS campaign_code
        FROM coupon_events i
        WHERE i.business_day = ? AND i.event_type = 'issue'
          AND NOT EXISTS (
            SELECT 1 FROM coupon_events r
            WHERE r.coupon_code = i.coupon_code AND r.event_type = 'redeem'
          )
          AND NOT EXISTS (
            SELECT 1 FROM coupon_events v
            WHERE v.coupon_code = i.coupon_code AND v.event_type = 'void'
          )
        GROUP BY i.coupon_code, i.campaign_code
        ORDER BY i.coupon_code
        """,
        (business_day,),
    ).fetchall()
    return [dict(r) for r in rows]


def issued_count(conn: sqlite3.Connection, business_day: str) -> int:
    row = conn.execute(
        "SELECT COUNT(DISTINCT coupon_code) c FROM coupon_events WHERE business_day=? AND event_type='issue'",
        (business_day,),
    ).fetchone()
    return int(row["c"])


def max_event_id(conn: sqlite3.Connection, business_day: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(id), 0) m FROM coupon_events WHERE business_day=?",
        (business_day,),
    ).fetchone()
    return int(row["m"])


def new_issues_after(conn: sqlite3.Connection, business_day: str, event_id: int) -> int:
    """扫描覆盖点之后出现的新发放笔数（>0 即扫描已不覆盖当前集合）。"""
    row = conn.execute(
        "SELECT COUNT(*) c FROM coupon_events WHERE business_day=? AND event_type='issue' AND id>?",
        (business_day, int(event_id)),
    ).fetchone()
    return int(row["c"])


def insert_scan(conn: sqlite3.Connection, **fields: Any) -> int:
    cur = conn.execute(
        "INSERT INTO expire_scans(business_day, scanned_at, issued_count, voided_count, covered_event_id, note) VALUES(?,?,?,?,?,?)",
        (
            fields["business_day"],
            fields["scanned_at"],
            int(fields.get("issued_count") or 0),
            int(fields.get("voided_count") or 0),
            int(fields.get("covered_event_id") or 0),
            fields.get("note") or "",
        ),
    )
    return int(cur.lastrowid)


def get_scan(conn: sqlite3.Connection, scan_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM expire_scans WHERE id=?", (int(scan_id),)).fetchone()
    return dict(row) if row else None


def latest_scan_for_day(conn: sqlite3.Connection, business_day: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM expire_scans WHERE business_day=? ORDER BY id DESC LIMIT 1",
        (business_day,),
    ).fetchone()
    return dict(row) if row else None


def list_scans(conn: sqlite3.Connection, business_day: str | None = None) -> list[dict[str, Any]]:
    if business_day:
        rows = conn.execute(
            "SELECT * FROM expire_scans WHERE business_day=? ORDER BY id DESC",
            (business_day,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM expire_scans ORDER BY id DESC LIMIT 200").fetchall()
    return [dict(r) for r in rows]


def insert_item(conn: sqlite3.Connection, **fields: Any) -> int:
    cur = conn.execute(
        "INSERT INTO expire_scan_items(scan_id, coupon_code, campaign_code, void_event_id) VALUES(?,?,?,?)",
        (
            int(fields["scan_id"]),
            fields["coupon_code"],
            fields["campaign_code"],
            int(fields["void_event_id"]),
        ),
    )
    return int(cur.lastrowid)


def items_for_scan(conn: sqlite3.Connection, scan_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM expire_scan_items WHERE scan_id=? ORDER BY id",
        (int(scan_id),),
    ).fetchall()
    return [dict(r) for r in rows]
