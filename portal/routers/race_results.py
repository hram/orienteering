from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from portal.services import race_grabber
from portal.db import (
    attach_race_result_to_training,
    connect_db,
    delete_race_result,
    get_race_result,
    get_training,
    get_training_player,
    list_attachable_race_results,
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


@router.get("/race-results/grabber", response_class=HTMLResponse)
async def race_result_grabber_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "race_result_grabber.html",
        {"participant_query": "", "include_archive": False, "search": None},
    )


@router.post("/race-results/grabber", response_class=HTMLResponse)
async def race_result_grabber_search(
    request: Request,
    participant_query: str = Form(...),
    include_archive: str | None = Form(None),
) -> HTMLResponse:
    include_archive_flag = include_archive == "1"
    search = await asyncio.to_thread(
        race_grabber.find_participant_races,
        participant_query,
        include_archive_flag,
    )
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        imported_results = await list_race_results(conn)
    finally:
        await conn.close()
    _annotate_grabber_matches(search, imported_results)
    return templates.TemplateResponse(
        request,
        "race_result_grabber.html",
        {
            "participant_query": participant_query,
            "include_archive": include_archive_flag,
            "search": search,
        },
    )


@router.get("/race-results/import/open", response_class=HTMLResponse)
async def race_result_import_open(
    request: Request,
    url: str,
    group_name: str,
    participant_name: str,
) -> HTMLResponse:
    return await _race_result_import_preview(
        request,
        url=url,
        training_id=None,
        selected_group_name=group_name,
        selected_participant_name=participant_name,
    )


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
    existing_results = await _list_attachable_results(training_id)
    return templates.TemplateResponse(
        request,
        "race_result_import.html",
        {"url": "", "error": None, "training": training, "existing_results": existing_results},
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
    selected_group_name: str | None = None,
    selected_participant_name: str | None = None,
) -> HTMLResponse:
    training = await _get_training_or_404(training_id) if training_id else None
    try:
        protocol = await _load_protocol(url)
    except Exception as error:
        existing_results = await _list_attachable_results(training_id)
        return templates.TemplateResponse(
            request,
            "race_result_import.html",
            {
                "url": url,
                "error": str(error),
                "training": training,
                "existing_results": existing_results,
            },
            status_code=400,
        )
    protocol_groups = protocol.groups
    if selected_group_name:
        selected_groups = [group for group in protocol.groups if group.get("name") == selected_group_name]
        if selected_groups:
            protocol_groups = selected_groups
    protocol_view = type(protocol)(
        event_name=protocol.event_name,
        event_meta=protocol.event_meta,
        groups=protocol_groups,
    )
    return templates.TemplateResponse(
        request,
        "race_result_preview.html",
        {
            "url": url,
            "protocol": protocol_view,
            "training": training,
            "selected_group_name": selected_group_name,
            "selected_participant_name": selected_participant_name,
        },
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


@router.post("/trainings/{training_id}/race-result/attach")
async def training_race_result_attach(
    training_id: str,
    race_result_id: str = Form(...),
) -> RedirectResponse:
    await _get_training_or_404(training_id)
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        result = await get_race_result(conn, race_result_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Race result not found")
        if result.get("training_id") and result["training_id"] != training_id:
            raise HTTPException(status_code=409, detail="Race result already attached to another training")
        attached = await attach_race_result_to_training(
            conn,
            race_result_id=race_result_id,
            training_id=training_id,
        )
    finally:
        await conn.close()
    if attached is None:
        raise HTTPException(status_code=404, detail="Race result not found")
    return RedirectResponse(f"/race-results/{race_result_id}", status_code=303)


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


@router.post("/race-results/{race_result_id}/delete")
async def race_result_delete(race_result_id: str) -> RedirectResponse:
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        deleted = await delete_race_result(conn, race_result_id)
    finally:
        await conn.close()
    if not deleted:
        raise HTTPException(status_code=404, detail="Race result not found")
    return RedirectResponse("/race-results", status_code=303)


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


async def _list_attachable_results(training_id: str | None) -> list[dict]:
    if training_id is None:
        return []
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        return await list_attachable_race_results(conn, training_id)
    finally:
        await conn.close()


def _compact_time(value: str | None) -> str:
    if not value:
        return ""
    parts = value.split(":")
    if len(parts) == 3 and parts[0] == "00":
        return f"{parts[1]}:{parts[2]}"
    return value


def _annotate_grabber_matches(search: dict, imported_results: list[dict]) -> None:
    imported_keys = {
        (
            race_grabber.build_report_id(result.get("source_url", "")),
            (result.get("self_participant") or {}).get("name", "").casefold(),
        )
        for result in imported_results
    }
    for match in search.get("matches", []):
        match["imported"] = (
            match.get("report_id", ""),
            match.get("participant_name", "").casefold(),
        ) in imported_keys
        match["import_url"] = "/race-results/import/open?" + urlencode(
            {
                "url": match.get("split_url", ""),
                "group_name": match.get("group_name", ""),
                "participant_name": match.get("participant_name", ""),
            }
        )


def _prepare_race_result_view(result: dict) -> None:
    participants = result.get("participants", [])
    leader_split_by_split = _leader_split_seconds_by_split(participants)
    self_row_index = result.get("self_row_index")
    self_participant = next((participant for participant in participants if participant.get("row_index") == self_row_index), None)
    hot_gap_indexes, warm_gap_indexes, good_gap_indexes = _classify_gap_indexes(self_participant, leader_split_by_split)
    problem_indexes = hot_gap_indexes | warm_gap_indexes
    controls = result.get("controls", [])
    result["problem_split_indexes"] = sorted(problem_indexes)
    result["virtual_leader"] = _virtual_leader_participant(participants, leader_split_by_split, controls)
    result["self_problem_total_gap"] = _self_problem_total_gap(self_participant, leader_split_by_split, problem_indexes)
    if self_participant:
        for split_index, split in enumerate(self_participant.get("splits", [])):
            split_time = _split_stage_time(split, split_index)
            if not split_time:
                continue
            split_time["short_time"] = _normalize_short_time(split_time.get("time"))
            distance = controls[split_index].get("distance_meters") if split_index < len(controls) else None
            split_time["pace"] = _format_pace(split_time.get("seconds"), distance)

    for participant in participants:
        participant["display_result"] = _compact_time(participant.get("result"))
        participant["relative_gap_text"] = ""
        participant["relative_gap_tone"] = ""
        if self_participant and participant.get("row_index") != self_row_index:
            participant_seconds = _result_seconds(participant.get("result"))
            self_seconds = _result_seconds(self_participant.get("result"))
            if participant_seconds is not None and self_seconds is not None:
                participant["relative_gap_text"] = _compact_gap(self_seconds - participant_seconds)
                participant["relative_gap_tone"] = "hot" if participant_seconds < self_seconds else "good"
        if participant.get("row_index") != self_row_index:
            continue
        for split_index, split in enumerate(participant.get("splits", [])):
            split_time = _split_stage_time(split, split_index) or {}
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
            elif split_index in good_gap_indexes:
                split["leader_gap_tone"] = "good"
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
            split_time = _split_stage_time(splits[split_index], split_index) or {}
            seconds = split_time.get("seconds")
            if seconds is None:
                continue
            if best_value is None or seconds < best_value:
                best_value = seconds
        leader_seconds.append(best_value)
    return leader_seconds


def _classify_gap_indexes(
    self_participant: dict | None,
    leader_split_by_split: list[int | None],
) -> tuple[set[int], set[int], set[int]]:
    if not self_participant:
        return set(), set(), set()
    gaps: list[tuple[int, int]] = []
    for split_index, split in enumerate(self_participant.get("splits", [])):
        split_time = _split_stage_time(split, split_index) or {}
        seconds = split_time.get("seconds")
        leader_seconds = leader_split_by_split[split_index] if split_index < len(leader_split_by_split) else None
        if seconds is None or leader_seconds is None:
            continue
        gaps.append((split_index, seconds - leader_seconds))

    good_sorted = sorted(gaps, key=lambda item: item[1])
    good_indexes = {split_index for split_index, _ in good_sorted[:3]}

    remaining = [
        (split_index, gap_seconds)
        for split_index, gap_seconds in gaps
        if split_index not in good_indexes and gap_seconds > 0
    ]
    remaining.sort(key=lambda item: item[1], reverse=True)
    hot_indexes = {split_index for split_index, _ in remaining[:3]}
    warm_indexes = {split_index for split_index, _ in remaining[3:6]}
    return hot_indexes, warm_indexes, good_indexes


def _format_pace(seconds: int | None, meters: int | float | None) -> str:
    if seconds is None or seconds <= 0 or meters is None or meters <= 0:
        return ""
    pace_seconds_per_km = float(seconds) * 1000.0 / float(meters)
    minutes = int(pace_seconds_per_km // 60)
    rest = int(round(pace_seconds_per_km - minutes * 60))
    if rest == 60:
        minutes += 1
        rest = 0
    return f"{minutes:02d}:{rest:02d}"


def _normalize_short_time(value: str | None) -> str:
    if not value:
        return ""
    parts = value.split(":")
    if len(parts) != 2:
        return value
    try:
        minutes = int(parts[0])
    except ValueError:
        return value
    return f"{minutes:02d}:{parts[1]}"


def _format_seconds_to_time(seconds: int | None) -> str:
    if seconds is None:
        return ""
    total = max(int(seconds), 0)
    hours = total // 3600
    minutes = (total % 3600) // 60
    rest = total % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{rest:02d}"
    return f"{minutes:02d}:{rest:02d}"


def _virtual_leader_participant(
    participants: list[dict],
    leader_split_seconds: list[int | None],
    controls: list[dict] | None = None,
) -> dict | None:
    if not participants or not leader_split_seconds:
        return None
    if any(seconds is None for seconds in leader_split_seconds):
        return None

    sample_splits: list[dict] = []
    for participant in participants:
        splits = participant.get("splits", [])
        if len(splits) >= len(leader_split_seconds):
            sample_splits = splits
            break

    splits: list[dict] = []
    cumulative = 0
    for split_index, leader_seconds in enumerate(leader_split_seconds):
        cumulative += leader_seconds
        label = sample_splits[split_index].get("label", "") if split_index < len(sample_splits) else ""
        formatted_split = _format_seconds_to_time(leader_seconds)
        distance = controls[split_index].get("distance_meters") if controls and split_index < len(controls) else None
        splits.append({
            "label": label,
            "split": {
                "seconds": leader_seconds,
                "time": formatted_split,
                "short_time": formatted_split,
                "pace": _format_pace(leader_seconds, distance),
                "rank": 1,
            },
            "cumulative": {
                "seconds": cumulative,
                "time": _format_seconds_to_time(cumulative),
                "rank": None,
            },
        })

    return {
        "name": "Идеальный лидер",
        "place": "★",
        "display_result": _format_seconds_to_time(cumulative),
        "splits": splits,
    }


def _self_problem_total_gap(
    self_participant: dict | None,
    leader_split_seconds: list[int | None],
    problem_indexes: set[int],
) -> str:
    if not self_participant or not problem_indexes:
        return ""
    splits = self_participant.get("splits", [])
    total_gap = 0
    has_data = False
    for split_index in problem_indexes:
        if split_index >= len(splits):
            continue
        split_seconds = (_split_stage_time(splits[split_index], split_index) or {}).get("seconds")
        leader_seconds = leader_split_seconds[split_index] if split_index < len(leader_split_seconds) else None
        if split_seconds is None or leader_seconds is None:
            continue
        total_gap += split_seconds - leader_seconds
        has_data = True
    return _compact_gap(total_gap) if has_data else ""


def _split_stage_time(split: dict, split_index: int) -> dict | None:
    split_time = split.get("split")
    if split_time:
        return split_time
    if split_index == 0:
        return split.get("cumulative")
    return None


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


def _result_seconds(value: str | None) -> int | None:
    if not value:
        return None
    parts = value.strip().split(":")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    numbers = [int(part) for part in parts]
    if len(numbers) == 3:
        return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    if len(numbers) == 1:
        return numbers[0]
    return None


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
