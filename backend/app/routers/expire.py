from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Query
from app.services import expire_service as svc

router = APIRouter(tags=["expire"])


@router.post("/expire/scan")
def scan(body: dict[str, Any]):
    return svc.run_scan(body)


@router.get("/expire/scans")
def scans(business_day: str | None = Query(None)):
    return svc.list_scans(business_day)


@router.get("/expire/scans/{scan_id}")
def scan_detail(scan_id: int):
    return svc.scan_detail(scan_id)
