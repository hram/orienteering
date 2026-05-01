from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from portal.db import (
    connect_db,
    get_race_result,
    get_training,
    get_training_player,
    list_race_results,
    normalize_db_path,
    save_race_result,
)
from portal.infrastructure import config
from portal.services.race_protocol import fetch_race_protocol, parse_race_protocol_html


BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter()


@router.get("/race-results", response_class=HTMLResponse)
async def race_results_page(request: Request) -> HTMLResponse:
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        results = await list_race_results(conn)
    finally:
        await conn.close()
    return templates.TemplateResponse(request, "race_results.html", {"results": results})


@router.get("/race-results/import", response_class=HTMLResponse)
async def race_result_import_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "race_result_import.html",
        {"url": "", "error": None, "training": None},
    )


@router.get("/trainings/{training_id}/race-result/import", response_class=HTMLResponse)
async def training_race_result_import_page(training_id: str, request: Request) -> HTMLResponse:
    training = await _get_training_or_404(training_id)
    return templates.TemplateResponse(
        request,
        "race_result_import.html",
        {"url": "", "error": None, "training": training},
    )


@router.post("/race-results/import/preview", response_class=HTMLResponse)
async def race_result_import_preview(request: Request, url: str = Form(...)) -> HTMLResponse:
    return await _race_result_import_preview(request, url=url, training_id=None)


@router.post("/trainings/{training_id}/race-result/import/preview", response_class=HTMLResponse)
async def training_race_result_import_preview(
    training_id: str,
    request: Request,
    url: str = Form(...),
) -> HTMLResponse:
    await _get_training_or_404(training_id)
    return await _race_result_import_preview(request, url=url, training_id=training_id)


async def _race_result_import_preview(
    request: Request,
    *,
    url: str,
    training_id: str | None,
) -> HTMLResponse:
    training = await _get_training_or_404(training_id) if training_id else None
    try:
        protocol = await _load_protocol(url)
    except Exception as error:
        return templates.TemplateResponse(
            request,
            "race_result_import.html",
            {"url": url, "error": str(error), "training": training},
            status_code=400,
        )
    return templates.TemplateResponse(
        request,
        "race_result_preview.html",
        {"url": url, "protocol": protocol, "training": training},
    )


@router.post("/race-results/import/save")
async def race_result_import_save(
    url: str = Form(...),
    group_name: str = Form(...),
    self_row_index: int = Form(...),
) -> RedirectResponse:
    return await _race_result_import_save(
        training_id=None,
        url=url,
        group_name=group_name,
        self_row_index=self_row_index,
    )


@router.post("/trainings/{training_id}/race-result/import/save")
async def training_race_result_import_save(
    training_id: str,
    url: str = Form(...),
    group_name: str = Form(...),
    self_row_index: int = Form(...),
) -> RedirectResponse:
    await _get_training_or_404(training_id)
    return await _race_result_import_save(
        training_id=training_id,
        url=url,
        group_name=group_name,
        self_row_index=self_row_index,
    )


async def _race_result_import_save(
    *,
    training_id: str | None,
    url: str,
    group_name: str,
    self_row_index: int,
) -> RedirectResponse:
    protocol = await _load_protocol(url)
    group = next((item for item in protocol.groups if item["name"] == group_name), None)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found in protocol")
    self_participant = next(
        (item for item in group["participants"] if item["row_index"] == self_row_index),
        None,
    )
    if self_participant is None:
        raise HTTPException(status_code=404, detail="Participant not found in group")

    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        result = await save_race_result(
            conn,
            training_id=training_id,
            source_url=url,
            event_name=protocol.event_name,
            event_meta=protocol.event_meta,
            group_name=group["name"],
            group_subtitle=group.get("subtitle") or None,
            controls=group["controls"],
            participants=group["participants"],
            self_row_index=self_row_index,
        )
    finally:
        await conn.close()
    return RedirectResponse(f"/race-results/{result['race_result_id']}", status_code=303)


@router.get("/race-results/{race_result_id}", response_class=HTMLResponse)
async def race_result_page(race_result_id: str, request: Request) -> HTMLResponse:
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        result = await get_race_result(conn, race_result_id)
        training = await get_training_player(conn, result["training_id"]) if result and result.get("training_id") else None
    finally:
        await conn.close()
    if result is None:
        raise HTTPException(status_code=404, detail="Race result not found")
    _prepare_race_result_view(result)
    return templates.TemplateResponse(
        request,
        "race_result.html",
        {"result": result, "training": _training_view_model(training) if training else None},
    )


async def _load_protocol(url: str):
    normalized_url = url.strip()
    if not normalized_url.startswith(("http://", "https://")):
        raise ValueError("URL протокола должен начинаться с http:// или https://")
    content = await asyncio.to_thread(fetch_race_protocol, normalized_url)
    return parse_race_protocol_html(content)


async def _get_training_or_404(training_id: str | None) -> dict:
    if training_id is None:
        raise HTTPException(status_code=404, detail="Training not found")
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        training = await get_training(conn, training_id)
    finally:
        await conn.close()
    if training is None:
        raise HTTPException(status_code=404, detail="Training not found")
    return training


def _compact_time(value: str | None) -> str:
    if not value:
        return ""
    parts = value.split(":")
    if len(parts) == 3 and parts[0] == "00":
        return f"{parts[1]}:{parts[2]}"
    return value


def _prepare_race_result_view(result: dict) -> None:
    participants = result.get("participants", [])
    leader_split_by_split = _leader_split_seconds_by_split(participants)
    self_row_index = result.get("self_row_index")
    self_participant = next((participant for participant in participants if participant.get("row_index") == self_row_index), None)
    gap_ranking = _rank_gap_split_indexes(self_participant, leader_split_by_split)
    hot_gap_indexes = set(gap_ranking[:3])
    warm_gap_indexes = set(gap_ranking[3:5])

    for participant in participants:
        participant["display_result"] = _compact_time(participant.get("result"))
        if participant.get("row_index") != self_row_index:
            continue
        for split_index, split in enumerate(participant.get("splits", [])):
            split_time = split.get("split") or {}
            seconds = split_time.get("seconds")
            leader_seconds = leader_split_by_split[split_index] if split_index < len(leader_split_by_split) else None
            if seconds is None or leader_seconds is None:
                split["leader_gap_text"] = ""
                split["leader_gap_tone"] = ""
                continue
            split["leader_gap_text"] = _compact_gap(seconds - leader_seconds)
            if split_index in hot_gap_indexes:
                split["leader_gap_tone"] = "hot"
            elif split_index in warm_gap_indexes:
                split["leader_gap_tone"] = "warm"
            else:
                split["leader_gap_tone"] = ""


def _leader_split_seconds_by_split(participants: list[dict]) -> list[int | None]:
    split_count = max((len(participant.get("splits", [])) for participant in participants), default=0)
    leader_seconds: list[int | None] = []
    for split_index in range(split_count):
        best_value = None
        for participant in participants:
            splits = participant.get("splits", [])
            if split_index >= len(splits):
                continue
            split_time = splits[split_index].get("split") or {}
            seconds = split_time.get("seconds")
            if seconds is None:
                continue
            if best_value is None or seconds < best_value:
                best_value = seconds
        leader_seconds.append(best_value)
    return leader_seconds


def _rank_gap_split_indexes(self_participant: dict | None, leader_split_by_split: list[int | None]) -> list[int]:
    if not self_participant:
        return []
    gaps: list[tuple[int, int]] = []
    for split_index, split in enumerate(self_participant.get("splits", [])):
        split_time = split.get("split") or {}
        seconds = split_time.get("seconds")
        leader_seconds = leader_split_by_split[split_index] if split_index < len(leader_split_by_split) else None
        if seconds is None or leader_seconds is None:
            continue
        gap_seconds = seconds - leader_seconds
        if gap_seconds <= 0:
            continue
        gaps.append((split_index, gap_seconds))
    gaps.sort(key=lambda item: item[1], reverse=True)
    return [split_index for split_index, _ in gaps]


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
