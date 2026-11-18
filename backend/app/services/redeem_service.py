from __future__ import annotations
from datetime import datetime
from typing import Any
from fastapi import HTTPException
from app.db import connect
from app.repositories import settings as settings_repo
from app.repositories import facts as fact_repo
from app.repositories import batches as batch_repo
from app.services import expire_service


def list_facts(business_day: str | None = None) -> list[dict[str, Any]]:
    conn = connect()
    try:
        day = business_day or settings_repo.get(conn, "business_day")
        return fact_repo.list_facts(conn, day)
    finally:
        conn.close()


def preview(business_day: str | None = None) -> dict[str, Any]:
    conn = connect()
    try:
        day = business_day or settings_repo.get(conn, "business_day")
        opens = fact_repo.open_facts_for_day(conn, day)
        total = round(sum(float(f["amount"]) for f in opens), 2)
        sealed = fact_repo.day_is_sealed(conn, day)
        gate = expire_service.day_gate(conn, day)
        if sealed:
            allowed, reason = False, "业务日已钉扎"
        elif not opens:
            allowed, reason = False, "无可钉扎的 open 核销事实"
        elif not gate["allowed"]:
            allowed, reason = False, gate["reason"]
        else:
            allowed, reason = True, ""
        return {
            "business_day": day,
            "open_count": len(opens),
            "open_total": total,
            "already_sealed": sealed,
            "expire_scan": gate,
            "seal_gate": {"allowed": allowed, "reason": reason},
            "facts": opens,
        }
    finally:
        conn.close()


def seal(body: dict[str, Any]) -> dict[str, Any]:
    conn = connect(immediate=True)
    try:
        day = body.get("business_day") or settings_repo.get(conn, "business_day")
        if fact_repo.day_is_sealed(conn, day):
            raise HTTPException(409, f"业务日 {day} 已有 sealed 钉扎批")
        scan_id = body.get("expire_scan_id")
        if scan_id is not None:
            try:
                scan_id = int(scan_id)
            except (TypeError, ValueError):
                raise HTTPException(400, "expire_scan_id 必须为整数")
        gate = expire_service.seal_gate(conn, day, scan_id)
        if not gate["ok"]:
            raise HTTPException(409, gate["reason"])
        opens = fact_repo.open_facts_for_day(conn, day)
        if not opens:
            raise HTTPException(400, "无可钉扎的 open 核销事实")
        scan = gate["scan"]
        total = round(sum(float(f["amount"]) for f in opens), 2)
        from app.services import void_ledger
        void_extra = void_ledger.void_amount_for(conn, day)
        total = round(total + void_extra, 2)
        bid = batch_repo.create_batch(
            conn,
            business_day=day,
            status="sealed",
            fact_count=len(opens),
            total_amount=total,
            sealed_at=datetime.now().replace(microsecond=0).isoformat(),
            note=body.get("note") or "",
            expire_scan_id=scan["id"],
            scan_scanned_at=scan["scanned_at"],
            scan_voided_count=scan["voided_count"],
        )
        fact_repo.mark_batched(conn, [int(f["id"]) for f in opens], bid)
        conn.commit()
        return {
            "batch_id": bid,
            "business_day": day,
            "fact_count": len(opens),
            "total_amount": total,
            "status": "sealed",
            "expire_scan_id": scan["id"],
            "scan_voided_count": scan["voided_count"],
        }
    finally:
        conn.close()


def list_batches() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return batch_repo.list_batches(conn)
    finally:
        conn.close()
