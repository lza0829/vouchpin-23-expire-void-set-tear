from __future__ import annotations
import sqlite3
from datetime import datetime, timedelta
from typing import Any
from fastapi import HTTPException
from app.db import connect
from app.repositories import settings as settings_repo
from app.repositories import events as event_repo
from app.repositories import facts as fact_repo
from app.repositories import scans as scan_repo
from app.services import settings_service

# 全局唯一策略：钉前必须扫描（expire-before-nail gate）。
# 钉扎请求须携带本次 expire_scan_id；扫描须覆盖该业务日发放未核集合；
# 无有效扫描 / 扫描跨日 / 扫描超 TTL / 扫描后有新发放，一律拒钉。
SCAN_POLICY = "required"


def _is_busy(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "locked" in msg or "busy" in msg


def _scan_state(conn: sqlite3.Connection, business_day: str, scan: dict[str, Any]) -> tuple[str, str]:
    """单次扫描的时效状态：valid / expired(超 TTL) / stale(扫描后有新发放)。"""
    ttl = settings_service.scan_ttl_seconds(conn)
    scanned_at = datetime.fromisoformat(scan["scanned_at"])
    if datetime.now() > scanned_at + timedelta(seconds=ttl):
        return "expired", f"扫描 #{scan['id']} 已过期（TTL {ttl}s），需重新扫描"
    new_issues = scan_repo.new_issues_after(conn, business_day, scan["covered_event_id"])
    if new_issues:
        return "stale", f"扫描 #{scan['id']} 后新增 {new_issues} 笔发放，集合已变化，需重新扫描"
    return "valid", ""


def day_gate(conn: sqlite3.Connection, business_day: str) -> dict[str, Any]:
    """业务日维度的闸口状态（预览/总览同源）：取当日最新扫描并评估时效。"""
    ttl = settings_service.scan_ttl_seconds(conn)
    scan = scan_repo.latest_scan_for_day(conn, business_day)
    if not scan:
        return {
            "policy": SCAN_POLICY,
            "state": "none",
            "allowed": False,
            "reason": "钉前必须执行过期扫描",
            "scan": None,
            "ttl_seconds": ttl,
        }
    state, reason = _scan_state(conn, business_day, scan)
    return {
        "policy": SCAN_POLICY,
        "state": state,
        "allowed": state == "valid",
        "reason": reason,
        "scan": scan,
        "ttl_seconds": ttl,
    }


def seal_gate(conn: sqlite3.Connection, business_day: str, scan_id: int | None) -> dict[str, Any]:
    """钉扎闸口（唯一强制点）：校验请求携带的 expire_scan_id。"""
    if scan_id is None:
        return {"ok": False, "reason": "钉前必须完成过期扫描：请求须携带 expire_scan_id", "scan": None}
    scan = scan_repo.get_scan(conn, scan_id)
    if not scan:
        return {"ok": False, "reason": f"无有效扫描：expire_scan #{scan_id} 不存在", "scan": None}
    if scan["business_day"] != business_day:
        return {
            "ok": False,
            "reason": f"扫描 #{scan_id} 属于业务日 {scan['business_day']}，不能用于 {business_day}",
            "scan": None,
        }
    state, reason = _scan_state(conn, business_day, scan)
    if state != "valid":
        return {"ok": False, "reason": reason, "scan": scan}
    return {"ok": True, "reason": "", "scan": scan}


def run_scan(body: dict[str, Any]) -> dict[str, Any]:
    """过期扫描：覆盖该业务日发放未核集合，作废入事件流，落扫描批次。

    事务语义：整批原子提交。任何一张券写入失败或中途中断都整体回滚
    （扫描批次、void 事件、清单行、事实 void 态全部撤销），回执不会
    出现 success 却留下半截作废。
    """
    try:
        conn = connect(immediate=True)
    except sqlite3.OperationalError as exc:
        if _is_busy(exc):
            # 与钉扎交错：连写事务都抢不到，整批不开始，绝不留下半截。
            raise HTTPException(409, "扫描与钉扎交错：请等待钉扎完成或稍后重试") from exc
        raise
    try:
        day = body.get("business_day") or settings_repo.get(conn, "business_day")
        if fact_repo.day_is_sealed(conn, day):
            raise HTTPException(409, f"业务日 {day} 已钉扎，禁止再扫描")
        now = datetime.now().replace(microsecond=0)
        from app.services import void_ledger
        stop_after = body.get("stop_after")
        try:
            result = void_ledger.apply_scan(
                conn,
                day=day,
                now_iso=now.isoformat(),
                note=body.get("note") or "",
                stop_after=int(stop_after) if stop_after not in (None, "") else None,
            )
        except RuntimeError as exc:
            conn.rollback()
            raise HTTPException(500, str(exc)) from exc
        except sqlite3.OperationalError as exc:
            conn.rollback()
            if _is_busy(exc):
                # 与钉扎交错：等待写锁失败即整批放弃，绝不带出半截结果。
                raise HTTPException(409, "扫描与钉扎交错：请等待钉扎完成或稍后重试") from exc
            raise
        except Exception:
            conn.rollback()
            raise
        conn.commit()
        return result
    finally:
        conn.close()


def list_scans(business_day: str | None = None) -> list[dict[str, Any]]:
    conn = connect()
    try:
        day = business_day or settings_repo.get(conn, "business_day")
        scans = scan_repo.list_scans(conn, day)
        for s in scans:
            state, reason = _scan_state(conn, day, s)
            s["state"] = state
            s["state_reason"] = reason
            voided = scan_repo.void_items_for_scan(conn, int(s["id"]))
            s["voided_count_effective"] = len(voided)
            s["void_consistent"] = len(voided) == int(s.get("voided_count") or 0)
        return scans
    finally:
        conn.close()


def scan_detail(scan_id: int) -> dict[str, Any]:
    conn = connect()
    try:
        scan = scan_repo.get_scan(conn, scan_id)
        if not scan:
            raise HTTPException(404, f"扫描批次 #{scan_id} 不存在")
        state, reason = _scan_state(conn, scan["business_day"], scan)
        scan["state"] = state
        scan["state_reason"] = reason
        declared = scan_repo.items_for_scan(conn, scan_id)
        voided_codes = {
            str(i["coupon_code"]) for i in scan_repo.void_items_for_scan(conn, scan_id)
        }
        # 事实 void 态为准：重算扫描清单，只有事实已 void 的券码才算「已作废」。
        effective = [i for i in declared if str(i["coupon_code"]) in voided_codes]
        scan["items"] = effective
        scan["declared_items"] = declared
        scan["voided_count_effective"] = len(effective)
        scan["void_consistent"] = len(effective) == len(declared)
        return scan
    finally:
        conn.close()
