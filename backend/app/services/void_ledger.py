from __future__ import annotations

from typing import Any

from app.repositories import events as event_repo
from app.repositories import facts as fact_repo
from app.repositories import scans as scan_repo

# 作废（void）的权威记录是事件流中的 void 事件。扫描清单、事实状态、预览
# 过滤、sealed 明细与总览过期计数全部以它为唯一口径：
#   - 扫描清单（expire_scan_items）= 本次扫描强制作废的券码集合；
#   - 事实 void 态 = 该券码对应 redeem_fact 的 status 变为 'void'；
#   - 预览/钉扎只消费 open 且无 void 事件的券码；
#   - 总览「过期计数」= 事件流 void ∩ 事实 void 的券码数，与清单逐条对齐。
#
# 扫描与钉扎的交错规则：扫描整批原子提交，失败/被写锁挡住即整批回滚；
# 钉扎只承认「事实已 void」的清单行，撕裂/半截一律拒绝并要求重扫。


def _fact_for_code(conn, coupon_code: str) -> dict[str, Any] | None:
    """券码对应的核销事实（跨业务日唯一，coupon_code 有唯一约束）。"""
    return fact_repo.fact_by_coupon(conn, coupon_code)


def claimed_codes(conn, business_day: str) -> list[dict[str, Any]]:
    """本次扫描应强制作废的券码清单。

    覆盖该业务日「发放未核且未作废」的集合；这些券码无论是否已有
    核销事实，都属于过期未核，必须由本次扫描强制作废。
    """
    issued = scan_repo.issued_unredeemed(conn, business_day)
    claimed: list[dict[str, Any]] = []
    for row in issued:
        code = str(row["coupon_code"])
        fact = _fact_for_code(conn, code)
        claimed.append(
            {
                "coupon_code": code,
                "campaign_code": row["campaign_code"],
                "amount": float(fact["amount"]) if fact else 0.0,
                "fact_id": int(fact["id"]) if fact else None,
            }
        )
    return claimed


def _force_void_fact(
    conn, *, day: str, code: str, campaign_code: str, void_event_id: int
) -> int:
    """把清单内券码的核销事实强制作废，并踢出任何 sealed 明细。

    若该券码从未核销（无事实行），补建一条金额 0 的 void 事实（event_id 指向
    本次 void 事件）。这样「扫描清单 / 事实 void 态 / 总览过期计数」三者逐条
    对齐：清单宣告作废的每个券码，都必然对应且仅对应一条 void 事实行。
    """
    fact = _fact_for_code(conn, code)
    if fact is None:
        return fact_repo.insert_fact(
            conn,
            coupon_code=code,
            campaign_code=campaign_code,
            amount=0.0,
            business_day=day,
            event_id=void_event_id,
            status="void",
        )
    batch_id = fact["batch_id"]
    fact_repo.mark_status(conn, int(fact["id"]), "void")
    if batch_id is not None:
        # 已进 sealed 的券码被作废后自动出明细，批头须同步收敛，
        # 避免「已 void 仍在 sealed 明细 / 批头含作废额」。
        # 保留 batch_id 作为审计回溯，状态 void 已足以将其排除出明细。
        from app.repositories import batches as batch_repo

        batch_repo.recompute_batch(conn, int(batch_id))
    return int(fact["id"])


def reconcile_void_facts(conn, business_day: str) -> int:
    """按事件流 void 记录重算事实 void 态（幂等，用于重扫自愈）。

    历史撕裂（回执已宣告作废、事实仍 open）不能让券码永久卡死：重扫时
    以事件流为权威，把每个 void 券码的事实拉回 void 并剔出 sealed 明细；
    若某 void 券码根本没有事实行，则补建一条 0 额 void 事实，保证
    「void 事件 ↔ void 事实行」严格 1:1，总览计数与清单不再分叉。
    返回本次修正/补齐的事实数。
    """
    fixed = 0
    for code in event_repo.void_coupon_codes(conn, business_day):
        fact = _fact_for_code(conn, code)
        if fact is None:
            fact_repo.insert_fact(
                conn,
                coupon_code=code,
                campaign_code=_campaign_for_code(conn, business_day, code),
                amount=0.0,
                business_day=business_day,
                event_id=_void_event_id(conn, code),
                status="void",
            )
            fixed += 1
            continue
        if fact["status"] == "void":
            continue
        batch_id = fact["batch_id"]
        fact_repo.mark_status(conn, int(fact["id"]), "void")
        if batch_id is not None:
            from app.repositories import batches as batch_repo

            batch_repo.recompute_batch(conn, int(batch_id))
        fixed += 1
    return fixed


def _void_event_id(conn, coupon_code: str) -> int:
    row = conn.execute(
        "SELECT id FROM coupon_events WHERE coupon_code=? AND event_type='void' ORDER BY id LIMIT 1",
        (coupon_code,),
    ).fetchone()
    return int(row["id"]) if row else 0


def _campaign_for_code(conn, business_day: str, coupon_code: str) -> str:
    row = conn.execute(
        "SELECT campaign_code FROM coupon_events WHERE coupon_code=? AND business_day=? ORDER BY id LIMIT 1",
        (coupon_code, business_day),
    ).fetchone()
    if row:
        return str(row["campaign_code"])
    row = conn.execute(
        "SELECT campaign_code FROM coupon_events WHERE coupon_code=? ORDER BY id LIMIT 1",
        (coupon_code,),
    ).fetchone()
    return str(row["campaign_code"]) if row else ""


def effective_void_codes(conn, business_day: str) -> list[str]:
    """该业务日权威作废集合：事件流 void ∩ 事实 void 态。

    两侧同时满足才算「已作废落定」；任何一侧缺失都说明口径撕裂，
    由 reconcile / 扫描自愈收敛。总览计数、清单、预览均以此为准。
    """
    events = set(event_repo.void_coupon_codes(conn, business_day))
    facts = fact_repo.void_fact_codes(conn, business_day)
    return sorted(events & facts)


def apply_scan(conn, *, day: str, now_iso: str, note: str, stop_after: int | None) -> dict[str, Any]:
    """执行一次过期扫描：整批原子写入，失败即整体回滚，不留半截 void。

    成功回执必须满足：清单内每个券码都已落 void 事件、事实已转 'void'、
    清单行可逐条回溯。任何一张写失败/中断即回滚整批，包括扫描批次本身，
    绝不让「回执 success」与「事实仍 open」并存。
    """
    # 重扫自愈：先按事件流 void 记录把遗留 open 的事实拉回 void，
    # 让「回执已作废但仍 open」的撕裂态在重扫后必然收敛。
    reconciled = reconcile_void_facts(conn, day)
    claimed = claimed_codes(conn, day)
    covered = scan_repo.max_event_id(conn, day)
    issued = scan_repo.issued_count(conn, day)
    scan_id = scan_repo.insert_scan(
        conn,
        business_day=day,
        scanned_at=now_iso,
        issued_count=issued,
        voided_count=0,
        covered_event_id=covered,
        note=note,
    )
    written = 0
    for row in claimed:
        code = str(row["coupon_code"])
        if event_repo.has_void_event(conn, code):
            # 幂等：已作废的券码不重复落事件，也不进本次清单。
            continue
        eid = event_repo.insert_event(
            conn,
            event_type="void",
            coupon_code=code,
            campaign_code=row["campaign_code"],
            amount=float(row.get("amount") or 0),
            business_day=day,
            occurred_at=now_iso,
            note=f"过期扫描作废 scan#{scan_id}",
        )
        scan_repo.insert_item(
            conn,
            scan_id=scan_id,
            coupon_code=code,
            campaign_code=row["campaign_code"],
            void_event_id=eid,
        )
        _force_void_fact(
            conn,
            day=day,
            code=code,
            campaign_code=row["campaign_code"],
            void_event_id=eid,
        )
        written += 1
        if stop_after is not None and written >= int(stop_after):
            # 故障注入：整体回滚，扫描批次与已写事件/清单/事实全部撤销。
            raise RuntimeError(
                f"扫描在第 {written} 张券后中断，整批回滚，未留下半截作废"
            )

    # 落库后自检：清单、事件流 void、事实 void 态三者必须逐条对齐。
    items = scan_repo.items_for_scan(conn, scan_id)
    scan_repo.update_scan_counts(
        conn, scan_id, issued_count=issued, voided_count=len(items)
    )
    listed = sorted(str(i["coupon_code"]) for i in items)
    void_codes = set(event_repo.void_coupon_codes(conn, day))
    if not set(listed).issubset(void_codes):
        raise RuntimeError(f"扫描 #{scan_id} 清单与事件流作废不一致")
    for i in items:
        fact = _fact_for_code(conn, str(i["coupon_code"]))
        if fact is not None and fact["status"] != "void":
            raise RuntimeError(f"扫描 #{scan_id} 回执未把事实 {i['coupon_code']} 置 void")

    return {
        "scan_id": scan_id,
        "business_day": day,
        "scanned_at": now_iso,
        "issued_count": issued,
        "voided_count": len(items),
        "covered_event_id": covered,
        "voided_coupons": listed,
        "void_fact_count": void_fact_count(conn, day),
        "reconciled_facts": reconciled,
        "facts_left_open": [],
        "success": True,
    }


def void_fact_only(conn, fact_id: int) -> dict[str, Any]:
    """作废旁路：作废单条核销事实，并把它从 sealed 明细中剔除。

    旁路与扫描清单同口径：
      - 事实转 'void'；
      - 若券码尚无 void 事件则补写一条（事件流仍是权威记录）；
      - 若事实已在 sealed 批内，则该券码须剔出批明细并重算批头，避免
        「已 void 却仍在 sealed 明细 / 批头含作废额」。
    """
    row = fact_repo.get_fact(conn, fact_id)
    if row is None:
        return {"found": False}
    business_day = str(row["business_day"])
    code = str(row["coupon_code"])

    if not event_repo.has_void_event(conn, code):
        event_repo.insert_event(
            conn,
            event_type="void",
            coupon_code=code,
            campaign_code=row["campaign_code"],
            amount=float(row["amount"]),
            business_day=business_day,
            occurred_at=_now_iso(),
            note="作废旁路",
        )

    batch_id = row["batch_id"]
    fact_repo.mark_status(conn, int(fact_id), "void")

    batch_removed = False
    if batch_id is not None:
        from app.repositories import batches as batch_repo

        batch_repo.recompute_batch(conn, int(batch_id))
        batch_removed = True

    return {
        "fact_id": int(fact_id),
        "status": "void",
        "coupon_code": code,
        "batch_id": batch_id,
        "removed_from_batch": batch_removed,
        "scan_count_unchanged": True,
    }


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().replace(microsecond=0).isoformat()


def void_fact_count(conn, business_day: str) -> int:
    """该业务日事实里 status='void' 的行数（与权威作废集合逐条对齐）。"""
    row = conn.execute(
        "SELECT COUNT(*) c FROM redeem_facts WHERE business_day=? AND status='void'",
        (business_day,),
    ).fetchone()
    return int(row["c"])
