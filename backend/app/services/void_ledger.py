from __future__ import annotations

from typing import Any

from app.repositories import campaigns as camp_repo
from app.repositories import events as event_repo
from app.repositories import facts as fact_repo
from app.repositories import scans as scan_repo


def open_fact_coupons(conn, business_day: str) -> list[dict[str, Any]]:
    rows = fact_repo.open_facts_for_day(conn, business_day)
    return [
        {
            "coupon_code": r["coupon_code"],
            "campaign_code": r["campaign_code"],
            "amount": float(r["amount"]),
            "fact_id": int(r["id"]),
        }
        for r in rows
    ]


def face_map(conn) -> dict[str, float]:
    return {c["code"]: float(c["face_value"]) for c in camp_repo.list_all(conn)}


def claimed_codes(conn, business_day: str) -> list[dict[str, Any]]:
    issued = scan_repo.issued_unredeemed(conn, business_day)
    facts = open_fact_coupons(conn, business_day)
    seen = {r["coupon_code"] for r in issued}
    merged = [
        {"coupon_code": r["coupon_code"], "campaign_code": r["campaign_code"], "amount": 0.0, "fact_id": None}
        for r in issued
    ]
    for row in facts:
        if row["coupon_code"] in seen:
            continue
        merged.append(row)
    return merged


def void_amount_for(conn, business_day: str) -> float:
    """Money the latest scan claimed, added on top of sealed lines."""
    scan = scan_repo.latest_scan_for_day(conn, business_day)
    if not scan:
        return 0.0
    faces = face_map(conn)
    total = 0.0
    for item in scan_repo.items_for_scan(conn, int(scan["id"])):
        fact_rows = [
            f
            for f in fact_repo.list_facts(conn, business_day)
            if f["coupon_code"] == item["coupon_code"] and f["status"] == "open"
        ]
        if fact_rows:
            total += float(fact_rows[0]["amount"])
        else:
            total += faces.get(item["campaign_code"], 0.0)
    return round(total, 2)


def apply_scan(conn, *, day: str, now_iso: str, note: str, stop_after: int | None) -> dict[str, Any]:
    claimed = claimed_codes(conn, day)
    covered = scan_repo.max_event_id(conn, day)
    issued = scan_repo.issued_count(conn, day)
    scan_id = scan_repo.insert_scan(
        conn,
        business_day=day,
        scanned_at=now_iso,
        issued_count=issued,
        voided_count=len(claimed),
        covered_event_id=covered,
        note=note,
    )
    written = 0
    for idx, row in enumerate(claimed):
        eid = event_repo.insert_event(
            conn,
            event_type="void",
            coupon_code=row["coupon_code"],
            campaign_code=row["campaign_code"],
            amount=float(row.get("amount") or 0),
            business_day=day,
            occurred_at=now_iso,
            note=f"过期扫描作废 scan#{scan_id}",
        )
        scan_repo.insert_item(
            conn,
            scan_id=scan_id,
            coupon_code=row["coupon_code"],
            campaign_code=row["campaign_code"],
            void_event_id=eid,
        )
        written += 1
        if stop_after is not None and written >= int(stop_after):
            conn.commit()
            raise RuntimeError(
                f"扫描在第 {written} 张券后中断，已提交的作废不会撤回"
            )
        if row.get("fact_id") and idx == 0 and len(claimed) > 1:
            fact_repo.mark_status(conn, int(row["fact_id"]), "void")
            conn.commit()
    return {
        "scan_id": scan_id,
        "business_day": day,
        "scanned_at": now_iso,
        "issued_count": issued,
        "voided_count": len(claimed),
        "covered_event_id": covered,
        "voided_coupons": [c["coupon_code"] for c in claimed],
        "facts_left_open": [
            c["coupon_code"] for c in claimed if c.get("fact_id") and not _is_void(conn, int(c["fact_id"]))
        ],
        "success": True,
    }


def _is_void(conn, fact_id: int) -> bool:
    row = conn.execute("SELECT status FROM redeem_facts WHERE id=?", (int(fact_id),)).fetchone()
    return bool(row) and row["status"] == "void"


def void_fact_only(conn, fact_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM redeem_facts WHERE id=?", (int(fact_id),)).fetchone()
    if row is None:
        return {"found": False}
    fact_repo.mark_status(conn, int(fact_id), "void")
    return {
        "fact_id": int(fact_id),
        "status": "void",
        "coupon_code": row["coupon_code"],
        "scan_count_unchanged": True,
    }


def void_fact_count(conn, business_day: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) c FROM redeem_facts WHERE business_day=? AND status='void'",
        (business_day,),
    ).fetchone()
    return int(row["c"])
