from __future__ import annotations

import asyncio
import html as html_lib
import json
import re
from pathlib import Path
from statistics import median
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

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
from portal.services.race_protocol import ParsedRaceProtocol, fetch_race_protocol, parse_race_protocol_html


BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter()


@router.get("/race-results", response_class=HTMLResponse)
async def race_results_page(request: Request) -> HTMLResponse:
    user = request.state.user
    viewer_user_id = None if user.is_admin else user.user_id
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        results = await list_race_results(conn, viewer_user_id=viewer_user_id)
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
    from portal.services import race_grabber

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
        kind=protocol.kind,
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
    if _is_orgeo_url(url):
        protocol = await asyncio.to_thread(_load_orgeo_full_protocol, url, group_name)
    else:
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
            kind=protocol.kind,
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
    if result.get("kind") == "score":
        _prepare_score_result_view(result)
    else:
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
    if _is_orgeo_url(normalized_url):
        return await asyncio.to_thread(_load_orgeo_preview_protocol, normalized_url)
    content = await asyncio.to_thread(fetch_race_protocol, normalized_url)
    return parse_race_protocol_html(content)


def _is_orgeo_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.endswith("orgeo.ru")


def _load_orgeo_preview_protocol(url: str) -> ParsedRaceProtocol:
    event_id, sub_id = _orgeo_event_context(url)
    info_url = f"https://orgeo.ru/event/info/{event_id}"
    export_url = f"https://orgeo.ru/event/export/event_id/{event_id}/sub_id/{sub_id}/format/json"
    info_content = fetch_race_protocol(info_url)
    export_content = fetch_race_protocol(export_url)
    event_name = _extract_orgeo_event_name(info_content)
    event_meta = _extract_orgeo_event_meta(info_content)
    groups = _parse_orgeo_export_groups(json.loads(export_content))
    if not event_name:
        raise ValueError("Не найдено название соревнований в Orgeo")
    if not groups:
        raise ValueError("Не найдены группы в Orgeo")
    return ParsedRaceProtocol(event_name=event_name, event_meta=event_meta, groups=groups, kind="course")


def _load_orgeo_full_protocol(url: str, group_name: str) -> ParsedRaceProtocol:
    event_id, sub_id = _orgeo_event_context(url)
    info_url = f"https://orgeo.ru/event/info/{event_id}"
    export_url = f"https://orgeo.ru/online/finish/{event_id}?" + urlencode(
        {"s": "1", "d": group_name, "api": "json", "test_time": "", "phone": "0"}
    )
    info_content = fetch_race_protocol(info_url)
    export_content = fetch_race_protocol(export_url)
    event_name = _extract_orgeo_event_name(info_content)
    event_meta = _extract_orgeo_event_meta(info_content)
    groups = _parse_orgeo_live_groups(json.loads(export_content), group_name)
    if not event_name:
        raise ValueError("Не найдено название соревнований в Orgeo")
    if not groups:
        raise ValueError("Не найдены группы в Orgeo")
    return ParsedRaceProtocol(event_name=event_name, event_meta=event_meta, groups=groups, kind="course")


def _orgeo_event_context(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    path = parsed.path or ""
    export_match = re.search(r"/event/export/event_id/(\d+)/sub_id/(\d+)/format/json/?$", path)
    if export_match:
        return export_match.group(1), int(export_match.group(2))
    info_match = re.search(r"/event/info/(\d+)/?$", path)
    if info_match:
        return info_match.group(1), 1
    live_fragment = (parsed.fragment or "").lstrip("#/")
    live_match = re.match(r"(\d+)(?:/(\d+))?$", live_fragment)
    if live_match:
        return live_match.group(1), int(live_match.group(2) or 1)
    raise ValueError("Не удалось распознать URL Orgeo")


def _extract_orgeo_event_name(content: str) -> str:
    patterns = (
        r'<meta\s+itemprop="name"\s+content="([^"]+)"',
        r'<meta\s+property="og:title"\s+content="Orgeo:\s*([^"]+?)\s*-\s*Инфо\s*-\s*События"',
        r"<title>Orgeo:\s*(.*?)\s*-\s*Инфо\s*-\s*События</title>",
    )
    for pattern in patterns:
        match = re.search(pattern, content, re.I | re.S)
        if match:
            return _clean_orgeo_text(match.group(1))
    return ""


def _extract_orgeo_event_meta(content: str) -> str:
    patterns = (
        r'<meta\s+itemprop="description"\s+content="([^"]+)"',
        r'<meta\s+property="og:description"\s+content="([^"]+)"',
        r'<meta\s+name="description"\s+content="([^"]+)"',
    )
    for pattern in patterns:
        match = re.search(pattern, content, re.I | re.S)
        if match:
            return _clean_orgeo_text(match.group(1))
    return ""


def _parse_orgeo_export_groups(data: dict) -> list[dict]:
    finish = data.get("finish")
    if isinstance(finish, list):
        rows = finish
    elif isinstance(data, dict):
        rows = [row for row in data.values() if isinstance(row, dict)]
    else:
        rows = []
    if not rows:
        raise ValueError("Не найден экспорт результатов Orgeo")

    grouped_rows: dict[str, list[tuple[int, dict]]] = {}
    group_order: list[str] = []
    for source_index, row in enumerate(rows):
        group_name = _orgeo_group_name(row)
        if not group_name:
            continue
        if group_name not in grouped_rows:
            grouped_rows[group_name] = []
            group_order.append(group_name)
        grouped_rows[group_name].append((source_index, row))

    groups: list[dict] = []
    for group_name in group_order:
        rows = grouped_rows[group_name]
        rows.sort(key=lambda item: _orgeo_participant_sort_key(item[0], item[1]))
        participants = [_parse_orgeo_participant(row_index, row) for row_index, (_, row) in enumerate(rows)]
        _apply_orgeo_control_distances(participants)
        _fill_missing_split_ranks(participants)
        controls = participants[0]["_orgeo_controls"] if participants and participants[0].get("_orgeo_controls") else []
        for participant in participants:
            participant.pop("_orgeo_controls", None)
        groups.append(
            {
                "name": group_name,
                "subtitle": "",
                "controls": controls,
                "participants": participants,
            }
        )
    return groups


def _parse_orgeo_live_groups(data: dict, group_name: str | None = None) -> list[dict]:
    finish = data.get("finish")
    if not isinstance(finish, list):
        raise ValueError("Не найден экспорт результатов Orgeo")

    grouped_rows: dict[str, list[tuple[int, dict]]] = {}
    group_order: list[str] = []
    for source_index, row in enumerate(finish):
        if not isinstance(row, dict):
            continue
        row_group_name = _orgeo_live_group_name(row)
        if not row_group_name:
            continue
        if group_name and row_group_name != group_name:
            continue
        if row_group_name not in grouped_rows:
            grouped_rows[row_group_name] = []
            group_order.append(row_group_name)
        grouped_rows[row_group_name].append((source_index, row))

    groups: list[dict] = []
    for current_group_name in group_order:
        rows = grouped_rows[current_group_name]
        rows.sort(key=lambda item: _orgeo_participant_sort_key(item[0], item[1]))
        participants = [_parse_orgeo_live_participant(row_index, row) for row_index, (_, row) in enumerate(rows)]
        _apply_orgeo_control_distances(participants)
        _fill_missing_split_ranks(participants)
        controls = participants[0]["_orgeo_controls"] if participants and participants[0].get("_orgeo_controls") else []
        for participant in participants:
            participant.pop("_orgeo_controls", None)
        groups.append(
            {
                "name": current_group_name,
                "subtitle": "",
                "controls": controls,
                "participants": participants,
            }
        )
    return groups


def _fill_missing_split_ranks(participants: list[dict]) -> None:
    split_count = max((len(participant.get("splits", [])) for participant in participants), default=0)
    for split_index in range(split_count):
        ranked_seconds = sorted(
            {
                split_time["seconds"]
                for participant in participants
                if split_index < len(participant.get("splits", []))
                for split_time in [participant["splits"][split_index].get("split")]
                if split_time and split_time.get("seconds") is not None
            }
        )
        ranks = {seconds: index + 1 for index, seconds in enumerate(ranked_seconds)}
        for participant in participants:
            splits = participant.get("splits", [])
            if split_index >= len(splits):
                continue
            split_time = splits[split_index].get("split")
            if not split_time or split_time.get("rank") is not None:
                continue
            seconds = split_time.get("seconds")
            if seconds is not None and seconds in ranks:
                split_time["rank"] = ranks[seconds]


def _orgeo_group_name(row: dict) -> str:
    for key in ("group_name", "dist", "team"):
        value = row.get(key)
        if value:
            return str(value).strip()
    return ""


def _orgeo_live_group_name(row: dict) -> str:
    for key in ("dist", "group_name", "team"):
        value = row.get(key)
        if value:
            return str(value).strip()
    return ""


def _orgeo_participant_sort_key(source_index: int, row: dict) -> tuple[int, int]:
    place = row.get("place")
    try:
        place_value = int(place)
    except (TypeError, ValueError):
        place_value = 10**9
    return place_value, source_index


def _parse_orgeo_participant(row_index: int, row: dict) -> dict:
    split_pairs = _orgeo_time_code_pairs(str(row.get("spl") or ""))
    comment_pairs = _orgeo_time_code_pairs(str(row.get("spl_comment") or ""))
    cumulative_seconds = 0
    splits: list[dict] = []
    controls: list[dict] = []

    for split_index, (split_time_text, code) in enumerate(split_pairs):
        split_seconds = _parse_orgeo_seconds(split_time_text)
        cumulative_seconds += split_seconds or 0
        pace_text = comment_pairs[split_index][0] if split_index < len(comment_pairs) else ""
        pace_seconds = _parse_orgeo_pace_seconds(pace_text)
        distance_meters = None
        if split_seconds is not None and pace_seconds and pace_seconds > 0:
            distance_meters = round(split_seconds * 1000 / pace_seconds)
        controls.append(
            {
                "label": str(split_index + 1),
                "code": code,
                "distance_meters": distance_meters,
            }
        )
        splits.append(
            {
                "label": str(split_index + 1),
                "code": code,
                "distance_meters": distance_meters,
                "cumulative": {
                    "raw": _format_seconds_to_time(cumulative_seconds) if split_seconds is not None else "",
                    "time": _format_seconds_to_time(cumulative_seconds) if split_seconds is not None else "",
                    "short_time": _normalize_short_time(_format_seconds_to_time(cumulative_seconds)) if split_seconds is not None else "",
                    "seconds": cumulative_seconds if split_seconds is not None else None,
                },
                "split": {
                    "raw": split_time_text,
                    "time": split_time_text,
                    "short_time": _normalize_short_time(split_time_text),
                    "seconds": split_seconds,
                    "pace": pace_text or "",
                },
            }
        )

    return {
        "row_index": row_index,
        "order": _to_int_or_none(str(row.get("place") or "")),
        "name": str(row.get("name") or "").strip(),
        "bib": str(row.get("number") or row.get("bib") or row.get("si") or "").strip(),
        "result": str(row.get("finish") or row.get("time") or "").strip(),
        "place": str(row.get("place") or "").strip(),
        "gap": str(row.get("diff") or "").strip(),
        "splits": splits,
        "_orgeo_controls": controls,
    }


def _parse_orgeo_live_participant(row_index: int, row: dict) -> dict:
    split_pairs = _orgeo_time_code_pairs(str(row.get("spl") or ""))
    comment_pairs = _orgeo_time_code_pairs(str(row.get("spl_comment") or ""))
    cumulative_seconds = 0
    splits: list[dict] = []
    controls: list[dict] = []

    for split_index, (split_time_text, code) in enumerate(split_pairs):
        split_seconds = _parse_orgeo_seconds(split_time_text)
        if split_seconds is not None:
            cumulative_seconds += split_seconds
        pace_text = comment_pairs[split_index][0] if split_index < len(comment_pairs) else ""
        pace_seconds = _parse_orgeo_pace_seconds(pace_text)
        distance_meters = None
        if split_seconds is not None and pace_seconds and pace_seconds > 0:
            distance_meters = round(split_seconds * 1000 / pace_seconds)
        controls.append(
            {
                "label": str(split_index + 1),
                "code": code,
                "distance_meters": distance_meters,
            }
        )
        splits.append(
            {
                "label": str(split_index + 1),
                "code": code,
                "distance_meters": distance_meters,
                "cumulative": {
                    "raw": _format_seconds_to_time(cumulative_seconds) if split_seconds is not None else "",
                    "time": _format_seconds_to_time(cumulative_seconds) if split_seconds is not None else "",
                    "short_time": _normalize_short_time(_format_seconds_to_time(cumulative_seconds)) if split_seconds is not None else "",
                    "seconds": cumulative_seconds if split_seconds is not None else None,
                },
                "split": {
                    "raw": split_time_text,
                    "time": split_time_text,
                    "short_time": _normalize_short_time(split_time_text),
                    "seconds": split_seconds,
                    "pace": pace_text or "",
                },
            }
        )

    return {
        "row_index": row_index,
        "order": _to_int_or_none(str(row.get("place") or "")),
        "name": str(row.get("name") or "").strip(),
        "bib": str(row.get("number") or row.get("bib") or row.get("si") or "").strip(),
        "result": str(row.get("finish") or row.get("time") or "").strip(),
        "place": str(row.get("place") or "").strip(),
        "gap": str(row.get("diff") or row.get("otm_name") or "").strip(),
        "splits": splits,
        "_orgeo_controls": controls,
    }


def _apply_orgeo_control_distances(participants: list[dict]) -> None:
    if not participants:
        return
    control_count = max((len(participant.get("splits", [])) for participant in participants), default=0)
    controls: list[dict] = []
    for split_index in range(control_count):
        distances = [
            participant["splits"][split_index]["distance_meters"]
            for participant in participants
            if split_index < len(participant.get("splits", []))
            and participant["splits"][split_index].get("distance_meters") is not None
        ]
        control_distance = int(round(median(distances))) if distances else None
        template_split = next(
            (
                participant["splits"][split_index]
                for participant in participants
                if split_index < len(participant.get("splits", []))
            ),
            None,
        )
        controls.append(
            {
                "label": template_split.get("label", str(split_index + 1)) if template_split else str(split_index + 1),
                "code": template_split.get("code", "") if template_split else "",
                "distance_meters": control_distance,
            }
        )

    for participant in participants:
        for split_index, split in enumerate(participant.get("splits", [])):
            if split_index < len(controls):
                split["distance_meters"] = controls[split_index]["distance_meters"]
        participant["_orgeo_controls"] = controls


def _orgeo_time_code_pairs(value: str) -> list[tuple[str, str]]:
    tokens = [token.strip() for token in value.split("|") if token.strip()]
    pairs: list[tuple[str, str]] = []
    for index in range(0, len(tokens) - 1, 2):
        pairs.append((tokens[index], tokens[index + 1]))
    return pairs


def _parse_orgeo_seconds(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    parts = text.split(":")
    if not all(part.isdigit() for part in parts):
        return None
    numbers = [int(part) for part in parts]
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    if len(numbers) == 3:
        return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    if len(numbers) == 1:
        return numbers[0]
    return None


def _parse_orgeo_pace_seconds(value: str) -> int | None:
    match = re.search(r"(\d+:\d{2})(?:\s*/\s*km|/km|km)?$", value.strip(), re.I)
    if not match:
        return None
    return _parse_orgeo_seconds(match.group(1))


def _clean_orgeo_text(value: str) -> str:
    normalized = re.sub(r"(?i)<br\s*/?>", " ", value)
    normalized = re.sub(r"<[^>]+>", "", normalized)
    return html_lib.unescape(re.sub(r"\s+", " ", normalized)).strip()


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
    from portal.services import race_grabber

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
    result["pace_distribution"] = _pace_distribution_view(result["virtual_leader"], controls)
    result["self_problem_total_gap"] = _self_problem_total_gap(self_participant, leader_split_by_split, problem_indexes)
    result["reachability_chart"] = _reachability_chart_view(result, self_participant)
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


def _prepare_score_result_view(result: dict) -> None:
    """View-model for score / rogaining protocols.

    Course-specific machinery (leader splits, virtual leader, problem indexes,
    reachability chart) doesn't apply: each participant takes a different set of
    KPs in their own order. We just normalize display fields.
    """
    participants = result.get("participants", [])
    self_row_index = result.get("self_row_index")
    self_participant = next(
        (participant for participant in participants if participant.get("row_index") == self_row_index),
        None,
    )

    result["controls"] = result.get("controls") or []
    result["problem_split_indexes"] = []
    result["problem_visit_indexes"] = []
    result["virtual_leader"] = None
    result["pace_distribution"] = {}
    result["self_problem_total_gap"] = ""
    result["reachability_chart"] = {}

    self_total = _to_int_or_none(self_participant.get("total_points")) if self_participant else None

    for participant in participants:
        participant["display_result"] = _compact_time(participant.get("result"))
        participant["relative_gap_text"] = ""
        participant["relative_gap_tone"] = ""
        if (
            self_participant
            and participant.get("row_index") != self_row_index
            and self_total is not None
        ):
            other_total = _to_int_or_none(participant.get("total_points"))
            if other_total is not None:
                diff = other_total - self_total
                if diff > 0:
                    participant["relative_gap_text"] = f"+{diff}"
                    participant["relative_gap_tone"] = "hot"
                elif diff < 0:
                    participant["relative_gap_text"] = f"{diff}"
                    participant["relative_gap_tone"] = "good"

        for visit in participant.get("visits", []):
            cumulative = visit.get("cumulative") or {}
            split = visit.get("split") or {}
            visit["cumulative_text"] = cumulative.get("time", "")
            visit["split_text"] = split.get("time", "") if split else ""
            visit["is_best_leg"] = False
            visit["leader_gap_text"] = ""
            visit["leader_gap_tone"] = ""
            visit["from_code"] = None
            visit["best_leg_seconds"] = None
            visit["best_leg_text"] = ""

    _annotate_score_best_legs(participants, self_participant)

    hot_indexes, warm_indexes, good_indexes = _classify_score_gap_indexes(self_participant)
    problem_indexes = hot_indexes | warm_indexes
    result["problem_visit_indexes"] = sorted(problem_indexes)
    result["self_problem_total_gap"] = _score_self_problem_total_gap(self_participant, problem_indexes)
    if self_participant:
        for visit_index, visit in enumerate(self_participant.get("visits", [])):
            if visit_index in hot_indexes:
                visit["leader_gap_tone"] = "hot"
            elif visit_index in warm_indexes:
                visit["leader_gap_tone"] = "warm"
            elif visit_index in good_indexes:
                visit["leader_gap_tone"] = "good"


def _annotate_score_best_legs(
    participants: list[dict],
    self_participant: dict | None,
) -> None:
    """For each leg the self-participant ran, find the best time across the field.

    A leg is the directed pair (prev_kp, current_kp). We only score legs that
    self ran (otherwise the comparison has no anchor); we only mark a "best"
    when at least two participants have a timed entry on that leg (otherwise
    "best" is meaningless). The participant that holds the minimum gets
    `is_best_leg=True` on that visit (used to paint the cell green); self gets
    a `leader_gap_text` showing the signed gap to that minimum and stashes the
    leg's best time in `best_leg_seconds` / `best_leg_text` for the problem
    table's "Идеальный лидер" row.
    """
    if not self_participant:
        return

    my_legs: set[tuple[str | None, str]] = set()
    prev_code: str | None = None
    for visit in self_participant.get("visits", []):
        code = visit.get("code")
        visit["from_code"] = prev_code
        visit["best_leg_seconds"] = None
        visit["best_leg_text"] = ""
        if code:
            my_legs.add((prev_code, code))
        prev_code = code

    if not my_legs:
        return

    leg_stats: dict[tuple[str | None, str], dict] = {}
    for participant in participants:
        prev_code = None
        for visit in participant.get("visits", []):
            code = visit.get("code")
            split = visit.get("split") or {}
            seconds = split.get("seconds")
            key = (prev_code, code)
            prev_code = code
            if key not in my_legs or seconds is None:
                continue
            entry = leg_stats.setdefault(key, {"best_seconds": seconds, "best_visit": visit, "count": 0})
            if seconds < entry["best_seconds"]:
                entry["best_seconds"] = seconds
                entry["best_visit"] = visit
            entry["count"] += 1

    for entry in leg_stats.values():
        if entry["count"] >= 2:
            entry["best_visit"]["is_best_leg"] = True

    prev_code = None
    for visit in self_participant.get("visits", []):
        code = visit.get("code")
        split = visit.get("split") or {}
        seconds = split.get("seconds")
        key = (prev_code, code)
        prev_code = code
        entry = leg_stats.get(key)
        if entry and entry["count"] >= 2:
            visit["best_leg_seconds"] = entry["best_seconds"]
            visit["best_leg_text"] = _format_seconds_to_time(entry["best_seconds"])
            if seconds is not None:
                visit["leader_gap_text"] = _compact_gap(seconds - entry["best_seconds"])


def _classify_score_gap_indexes(self_participant: dict | None) -> tuple[set[int], set[int], set[int]]:
    """Mirror _classify_gap_indexes for score: top-3 best gaps → "good",
    next worst-3 positive gaps → "hot", next 3 → "warm".

    Only visits with a comparator (best_leg_seconds is set) are eligible.
    """
    if not self_participant:
        return set(), set(), set()
    gaps: list[tuple[int, int]] = []
    for visit_index, visit in enumerate(self_participant.get("visits", [])):
        best = visit.get("best_leg_seconds")
        split = visit.get("split") or {}
        seconds = split.get("seconds")
        if best is None or seconds is None:
            continue
        gaps.append((visit_index, seconds - best))

    good_sorted = sorted(gaps, key=lambda item: item[1])
    good_indexes = {visit_index for visit_index, _ in good_sorted[:3]}

    remaining = [
        (visit_index, gap)
        for visit_index, gap in gaps
        if visit_index not in good_indexes and gap > 0
    ]
    remaining.sort(key=lambda item: item[1], reverse=True)
    hot_indexes = {visit_index for visit_index, _ in remaining[:3]}
    warm_indexes = {visit_index for visit_index, _ in remaining[3:6]}
    return hot_indexes, warm_indexes, good_indexes


def _score_self_problem_total_gap(
    self_participant: dict | None,
    problem_indexes: set[int],
) -> str:
    if not self_participant or not problem_indexes:
        return ""
    visits = self_participant.get("visits", [])
    total = 0
    has_data = False
    for visit_index in problem_indexes:
        if visit_index >= len(visits):
            continue
        visit = visits[visit_index]
        best = visit.get("best_leg_seconds")
        split = visit.get("split") or {}
        seconds = split.get("seconds")
        if best is None or seconds is None:
            continue
        total += seconds - best
        has_data = True
    return _compact_gap(total) if has_data else ""


def _to_int_or_none(value: str | None) -> int | None:
    if not value:
        return None
    text = str(value).strip()
    if not text or not text.lstrip("-").isdigit():
        return None
    return int(text)


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


def _pace_distribution_view(leader: dict | None, controls: list[dict] | None = None) -> dict:
    if not leader:
        return {}

    paces = []
    for split_index, split in enumerate(leader.get("splits", [])):
        split_time = _split_stage_time(split, split_index) or {}
        seconds = split_time.get("seconds")
        distance = controls[split_index].get("distance_meters") if controls and split_index < len(controls) else None
        if seconds is None or not distance or distance <= 0:
            continue
        pace_seconds = float(seconds) * 1000.0 / float(distance)
        paces.append(
            {
                "label": str(split.get("label") or split_index + 1),
                "pace_seconds": round(pace_seconds),
            }
        )

    if not paces:
        return {}

    values = [point["pace_seconds"] for point in paces]
    mean = sum(values) / len(values)
    sorted_values = sorted(values)
    mid = len(sorted_values) // 2
    median = sorted_values[mid] if len(sorted_values) % 2 else (sorted_values[mid - 1] + sorted_values[mid]) / 2
    std = (sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5
    bucket_size = _pace_bucket_size(values)
    half_bucket = bucket_size // 2
    bucket_min = int(min(values) // bucket_size * bucket_size - half_bucket)
    bucket_max = int(((max(values) + bucket_size - 1) // bucket_size) * bucket_size + half_bucket)
    if bucket_max == bucket_min:
        bucket_max += bucket_size

    buckets = []
    start = bucket_min
    while start < bucket_max:
        end = start + bucket_size
        count = sum(1 for value in values if start <= value < end or (end == bucket_max and value == bucket_max))
        mid_value = (start + end) / 2
        buckets.append(
            {
                "from": start,
                "to": end,
                "count": count,
                "tone": _pace_tone(mid_value, mean, std),
            }
        )
        start = end

    return {
        "leader_name": leader.get("name") or "Абсолютный лидер",
        "split_count": len(paces),
        "min": min(values),
        "max": max(values),
        "mean": round(mean),
        "median": round(median),
        "std": round(std, 2),
        "green_threshold": round(mean - 0.75 * std),
        "red_threshold": round(mean + 0.75 * std),
        "bucket_size": bucket_size,
        "points": [
            {
                **point,
                "tone": _pace_tone(point["pace_seconds"], mean, std),
            }
            for point in paces
        ],
        "buckets": buckets,
    }


def _pace_bucket_size(values: list[int]) -> int:
    import math

    if len(values) < 2:
        return 30
    bucket_count = max(round(1 + 3.322 * math.log10(len(values))), 1)
    raw_bucket = (max(values) - min(values)) / bucket_count
    rounded = int(round(raw_bucket / 30) * 30) if raw_bucket > 0 else 30
    return max(30, min(120, rounded))


def _pace_tone(value: float, mean: float, std: float) -> str:
    if std <= 0:
        return "normal"
    if value < mean - 0.75 * std:
        return "fast"
    if value > mean + 0.75 * std:
        return "slow"
    return "normal"


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


def _gap_seconds(value: str | None) -> int | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return 0
    sign = 1
    if text.startswith("-"):
        sign = -1
        text = text[1:].strip()
    elif text.startswith("+"):
        text = text[1:].strip()
    seconds = _result_seconds(text)
    if seconds is None:
        return None
    return sign * seconds


def _place_number(value: str | None, fallback: int) -> int:
    if value and value.isdigit():
        return int(value)
    return fallback


def _reachability_chart_view(result: dict, self_participant: dict | None) -> dict:
    if not self_participant:
        return {}

    participants = result.get("participants", [])
    self_place_number = _place_number(self_participant.get("place"), self_participant.get("row_index", 0) + 1)
    self_gap_seconds = _gap_seconds(self_participant.get("gap"))
    if self_gap_seconds is None:
        self_gap_seconds = 0

    points = []
    for participant in participants:
        gap_seconds = _gap_seconds(participant.get("gap"))
        if gap_seconds is None:
            continue
        place_number = _place_number(participant.get("place"), participant.get("row_index", 0) + 1)
        if place_number > self_place_number:
            continue
        points.append(
            {
                "place": place_number,
                "name": participant.get("name", ""),
                "gap_seconds": gap_seconds,
                "x_seconds": self_gap_seconds - gap_seconds,
                "is_self": participant.get("row_index") == self_participant.get("row_index"),
            }
        )

    if len(points) < 2:
        return {}

    return {
        "self_name": self_participant.get("name", ""),
        "self_place": self_place_number,
        "self_gap_seconds": self_gap_seconds,
        "points": points,
    }


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
