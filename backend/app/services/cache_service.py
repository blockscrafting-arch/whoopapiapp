"""Кеш ответов WHOOP в PostgreSQL."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import WhoopCache


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def get_cached(
    db: AsyncSession,
    cache_key: str,
    ttl_seconds: int,
) -> tuple[Optional[dict[str, Any]], bool]:
    """
    Возвращает (payload, stale).
    stale=True если запись есть, но TTL истёк (можно показать как fallback).
    """
    r = await db.execute(select(WhoopCache).where(WhoopCache.cache_key == cache_key))
    row = r.scalar_one_or_none()
    if not row:
        return None, False
    age = _now() - row.fetched_at
    fresh = age < timedelta(seconds=ttl_seconds)
    return row.data_json, not fresh


async def set_cached(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    data_type: str,
    cache_key: str,
    payload: dict[str, Any],
) -> None:
    await db.execute(delete(WhoopCache).where(WhoopCache.cache_key == cache_key))
    db.add(
        WhoopCache(
            user_id=user_id,
            data_type=data_type,
            cache_key=cache_key,
            data_json=payload,
            fetched_at=_now(),
        )
    )
    await db.flush()


async def get_or_fetch(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    data_type: str,
    cache_key: str,
    ttl_seconds: int,
    fetcher: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Сначала кеш; при промахе или протухшем TTL — fetcher()."""
    cached, stale = await get_cached(db, cache_key, ttl_seconds)
    if cached is not None and not stale:
        out = dict(cached)
        out["_cache"] = {"hit": True, "stale": False}
        return out

    try:
        data = await fetcher()
        await set_cached(db, user_id=user_id, data_type=data_type, cache_key=cache_key, payload=data)
        out = dict(data)
        out["_cache"] = {"hit": False, "stale": False}
        return out
    except Exception:
        if cached is not None:
            out = dict(cached)
            out["_cache"] = {"hit": True, "stale": True, "error": "WHOOP временно недоступен"}
            return out
        raise


def cache_key(user_id: uuid.UUID, data_type: str, suffix: str) -> str:
    return f"{user_id}:{data_type}:{suffix}"
