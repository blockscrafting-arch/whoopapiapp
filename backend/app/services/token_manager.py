"""Валидный access_token: proactive refresh + атомарность между воркерами.

WHOOP инвалидирует предыдущий refresh при каждом успешном refresh; параллельные
запросы из разных процессов ломают токен. Используем короткую транзакцию с
pg_advisory_xact_lock (PostgreSQL) — блокировка снимается при COMMIT.

См. https://developer.whoop.com/docs/developing/oauth (одновременный refresh).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models import User, WhoopToken
from app.services import whoop_client
from app.token_crypto import decrypt_token, encrypt_token


def _pg_advisory_keys(user_id: uuid.UUID) -> tuple[int, int]:
    """Два int32 для pg_advisory_xact_lock (стабильно от UUID)."""
    h = hashlib.blake2b(str(user_id).encode(), digest_size=8).digest()
    k1 = int.from_bytes(h[:4], "big", signed=False) & 0x7FFF_FFFF
    k2 = int.from_bytes(h[4:8], "big", signed=False) & 0x7FFF_FFFF
    return k1, k2


async def _load_user_with_token(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    q = await db.execute(
        select(User)
        .options(selectinload(User.token))
        .where(User.id == user_id)
        .execution_options(populate_existing=True)
    )
    return q.scalar_one_or_none()


async def _refresh_tokens_locked_transaction(
    http: httpx.AsyncClient,
    user_id: uuid.UUID,
    *,
    force_refresh: bool,
) -> None:
    """
    Отдельная короткая сессия + транзакция: lock → FOR UPDATE → refresh → commit.
    При ошибке WHOOP — откат изменений токена и отдельная транзакция is_active=False.
    """
    now = datetime.now(timezone.utc)
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                k1, k2 = _pg_advisory_keys(user_id)
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:k1, :k2)"),
                    {"k1": k1, "k2": k2},
                )
                r = await session.execute(
                    select(WhoopToken)
                    .where(WhoopToken.user_id == user_id)
                    .with_for_update()
                )
                row = r.scalar_one_or_none()
                if not row:
                    raise PermissionError("Нет токенов WHOOP")

                if (
                    not force_refresh
                    and row.token_expires_at > now + timedelta(minutes=5)
                ):
                    return

                try:
                    refresh_plain = decrypt_token(row.refresh_token_enc)
                except ValueError as e:
                    raise PermissionError(
                        "Не удалось расшифровать токены. Проверьте TOKEN_ENCRYPTION_KEY "
                        "или подключите WHOOP заново."
                    ) from e
                scope = (row.scopes or "").strip() or None
                data = await whoop_client.refresh_tokens(
                    http, refresh_plain, scope=scope
                )

                new_access = data["access_token"]
                new_refresh = data.get("refresh_token", refresh_plain)
                expires_in = int(data.get("expires_in", 3600))
                row.access_token_enc = encrypt_token(new_access)
                row.refresh_token_enc = encrypt_token(new_refresh)
                row.token_expires_at = now + timedelta(seconds=max(expires_in - 60, 60))
                if data.get("scope"):
                    row.scopes = str(data["scope"])
    except PermissionError:
        raise
    except whoop_client.WhoopApiError as e:
        if e.status_code in (400, 401, 403):
            async with AsyncSessionLocal() as s2:
                async with s2.begin():
                    await s2.execute(
                        update(User).where(User.id == user_id).values(is_active=False)
                    )
            raise PermissionError(
                "Не удалось обновить токен. Подключите WHOOP снова."
            ) from None
        # Для 429, 5xx и других ошибок выбрасываем временную ошибку, чтобы не разлогинить пользователя
        raise RuntimeError(f"WHOOP API временно недоступен ({e.status_code}).") from None


async def get_valid_access_token(
    db: AsyncSession,
    http: httpx.AsyncClient,
    user: User,
    *,
    force_refresh: bool = False,
) -> str:
    """Расшифрованный access_token; refresh в отдельной транзакции с advisory lock."""
    u = await _load_user_with_token(db, user.id)
    if not u or not u.token:
        raise PermissionError("Нет токенов WHOOP")

    row = u.token
    now = datetime.now(timezone.utc)

    if not force_refresh and row.token_expires_at > now + timedelta(minutes=5):
        return decrypt_token(row.access_token_enc)

    await _refresh_tokens_locked_transaction(
        http, user.id, force_refresh=force_refresh
    )

    u2 = await _load_user_with_token(db, user.id)
    if not u2 or not u2.token:
        raise PermissionError("Нет токенов WHOOP после обновления")
    return decrypt_token(u2.token.access_token_enc)
