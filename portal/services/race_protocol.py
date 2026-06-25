from __future__ import annotations

import html
import re
from io import BytesIO
from dataclasses import dataclass
from typing import Any, Literal
from urllib.request import Request, urlopen

ProtocolFormat = Literal["js_course", "js_score", "legacy_html", "pdf_text", "sportident_online_html"]
ProtocolKind = Literal["course", "score"]


@dataclass(frozen=True)
class ParsedRaceProtocol:
    event_name: str
    event_meta: str
    groups: list[dict[str, Any]]
    kind: ProtocolKind = "course"


def fetch_race_protocol(url: str) -> str:
    request = Request(url, headers={"User-Agent": "orienteering-portal/0.1"})
    with urlopen(request, timeout=20) as response:
        content = response.read()
        content_type = response.headers.get_content_type()
        if content_type == "application/pdf" or url.lower().split("?", 1)[0].endswith(".pdf"):
            return _extract_pdf_text(content)
        for encoding in ("utf-8-sig", response.headers.get_content_charset(), "cp1251"):
            if not encoding:
                continue
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="replace")


def detect_protocol_format(content: str) -> ProtocolFormat:
    """Pick the parser to use, based on cheap shape signals.

    Logic:
      - SportOrg PDF text export → PDF parser
      - no `const db = "..."` JS blob → legacy HTML protocol with <table class="rezult">
      - blob has score-only column markers (Баллы / Штраф / Итог) → rogaining / score-O
      - otherwise → classic course protocol with fixed legs
    """
    if _looks_like_pdf_protocol_text(content):
        return "pdf_text"
    if _looks_like_sportident_online_protocol(content):
        return "sportident_online_html"
    db_match = re.search(r'const db = "(.*?)";', content, re.S)
    if not db_match:
        return "legacy_html"
    db = db_match.group(1)
    if re.search(r"\|Баллы\|", db) and re.search(r"\|Итог\|", db):
        return "js_score"
    return "js_course"


def parse_race_protocol_html(content: str) -> ParsedRaceProtocol:
    fmt = detect_protocol_format(content)
    if fmt == "pdf_text":
        return parse_pdf_race_protocol(content)
    if fmt == "sportident_online_html":
        return _parse_sportident_online_protocol_html(content)
    if fmt == "legacy_html":
        return _parse_legacy_race_protocol_html(content)
    if fmt == "js_score":
        return _parse_js_score_race_protocol_html(content)
    return _parse_js_course_race_protocol_html(content)


def _extract_pdf_text(content: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _looks_like_pdf_protocol_text(content: str) -> bool:
    return (
        "ПРОТОКОЛ РЕЗУЛЬТАТОВ" in content
        and "Фамилия, имя" in content
        and re.search(r",\s*\d+\s*КП,\s*[\d.,]+\s*км", content) is not None
    )


def _looks_like_sportident_online_protocol(content: str) -> bool:
    return (
        "sportident.online" in content
        and "class='name_grup'" in content
        and "class='hoverRow'" in content
        and "../ol/split.php?id=" in content
    )


def _parse_sportident_online_protocol_html(content: str) -> ParsedRaceProtocol:
    event_name, event_meta = _sportident_event_text(content)
    group_match = re.search(r"<td\b[^>]*class='name_grup'[^>]*>(.*?)</td>", content, re.I | re.S)
    if group_match is None:
        raise ValueError("Не найдена группа в протоколе sportident.online")

    group_text = _clean(group_match.group(1))
    group_name, group_subtitle = _sportident_group_parts(group_text)

    control_headers = re.findall(
        r"<th\b[^>]*class='[^']*\bth_ol\b[^']*'[^>]*>(.*?)</th>",
        content,
        re.I | re.S,
    )
    controls = [_parse_sportident_control(header, index) for index, header in enumerate(control_headers)]

    row_matches = re.findall(r"<tr\b[^>]*class='hoverRow'[^>]*>(.*?)</tr>", content, re.I | re.S)
    participants = []
    for row_index, row_html in enumerate(row_matches):
        participant = _parse_sportident_participant(row_index, row_html, controls)
        if participant is not None:
            participants.append(participant)
    _fill_missing_split_ranks(participants)

    return ParsedRaceProtocol(
        event_name=event_name,
        event_meta=event_meta,
        groups=[
            {
                "name": group_name,
                "subtitle": group_subtitle,
                "controls": controls,
                "participants": participants,
            }
        ],
        kind="course",
    )


def _sportident_event_text(content: str) -> tuple[str, str]:
    match = re.search(r"<td\b[^>]*class='name_comp'[^>]*>(.*?)</td>", content, re.I | re.S)
    if match is None:
        return "", ""
    parts = _html_line_parts(match.group(1))
    event_name = parts[0] if parts else ""
    event_meta = parts[1] if len(parts) > 1 else ""
    return event_name, event_meta


def _sportident_group_parts(group_text: str) -> tuple[str, str]:
    parts = [part.strip() for part in group_text.split(",") if part.strip()]
    if not parts:
        return "", ""
    return parts[0], ", ".join(parts[1:])


def _parse_sportident_control(header_html: str, column_index: int) -> dict[str, Any]:
    parts = _html_line_parts(header_html)
    code = ""
    distance_meters = None
    distance_text = ""
    if parts:
        code_match = re.search(r"КП\s*([A-Za-z0-9]+)", parts[0], re.I)
        if code_match:
            code = code_match.group(1)
    if len(parts) > 1:
        distance_match = re.search(r"(\d+)\s*м", parts[1], re.I)
        if distance_match:
            distance_meters = int(distance_match.group(1))
    if len(parts) > 2:
        distance_text = parts[2]
    label = str(column_index + 1)
    if code.upper() == "F":
        label = "F"
    return {
        "column_index": column_index,
        "label": label,
        "code": code,
        "distance_meters": distance_meters,
        "distance_text": distance_text,
    }


def _parse_sportident_participant(
    row_index: int,
    row_html: str,
    controls: list[dict[str, Any]],
) -> dict[str, Any] | None:
    cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row_html, re.I | re.S)
    if len(cells) < 11:
        return None

    def value(index: int) -> str:
        return _clean(cells[index]) if index < len(cells) else ""

    splits = [
        _parse_sportident_split_cell(control, cells[11 + index] if 11 + index < len(cells) else "")
        for index, control in enumerate(controls)
    ]
    bib = value(4)
    return {
        "row_index": row_index,
        "order": _to_int(value(0)),
        "name": value(1),
        "bib": bib,
        "result": value(8),
        "place": value(9),
        "gap": value(10),
        "team": value(2),
        "lap": _lap_from_bib(bib),
        "splits": splits,
        "raw_columns": [value(index) for index in range(len(cells))],
    }


def _parse_sportident_split_cell(control: dict[str, Any], raw_value: str) -> dict[str, Any]:
    parts = re.split(r"<br\s*/?>", raw_value, flags=re.I)
    split = _parse_time_rank(parts[0] if parts else "")
    cumulative = _parse_time_rank(parts[1] if len(parts) > 1 else "")
    if cumulative is None and split is not None:
        cumulative = dict(split)
    if split is None and cumulative is not None:
        split = dict(cumulative)
    return {
        "label": control["label"],
        "code": control["code"],
        "distance_meters": control["distance_meters"],
        "cumulative": cumulative,
        "split": split,
    }


def _parse_js_course_race_protocol_html(content: str) -> ParsedRaceProtocol:
    event_name = _extract_js_const(content, "eventName")
    event_meta = _extract_js_const(content, "eventMeta")
    db = _extract_js_const(content, "db")

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
        _fill_missing_split_ranks(participants)
        groups.append(
            {
                "name": _clean(group_header[0]) if group_header else "",
                "subtitle": _clean(group_header[1]) if len(group_header) > 1 else "",
                "controls": controls,
                "participants": participants,
            }
        )
    return ParsedRaceProtocol(event_name=event_name, event_meta=event_meta, groups=groups, kind="course")


def _parse_js_score_race_protocol_html(content: str) -> ParsedRaceProtocol:
    """Rogaining / score-O ("выбор", "100КП"): свободный порядок взятия КП.

    Колонки группы: п/п|Фамилия, Имя|Номер|Баллы|Штраф|Итог|Результат|Место|#1|#2|...
    Ячейка КП: `cumulative[code]<br>split` (split отсутствует у первого взятого КП).
    """
    event_name = _extract_js_const(content, "eventName")
    event_meta = _extract_js_const(content, "eventMeta")
    db = _extract_js_const(content, "db")

    groups = []
    for group_blob in db.split("|||"):
        if not group_blob.strip():
            continue
        parts = [part for part in group_blob.split("||") if part.strip()]
        if len(parts) < 2:
            continue
        group_header = parts[0].split("|")
        headers = parts[1].split("|")
        kp_columns = [index for index, header in enumerate(headers) if header.strip().startswith("#")]
        column_meta = _score_column_meta(headers)
        participants = [
            _parse_score_participant(row_index, headers, row.split("|"), kp_columns, column_meta)
            for row_index, row in enumerate(parts[2:])
            if row.strip()
        ]
        groups.append(
            {
                "name": _clean(group_header[0]) if group_header else "",
                "subtitle": _clean(group_header[1]) if len(group_header) > 1 else "",
                "controls": [],
                "participants": participants,
            }
        )
    return ParsedRaceProtocol(event_name=event_name, event_meta=event_meta, groups=groups, kind="score")


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
        _fill_missing_split_ranks(participants)
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
    return ParsedRaceProtocol(event_name=event_name, event_meta=event_meta, groups=groups, kind="course")


def parse_pdf_race_protocol(content: str) -> ParsedRaceProtocol:
    normalized = _normalize_pdf_text(content)
    group_matches = list(_iter_pdf_group_matches(normalized))
    if not group_matches:
        raise ValueError("Не найдены группы в PDF-протоколе")

    event_prefix = normalized[: group_matches[0].start()].strip()
    event_name, event_meta = _pdf_event_text(event_prefix)
    groups = []
    for index, match in enumerate(group_matches):
        body_start = match.end()
        body_end = group_matches[index + 1].start() if index + 1 < len(group_matches) else len(normalized)
        control_count = int(match.group("control_count"))
        codes = match.group("codes").split()
        controls = _pdf_controls(codes[: control_count + 1])
        body_prefix = " ".join(codes[control_count + 1 :])
        body = normalized[body_start:body_end]
        if body_prefix:
            body = f"{body_prefix} {body}"
        participants = _parse_pdf_participants(body, controls)
        _fill_missing_split_ranks(participants)
        groups.append(
            {
                "name": _clean(match.group("name")),
                "subtitle": f"{match.group('control_count')} КП, {match.group('distance')} км",
                "controls": controls,
                "participants": participants,
            }
        )

    return ParsedRaceProtocol(event_name=event_name, event_meta=event_meta, groups=groups, kind="course")


def _normalize_pdf_text(content: str) -> str:
    text = content.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(
        r"(?<!^)(?=([А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9_ -]{0,40}),\s*\d+\s*КП,)",
        "\n",
        text,
    )
    text = re.sub(r"\n+", "\n", text)
    return text.strip()


def _iter_pdf_group_matches(content: str):
    group_pattern = re.compile(
        r"(?P<name>[А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9_ -]{0,40}),\s*"
        r"(?P<control_count>\d+)\s*КП,\s*"
        r"(?P<distance>[\d.,]+)\s*км\s*"
        r"№\s*Фамилия,\s*имя\s+Коллектив\s+ГР\s+Разряд\s+Номер\s+Результат\s+Отставание\s*Место\s+"
        r"(?P<codes>(?:\d+|F)(?:\s+(?:\d+|F))*)",
        re.I,
    )
    return group_pattern.finditer(content)


def _pdf_event_text(prefix: str) -> tuple[str, str]:
    marker = "ПРОТОКОЛ РЕЗУЛЬТАТОВ"
    if marker in prefix:
        before, _, after = prefix.partition(marker)
        return _clean_pdf_event_name(before) or marker, _clean(f"{marker} {after}")
    spaced_marker = re.search(r"П\s*Р\s*О\s*Т\s*О\s*К\s*О\s*Л\s+Р\s*Е\s*З\s*У\s*Л\s*Ь\s*Т\s*А\s*Т\s*О\s*В", prefix)
    if spaced_marker:
        return _clean_pdf_event_name(prefix[: spaced_marker.start()]) or marker, marker
    return _clean_pdf_event_name(prefix), ""


def _clean_pdf_event_name(value: str) -> str:
    text = _clean(value)
    text = re.sub(r"(?<=[А-Яа-яЁё])(?=\d{2}\.\d{2}\.\d{4})", " ", text)
    text = re.sub(r"(?<=\d{4})(?=[А-Яа-яЁё])", " ", text)
    text = re.sub(r"(?<=[.,])(?=[А-Яа-яЁё])", " ", text)
    return _clean(text)


def _pdf_controls(codes: list[str]) -> list[dict[str, Any]]:
    controls = []
    for index, code in enumerate(codes):
        controls.append(
            {
                "column_index": index,
                "label": "F" if code == "F" else str(index + 1),
                "code": code,
                "distance_meters": None,
            }
        )
    return controls


def _parse_pdf_participants(body: str, controls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned_body = re.sub(
        r"№\s*Фамилия,\s*имя\s+Коллектив\s+ГР\s+Разряд\s+Номер\s+Результат\s+Отставание\s*Место\s+(?:\d+|F)(?:\s+(?:\d+|F))*",
        " ",
        body,
        flags=re.I,
    )
    records = _split_pdf_participant_records(cleaned_body)
    participants = []
    for record in records:
        parsed = _parse_pdf_participant_record(len(participants), record, controls)
        if parsed is not None:
            participants.append(parsed)
    return participants


def _split_pdf_participant_records(body: str) -> list[str]:
    text = " ".join(line.strip() for line in body.splitlines() if line.strip())
    starts = [
        match.start()
        for match in re.finditer(r"(?<![:\d])\d{1,3}\s+(?=[А-ЯЁA-Z][^\d]{1,80})", text)
    ]
    records = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        record = text[start:end].strip()
        if record:
            records.append(record)
    return records


def _parse_pdf_participant_record(
    row_index: int,
    record: str,
    controls: list[dict[str, Any]],
) -> dict[str, Any] | None:
    meta_match = re.match(
        r"(?P<order>\d{1,3})\s+"
        r"(?P<prefix>.*?)\s+"
        r"(?P<result>\d{2}:\d{2}:\d{2})\s+"
        r"(?:(?P<gap>\d{2}:\d{2}:\d{2})\s+)?"
        r"(?P<place>\d+)\s+"
        r"(?P<times>.*)$",
        record,
    )
    if meta_match is None:
        return None

    prefix = meta_match.group("prefix")
    identity = _parse_pdf_identity(prefix)
    if identity is None:
        return None

    time_tokens = _pdf_time_tokens(meta_match.group("times"))
    expected_token_count = len(controls) * 2
    if len(time_tokens) < expected_token_count:
        return None

    splits = []
    for split_index, control in enumerate(controls):
        split_token = time_tokens[split_index * 2]
        cumulative_token = time_tokens[split_index * 2 + 1]
        splits.append(
            {
                "label": control["label"],
                "code": control["code"],
                "distance_meters": control["distance_meters"],
                "cumulative": _pdf_time_token_to_split(cumulative_token),
                "split": _pdf_time_token_to_split(split_token),
            }
        )
    _normalize_first_split(splits)

    return {
        "row_index": row_index,
        "order": _to_int(meta_match.group("order")),
        "name": identity["name"],
        "bib": identity["bib"],
        "result": meta_match.group("result"),
        "place": meta_match.group("place"),
        "gap": meta_match.group("gap") or "",
        "splits": splits,
        "raw_columns": [
            meta_match.group("order"),
            identity["bib"],
            identity["name"],
            identity["team"],
            identity["year"],
            identity["rank"],
            meta_match.group("result"),
            meta_match.group("place"),
            meta_match.group("gap") or "",
        ],
    }


def _parse_pdf_identity(prefix: str) -> dict[str, str] | None:
    match = re.match(
        r"(?P<name_team>.*?)\s+"
        r"(?P<year>-?\d{1,4})\s+"
        r"(?P<rank>\S+)\s+"
        r"(?P<bib>\d+)$",
        prefix,
    )
    if match is None:
        return None
    words = match.group("name_team").split()
    if len(words) < 2:
        name = match.group("name_team")
        team = ""
    else:
        name = " ".join(words[:2])
        team = " ".join(words[2:])
    return {
        "name": _clean(name),
        "team": _clean(team),
        "year": match.group("year"),
        "rank": match.group("rank"),
        "bib": match.group("bib"),
    }


def _pdf_time_tokens(value: str) -> list[tuple[str, int | None]]:
    return [
        (match.group(1), int(match.group(2)) if match.group(2) else None)
        for match in re.finditer(r"(\d{2}:\d{2}:\d{2})(?:\s*\((\d+)\))?", value)
    ]


def _pdf_time_token_to_split(token: tuple[str, int | None]) -> dict[str, Any]:
    time_text, rank = token
    return {
        "raw": f"{time_text}({rank})" if rank is not None else time_text,
        "time": time_text,
        "seconds": _time_to_seconds(time_text),
        "rank": rank,
    }


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
        match = re.search(r"#(\d+|F)\s*(?:\(([^)]+)\))?(?:\s*(\d+)\s*m)?", text)
        if not match:
            continue
        controls.append(
            {
                "column_index": index,
                "label": match.group(1),
                "code": match.group(2) or "",
                "distance_meters": int(match.group(3)) if match.group(3) else None,
            }
        )
    return controls


def _score_column_meta(headers: list[str]) -> dict[str, int]:
    """Map well-known score-protocol header names to their column indexes.

    Headers are language-fixed for o-site protocols (Russian), so a name lookup
    is robust enough and tolerates extra/optional columns ("Команда", etc.) without
    a brittle positional schema.
    """
    indexes: dict[str, int] = {}
    for index, header in enumerate(headers):
        cleaned = _clean(header)
        if cleaned in indexes:
            continue
        indexes[cleaned] = index
    return {
        "order": indexes.get("п/п", 0),
        "name": indexes.get("Фамилия, Имя", 1),
        "bib": indexes.get("Номер", 2),
        "points": indexes.get("Баллы", -1),
        "penalty": indexes.get("Штраф", -1),
        "total_points": indexes.get("Итог", -1),
        "result": indexes.get("Результат", -1),
        "place": indexes.get("Место", -1),
    }


def _course_column_meta(headers: list[str]) -> dict[str, int]:
    indexes: dict[str, int] = {}
    for index, header in enumerate(headers):
        cleaned = _clean(header)
        if cleaned in indexes:
            continue
        indexes[cleaned] = index
    return {
        "order": indexes.get("п/п", 0),
        "bib": indexes.get("Номер", 1),
        "name": indexes.get("Фамилия, Имя", 2),
        "result": indexes.get("Результат", 3),
        "place": indexes.get("Место", 4),
        "gap": indexes.get("Отставание", indexes.get("Отст.", 5)),
    }


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
    meta = _course_column_meta(headers)

    bib = value(meta["bib"])
    return {
        "row_index": row_index,
        "order": _to_int(value(meta["order"])),
        "name": value(meta["name"]),
        "bib": bib,
        "lap": _lap_from_bib(bib),
        "result": value(meta["result"]),
        "place": value(meta["place"]),
        "gap": value(meta["gap"]),
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
    meta = _course_column_meta(headers)

    bib = _clean(value(meta["bib"]))
    return {
        "row_index": row_index,
        "order": _to_int(_clean(value(meta["order"]))),
        "name": _clean(value(meta["name"])),
        "bib": bib,
        "lap": _lap_from_bib(bib),
        "result": _clean(value(meta["result"])),
        "place": _clean(value(meta["place"])),
        "gap": _clean(value(meta["gap"])),
        "splits": splits,
        "raw_columns": [_clean(value(index)) for index in range(len(headers))],
    }


def _parse_score_participant(
    row_index: int,
    headers: list[str],
    values: list[str],
    kp_columns: list[int],
    meta: dict[str, int],
) -> dict[str, Any]:
    def value(index: int) -> str:
        if index < 0 or index >= len(values):
            return ""
        return values[index]

    visits: list[dict[str, Any]] = []
    for column_index in kp_columns:
        visit = _parse_score_visit_cell(value(column_index))
        if visit is None:
            continue
        visit["order"] = len(visits) + 1
        visits.append(visit)
    _normalize_first_score_visit(visits)

    return {
        "row_index": row_index,
        "order": _to_int(_clean(value(meta["order"]))),
        "name": _clean(value(meta["name"])),
        "bib": _clean(value(meta["bib"])),
        "points": _clean(value(meta["points"])),
        "penalty": _clean(value(meta["penalty"])),
        "total_points": _clean(value(meta["total_points"])),
        "result": _clean(value(meta["result"])),
        "place": _clean(value(meta["place"])),
        "gap": "",
        "splits": [],
        "visits": visits,
        "raw_columns": [_clean(value(index)) for index in range(len(headers))],
    }


def _fill_missing_split_ranks(participants: list[dict[str, Any]]) -> None:
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


def _parse_split_cell(control: dict[str, Any], raw_value: str) -> dict[str, Any]:
    parts = re.split(r"<br\s*/?>", raw_value, flags=re.I)
    cumulative = _parse_time_rank(parts[0] if parts else "")
    split = _parse_time_rank(parts[1] if len(parts) > 1 else "")
    return {
        "label": control["label"],
        "code": control["code"] or (cumulative or {}).get("code", ""),
        "distance_meters": control["distance_meters"],
        "cumulative": cumulative,
        "split": split,
    }


def _parse_score_visit_cell(raw_value: str) -> dict[str, Any] | None:
    text = (raw_value or "").strip()
    if not text:
        return None
    parts = re.split(r"<br\s*/?>", raw_value, flags=re.I)
    cumulative = _parse_time_code(parts[0] if parts else "")
    if cumulative is None:
        return None
    split_text = _clean(parts[1]) if len(parts) > 1 else ""
    split_seconds = _time_to_seconds(split_text)
    split: dict[str, Any] | None = None
    if split_text:
        split = {
            "raw": split_text,
            "time": split_text,
            "seconds": split_seconds,
        }
    return {
        "code": cumulative["code"],
        "cumulative": {
            "raw": cumulative["raw"],
            "time": cumulative["time"],
            "seconds": cumulative["seconds"],
        },
        "split": split,
    }


def _parse_time_rank(value: str) -> dict[str, Any] | None:
    text = _clean(value)
    if not text:
        return None
    match = re.match(r"(?P<time>[0-9:]+)\s*(?:\[(?P<code>[^\]]+)\])?\s*(?:\(\s*(?P<rank>\d+)\s*\))?$", text)
    if not match:
        return {"raw": text, "seconds": None, "rank": None}
    time_text = match.group("time").strip()
    parsed = {
        "raw": text,
        "time": time_text,
        "seconds": _time_to_seconds(time_text),
        "rank": int(match.group("rank")) if match.group("rank") else None,
    }
    if match.group("code"):
        parsed["code"] = match.group("code").strip()
    return parsed


def _parse_time_code(value: str) -> dict[str, Any] | None:
    text = _clean(value)
    if not text:
        return None
    match = re.match(r"([0-9:]+)\s*\[([^\]]+)\]\s*$", text)
    if not match:
        return None
    time_text = match.group(1).strip()
    return {
        "raw": text,
        "time": time_text,
        "seconds": _time_to_seconds(time_text),
        "code": match.group(2).strip(),
    }


def _normalize_first_split(splits: list[dict[str, Any]]) -> None:
    if not splits:
        return
    first = splits[0]
    if first.get("split") is None and first.get("cumulative") is not None:
        first["split"] = dict(first["cumulative"])


def _normalize_first_score_visit(visits: list[dict[str, Any]]) -> None:
    if not visits:
        return
    first = visits[0]
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


def _html_line_parts(value: str) -> list[str]:
    return [_clean(part) for part in re.split(r"(?i)<br\s*/?>", value) if _clean(part)]


def _to_int(value: str) -> int | None:
    return int(value) if value.isdigit() else None


def _lap_from_bib(value: str) -> str:
    match = re.search(r"\.(\d+)\s*$", value.strip())
    return match.group(1) if match else ""


def _extract_tag_text(content: str, tag: str) -> str:
    match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", content, re.I | re.S)
    return _clean(_strip_tags(match.group(1))) if match else ""


def _strip_tags(value: str) -> str:
    normalized = re.sub(r"(?i)<br\s*/?>", " ", value)
    return re.sub(r"<[^>]+>", "", normalized)
