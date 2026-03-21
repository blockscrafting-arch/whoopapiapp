from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.deps import CurrentUser
from app.services.cache_service import cache_key, get_or_fetch
from app.services.recommendations import (
    recovery_from_record,
    sleep_hours_from_record,
    strain_from_record,
)
from app.services.whoop_fetch import WhoopRequestError, get_json_collection

router = APIRouter(prefix="/api/history", tags=["history"])


def _record_date(rec: dict[str, Any]) -> Optional[str]:
    for k in ("start", "end", "created_at"):
        v = rec.get(k)
        if not v or not isinstance(v, str):
            continue
        try:
            s = v.replace("Z", "+00:00")
            return datetime.fromisoformat(s).date().isoformat()
        except ValueError:
            continue
    return None


def _trim_records(records: list[dict], days: int) -> list[dict]:
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    out: list[dict] = []
    for r in records:
        d = _record_date(r)
        if d and d >= cutoff:
            out.append(r)
    return out[:25]


@router.get("")
async def history(
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = Query(default=7, ge=1, le=30),
) -> dict:
    http = request.app.state.http_client
    ttl = settings.CACHE_TTL_SECONDS
    start_dt = datetime.now(timezone.utc) - timedelta(days=days + 1)
    start = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    suffix = f"{days}d_{datetime.now(timezone.utc).date().isoformat()}"

    ck_r = cache_key(user.id, "recovery", f"hist_{suffix}")
    ck_s = cache_key(user.id, "sleep", f"hist_{suffix}")
    ck_c = cache_key(user.id, "cycle", f"hist_{suffix}")

    async def fetch_recovery() -> dict:
        try:
            return await get_json_collection(
                db,
                http,
                user,
                "/v2/recovery",
                {"limit": 25, "start": start},
                max_pages=8,
                max_records=200,
            )
        except WhoopRequestError as e:
            raise RuntimeError(str(e)) from e

    async def fetch_sleep() -> dict:
        try:
            return await get_json_collection(
                db,
                http,
                user,
                "/v2/activity/sleep",
                {"limit": 25, "start": start},
                max_pages=8,
                max_records=200,
            )
        except WhoopRequestError as e:
            raise RuntimeError(str(e)) from e

    async def fetch_cycle() -> dict:
        try:
            return await get_json_collection(
                db,
                http,
                user,
                "/v2/cycle",
                {"limit": 25, "start": start},
                max_pages=8,
                max_records=200,
            )
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

    rec_r = _trim_records(list(raw_r.get("records") or []), days)
    rec_s = _trim_records(list(raw_s.get("records") or []), days)
    rec_c = _trim_records(list(raw_c.get("records") or []), days)

    recoveries_out = []
    for r in rec_r:
        score, st = recovery_from_record(r)
        recoveries_out.append(
            {
                "date": _record_date(r),
                "score_state": st,
                "recovery_score": score,
            }
        )

    sleeps_out = []
    for r in rec_s:
        h, st = sleep_hours_from_record(r)
        sleeps_out.append(
            {
                "date": _record_date(r),
                "score_state": st,
                "hours": h,
            }
        )

    cycles_out = []
    for r in rec_c:
        strain_v, st = strain_from_record(r)
        cycles_out.append(
            {
                "date": _record_date(r),
                "score_state": st,
                "strain": strain_v,
            }
        )

    return {
        "days": days,
        "recoveries": recoveries_out,
        "sleeps": sleeps_out,
        "cycles": cycles_out,
        "cache": {"recovery": r_meta, "sleep": s_meta, "cycle": c_meta},
        "pagination": {
            "recovery_truncated": bool(raw_r.get("_truncated")),
            "sleep_truncated": bool(raw_s.get("_truncated")),
            "cycle_truncated": bool(raw_c.get("_truncated")),
        },
    }
