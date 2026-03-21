"""Вызовы WHOOP с учётом refresh и 401."""

from typing import Any, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.services import whoop_client
from app.services import token_manager


class WhoopRequestError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


async def get_json(
    db: AsyncSession,
    http: httpx.AsyncClient,
    user: User,
    path: str,
    params: Optional[dict[str, Any]] = None,
) -> Any:
    """GET JSON; при 401 один раз принудительно обновляет токен."""
    force_refresh = False
    for _ in range(2):
        try:
            token = await token_manager.get_valid_access_token(
                db, http, user, force_refresh=force_refresh
            )
        except PermissionError as e:
            raise WhoopRequestError(401, str(e)) from e

        status, body = await whoop_client.whoop_get(http, token, path, params=params)
        if status == 401:
            force_refresh = True
            continue
        if status == 429:
            raise WhoopRequestError(429, "Превышен лимит запросов к WHOOP. Попробуйте позже.")
        if status >= 500:
            raise WhoopRequestError(status, "Сервис WHOOP временно недоступен.")
        if status >= 400:
            raise WhoopRequestError(status, "Ошибка запроса к WHOOP.")
        return body

    raise WhoopRequestError(401, "Не удалось авторизоваться в WHOOP.")


WHOOP_MAX_PER_PAGE = 25


async def get_json_collection(
    db: AsyncSession,
    http: httpx.AsyncClient,
    user: User,
    path: str,
    base_params: Optional[dict[str, Any]] = None,
    *,
    max_pages: int = 8,
    max_records: int = 200,
) -> dict[str, Any]:
    """
    Собирает страницы коллекции WHOOP (query: nextToken, ответ: next_token).
    См. OpenAPI: https://api.prod.whoop.com/developer/doc/openapi.json
    """
    base = dict(base_params or {})
    raw_limit = int(base.pop("limit", WHOOP_MAX_PER_PAGE))
    lim = min(raw_limit, WHOOP_MAX_PER_PAGE)

    merged: list[Any] = []
    next_tok: str | None = None
    last_next: str | None = None

    for _ in range(max_pages):
        params = {**base, "limit": lim}
        if next_tok:
            params["nextToken"] = next_tok

        body = await get_json(db, http, user, path, params)
        if not isinstance(body, dict):
            break

        recs = body.get("records") or []
        merged.extend(recs)
        last_next = body.get("next_token")
        next_tok = last_next

        if not next_tok:
            break
        if len(merged) >= max_records:
            break

    return {
        "records": merged[:max_records],
        "next_token": last_next,
        "_truncated": bool(last_next),
    }
