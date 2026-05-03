from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from portal.auth import (
    USER_COOKIE_NAME,
    auto_login_username,
    fetch_user_by_id,
    fetch_user_by_username,
)
from portal.db import connect_db, init_db, normalize_db_path
from portal.infrastructure import config
from portal.routers import ai, auth as auth_router, georef, imports, race_results


load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(_: FastAPI):
    db_path = normalize_db_path(config.DB_PATH)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    Path(config.UPLOAD_DIR).expanduser().mkdir(parents=True, exist_ok=True)
    Path(config.MAP_DIR).expanduser().mkdir(parents=True, exist_ok=True)
    await init_db(db_path)
    logger.info("Database initialized at %s", db_path)
    yield


app = FastAPI(lifespan=lifespan)
app.state.templates = templates


AUTH_WHITELIST_PATHS = {"/login", "/logout", "/favicon.ico"}
AUTH_WHITELIST_PREFIXES = ("/static/", "/uploads/")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in AUTH_WHITELIST_PATHS or path.startswith(AUTH_WHITELIST_PREFIXES):
        return await call_next(request)

    user = None
    user_id = request.cookies.get(USER_COOKIE_NAME)
    if user_id or auto_login_username():
        conn = await connect_db(normalize_db_path(config.DB_PATH))
        try:
            if user_id:
                user = await fetch_user_by_id(conn, user_id)
            if user is None:
                fallback_username = auto_login_username()
                if fallback_username:
                    user = await fetch_user_by_username(conn, fallback_username)
        finally:
            await conn.close()

    if user is None:
        if path.startswith("/api/"):
            return JSONResponse({"error": "not_authenticated"}, status_code=401)
        return RedirectResponse("/login", status_code=302)

    request.state.user = user
    return await call_next(request)


app.include_router(auth_router.router)
app.include_router(georef.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(imports.router)
app.include_router(race_results.router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(Path(config.UPLOAD_DIR).expanduser())), name="uploads")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.ico")
