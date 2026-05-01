from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ParsedRaceProtocol:
    event_name: str
    event_meta: str
    groups: list[dict[str, Any]]


def fetch_race_protocol(url: str) -> str:
    request = Request(url, headers={"User-Agent": "orienteering-portal/0.1"})
    with urlopen(request, timeout=20) as response:
        content = response.read()
        for encoding in ("utf-8-sig", response.headers.get_content_charset(), "cp1251"):
            if not encoding:
                continue
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="replace")


def parse_race_protocol_html(content: str) -> ParsedRaceProtocol:
    try:
        event_name = _extract_js_const(content, "eventName")
        event_meta = _extract_js_const(content, "eventMeta")
        db = _extract_js_const(content, "db")
    except ValueError:
        return _parse_legacy_race_protocol_html(content)

    groups = []
    for group_blob in db.split("|||"):
        if not group_blob.strip():
            continue
        parts = [part for part in group_blob.split("||") if part.strip()]
        if len(parts) < 2:
            continue
        group_header = parts[0].split("|")
        headers = parts[1].split("|")
        controls = _parse_controls(headers)
        participants = [
            _parse_participant(row_index, headers, row.split("|"), controls)
            for row_index, row in enumerate(parts[2:])
            if row.strip()
        ]
        groups.append(
            {
                "name": _clean(group_header[0]) if group_header else "",
                "subtitle": _clean(group_header[1]) if len(group_header) > 1 else "",
                "controls": controls,
                "participants": participants,
            }
        )
    return ParsedRaceProtocol(event_name=event_name, event_meta=event_meta, groups=groups)


def _parse_legacy_race_protocol_html(content: str) -> ParsedRaceProtocol:
    event_name = _extract_tag_text(content, "h1")
    event_meta = _extract_tag_text(content, "h3")
    groups = []
    for match in re.finditer(r"<h2>(.*?)</h2>\s*<table[^>]*class=['\"]rezult['\"][^>]*>(.*?)</table>", content, re.I | re.S):
        group_name = _clean(match.group(1))
        table_html = match.group(2)
        rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", table_html, re.I | re.S)
        if not rows:
            continue
        headers = [_clean(_strip_tags(cell)) for cell in re.findall(r"<th\b[^>]*>(.*?)</th>", rows[0], re.I | re.S)]
        controls = _parse_controls(headers)
        participants = []
        for row_index, row_html in enumerate(rows[1:]):
            cells = re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row_html, re.I | re.S)
            if not cells:
                continue
            participants.append(_parse_legacy_participant(row_index, headers, cells, controls))
        groups.append(
            {
                "name": group_name,
                "subtitle": "",
                "controls": controls,
                "participants": participants,
            }
        )
    if not event_name:
        raise ValueError("Не найдено название соревнований в протоколе")
    return ParsedRaceProtocol(event_name=event_name, event_meta=event_meta, groups=groups)


def _extract_js_const(content: str, name: str) -> str:
    match = re.search(rf'const {re.escape(name)} = "(.*?)";', content, re.S)
    if not match:
        raise ValueError(f"Не найден блок {name} в протоколе")
    return html.unescape(match.group(1))


def _parse_controls(headers: list[str]) -> list[dict[str, Any]]:
    controls = []
    for index, header in enumerate(headers):
        if not header.startswith("#"):
            continue
        text = _clean(header)
        match = re.search(r"#(\d+|F)\s*\(([^)]+)\)(?:\s*(\d+)\s*m)?", text)
        if not match:
            continue
        controls.append(
            {
                "column_index": index,
                "label": match.group(1),
                "code": match.group(2),
                "distance_meters": int(match.group(3)) if match.group(3) else None,
            }
        )
    return controls


def _parse_legacy_participant(
    row_index: int,
    headers: list[str],
    cells: list[str],
    controls: list[dict[str, Any]],
) -> dict[str, Any]:
    cleaned = [_clean(_strip_tags(cell)) for cell in cells]

    def value(index: int) -> str:
        return cleaned[index] if index < len(cleaned) else ""

    splits = [_parse_split_cell(control, cells[control["column_index"]] if control["column_index"] < len(cells) else "") for control in controls]
    _normalize_first_split(splits)

    return {
        "row_index": row_index,
        "order": _to_int(value(0)),
        "name": value(2),
        "bib": value(1),
        "result": value(4),
        "place": value(5),
        "gap": value(6),
        "splits": splits,
        "raw_columns": [value(index) for index in range(len(headers))],
    }


def _parse_participant(
    row_index: int,
    headers: list[str],
    values: list[str],
    controls: list[dict[str, Any]],
) -> dict[str, Any]:
    def value(index: int) -> str:
        return values[index] if index < len(values) else ""

    splits = [_parse_split_cell(control, value(control["column_index"])) for control in controls]
    _normalize_first_split(splits)

    return {
        "row_index": row_index,
        "order": _to_int(_clean(value(0))),
        "name": _clean(value(1)),
        "bib": _clean(value(2)),
        "result": _clean(value(3)),
        "place": _clean(value(4)),
        "gap": _clean(value(5)),
        "splits": splits,
        "raw_columns": [_clean(value(index)) for index in range(len(headers))],
    }


def _parse_split_cell(control: dict[str, Any], raw_value: str) -> dict[str, Any]:
    parts = re.split(r"<br\s*/?>", raw_value, flags=re.I)
    cumulative = _parse_time_rank(parts[0] if parts else "")
    split = _parse_time_rank(parts[1] if len(parts) > 1 else "")
    return {
        "label": control["label"],
        "code": control["code"],
        "distance_meters": control["distance_meters"],
        "cumulative": cumulative,
        "split": split,
    }


def _parse_time_rank(value: str) -> dict[str, Any] | None:
    text = _clean(value)
    if not text:
        return None
    match = re.match(r"([^()]+?)(?:\((\d+)\))?$", text)
    if not match:
        return {"raw": text, "seconds": None, "rank": None}
    time_text = match.group(1).strip()
    return {
        "raw": text,
        "time": time_text,
        "seconds": _time_to_seconds(time_text),
        "rank": int(match.group(2)) if match.group(2) else None,
    }


def _normalize_first_split(splits: list[dict[str, Any]]) -> None:
    if not splits:
        return
    first = splits[0]
    if first.get("split") is None and first.get("cumulative") is not None:
        first["split"] = dict(first["cumulative"])


def _time_to_seconds(value: str) -> int | None:
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


def _clean(value: str) -> str:
    normalized = re.sub(r"(?i)<br\s*/?>", " ", value)
    normalized = re.sub(r"<[^>]+>", "", normalized)
    return html.unescape(re.sub(r"\s+", " ", normalized)).strip()


def _to_int(value: str) -> int | None:
    return int(value) if value.isdigit() else None


def _extract_tag_text(content: str, tag: str) -> str:
    match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", content, re.I | re.S)
    return _clean(_strip_tags(match.group(1))) if match else ""


def _strip_tags(value: str) -> str:
    normalized = re.sub(r"(?i)<br\s*/?>", " ", value)
    return re.sub(r"<[^>]+>", "", normalized)
