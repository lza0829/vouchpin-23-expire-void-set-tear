from __future__ import annotations
from typing import Any
from fastapi import APIRouter
from app.services import settings_service as svc

router = APIRouter(tags=["settings"])


@router.get("/settings/day")
def get_day():
    return svc.get_day()


@router.put("/settings/day")
def put_day(body: dict[str, Any]):
    return svc.set_day(body)


@router.get("/settings/scan-ttl")
def get_scan_ttl():
    return svc.get_scan_ttl()


@router.put("/settings/scan-ttl")
def put_scan_ttl(body: dict[str, Any]):
    return svc.set_scan_ttl(body)
