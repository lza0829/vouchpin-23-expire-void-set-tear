from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Query
from app.services import redeem_service as svc

router = APIRouter(tags=["redeem"])


@router.get("/facts")
def facts(business_day: str | None = Query(None)):
    return svc.list_facts(business_day)


@router.get("/redeem/preview")
def preview(business_day: str | None = Query(None)):
    return svc.preview(business_day)


@router.post("/redeem/seal")
def seal(body: dict[str, Any]):
    return svc.seal(body)


@router.get("/batches")
def batches():
    return svc.list_batches()


@router.post("/facts/{fact_id}/void")
def void_fact(fact_id: int):
    from app.db import connect
    from app.services import void_ledger
    conn = connect(immediate=True)
    try:
        result = void_ledger.void_fact_only(conn, fact_id)
        if not result.get("found", True) and result.get("found") is False:
            from fastapi import HTTPException
            raise HTTPException(404, "事实不存在")
        conn.commit()
        return result
    finally:
        conn.close()
