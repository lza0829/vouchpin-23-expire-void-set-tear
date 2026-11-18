from __future__ import annotations
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


def test_seal_without_scan_rejected(client):
    """无扫描钉：未扫描直接钉、伪造 scan_id 钉，一律拒，且不落批。"""
    set_day(client, "2099-01-01")
    assert add_event(client, "issue", "T-100").status_code == 200
    assert add_event(client, "redeem", "T-100", amount=10).status_code == 200

    r = seal(client)
    assert r.status_code == 409
    assert "扫描" in r.json()["detail"]

    r2 = seal(client, expire_scan_id=999999)
    assert r2.status_code == 409
    assert "不存在" in r2.json()["detail"]

    assert client.get("/api/batches").json() == []


def test_scan_then_seal_binds_snapshot(client):
    """先扫再钉：扫描作废未核集合，钉批快照绑定 scan_id 与扫描摘要。"""
    set_day(client, "2099-01-02")
    add_event(client, "issue", "T-201")
    add_event(client, "issue", "T-202")
    add_event(client, "redeem", "T-201", amount=10)

    s = scan(client)
    assert s.status_code == 200
    sd = s.json()
    assert sd["issued_count"] == 2
    assert sd["voided_count"] == 1
    assert sd["voided_coupons"] == ["T-202"]

    r = seal(client, expire_scan_id=sd["scan_id"])
    assert r.status_code == 200
    body = r.json()
    assert body["expire_scan_id"] == sd["scan_id"]
    assert body["scan_voided_count"] == 1

    batches = client.get("/api/batches").json()
    assert len(batches) == 1
    b = batches[0]
    assert b["expire_scan_id"] == sd["scan_id"]
    assert b["scan_scanned_at"] == sd["scanned_at"]
    assert b["scan_voided_count"] == 1

    events = client.get("/api/events").json()
    voids = [e for e in events if e["event_type"] == "void"]
    assert len(voids) == 1 and voids[0]["coupon_code"] == "T-202"

    detail = client.get(f"/api/expire/scans/{sd['scan_id']}").json()
    assert detail["state"] == "valid"
    assert [i["coupon_code"] for i in detail["items"]] == ["T-202"]

    # 钉扎后禁止再扫描、再钉
    assert scan(client).status_code == 409
    assert seal(client, expire_scan_id=sd["scan_id"]).status_code == 409


def test_expired_scan_id_reuse_rejected(client):
    """过期 scan_id 复用：超 TTL 的扫描拒钉；重扫后放行。"""
    set_day(client, "2099-01-03")
    add_event(client, "issue", "T-301")
    add_event(client, "redeem", "T-301", amount=10)
    sid = scan(client).json()["scan_id"]

    conn = db.connect()
    conn.execute("UPDATE expire_scans SET scanned_at='2000-01-01T00:00:00' WHERE id=?", (sid,))
    conn.commit()
    conn.close()

    r = seal(client, expire_scan_id=sid)
    assert r.status_code == 409
    assert "过期" in r.json()["detail"]

    sid2 = scan(client).json()["scan_id"]
    assert seal(client, expire_scan_id=sid2).status_code == 200


def test_foreign_day_scan_rejected(client):
    """扫描不属于该业务日：跨日复用 scan_id 拒钉。"""
    set_day(client, "2099-01-04")
    add_event(client, "issue", "T-401")
    add_event(client, "redeem", "T-401", amount=10)
    sid = scan(client).json()["scan_id"]

    set_day(client, "2099-01-05")
    add_event(client, "issue", "T-501")
    add_event(client, "redeem", "T-501", amount=10)
    r = seal(client, expire_scan_id=sid)
    assert r.status_code == 409
    assert "业务日" in r.json()["detail"]
    assert client.get("/api/batches").json() == []


def test_new_issue_after_scan_stales_it(client):
    """扫描后新增发放再钉：旧扫描失效拒钉，重扫覆盖新集合后放行。"""
    set_day(client, "2099-01-06")
    add_event(client, "issue", "T-601")
    add_event(client, "redeem", "T-601", amount=10)
    sid = scan(client).json()["scan_id"]

    assert add_event(client, "issue", "T-602").status_code == 200
    r = seal(client, expire_scan_id=sid)
    assert r.status_code == 409
    assert "新增" in r.json()["detail"] and "发放" in r.json()["detail"]

    s2 = scan(client).json()
    assert s2["voided_count"] == 1
    assert s2["voided_coupons"] == ["T-602"]
    assert seal(client, expire_scan_id=s2["scan_id"]).status_code == 200


def test_preview_and_dashboard_share_gate(client):
    """预览/总览与钉闸同源：同一 gate 状态出口。"""
    set_day(client, "2099-01-07")
    add_event(client, "issue", "T-701")
    add_event(client, "redeem", "T-701", amount=10)

    p = client.get("/api/redeem/preview").json()
    assert p["expire_scan"]["state"] == "none"
    assert p["expire_scan"]["policy"] == "required"
    assert p["seal_gate"]["allowed"] is False
    assert "扫描" in p["seal_gate"]["reason"]
    d = client.get("/api/dashboard").json()
    assert d["expire_scan"]["state"] == "none"

    sid = scan(client).json()["scan_id"]
    p2 = client.get("/api/redeem/preview").json()
    assert p2["expire_scan"]["state"] == "valid"
    assert p2["expire_scan"]["scan"]["id"] == sid
    assert p2["seal_gate"]["allowed"] is True
    d2 = client.get("/api/dashboard").json()
    assert d2["expire_scan"]["state"] == "valid"
    assert d2["expire_scan"]["scan"]["voided_count"] == 0


def test_scan_ttl_configurable(client):
    """TTL 可配：默认 3600，可改，非法值拒。"""
    assert client.get("/api/settings/scan-ttl").json()["ttl_seconds"] == 3600
    r = client.put("/api/settings/scan-ttl", json={"ttl_seconds": 60})
    assert r.status_code == 200 and r.json()["ttl_seconds"] == 60
    assert client.get("/api/settings/scan-ttl").json()["ttl_seconds"] == 60
    assert client.put("/api/settings/scan-ttl", json={"ttl_seconds": 0}).status_code == 400
    assert client.put("/api/settings/scan-ttl", json={"ttl_seconds": "x"}).status_code == 400


def test_issue_blocked_after_seal(client):
    """钉扎后当日发放集合冻结，保证钉闸审计的集合不再变动。"""
    set_day(client, "2099-01-08")
    add_event(client, "issue", "T-801")
    add_event(client, "redeem", "T-801", amount=10)
    sid = scan(client).json()["scan_id"]
    assert seal(client, expire_scan_id=sid).status_code == 200
    r = add_event(client, "issue", "T-802")
    assert r.status_code == 409
    assert "钉扎" in r.json()["detail"]
