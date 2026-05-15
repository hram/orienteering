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
from portal.db import connect_db, init_db, list_dashboard_race_results, normalize_db_path
from portal.infrastructure import config
from portal.routers import ai, auth as auth_router, georef, imports, race_results, settings


load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
DASHBOARD_PROBLEM_LIMIT = 6


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
app.include_router(settings.router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(Path(config.UPLOAD_DIR).expanduser())), name="uploads")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    dashboard = await _dashboard_context(request, limit=DASHBOARD_PROBLEM_LIMIT)
    return templates.TemplateResponse(request, "index.html", dashboard)


@app.get("/problem-splits", response_class=HTMLResponse)
async def problem_splits_page(request: Request) -> HTMLResponse:
    dashboard = await _dashboard_context(request, limit=None)
    return templates.TemplateResponse(request, "problem_splits.html", dashboard)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.ico")


async def _dashboard_context(request: Request, *, limit: int | None) -> dict:
    user = request.state.user
    viewer_user_id = None if user.is_admin else user.user_id
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        sources = await list_dashboard_race_results(conn, viewer_user_id=viewer_user_id)
    finally:
        await conn.close()
    problem_splits, trainings = _build_problem_splits(sources)
    visible_splits = problem_splits[:limit] if limit is not None else problem_splits
    visible_training_ids = {split["training_id"] for split in visible_splits}
    return {
        "problem_splits": visible_splits,
        "problem_split_total": len(problem_splits),
        "dashboard_training_data": {
            training_id: training
            for training_id, training in trainings.items()
            if training_id in visible_training_ids
        },
    }


def _build_problem_splits(sources: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    problem_splits: list[dict] = []
    trainings: dict[str, dict] = {}
    for result in sources:
        training_id = result.get("training_id")
        if not training_id or not _dashboard_training_ready(result):
            continue
        trainings.setdefault(training_id, _dashboard_training_payload(result))
        if result.get("kind") == "score":
            _append_score_problem_splits(problem_splits, result)
        else:
            _append_course_problem_splits(problem_splits, result)
    problem_splits.sort(key=lambda item: item["gap_seconds"], reverse=True)
    for index, item in enumerate(problem_splits):
        item["problem_index"] = index
    return problem_splits, trainings


def _dashboard_training_ready(result: dict) -> bool:
    return bool(
        result.get("map_image_path")
        and result.get("georef_transform")
        and result.get("training_course_controls")
        and result.get("training_track_points")
    )


def _dashboard_training_payload(result: dict) -> dict:
    return {
        "training_id": result["training_id"],
        "training_type": result.get("training_type") or "",
        "map_image_url": _map_image_url(result.get("map_image_path")),
        "course_controls": result.get("training_course_controls") or [],
        "track_points": result.get("training_track_points") or [],
        "transform": result.get("georef_transform"),
    }


def _append_course_problem_splits(items: list[dict], result: dict) -> None:
    race_results._prepare_race_result_view(result)
    self_participant = result.get("self_participant")
    if not self_participant:
        return
    leader_splits = race_results._leader_split_seconds_by_split(result.get("participants", []))
    for split_index in result.get("problem_split_indexes", []):
        splits = self_participant.get("splits", [])
        if split_index >= len(splits):
            continue
        split = splits[split_index]
        split_time = race_results._split_stage_time(split, split_index) or {}
        seconds = split_time.get("seconds")
        leader_seconds = leader_splits[split_index] if split_index < len(leader_splits) else None
        if seconds is None or leader_seconds is None:
            continue
        gap_seconds = seconds - leader_seconds
        if gap_seconds <= 0:
            continue
        if _is_reviewed_problem_split(result, split_index):
            continue
        items.append(_problem_split_payload(result, split_index, split.get("label", ""), split_time, leader_seconds, gap_seconds))


def _append_score_problem_splits(items: list[dict], result: dict) -> None:
    race_results._prepare_score_result_view(result)
    self_participant = result.get("self_participant")
    if not self_participant:
        return
    for visit_index in result.get("problem_visit_indexes", []):
        visits = self_participant.get("visits", [])
        if visit_index >= len(visits):
            continue
        visit = visits[visit_index]
        split = visit.get("split") or {}
        seconds = split.get("seconds")
        leader_seconds = visit.get("best_leg_seconds")
        if seconds is None or leader_seconds is None:
            continue
        gap_seconds = seconds - leader_seconds
        if gap_seconds <= 0:
            continue
        if _is_reviewed_problem_split(result, visit_index):
            continue
        label = visit.get("code") or str(visit_index + 1)
        items.append(_problem_split_payload(result, visit_index, label, split, leader_seconds, gap_seconds))


def _is_reviewed_problem_split(result: dict, split_index: int) -> bool:
    reviewed_keys = result.get("reviewed_split_keys") or set()
    if not reviewed_keys:
        return False
    key = _dashboard_review_key(result, split_index)
    return key in reviewed_keys if key else False


def _dashboard_review_key(result: dict, split_index: int) -> tuple[str, str, str] | None:
    controls = _normalized_dashboard_controls(
        result.get("training_course_controls") or [],
        is_rogaine=result.get("training_type") == "rogaine",
    )
    split_controls = [control for control in controls if control["kind"] != "start-point"]
    if split_index < 0 or split_index + 1 >= len(split_controls):
        return None
    from_control = split_controls[split_index]
    to_control = split_controls[split_index + 1]
    return (
        str(to_control["label"]),
        str(from_control["label"]),
        str(to_control["label"]),
    )


def _normalized_dashboard_controls(controls: list[dict], *, is_rogaine: bool) -> list[dict]:
    total = len(controls)
    return [
        {
            **control,
            "index": index + 1,
            "label": _dashboard_control_label(index, total, is_rogaine=is_rogaine),
            "kind": _dashboard_control_kind(index, total, is_rogaine=is_rogaine),
        }
        for index, control in enumerate(controls)
    ]


def _dashboard_control_label(index: int, total: int, *, is_rogaine: bool) -> str:
    if index == 0:
        return "С"
    if not is_rogaine and total > 2 and index == 1:
        return "К"
    if total > 1 and index == total - 1:
        return "Ф"
    return str(index if is_rogaine else index - 1)


def _dashboard_control_kind(index: int, total: int, *, is_rogaine: bool) -> str:
    if index == 0:
        return "start"
    if not is_rogaine and total > 2 and index == 1:
        return "start-point"
    if total > 1 and index == total - 1:
        return "finish"
    return "control"


def _problem_split_payload(
    result: dict,
    split_index: int,
    label: str,
    split_time: dict,
    leader_seconds: int,
    gap_seconds: int,
) -> dict:
    return {
        "training_id": result["training_id"],
        "race_result_id": result["race_result_id"],
        "split_index": split_index,
        "split_label": str(label),
        "gap_seconds": gap_seconds,
        "gap_text": race_results._compact_gap(gap_seconds),
        "split_time": _compact_split_time(split_time),
        "leader_time": race_results._format_seconds_to_time(leader_seconds),
        "training_title": result.get("training_title") or "Тренировка",
        "training_date": result.get("training_date") or "",
        "event_name": result.get("event_name") or "",
        "group_name": result.get("group_name") or "",
    }


def _compact_split_time(split_time: dict) -> str:
    seconds = split_time.get("seconds")
    if seconds is not None:
        return _format_minutes_seconds(seconds)
    value = split_time.get("short_time") or split_time.get("time")
    if not value:
        return ""
    parsed_seconds = race_results._result_seconds(value)
    return _format_minutes_seconds(parsed_seconds) if parsed_seconds is not None else value


def _format_minutes_seconds(seconds: int) -> str:
    total = max(int(seconds), 0)
    minutes = total // 60
    rest = total % 60
    return f"{minutes:02d}:{rest:02d}"


def _map_image_url(image_path: str | None) -> str | None:
    if not image_path:
        return None
    upload_root = Path(config.UPLOAD_DIR).expanduser().resolve()
    resolved_image = Path(image_path).expanduser().resolve()
    try:
        relative = resolved_image.relative_to(upload_root)
    except ValueError:
        return None
    return f"/uploads/{relative.as_posix()}"
