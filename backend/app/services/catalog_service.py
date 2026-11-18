from __future__ import annotations
from typing import Any
from app.db import connect
from app.repositories import settings as settings_repo
from app.repositories import facts as fact_repo
from app.repositories import batches as batch_repo
from app.repositories import events as event_repo
from app.services import expire_service


def dashboard() -> dict[str, Any]:
    conn = connect()
    try:
        day = settings_repo.get(conn, "business_day")
        facts = fact_repo.list_facts(conn, day)
        open_n = sum(1 for f in facts if f["status"] == "open")
        sealed_n = sum(1 for f in facts if f["status"] == "sealed")
        # 作废额不并入核销合计：合计只统计未作废事实。
        total = round(
            sum(float(f["amount"]) for f in facts if f["status"] != "void"), 2
        )
        events = event_repo.list_events(conn, day)
        batches = batch_repo.list_batches(conn)
        sealed_today = fact_repo.day_is_sealed(conn, day)
        gate = expire_service.day_gate(conn, day)
        from app.services import void_ledger
        # 总览「过期计数」与事实 void 态、扫描清单同口径：以权威作废集合
        # （事件流 void ∩ 事实 void）为准，不再采信扫描批头快照。
        effective = void_ledger.effective_void_codes(conn, day)
        voided_facts = len(effective)
        scan = (gate.get("scan") or {}) if isinstance(gate, dict) else {}
        return {
            "business_day": day,
            "event_count": len(events),
            "fact_count": len(facts),
            "open_fact_count": open_n,
            "sealed_fact_count": sealed_n,
            "redeem_total_today": total,
            "batch_count": len(batches),
            "day_sealed": sealed_today,
            "expire_scan": gate,
            "expire_count": voided_facts,
            "expire_void_coupons": effective,
            "scan_listed_count": int(scan.get("voided_count") or 0),
            "void_fact_count": voided_facts,
        }
    finally:
        conn.close()
