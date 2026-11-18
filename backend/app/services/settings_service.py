from __future__ import annotations
import sqlite3
from typing import Any
from fastapi import HTTPException
from app.db import connect
from app.repositories import settings as settings_repo

DEFAULT_SCAN_TTL_SECONDS = 3600
SCAN_TTL_KEY = "expire_scan_ttl_seconds"


def scan_ttl_seconds(conn: sqlite3.Connection) -> int:
    raw = settings_repo.get(conn, SCAN_TTL_KEY)
    try:
        ttl = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_SCAN_TTL_SECONDS
    return ttl if ttl >= 1 else DEFAULT_SCAN_TTL_SECONDS


def get_day() -> dict[str, Any]:
    conn = connect()
    try:
        return {"business_day": settings_repo.get(conn, "business_day")}
    finally:
        conn.close()


def set_day(body: dict[str, Any]) -> dict[str, Any]:
    day = (body.get("business_day") or "").strip()
    if len(day) != 10:
        raise HTTPException(400, "business_day 格式 YYYY-MM-DD")
    conn = connect(immediate=True)
    try:
        settings_repo.set_(conn, "business_day", day)
        conn.commit()
        return {"business_day": day}
    finally:
        conn.close()


def get_scan_ttl() -> dict[str, Any]:
    conn = connect()
    try:
        return {"ttl_seconds": scan_ttl_seconds(conn)}
    finally:
        conn.close()


def set_scan_ttl(body: dict[str, Any]) -> dict[str, Any]:
    try:
        ttl = int(body.get("ttl_seconds"))
    except (TypeError, ValueError):
        raise HTTPException(400, "ttl_seconds 须为正整数（秒）")
    if ttl < 1:
        raise HTTPException(400, "ttl_seconds 须 ≥ 1")
    conn = connect(immediate=True)
    try:
        settings_repo.set_(conn, SCAN_TTL_KEY, str(ttl))
        conn.commit()
        return {"ttl_seconds": ttl}
    finally:
        conn.close()
