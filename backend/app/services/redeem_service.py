from __future__ import annotations
import sqlite3
from datetime import datetime
from typing import Any
from fastapi import HTTPException
from app.db import connect
from app.repositories import settings as settings_repo
from app.repositories import facts as fact_repo
from app.repositories import batches as batch_repo
from app.repositories import events as event_repo
from app.repositories import scans as scan_repo
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
        from app.services import void_ledger

        scan = gate.get("scan") or {}
        scan_id = scan.get("id")
        declared = (
            scan_repo.items_for_scan(conn, int(scan_id)) if scan_id else []
        )
        voided = (
            scan_repo.void_items_for_scan(conn, int(scan_id)) if scan_id else []
        )
        declared_codes = {str(i["coupon_code"]) for i in declared}
        listed = {str(i["coupon_code"]) for i in voided}
        open_codes = {str(f["coupon_code"]) for f in opens}
        # 事实 void 态为准：清单宣告作废、事实却仍未 void 的券码 = 撕裂集合。
        torn = sorted(declared_codes - listed)
        # 清单内已作废券码若仍出现在 open 事实里，也不得进预览。
        still_open = sorted(listed & open_codes)
        if sealed:
            allowed, reason = False, "业务日已钉扎"
        elif torn:
            allowed, reason = False, "扫描清单已宣告作废但事实未落 void，须重新扫描"
        elif still_open:
            allowed, reason = False, "扫描清单内已作废券码仍为 open，预览不可用"
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
            "scan_voided_coupons": sorted(listed),
            "scan_declared_coupons": sorted(declared_codes),
            "scan_void_still_open": still_open,
            "scan_void_torn": torn,
            "void_fact_count": void_ledger.void_fact_count(conn, day),
        }
    finally:
        conn.close()


def seal(body: dict[str, Any]) -> dict[str, Any]:
    try:
        conn = connect(immediate=True)
    except sqlite3.OperationalError as exc:
        if expire_service._is_busy(exc):
            raise HTTPException(409, "钉扎与扫描交错：请等待扫描完成或重新扫描后再钉") from exc
        raise
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
        scan = gate["scan"]

        # 事实 void 态为准：扫描清单只对「事实已 void」的券码生效。
        scan_items = scan_repo.items_for_scan(conn, int(scan["id"]))
        voided_items = scan_repo.void_items_for_scan(conn, int(scan["id"]))
        listed = {str(i["coupon_code"]) for i in voided_items}

        opens = fact_repo.open_facts_for_day(conn, day)
        # 清单宣告作废但事实仍未 void（半截/撕裂）：既不信任该清单，
        # 也绝不让这些 open 码钉进 sealed；要求重扫收敛。
        declared = {str(i["coupon_code"]) for i in scan_items}
        torn = sorted(declared - listed)
        if torn:
            raise HTTPException(
                409,
                "扫描清单已宣告作废但这些券码事实未落 void，须重新扫描："
                + ", ".join(torn),
            )
        # open_facts_for_day 已排除有 void 事件的券码；这里再断言一次，
        # 防止未来查询改动让「已作废仍可钉进 sealed」回归。
        leaked = [f for f in opens if event_repo.has_void_event(conn, str(f["coupon_code"]))]
        if leaked:  # pragma: no cover - 不可达，仅作不变量护栏
            raise HTTPException(
                409,
                "扫描清单内已作废券码不得钉入 sealed："
                + ", ".join(str(f["coupon_code"]) for f in leaked),
            )
        if not opens:
            raise HTTPException(400, "无可钉扎的 open 核销事实")

        # 批头合计只统计 sealed 明细（open 事实），作废额不并入。
        total = round(sum(float(f["amount"]) for f in opens), 2)
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
            scan_voided_count=len(voided_items),
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
            "scan_voided_count": len(voided_items),
            "scan_voided_coupons": sorted(listed),
            "sealed_coupons": sorted(str(f["coupon_code"]) for f in opens),
        }
    except HTTPException:
        conn.rollback()
        raise
    except sqlite3.OperationalError as exc:
        conn.rollback()
        if expire_service._is_busy(exc):
            # 与扫描交错：钉扎抢不到写锁即整笔失败，不带着旧清单钉进 sealed。
            raise HTTPException(409, "钉扎与扫描交错：请等待扫描完成或重新扫描后再钉") from exc
        raise
    finally:
        conn.close()


def list_batches() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return batch_repo.list_batches(conn)
    finally:
        conn.close()
