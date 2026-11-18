"""过期扫描 / 事实 void 态 / 预览过滤 / 钉写批 / 总览计数 的联调口径测试。

权威口径：扫描批清单为准（清单内码强制作废事实并踢出预览），
事实 void 态为唯一落定记录。夹具覆盖：
  - 「回执作废仍 open」
  - 「失败半截 void」
  - 「扫描中钉进清单码」
  - 「计数≠void 行」
以及扫描与钉扎交错的整批回滚 / 拒钉。
"""
from __future__ import annotations

import threading
import time

import app.db as db


def set_day(client, day):
    r = client.put("/api/settings/day", json={"business_day": day})
    assert r.status_code == 200


def add_event(client, et, code, camp="NEW10", amount=None):
    body = {"event_type": et, "coupon_code": code, "campaign_code": camp}
    if amount is not None:
        body["amount"] = amount
    return client.post("/api/events", json=body)


def scan(client, **kw):
    return client.post("/api/expire/scan", json=kw)


def seal(client, **kw):
    return client.post("/api/redeem/seal", json=kw)


def _tear_scan_item(scan_id, code, campaign="NEW10", day="2099-01-01"):
    """制造历史撕裂：清单宣告作废 + void 事件，但事实仍保持 open。"""
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO coupon_events(event_type,coupon_code,campaign_code,amount,business_day,occurred_at,note) "
            "VALUES('void',?,?,10,?,?,'torn')",
            (code, campaign, day, f"{day}T20:00:00"),
        )
        eid = conn.execute("SELECT last_insert_rowid() i").fetchone()["i"]
        conn.execute(
            "INSERT INTO expire_scan_items(scan_id,coupon_code,campaign_code,void_event_id) VALUES(?,?,?,?)",
            (scan_id, code, campaign, eid),
        )
        conn.execute(
            "UPDATE expire_scans SET voided_count=voided_count+1 WHERE id=?", (scan_id,)
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- 夹具 1
def test_receipt_voided_but_fact_open_blocks_preview_and_seal(client):
    """「回执作废仍 open」：事实 void 态为准——撕裂态不得进预览，重扫后自愈。"""
    day = "2099-11-01"
    set_day(client, day)
    add_event(client, "issue", "R-1")
    add_event(client, "redeem", "R-1", amount=10)
    sid = scan(client).json()["scan_id"]
    _tear_scan_item(sid, "R-1", day=day)

    p = client.get("/api/redeem/preview").json()
    assert p["seal_gate"]["allowed"] is False
    assert "void" in p["seal_gate"]["reason"]
    assert p["scan_void_torn"] == ["R-1"]
    assert client.get("/api/redeem/preview").json()["facts"] == []

    r = seal(client, expire_scan_id=sid)
    assert r.status_code == 409
    assert client.get("/api/batches").json() == []

    # 重扫按事件流重算清单与事实 void 态，撕裂收敛。
    s2 = scan(client).json()
    assert s2["reconciled_facts"] == 1
    assert s2["void_fact_count"] == 1
    facts = [(f["coupon_code"], f["status"]) for f in client.get("/api/facts").json()]
    assert facts == [("R-1", "void")]
    assert client.get("/api/dashboard").json()["expire_count"] == 1


# ---------------------------------------------------------------- 夹具 2
def test_failed_scan_rolls_back_no_partial_void(client):
    """「失败半截 void」：扫描中断整批回滚——无扫描批、无 void 事件、无事实。"""
    day = "2099-11-02"
    set_day(client, day)
    for code in ("H-1", "H-2", "H-3"):
        add_event(client, "issue", code)

    r = scan(client, stop_after=2)
    assert r.status_code == 500
    assert "回滚" in r.json()["detail"]

    assert client.get("/api/expire/scans").json() == []
    events = client.get("/api/events").json()
    assert [e["event_type"] for e in events] == ["issue", "issue", "issue"]
    assert client.get("/api/facts").json() == []
    d = client.get("/api/dashboard").json()
    assert d["expire_count"] == 0 and d["void_fact_count"] == 0

    # 失败后仍可正常整批扫描并钉扎。
    ok = scan(client).json()
    assert sorted(ok["voided_coupons"]) == ["H-1", "H-2", "H-3"]
    assert ok["void_fact_count"] == 3


# ---------------------------------------------------------------- 夹具 3
def test_scan_nail_interleave_never_seals_listed_codes(client):
    """「扫描中钉进清单码」：清单内码必须已 void 且不得进 sealed 明细。"""
    day = "2099-11-03"
    set_day(client, day)
    add_event(client, "issue", "N-1")
    add_event(client, "issue", "N-2")
    add_event(client, "redeem", "N-2", amount=10)

    sd = scan(client).json()
    assert sd["voided_coupons"] == ["N-1"]
    assert sd["void_fact_count"] == 1

    # N-1 已被扫描作废 → 不进预览；sealed 明细只含 N-2。
    p = client.get("/api/redeem/preview").json()
    assert [f["coupon_code"] for f in p["facts"]] == ["N-2"]

    r = seal(client, expire_scan_id=sd["scan_id"]).json()
    assert r["sealed_coupons"] == ["N-2"]
    assert r["scan_voided_coupons"] == ["N-1"]
    assert r["scan_voided_count"] == 1
    # 批头只计 sealed 明细，作废额不并入。
    assert r["fact_count"] == 1 and r["total_amount"] == 10.0


def test_listed_code_still_open_blocks_seal(client):
    """清单宣告作废但事实未 void：钉扎必须 409，不得钉进 sealed。"""
    day = "2099-11-04"
    set_day(client, day)
    add_event(client, "issue", "S-1")
    add_event(client, "redeem", "S-1", amount=10)
    sid = scan(client).json()["scan_id"]
    _tear_scan_item(sid, "S-1", day=day)

    r = seal(client, expire_scan_id=sid)
    assert r.status_code == 409
    assert "void" in r.json()["detail"]
    assert client.get("/api/batches").json() == []


# ---------------------------------------------------------------- 夹具 4
def test_expire_count_equals_void_rows(client):
    """「计数≠void 行」：总览过期计数必须与 void 事实行逐条对齐。"""
    day = "2099-11-05"
    set_day(client, day)
    add_event(client, "issue", "C-1")              # 从未核销
    add_event(client, "issue", "C-2")              # 从未核销
    add_event(client, "issue", "C-3")
    add_event(client, "redeem", "C-3", amount=7)   # 已核销，不在过期集合

    sd = scan(client).json()
    assert sorted(sd["voided_coupons"]) == ["C-1", "C-2"]
    assert sd["voided_count"] == len(sd["voided_coupons"]) == 2

    facts = client.get("/api/facts").json()
    void_rows = [f for f in facts if f["status"] == "void"]
    assert sorted(f["coupon_code"] for f in void_rows) == ["C-1", "C-2"]

    d = client.get("/api/dashboard").json()
    assert d["expire_count"] == len(void_rows) == 2
    assert d["void_fact_count"] == 2
    assert d["expire_void_coupons"] == ["C-1", "C-2"]

    detail = client.get(f"/api/expire/scans/{sd['scan_id']}").json()
    assert [i["coupon_code"] for i in detail["items"]] == ["C-1", "C-2"]
    assert detail["voided_count_effective"] == 2
    assert detail["void_consistent"] is True


def test_scan_does_not_void_redeemed_coupons(client):
    """清单外仍 open 不得被本扫描宣称已过期：已核销券不进扫描清单。"""
    day = "2099-11-06"
    set_day(client, day)
    add_event(client, "issue", "X-1")
    add_event(client, "redeem", "X-1", amount=10)

    sd = scan(client).json()
    assert sd["voided_coupons"] == []
    assert sd["voided_count"] == 0
    assert [f["coupon_code"] for f in client.get("/api/redeem/preview").json()["facts"]] == ["X-1"]


# ------------------------------------------------------- sealed 明细 / 旁路
def test_bypass_void_removes_from_sealed_detail(client):
    """作废旁路：已 sealed 的券被作废后剔出明细、批头收敛，且不得残留双态。"""
    day = "2099-11-07"
    set_day(client, day)
    add_event(client, "issue", "B-1")
    add_event(client, "issue", "B-2")
    add_event(client, "redeem", "B-1", amount=10)
    add_event(client, "redeem", "B-2", amount=20)
    sid = scan(client).json()["scan_id"]
    sr = seal(client, expire_scan_id=sid).json()
    assert sr["fact_count"] == 2 and sr["total_amount"] == 30.0

    fid = [f["id"] for f in client.get("/api/facts").json() if f["coupon_code"] == "B-1"][0]
    r = client.post(f"/api/facts/{fid}/void").json()
    assert r["status"] == "void" and r["removed_from_batch"] is True

    # sealed 明细只剩 B-2；批头收敛，作废额不并入。
    b = client.get("/api/batches").json()[0]
    assert b["fact_count"] == 1 and b["total_amount"] == 20.0
    facts = {f["coupon_code"]: f["status"] for f in client.get("/api/facts").json()}
    assert facts == {"B-1": "void", "B-2": "sealed"}

    d = client.get("/api/dashboard").json()
    assert d["expire_count"] == 1
    assert d["sealed_fact_count"] == 1
    assert d["redeem_total_today"] == 20.0  # 作废额不计入核销合计


def test_manual_void_event_keeps_fact_and_batch_in_sync(client):
    """手工 void 事件：事件流是权威记录，事实与 sealed 明细必须同步，不留双态。"""
    day = "2099-11-08"
    set_day(client, day)
    add_event(client, "issue", "M-1")
    add_event(client, "redeem", "M-1", amount=10)
    sid = scan(client).json()["scan_id"]
    seal(client, expire_scan_id=sid)

    assert add_event(client, "void", "M-1").status_code == 200
    facts = {f["coupon_code"]: f["status"] for f in client.get("/api/facts").json()}
    assert facts == {"M-1": "void"}
    b = client.get("/api/batches").json()[0]
    assert b["fact_count"] == 0 and b["total_amount"] == 0.0


# ------------------------------------------------------------ 交错并发
def test_seal_after_scan_commit_uses_fresh_list(client):
    """扫描已提交后钉扎：必须按最新清单口径钉扎，不消费旧清单。"""
    day = "2099-11-09"
    set_day(client, day)
    add_event(client, "issue", "I-1")
    add_event(client, "issue", "I-2")
    add_event(client, "redeem", "I-2", amount=10)
    sid = scan(client).json()["scan_id"]

    # 扫描后新发放会让旧扫描 stale，重扫覆盖新集合（已 void 的 I-1 不重复认领）。
    add_event(client, "issue", "I-3")
    assert seal(client, expire_scan_id=sid).status_code == 409
    s2 = scan(client).json()
    assert s2["voided_coupons"] == ["I-3"]
    r = seal(client, expire_scan_id=s2["scan_id"])
    assert r.status_code == 200
    assert r.json()["sealed_coupons"] == ["I-2"]


def test_scan_waits_or_fails_when_locked_by_seal(client, monkeypatch):
    """扫描与钉扎交错：写锁被占时扫描等待后失败，整批回滚不留半截 void。"""
    day = "2099-11-10"
    set_day(client, day)
    add_event(client, "issue", "L-1")
    add_event(client, "issue", "L-2")
    add_event(client, "redeem", "L-2", amount=10)

    monkeypatch.setattr(db, "LOCK_TIMEOUT_SECONDS", 0.2)

    # 用另一连接持有写锁，模拟钉扎事务进行中。
    blocker = db.connect(immediate=True)
    try:
        blocker.execute(
            "INSERT INTO coupon_events(event_type,coupon_code,campaign_code,amount,business_day,occurred_at) "
            "VALUES('issue','L-0','NEW10',0,?,?)",
            (day, f"{day}T08:00:00"),
        )
        r = scan(client)
        assert r.status_code == 409
        assert "交错" in r.json()["detail"]
        assert client.get("/api/expire/scans").json() == []
    finally:
        blocker.rollback()
        blocker.close()

    # 写锁释放后扫描正常，且整批作废。
    ok = scan(client).json()
    assert ok["voided_coupons"] == ["L-1"]
