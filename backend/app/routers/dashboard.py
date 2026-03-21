from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.deps import CurrentUser
from app.services.cache_service import cache_key, get_or_fetch
from app.services.recommendations import (
    build_recommendations,
    recovery_from_record,
    sleep_hours_from_record,
    strain_from_record,
)
from app.services.whoop_fetch import WhoopRequestError, get_json

router = APIRouter(prefix="/api", tags=["dashboard"])


def _first_record(payload: Any) -> Optional[dict]:
    if not isinstance(payload, dict):
        return None
    recs = payload.get("records") or []
    return recs[0] if recs else None


def _score_message(state: Optional[str]) -> Optional[str]:
    if state == "PENDING_SCORE":
        return "Данные обрабатываются WHOOP…"
    if state == "UNSCORABLE":
        return "Недостаточно данных для оценки"
    return None


@router.get("/dashboard")
async def dashboard(
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    http = request.app.state.http_client
    ttl = settings.CACHE_TTL_SECONDS
    day = datetime.now(timezone.utc).date().isoformat()
    ck_r = cache_key(user.id, "recovery", f"dash_{day}")
    ck_s = cache_key(user.id, "sleep", f"dash_{day}")
    ck_c = cache_key(user.id, "cycle", f"dash_{day}")

    async def fetch_recovery() -> dict:
        try:
            return await get_json(db, http, user, "/v2/recovery", {"limit": 5})
        except WhoopRequestError as e:
            raise RuntimeError(str(e)) from e

    async def fetch_sleep() -> dict:
        try:
            return await get_json(db, http, user, "/v2/activity/sleep", {"limit": 5})
        except WhoopRequestError as e:
            raise RuntimeError(str(e)) from e

    async def fetch_cycle() -> dict:
        try:
            return await get_json(db, http, user, "/v2/cycle", {"limit": 5})
        except WhoopRequestError as e:
            raise RuntimeError(str(e)) from e

    try:
        raw_r = await get_or_fetch(
            db,
            user_id=user.id,
            data_type="recovery",
            cache_key=ck_r,
            ttl_seconds=ttl,
            fetcher=fetch_recovery,
        )
        raw_s = await get_or_fetch(
            db,
            user_id=user.id,
            data_type="sleep",
            cache_key=ck_s,
            ttl_seconds=ttl,
            fetcher=fetch_sleep,
        )
        raw_c = await get_or_fetch(
            db,
            user_id=user.id,
            data_type="cycle",
            cache_key=ck_c,
            ttl_seconds=ttl,
            fetcher=fetch_cycle,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    r_meta = raw_r.pop("_cache", {})
    s_meta = raw_s.pop("_cache", {})
    c_meta = raw_c.pop("_cache", {})

    rec_r = _first_record(raw_r)
    rec_s = _first_record(raw_s)
    rec_c = _first_record(raw_c)

    rec_score, rec_state = recovery_from_record(rec_r) if rec_r else (None, None)
    sleep_h, sleep_state = sleep_hours_from_record(rec_s) if rec_s else (None, None)
    strain_v, strain_state = strain_from_record(rec_c) if rec_c else (None, None)

    recommendations = build_recommendations(
        recovery_score=rec_score,
        recovery_state=rec_state,
        sleep_hours=sleep_h,
        sleep_state=sleep_state,
        strain=strain_v,
        strain_state=strain_state,
    )

    return {
        "recovery": {
            "score": rec_score,
            "score_state": rec_state,
            "message": _score_message(rec_state),
        },
        "sleep": {
            "hours": sleep_h,
            "score_state": sleep_state,
            "message": _score_message(sleep_state),
        },
        "strain": {
            "score": strain_v,
            "score_state": strain_state,
            "message": _score_message(strain_state),
        },
        "recommendations": recommendations,
        "cache": {"recovery": r_meta, "sleep": s_meta, "cycle": c_meta},
    }


@router.get("/health")
async def health() -> dict:
    return {"ok": True}
