from __future__ import annotations
import sqlite3
from typing import Any


def list_batches(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM redeem_batches ORDER BY id DESC").fetchall()]


def get_batch(conn: sqlite3.Connection, batch_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM redeem_batches WHERE id=?", (int(batch_id),)).fetchone()
    return dict(row) if row else None


def create_batch(conn: sqlite3.Connection, **fields: Any) -> int:
    cur = conn.execute(
        "INSERT INTO redeem_batches(business_day, status, fact_count, total_amount, sealed_at, note, expire_scan_id, scan_scanned_at, scan_voided_count) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            fields["business_day"],
            fields.get("status") or "sealed",
            int(fields.get("fact_count") or 0),
            float(fields.get("total_amount") or 0),
            fields.get("sealed_at"),
            fields.get("note") or "",
            fields.get("expire_scan_id"),
            fields.get("scan_scanned_at"),
            fields.get("scan_voided_count"),
        ),
    )
    return int(cur.lastrowid)


def recompute_batch(conn: sqlite3.Connection, batch_id: int) -> dict[str, Any] | None:
    """按 sealed 明细（仍为 sealed 的事实）重算批头笔数与合计。

    作废旁路把已 sealed 的事实转 void 后，它自动从明细口径中剔除；批头
    必须同步收敛，否则「sealed 明细 / void 态 / 总览计数」三处口径再次分叉。
    保留 fact.batch_id 作为审计回溯（该券曾属哪一批），但不再计入明细。
    """
    rows = conn.execute(
        "SELECT amount FROM redeem_facts WHERE batch_id=? AND status='sealed' ORDER BY id",
        (int(batch_id),),
    ).fetchall()
    count = len(rows)
    total = round(sum(float(r["amount"]) for r in rows), 2)
    conn.execute(
        "UPDATE redeem_batches SET fact_count=?, total_amount=? WHERE id=?",
        (count, total, int(batch_id)),
    )
    return get_batch(conn, batch_id)
