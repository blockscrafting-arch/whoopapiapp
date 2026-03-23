from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.routers import auth, dashboard, history, profile, workouts

ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(follow_redirects=True) as client:
        app.state.http_client = client
        yield


app = FastAPI(title="WHOOP PWA", lifespan=lifespan)


@app.middleware("http")
async def force_json_utf8_charset(request: Request, call_next):
    """Safari/iOS иногда показывает кириллицу в сыром JSON как mojibake без charset в заголовке."""
    response = await call_next(request)
    ct = response.headers.get("content-type", "")
    if "application/json" in ct and "charset=" not in ct.lower():
        base = ct.split(";", 1)[0].strip()
        response.headers["content-type"] = f"{base}; charset=utf-8"
    return response


app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET_KEY,
    session_cookie="whoop_session",
    max_age=86400 * 30,
    same_site="lax",
    https_only=not settings.DEBUG,
)

if settings.cors_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(history.router)
app.include_router(workouts.router)
app.include_router(profile.router)


@app.get("/")
async def spa_index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    icon = FRONTEND_DIR / "icons" / "icon-192.png"
    if icon.exists():
        return FileResponse(icon, media_type="image/png")
    from fastapi.responses import Response
    return Response(status_code=204)


@app.get("/manifest.json")
async def manifest_json() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "manifest.json")


@app.get("/sw.js")
async def service_worker() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "sw.js", media_type="application/javascript")


app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")
icons_dir = FRONTEND_DIR / "icons"
if icons_dir.is_dir():
    app.mount("/icons", StaticFiles(directory=icons_dir), name="icons")
