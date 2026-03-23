from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.deps import CurrentUser
from app.services.cache_service import cache_key, get_or_fetch
from app.services.whoop_fetch import WhoopRequestError, get_json_collection

router = APIRouter(prefix="/api/workouts", tags=["workouts"])


def _workout_summary(rec: dict[str, Any]) -> dict[str, Any]:
    score = rec.get("score") or {}
    start = rec.get("start")
    end = rec.get("end")
    duration_min = None
    if start and end:
        try:
            a = datetime.fromisoformat(start.replace("Z", "+00:00"))
            b = datetime.fromisoformat(end.replace("Z", "+00:00"))
            duration_min = int((b - a).total_seconds() // 60)
        except ValueError:
            duration_min = None
    return {
        "id": rec.get("id"),
        "start": start,
        "sport_name": rec.get("sport_name"),
        "score_state": rec.get("score_state"),
        "strain": score.get("strain"),
        "average_heart_rate": score.get("average_heart_rate"),
        "max_heart_rate": score.get("max_heart_rate"),
        "duration_min": duration_min,
    }


@router.get("")
async def list_workouts(
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = Query(default=7, ge=1, le=30),
) -> dict:
    http = request.app.state.http_client
    ttl = settings.CACHE_TTL_SECONDS
    start_dt = datetime.now(timezone.utc) - timedelta(days=days + 1)
    start = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    suffix = f"w_{days}d_{datetime.now(timezone.utc).date().isoformat()}"
    ck = cache_key(user.id, "workout", suffix)

    async def fetcher() -> dict:
        try:
            return await get_json_collection(
                db,
                http,
                user,
                "/v2/activity/workout",
                {"limit": 25, "start": start},
                max_pages=8,
                max_records=200,
            )
        except WhoopRequestError as e:
            raise RuntimeError(str(e)) from e

    try:
        raw = await get_or_fetch(
            db,
            user_id=user.id,
            data_type="workout",
            cache_key=ck,
            ttl_seconds=ttl,
            fetcher=fetcher,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    meta = raw.pop("_cache", {})
    truncated = bool(raw.get("_truncated"))
    records = list(raw.get("records") or [])
    workouts = [_workout_summary(r) for r in records]
    return {
        "days": days,
        "workouts": workouts,
        "cache": meta,
        "pagination": {"truncated": truncated},
    }
