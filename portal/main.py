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
from portal.db import (
    connect_db,
    init_db,
    list_dashboard_error_reason_stats,
    list_dashboard_race_results,
    list_dashboard_split_error_reviews,
    normalize_db_path,
)
from portal.infrastructure import config, media
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


@app.get("/reviewed-splits", response_class=HTMLResponse)
async def reviewed_splits_page(
    request: Request,
    reason_id: str | None = None,
    custom_reason: str | None = None,
) -> HTMLResponse:
    dashboard = await _reviewed_splits_context(
        request,
        reason_id=reason_id,
        custom_reason=custom_reason,
    )
    return templates.TemplateResponse(request, "reviewed_splits.html", dashboard)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.ico")


async def _dashboard_context(request: Request, *, limit: int | None) -> dict:
    user = request.state.user
    viewer_user_id = None if user.is_admin else user.user_id
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        sources = await list_dashboard_race_results(conn, viewer_user_id=viewer_user_id)
        error_reason_rows = await list_dashboard_error_reason_stats(conn, viewer_user_id=viewer_user_id)
    finally:
        await conn.close()
    problem_splits, trainings = _build_problem_splits(sources)
    visible_splits = problem_splits[:limit] if limit is not None else problem_splits
    visible_training_ids = {split["training_id"] for split in visible_splits}
    error_reason_stats = _build_error_reason_stats(error_reason_rows)
    error_reason_partial = (
        "partials/error_reasons_dashboard_admin.html"
        if user.is_admin
        else "partials/error_reasons_dashboard.html"
    )
    error_reason_card_html = templates.get_template(error_reason_partial).render(
        {
            "error_reason_stats": error_reason_stats,
            "request": request,
        }
    )
    return {
        "problem_splits": visible_splits,
        "problem_split_total": len(problem_splits),
        "dashboard_training_data": {
            training_id: training
            for training_id, training in trainings.items()
            if training_id in visible_training_ids
        },
        "error_reason_stats": error_reason_stats,
        "error_reason_card_html": error_reason_card_html,
        "race_position_stats": _build_race_position_stats(sources),
        "viewer_is_admin": user.is_admin,
    }


async def _reviewed_splits_context(
    request: Request,
    *,
    reason_id: str | None,
    custom_reason: str | None,
) -> dict:
    user = request.state.user
    viewer_user_id = None if user.is_admin else user.user_id
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        sources = await list_dashboard_race_results(conn, viewer_user_id=viewer_user_id)
        reviews = await list_dashboard_split_error_reviews(
            conn,
            viewer_user_id=viewer_user_id,
            reason_id=reason_id,
            custom_reason=custom_reason,
        )
    finally:
        await conn.close()
    reviewed_splits, trainings = _build_reviewed_splits(sources, reviews)
    visible_training_ids = {split["training_id"] for split in reviewed_splits}
    reason_label = reviewed_splits[0]["reason_text"] if reviewed_splits and (reason_id or custom_reason) else None
    return {
        "reviewed_splits": reviewed_splits,
        "reviewed_split_total": len(reviewed_splits),
        "reviewed_reason_label": reason_label,
        "dashboard_training_data": {
            training_id: training
            for training_id, training in trainings.items()
            if training_id in visible_training_ids
        },
    }


ERROR_REASON_COLORS = (
    "#c63d3d",
    "#b46a12",
    "#267bc6",
    "#756bd8",
    "#148762",
    "#8c5a2b",
    "#5f6f78",
    "#9f2f68",
)


def _build_error_reason_stats(rows: list[dict]) -> dict:
    if not rows:
        return {
            "total": 0,
            "start_count": 0,
            "top_reason": None,
            "dates": [],
            "reasons": [],
            "insight": "",
        }

    date_labels = sorted({str(row["training_date"]) for row in rows if row.get("training_date")})
    reason_labels: dict[str, str] = {}
    reason_ids: dict[str, str | None] = {}
    counts_by_key: dict[str, int] = {}
    counts_by_key_date: dict[tuple[str, str], int] = {}

    for row in rows:
        label = str(row.get("reason_label") or "Другое")
        reason_id = row.get("reason_id")
        key = str(reason_id or label)
        date = str(row.get("training_date") or "")
        count = int(row.get("count") or 0)
        reason_labels[key] = label
        reason_ids[key] = str(reason_id) if reason_id else None
        counts_by_key[key] = counts_by_key.get(key, 0) + count
        if date:
            counts_by_key_date[(key, date)] = counts_by_key_date.get((key, date), 0) + count

    sorted_keys = sorted(counts_by_key, key=lambda key: (-counts_by_key[key], reason_labels[key]))
    reasons = [
        {
            "label": reason_labels[key],
            "count": counts_by_key[key],
            "color": ERROR_REASON_COLORS[index % len(ERROR_REASON_COLORS)],
            "trend": [counts_by_key_date.get((key, date), 0) for date in date_labels],
            "url": _reviewed_splits_reason_url(reason_ids[key], reason_labels[key]),
        }
        for index, key in enumerate(sorted_keys[:5])
    ]
    top_reason = reasons[0] if reasons else None
    return {
        "total": sum(counts_by_key.values()),
        "start_count": len(date_labels),
        "top_reason": top_reason,
        "dates": [_format_dashboard_date_label(date) for date in date_labels],
        "reasons": reasons,
        "insight": _error_reason_insight(top_reason, date_labels),
    }


def _reviewed_splits_reason_url(reason_id: str | None, label: str) -> str:
    from urllib.parse import urlencode

    query = {"reason_id": reason_id} if reason_id else {"custom_reason": label}
    return f"/reviewed-splits?{urlencode(query)}"


def _format_dashboard_date_label(value: str) -> str:
    parts = value.split("-")
    if len(parts) == 3:
        return f"{parts[2]}.{parts[1]}"
    return value


def _error_reason_insight(top_reason: dict | None, date_labels: list[str]) -> str:
    if not top_reason or len(date_labels) < 2:
        return ""
    first = top_reason["trend"][0]
    last = top_reason["trend"][-1]
    label = top_reason["label"]
    if last < first:
        return f"«{label}» встречается реже: с {first} до {last} за период."
    if last > first:
        return f"«{label}» пока растет: с {first} до {last} за период."
    return f"«{label}» держится на одном уровне: {last} за последний старт."


def _build_race_position_stats(sources: list[dict]) -> dict:
    points = []
    for result in sources:
        self_participant = result.get("self_participant") or {}
        place = _dashboard_effective_place(result, self_participant)
        if place is None:
            continue
        participant_count = _dashboard_ranked_participant_count(result, place)
        date = str(result.get("race_date") or result.get("training_date") or "")
        if not date:
            continue
        points.append(
            {
                "date": date,
                "date_label": _format_dashboard_date_label(date),
                "place": place,
                "participant_count": participant_count,
                "position_ratio": round(place / participant_count, 4) if participant_count else None,
                "group_name": result.get("group_name") or "",
                "event_name": result.get("event_name") or result.get("training_title") or "Соревнование",
                "training_title": result.get("training_title") or result.get("event_name") or "Соревнование",
            }
        )
    points.sort(key=lambda point: (point["date"], point["event_name"], point["group_name"]))
    latest = points[-1] if points else None
    comparable_points = [point for point in points if point["position_ratio"] is not None]
    best = min(comparable_points, key=lambda point: point["position_ratio"]) if comparable_points else None
    return {
        "points": points,
        "race_count": len(points),
        "latest_place": latest["place"] if latest else None,
        "latest_participant_count": latest["participant_count"] if latest else None,
        "best_place": best["place"] if best else None,
        "best_participant_count": best["participant_count"] if best else None,
        "max_place": max((point["place"] for point in points), default=1),
    }


def _dashboard_ranked_participant_count(result: dict, place: int) -> int:
    participants = result.get("participants") or []
    place_numbers = [
        parsed
        for participant in participants
        if (parsed := _place_to_int(participant.get("place"))) is not None
    ]
    return max([len(participants), place, *place_numbers], default=place)


def _dashboard_effective_place(result: dict, self_participant: dict) -> int | None:
    if not self_participant:
        return None
    kind = str(result.get("kind") or "").strip()
    participants = result.get("participants") or []
    is_relay_course = kind == "course" and any(str(participant.get("lap") or "").strip() for participant in participants)
    if not is_relay_course:
        return _place_to_int(self_participant.get("place"))

    self_row_index = self_participant.get("row_index")
    ranked = []
    for participant in participants:
        display_seconds = _dashboard_display_result_seconds(participant, kind)
        if display_seconds is None:
            continue
        ranked.append(
            (
                display_seconds,
                _place_to_int(participant.get("place")) or 10**9,
                participant.get("row_index") if isinstance(participant.get("row_index"), int) else 10**9,
                participant,
            )
        )
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    for index, (_, _, _, participant) in enumerate(ranked, start=1):
        if participant.get("row_index") == self_row_index:
            return index
    return _place_to_int(self_participant.get("place"))


def _dashboard_display_result_seconds(participant: dict, kind: str | None) -> int | None:
    if kind == "course" and str(participant.get("lap") or "").strip():
        total_seconds = 0
        has_split_seconds = False
        for split_index, split in enumerate(participant.get("splits", [])):
            split_time = split.get("split") or {}
            seconds = split_time.get("seconds")
            if seconds is None:
                return race_results._result_seconds(participant.get("result"))
            total_seconds += int(seconds)
            has_split_seconds = True
        if has_split_seconds:
            return total_seconds
    return race_results._result_seconds(participant.get("result"))


def _place_to_int(value: object) -> int | None:
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


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


def _build_reviewed_splits(sources: list[dict], reviews: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    reviews_by_key = {
        (
            review["training_id"],
            review["split_label"],
            review["from_control_label"],
            review["to_control_label"],
        ): review
        for review in reviews
    }
    reviewed_splits: list[dict] = []
    trainings: dict[str, dict] = {}
    for result in sources:
        training_id = result.get("training_id")
        if not training_id or not _dashboard_training_ready(result):
            continue
        trainings.setdefault(training_id, _dashboard_training_payload(result))
        if result.get("kind") == "score":
            _append_score_reviewed_splits(reviewed_splits, result, reviews_by_key)
        else:
            _append_course_reviewed_splits(reviewed_splits, result, reviews_by_key)
    reviewed_splits.sort(key=lambda item: (item.get("training_date") or "", item.get("reviewed_at") or ""), reverse=True)
    for index, item in enumerate(reviewed_splits):
        item["problem_index"] = index
    return reviewed_splits, trainings


def _dashboard_training_ready(result: dict) -> bool:
    return bool(
        _dashboard_training_has_map(result)
        and result.get("training_course_controls")
        and result.get("training_track_points")
    )


def _dashboard_training_payload(result: dict) -> dict:
    map_layers = _dashboard_map_layers_payload(result.get("training_map_layers") or [])
    return {
        "training_id": result["training_id"],
        "training_type": result.get("training_type") or "",
        "map_image_url": _map_image_url(result.get("map_image_path")),
        "map_layers": map_layers,
        "course_controls": result.get("training_course_controls") or [],
        "track_points": result.get("training_track_points") or [],
        "transform": result.get("georef_transform"),
    }


def _dashboard_training_has_map(result: dict) -> bool:
    if result.get("map_image_path") and result.get("georef_transform"):
        return True
    return any(
        layer.get("image_path") and layer.get("georef_transform")
        for layer in result.get("training_map_layers") or []
    )


def _dashboard_map_layers_payload(layers: list[dict]) -> list[dict]:
    result = []
    for layer in layers:
        item = dict(layer)
        item["map_image_url"] = _map_image_url(layer.get("image_path"))
        result.append(item)
    return result


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


def _append_course_reviewed_splits(
    items: list[dict],
    result: dict,
    reviews_by_key: dict[tuple[str, str, str, str], dict],
) -> None:
    race_results._prepare_race_result_view(result)
    self_participant = result.get("self_participant")
    if not self_participant:
        return
    leader_splits = race_results._leader_split_seconds_by_split(result.get("participants", []))
    for split_index, split in enumerate(self_participant.get("splits", [])):
        key = _dashboard_review_key(result, split_index)
        if not key:
            continue
        review = reviews_by_key.get((result["training_id"], *key))
        if not review:
            continue
        split_time = race_results._split_stage_time(split, split_index) or {}
        seconds = split_time.get("seconds")
        leader_seconds = leader_splits[split_index] if split_index < len(leader_splits) else None
        if seconds is None or leader_seconds is None:
            continue
        item = _problem_split_payload(
            result,
            split_index,
            split.get("label", ""),
            split_time,
            leader_seconds,
            seconds - leader_seconds,
        )
        _attach_review_payload(item, review)
        items.append(item)


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


def _append_score_reviewed_splits(
    items: list[dict],
    result: dict,
    reviews_by_key: dict[tuple[str, str, str, str], dict],
) -> None:
    race_results._prepare_score_result_view(result)
    self_participant = result.get("self_participant")
    if not self_participant:
        return
    for visit_index, visit in enumerate(self_participant.get("visits", [])):
        key = _dashboard_review_key(result, visit_index)
        if not key:
            continue
        review = reviews_by_key.get((result["training_id"], *key))
        if not review:
            continue
        split = visit.get("split") or {}
        seconds = split.get("seconds")
        leader_seconds = visit.get("best_leg_seconds")
        if seconds is None or leader_seconds is None:
            continue
        label = visit.get("code") or str(visit_index + 1)
        item = _problem_split_payload(
            result,
            visit_index,
            label,
            split,
            leader_seconds,
            seconds - leader_seconds,
        )
        _attach_review_payload(item, review)
        items.append(item)


def _attach_review_payload(item: dict, review: dict) -> None:
    item["reviewed_at"] = review.get("reviewed_at") or ""
    item["reason_text"] = review.get("reason_label") or review.get("custom_reason") or "Другое"


def _is_reviewed_problem_split(result: dict, split_index: int) -> bool:
    reviewed_keys = result.get("reviewed_split_keys") or set()
    if not reviewed_keys:
        return False
    key = _dashboard_review_key(result, split_index)
    return key in reviewed_keys if key else False


def _dashboard_review_key(result: dict, split_index: int) -> tuple[str, str, str] | None:
    controls = _dashboard_course_controls(result)
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


def _dashboard_course_controls(result: dict) -> list[dict]:
    map_layers = result.get("training_map_layers") or []
    layer_controls: list[dict] = []
    for layer_index, layer in enumerate(map_layers):
        layer_id = layer.get("id") or f"map-{layer_index + 1}"
        for control in layer.get("course_controls") or []:
            layer_controls.append({**control, "map_layer_id": control.get("map_layer_id") or layer_id})
    controls = layer_controls or (result.get("training_course_controls") or [])
    return _normalized_dashboard_controls(
        controls,
        is_rogaine=result.get("training_type") == "rogaine",
    )


def _normalized_dashboard_controls(controls: list[dict], *, is_rogaine: bool) -> list[dict]:
    total = len(controls)
    return [
        {
            **control,
            "index": index + 1,
            "label": control.get("label") or _dashboard_control_label(index, total, is_rogaine=is_rogaine),
            "kind": control.get("kind") or _dashboard_control_kind(index, total, is_rogaine=is_rogaine),
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
    return media.map_image_url(image_path)
