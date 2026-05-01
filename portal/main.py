from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from portal.db import init_db, normalize_db_path
from portal.infrastructure import config
from portal.routers import ai, georef, imports, race_results


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
app.include_router(georef.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(imports.router)
app.include_router(race_results.router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(Path(config.UPLOAD_DIR).expanduser())), name="uploads")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {})
