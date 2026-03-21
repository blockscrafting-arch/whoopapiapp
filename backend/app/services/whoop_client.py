"""Низкоуровневый HTTP-клиент WHOOP API v2.

Документация WHOOP (OAuth): примеры token endpoint с JSON-телом; RFC 6749 часто
использует application/x-www-form-urlencoded. Отправляем сначала JSON, затем
fallback на form — см. https://developer.whoop.com/docs/developing/oauth
"""

from typing import Any, Optional

import httpx

from app.config import settings


class WhoopApiError(Exception):
    def __init__(self, status_code: int, message: str, body: Optional[str] = None):
        self.status_code = status_code
        self.message = message
        self.body = body
        super().__init__(message)


def _validate_token_payload(
    data: Any,
    *,
    require_refresh_token: bool,
) -> dict[str, Any]:
    """
    Защита от KeyError / пустых ответов WHOOP (M3 аудита).
    """
    if not isinstance(data, dict):
        raise WhoopApiError(
            502,
            "OAuth token: ответ не JSON-объект",
            str(data)[:300] if data is not None else None,
        )
    if not data.get("access_token"):
        raise WhoopApiError(
            502,
            "OAuth token: в ответе нет access_token",
            str(data)[:300],
        )
    if require_refresh_token and not data.get("refresh_token"):
        raise WhoopApiError(
            502,
            "OAuth token: нет refresh_token. В приложении WHOOP должен быть scope offline.",
            str(data)[:300],
        )
    return data


def _parse_token_dict(response: httpx.Response) -> Optional[dict[str, Any]]:
    if response.status_code != 200:
        return None
    try:
        data = response.json()
    except Exception:
        return None
    if isinstance(data, dict) and data.get("access_token"):
        return data
    return None


async def _post_token(client: httpx.AsyncClient, payload: dict[str, Any]) -> dict[str, Any]:
    """
    POST на /oauth/oauth2/token.
    1) application/json (как в официальных примерах WHOOP / Postman).
    2) application/x-www-form-urlencoded (RFC 6749).

    Если JSON вернул 200 без access_token — пробуем form (разные серверы / ошибки в теле).
    """
    r_json = await client.post(
        settings.WHOOP_TOKEN_URL,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=30.0,
    )
    parsed = _parse_token_dict(r_json)
    if parsed is not None:
        return parsed

    r_form = await client.post(
        settings.WHOOP_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30.0,
    )
    parsed = _parse_token_dict(r_form)
    if parsed is not None:
        return parsed

    body = r_form.text or r_json.text
    st = r_form.status_code if r_form.status_code != 200 else r_json.status_code
    raise WhoopApiError(
        st,
        "Ошибка запроса к token endpoint WHOOP",
        body,
    )


async def exchange_code_for_tokens(client: httpx.AsyncClient, code: str) -> dict[str, Any]:
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.WHOOP_REDIRECT_URI,
        "client_id": settings.WHOOP_CLIENT_ID,
        "client_secret": settings.WHOOP_CLIENT_SECRET,
    }
    try:
        raw = await _post_token(client, payload)
        return _validate_token_payload(raw, require_refresh_token=True)
    except WhoopApiError as e:
        raise WhoopApiError(e.status_code, "Ошибка обмена code на токены", e.body) from e


async def refresh_tokens(
    client: httpx.AsyncClient,
    refresh_token: str,
    *,
    scope: Optional[str] = None,
) -> dict[str, Any]:
    """
    scope: если передан (например полная строка из ответа OAuth), уходит в теле;
    иначе — минимум offline (как в примере WHOOP).
    """
    payload: dict[str, Any] = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": settings.WHOOP_CLIENT_ID,
        "client_secret": settings.WHOOP_CLIENT_SECRET,
        "scope": scope if scope else "offline",
    }
    try:
        raw = await _post_token(client, payload)
        return _validate_token_payload(raw, require_refresh_token=False)
    except WhoopApiError as e:
        raise WhoopApiError(e.status_code, "Ошибка обновления токена", e.body) from e


async def whoop_get(
    client: httpx.AsyncClient,
    access_token: str,
    path: str,
    params: Optional[dict[str, Any]] = None,
) -> tuple[int, Any]:
    url = f"{settings.WHOOP_API_BASE.rstrip('/')}{path}"
    r = await client.get(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        params=params or {},
        timeout=30.0,
    )
    if r.status_code == 204:
        return r.status_code, None
    try:
        body = r.json() if r.content else None
    except Exception:
        body = {"raw": r.text}
    return r.status_code, body


async def revoke_access(client: httpx.AsyncClient, access_token: str) -> int:
    url = f"{settings.WHOOP_API_BASE.rstrip('/')}/v2/user/access"
    r = await client.delete(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30.0,
    )
    return r.status_code
