import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.deps import CurrentUser
from app.models import User, WhoopToken
from app.services import whoop_client
from app.token_crypto import decrypt_token, encrypt_token

router = APIRouter(prefix="/auth", tags=["auth"])

WHOOP_SCOPES = "offline read:profile read:recovery read:sleep read:cycles read:workout"


def _http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


@router.get("/login")
async def login(request: Request) -> RedirectResponse:
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    params = {
        "response_type": "code",
        "client_id": settings.WHOOP_CLIENT_ID,
        "redirect_uri": settings.WHOOP_REDIRECT_URI,
        "scope": WHOOP_SCOPES,
        "state": state,
    }
    url = f"{settings.WHOOP_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.get("/callback")
async def oauth_callback(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    error: str | None = None,
    error_description: str | None = None,
    code: str | None = None,
    state: str | None = None,
) -> RedirectResponse:
    if error:
        msg = (error_description or error or "OAuth error")[:500]
        return RedirectResponse(
            url=f"/?oauth_error={quote(msg, safe='')}",
            status_code=status.HTTP_302_FOUND,
        )
    if not code or not state:
        raise HTTPException(
            status_code=400,
            detail="Отсутствуют параметры OAuth (code/state).",
        )

    expected = request.session.get("oauth_state")
    if not expected or state != expected:
        raise HTTPException(status_code=400, detail="Неверный параметр state (CSRF)")
    request.session.pop("oauth_state", None)

    http = _http(request)
    try:
        data = await whoop_client.exchange_code_for_tokens(http, code)
    except whoop_client.WhoopApiError as e:
        raise HTTPException(status_code=400, detail=e.message) from e

    access = data["access_token"]
    refresh = data["refresh_token"]
    expires_in = int(data.get("expires_in", 3600))
    scope_str = str(data.get("scope", ""))

    st, profile = await whoop_client.whoop_get(
        http, access, "/v2/user/profile/basic", params=None
    )
    if st != 200 or not isinstance(profile, dict):
        raise HTTPException(status_code=400, detail="Не удалось получить профиль WHOOP")

    whoop_user_id = int(profile["user_id"])
    email = profile.get("email")
    first_name = profile.get("first_name")
    last_name = profile.get("last_name")

    r = await db.execute(
        select(User)
        .options(selectinload(User.token))
        .where(User.whoop_user_id == whoop_user_id)
    )
    user = r.scalar_one_or_none()
    is_new = False
    if user:
        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.is_active = True
    else:
        user = User(
            whoop_user_id=whoop_user_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            is_active=True,
        )
        db.add(user)
        is_new = True
    await db.flush()

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=max(expires_in - 60, 120))

    if not is_new and user.token:
        user.token.access_token_enc = encrypt_token(access)
        user.token.refresh_token_enc = encrypt_token(refresh)
        user.token.token_expires_at = expires_at
        user.token.scopes = scope_str
    else:
        db.add(
            WhoopToken(
                user_id=user.id,
                access_token_enc=encrypt_token(access),
                refresh_token_enc=encrypt_token(refresh),
                token_expires_at=expires_at,
                scopes=scope_str,
            )
        )

    request.session["user_id"] = str(user.id)
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)


@router.get("/status")
async def auth_status(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    uid_str = request.session.get("user_id")
    if not uid_str:
        return {"logged_in": False}
    try:
        uid = uuid.UUID(uid_str)
    except ValueError:
        return {"logged_in": False}
    user = await db.get(User, uid)
    if not user or not user.is_active:
        return {"logged_in": False}
    return {"logged_in": True}


@router.post("/logout")
async def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True, "message": "Вы вышли из сессии"}


@router.post("/disconnect")
async def disconnect_whoop(
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Revoke у WHOOP (если есть валидный access), затем удаление строки users.
    CASCADE убирает whoop_tokens и whoop_cache — без PII на сервере (M2).
    """
    http = _http(request)
    uid = user.id

    if user.token:
        try:
            access = decrypt_token(user.token.access_token_enc)
        except ValueError:
            access = None
        if access:
            try:
                await whoop_client.revoke_access(http, access)
            except Exception:
                pass

    await db.execute(delete(User).where(User.id == uid))
    request.session.clear()
    return {
        "ok": True,
        "message": "WHOOP отключён, локальная учётная запись и токены удалены",
    }
