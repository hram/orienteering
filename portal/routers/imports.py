from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from portal.db import (
    connect_db,
    create_edit_import_draft,
    create_import_draft,
    finalize_import_draft,
    get_latest_race_result_for_training,
    get_import_draft,
    get_training_player,
    list_trainings,
    normalize_db_path,
    set_import_draft_course_controls,
    set_import_draft_georef,
    set_import_draft_map_image,
    set_import_draft_track,
    update_import_draft_details,
    update_training_track_points,
)
from portal.infrastructure import config
from portal.routers.georef import ControlPointPayload
from portal.services.gpx import parse_gpx_track_points
from portal.services.georef import ControlPoint, fit_affine_transform, residuals_meters


BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter()

ALLOWED_MAP_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_TRACK_SUFFIXES = {".gpx"}


class SaveGeorefPayload(BaseModel):
    control_points: list[ControlPointPayload] = Field(..., min_length=3)


class CourseControlPayload(BaseModel):
    index: int = Field(..., ge=1)
    pixel_x: float = Field(..., ge=0)
    pixel_y: float = Field(..., ge=0)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class SaveCourseControlsPayload(BaseModel):
    controls: list[CourseControlPayload] = Field(default_factory=list)


class TrainingTrackPointPayload(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    ele: float | None = None
    time: str | None = None


class SaveTrainingTrackPayload(BaseModel):
    track_points: list[TrainingTrackPointPayload] = Field(..., min_length=2)


@router.get("/trainings", response_class=HTMLResponse)
async def trainings_page(request: Request) -> HTMLResponse:
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        trainings = await list_trainings(conn)
    finally:
        await conn.close()
    return templates.TemplateResponse(request, "trainings.html", {"trainings": trainings})


@router.get("/trainings/new", response_class=HTMLResponse)
async def new_training_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "training_import_details.html",
        {
            "draft": {},
            "form_action": "/trainings/imports",
            "page_title": "Новая тренировка",
            "submit_label": "Дальше",
        },
    )


@router.get("/trainings/{training_id}/edit")
async def edit_training(training_id: str) -> RedirectResponse:
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        draft = await create_edit_import_draft(conn, training_id)
    finally:
        await conn.close()
    if draft is None:
        raise HTTPException(status_code=404, detail="Training not found")
    return RedirectResponse(
        f"/trainings/imports/{draft['draft_id']}/details",
        status_code=303,
    )


@router.get("/trainings/{training_id}/play", response_class=HTMLResponse)
async def training_player_page(training_id: str, request: Request) -> HTMLResponse:
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        training = await get_training_player(conn, training_id)
        race_result = await get_latest_race_result_for_training(conn, training_id)
    finally:
        await conn.close()
    if training is None:
        raise HTTPException(status_code=404, detail="Training not found")
    training_view = _training_view_model(training)
    training_view["has_race_result"] = race_result is not None
    training_view["race_result_split_gaps"] = _race_result_split_gaps(race_result)
    return templates.TemplateResponse(
        request,
        "training_player.html",
        {"training": training_view},
    )


@router.post("/trainings/imports")
async def create_training_import_from_form(
    title: str = Form(...),
    date: str = Form(...),
    training_type: str = Form("training"),
    location: str = Form(""),
    notes: str = Form(""),
) -> RedirectResponse:
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        draft = await create_import_draft(
            conn,
            title=title.strip(),
            date=date,
            training_type=training_type,
            location=location.strip() or None,
            notes=notes.strip() or None,
        )
    finally:
        await conn.close()
    return RedirectResponse(
        f"/trainings/imports/{draft['draft_id']}/map",
        status_code=303,
    )


@router.get("/trainings/imports/{draft_id}/details", response_class=HTMLResponse)
async def edit_import_details_page(draft_id: str, request: Request) -> HTMLResponse:
    draft = await _get_draft_or_404(draft_id)
    return templates.TemplateResponse(
        request,
        "training_import_details.html",
        {
            "draft": _draft_view_model(draft),
            "form_action": f"/trainings/imports/{draft_id}/details",
            "page_title": "Редактирование тренировки",
            "submit_label": "К карте",
        },
    )


@router.post("/trainings/imports/{draft_id}/details")
async def update_training_import_details_from_form(
    draft_id: str,
    title: str = Form(...),
    date: str = Form(...),
    training_type: str = Form("training"),
    location: str = Form(""),
    notes: str = Form(""),
) -> RedirectResponse:
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        draft = await update_import_draft_details(
            conn,
            draft_id,
            title=title.strip(),
            date=date,
            training_type=training_type,
            location=location.strip() or None,
            notes=notes.strip() or None,
        )
    finally:
        await conn.close()
    if draft is None:
        raise HTTPException(status_code=404, detail="Import draft not found")
    return RedirectResponse(
        f"/trainings/imports/{draft_id}/map",
        status_code=303,
    )


@router.get("/trainings/imports/{draft_id}/map", response_class=HTMLResponse)
async def import_map_page(draft_id: str, request: Request) -> HTMLResponse:
    draft = await _get_draft_or_404(draft_id)
    return templates.TemplateResponse(
        request,
        "training_import_map.html",
        {"draft": _draft_view_model(draft)},
    )


@router.get("/trainings/imports/{draft_id}/track", response_class=HTMLResponse)
async def import_track_page(draft_id: str, request: Request) -> HTMLResponse:
    draft = await _get_draft_or_404(draft_id)
    return templates.TemplateResponse(
        request,
        "training_import_track.html",
        {"draft": _draft_view_model(draft)},
    )


@router.get("/api/imports/{draft_id}")
async def get_import_draft_api(draft_id: str) -> dict:
    draft = await _get_draft_or_404(draft_id)
    return {"draft": _draft_view_model(draft)}


@router.post("/api/imports/{draft_id}/map-image")
async def upload_import_map_image(draft_id: str, file: UploadFile = File(...)) -> dict:
    await _get_draft_or_404(draft_id)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_MAP_SUFFIXES:
        raise HTTPException(status_code=400, detail="Map image must be jpg, png, or webp")

    upload_dir = Path(config.UPLOAD_DIR).expanduser() / "imports" / draft_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    image_path = upload_dir / f"map{suffix}"

    with image_path.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            output.write(chunk)

    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        draft = await set_import_draft_map_image(
            conn,
            draft_id,
            image_path=str(image_path),
            filename=file.filename or image_path.name,
        )
    finally:
        await conn.close()
    if draft is None:
        raise HTTPException(status_code=404, detail="Import draft not found")
    return {"draft": _draft_view_model(draft)}


@router.post("/api/imports/{draft_id}/georef")
async def save_import_georef(draft_id: str, payload: SaveGeorefPayload) -> dict:
    draft = await _get_draft_or_404(draft_id)
    if not draft.get("map_image_path"):
        raise HTTPException(status_code=409, detail="Upload a map image before georeferencing")

    points = [
        ControlPoint(point.pixel_x, point.pixel_y, point.lat, point.lon)
        for point in payload.control_points
    ]
    try:
        transform = fit_affine_transform(points)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    residuals = residuals_meters(points, transform)
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        updated = await set_import_draft_georef(
            conn,
            draft_id,
            method="affine",
            control_points=[_model_to_dict(point) for point in payload.control_points],
            transform=transform.to_dict(),
            residuals=residuals,
        )
    finally:
        await conn.close()
    if updated is None:
        raise HTTPException(status_code=404, detail="Import draft not found")
    return {
        "draft": _draft_view_model(updated),
        "method": "affine",
        "transform": transform.to_dict(),
        "residuals": residuals,
        "max_residual_meters": max(item["meters"] for item in residuals),
    }


@router.post("/api/imports/{draft_id}/course-controls")
async def save_import_course_controls(draft_id: str, payload: SaveCourseControlsPayload) -> dict:
    draft = await _get_draft_or_404(draft_id)
    if not draft.get("georef_transform"):
        raise HTTPException(status_code=409, detail="Save map georeferencing before adding controls")

    controls = [_model_to_dict(control) for control in payload.controls]
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        updated = await set_import_draft_course_controls(conn, draft_id, controls=controls)
    finally:
        await conn.close()
    if updated is None:
        raise HTTPException(status_code=404, detail="Import draft not found")
    return {"draft": _draft_view_model(updated)}


@router.post("/api/imports/{draft_id}/track-gpx")
async def upload_import_track_gpx(draft_id: str, file: UploadFile = File(...)) -> dict:
    draft = await _get_draft_or_404(draft_id)
    if not draft.get("georef_transform"):
        raise HTTPException(status_code=409, detail="Save map georeferencing before uploading a track")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_TRACK_SUFFIXES:
        raise HTTPException(status_code=400, detail="Track file must be GPX")

    content = await file.read()
    try:
        track_points = [point.to_dict() for point in parse_gpx_track_points(content)]
    except (ValueError, SyntaxError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    upload_dir = Path(config.UPLOAD_DIR).expanduser() / "imports" / draft_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    gpx_path = upload_dir / "track.gpx"
    gpx_path.write_bytes(content)

    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        updated = await set_import_draft_track(
            conn,
            draft_id,
            gpx_path=str(gpx_path),
            filename=file.filename or gpx_path.name,
            track_points=track_points,
        )
    finally:
        await conn.close()
    if updated is None:
        raise HTTPException(status_code=404, detail="Import draft not found")
    return {
        "draft": _draft_view_model(updated),
        "track_points": track_points,
        "point_count": len(track_points),
    }


@router.post("/api/trainings/{training_id}/track-points")
async def save_training_track_points(training_id: str, payload: SaveTrainingTrackPayload) -> dict:
    track_points = [_model_to_dict(point) for point in payload.track_points]
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        training = await update_training_track_points(
            conn,
            training_id,
            track_points=track_points,
        )
    finally:
        await conn.close()
    if training is None:
        raise HTTPException(status_code=404, detail="Training not found")
    return {"training_id": training_id, "point_count": len(track_points)}


@router.post("/trainings/imports/{draft_id}/finish")
async def finish_training_import(draft_id: str) -> RedirectResponse:
    draft = await _get_draft_or_404(draft_id)
    if not draft.get("georef_transform"):
        raise HTTPException(status_code=409, detail="Save map georeferencing before finishing import")

    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        training = await finalize_import_draft(conn, draft_id)
    finally:
        await conn.close()
    if training is None:
        raise HTTPException(status_code=404, detail="Import draft not found")
    return RedirectResponse("/trainings", status_code=303)


async def _get_draft_or_404(draft_id: str) -> dict:
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        draft = await get_import_draft(conn, draft_id)
    finally:
        await conn.close()
    if draft is None:
        raise HTTPException(status_code=404, detail="Import draft not found")
    return draft


def _draft_view_model(draft: dict) -> dict:
    payload = dict(draft)
    payload["map_image_url"] = None
    image_path = draft.get("map_image_path")
    if image_path:
        upload_root = Path(config.UPLOAD_DIR).expanduser().resolve()
        resolved_image = Path(image_path).expanduser().resolve()
        try:
            relative = resolved_image.relative_to(upload_root)
        except ValueError:
            relative = None
        if relative is not None:
            payload["map_image_url"] = f"/uploads/{relative.as_posix()}"
    return payload


def _training_view_model(training: dict) -> dict:
    payload = dict(training)
    payload["map_image_url"] = None
    image_path = training.get("map_image_path")
    if image_path:
        upload_root = Path(config.UPLOAD_DIR).expanduser().resolve()
        resolved_image = Path(image_path).expanduser().resolve()
        try:
            relative = resolved_image.relative_to(upload_root)
        except ValueError:
            relative = None
        if relative is not None:
            payload["map_image_url"] = f"/uploads/{relative.as_posix()}"
    return payload


def _race_result_split_gaps(race_result: dict | None) -> dict[str, dict[str, str]]:
    if not race_result:
        return {}
    participants = race_result.get("participants", [])
    self_participant = race_result.get("self_participant")
    if not participants or not self_participant:
        return {}

    split_count = max((len(participant.get("splits", [])) for participant in participants), default=0)
    leader_split_seconds: list[int | None] = []
    for split_index in range(split_count):
        leader_seconds = None
        for participant in participants:
            splits = participant.get("splits", [])
            if split_index >= len(splits):
                continue
            split_time = (splits[split_index].get("split") or {})
            seconds = split_time.get("seconds")
            if seconds is None:
                continue
            if leader_seconds is None or seconds < leader_seconds:
                leader_seconds = seconds
        leader_split_seconds.append(leader_seconds)

    positive_gaps: list[tuple[int, int]] = []
    for split_index, split in enumerate(self_participant.get("splits", [])):
        split_time = split.get("split") or {}
        seconds = split_time.get("seconds")
        leader_seconds = leader_split_seconds[split_index] if split_index < len(leader_split_seconds) else None
        if seconds is None or leader_seconds is None:
            continue
        gap_seconds = seconds - leader_seconds
        if gap_seconds <= 0:
            continue
        positive_gaps.append((split_index, gap_seconds))
    positive_gaps.sort(key=lambda item: item[1], reverse=True)
    ranked_indexes = [split_index for split_index, _ in positive_gaps]
    hot_indexes = set(ranked_indexes[:3])
    warm_indexes = set(ranked_indexes[3:5])

    gaps: dict[str, dict[str, str]] = {}
    for split_index, split in enumerate(self_participant.get("splits", [])):
        split_time = split.get("split") or {}
        seconds = split_time.get("seconds")
        leader_seconds = leader_split_seconds[split_index] if split_index < len(leader_split_seconds) else None
        if seconds is None or leader_seconds is None:
            continue
        label = _normalize_split_label(split.get("label"))
        if not label:
            continue
        if split_index in hot_indexes:
            tone = "hot"
        elif split_index in warm_indexes:
            tone = "warm"
        else:
            tone = ""
        gaps[label] = {
            "text": _compact_gap(seconds - leader_seconds),
            "tone": tone,
        }
    return gaps


def _normalize_split_label(label: str | None) -> str:
    value = (label or "").strip()
    return "Ф" if value.upper() == "F" else value


def _compact_gap(seconds: int | None) -> str:
    if seconds is None:
        return ""
    sign = "+" if seconds >= 0 else "-"
    total = abs(int(seconds))
    hours = total // 3600
    minutes = (total % 3600) // 60
    rest = total % 60
    if hours > 0:
        return f"{sign}{hours}:{minutes:02d}:{rest:02d}"
    return f"{sign}{minutes:02d}:{rest:02d}"


def _model_to_dict(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()
