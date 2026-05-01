from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiosqlite


SCHEMA = """
CREATE TABLE IF NOT EXISTS maps (
    map_id          TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    image_path      TEXT NOT NULL,
    image_width     INTEGER,
    image_height    INTEGER,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS map_georeferences (
    map_id          TEXT PRIMARY KEY,
    method          TEXT NOT NULL,
    control_points  TEXT NOT NULL,
    transform       TEXT NOT NULL,
    residuals       TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (map_id) REFERENCES maps(map_id)
);

CREATE TABLE IF NOT EXISTS trainings (
    training_id     TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    date            TEXT NOT NULL,
    training_type   TEXT,
    location        TEXT,
    map_id          TEXT,
    gpx_path        TEXT,
    notes           TEXT,
    course_controls TEXT,
    track_points    TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (map_id) REFERENCES maps(map_id)
);

CREATE TABLE IF NOT EXISTS ai_analysis (
    training_id     TEXT PRIMARY KEY,
    analysis        TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (training_id) REFERENCES trainings(training_id)
);

CREATE TABLE IF NOT EXISTS training_import_drafts (
    draft_id              TEXT PRIMARY KEY,
    title                 TEXT NOT NULL,
    date                  TEXT NOT NULL,
    training_type         TEXT,
    location              TEXT,
    notes                 TEXT,
    map_image_path        TEXT,
    map_image_filename    TEXT,
    georef_method         TEXT,
    georef_control_points TEXT,
    georef_transform      TEXT,
    georef_residuals      TEXT,
    course_controls       TEXT,
    track_gpx_path        TEXT,
    track_gpx_filename    TEXT,
    track_points          TEXT,
    edit_training_id      TEXT,
    finalized_training_id TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS race_results (
    race_result_id TEXT PRIMARY KEY,
    training_id    TEXT,
    source_url     TEXT NOT NULL,
    event_name     TEXT NOT NULL,
    event_meta     TEXT,
    group_name     TEXT NOT NULL,
    group_subtitle TEXT,
    controls       TEXT NOT NULL,
    participants   TEXT NOT NULL,
    self_row_index INTEGER NOT NULL,
    created_at     TEXT NOT NULL,
    FOREIGN KEY (training_id) REFERENCES trainings(training_id)
);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_db_path(db_path: str) -> str:
    return str(Path(db_path).expanduser())


async def connect_db(db_path: str) -> aiosqlite.Connection:
    conn = await aiosqlite.connect(normalize_db_path(db_path))
    conn.row_factory = aiosqlite.Row
    return conn


async def init_db(db_path: str) -> None:
    normalized = normalize_db_path(db_path)
    Path(normalized).parent.mkdir(parents=True, exist_ok=True)
    conn = await connect_db(normalized)
    try:
        await conn.executescript(SCHEMA)
        await _migrate_schema(conn)
        await conn.commit()
    finally:
        await conn.close()


def serialize_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def deserialize_json(value: str | None, default: Any = None) -> Any:
    if value is None:
        return default
    return json.loads(value)


async def _migrate_schema(conn: aiosqlite.Connection) -> None:
    cursor = await conn.execute("PRAGMA table_info(training_import_drafts)")
    draft_columns = {row["name"] for row in await cursor.fetchall()}
    if "course_controls" not in draft_columns:
        await conn.execute("ALTER TABLE training_import_drafts ADD COLUMN course_controls TEXT")
    if "track_gpx_path" not in draft_columns:
        await conn.execute("ALTER TABLE training_import_drafts ADD COLUMN track_gpx_path TEXT")
    if "track_gpx_filename" not in draft_columns:
        await conn.execute("ALTER TABLE training_import_drafts ADD COLUMN track_gpx_filename TEXT")
    if "track_points" not in draft_columns:
        await conn.execute("ALTER TABLE training_import_drafts ADD COLUMN track_points TEXT")
    if "edit_training_id" not in draft_columns:
        await conn.execute("ALTER TABLE training_import_drafts ADD COLUMN edit_training_id TEXT")
    if "finalized_training_id" not in draft_columns:
        await conn.execute("ALTER TABLE training_import_drafts ADD COLUMN finalized_training_id TEXT")

    cursor = await conn.execute("PRAGMA table_info(trainings)")
    training_columns = {row["name"] for row in await cursor.fetchall()}
    if "training_type" not in training_columns:
        await conn.execute("ALTER TABLE trainings ADD COLUMN training_type TEXT")
    if "location" not in training_columns:
        await conn.execute("ALTER TABLE trainings ADD COLUMN location TEXT")
    if "course_controls" not in training_columns:
        await conn.execute("ALTER TABLE trainings ADD COLUMN course_controls TEXT")
    if "track_points" not in training_columns:
        await conn.execute("ALTER TABLE trainings ADD COLUMN track_points TEXT")

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS race_results (
            race_result_id TEXT PRIMARY KEY,
            training_id    TEXT,
            source_url     TEXT NOT NULL,
            event_name     TEXT NOT NULL,
            event_meta     TEXT,
            group_name     TEXT NOT NULL,
            group_subtitle TEXT,
            controls       TEXT NOT NULL,
            participants   TEXT NOT NULL,
            self_row_index INTEGER NOT NULL,
            created_at     TEXT NOT NULL,
            FOREIGN KEY (training_id) REFERENCES trainings(training_id)
        )
        """
    )
    cursor = await conn.execute("PRAGMA table_info(race_results)")
    race_result_columns = {row["name"] for row in await cursor.fetchall()}
    if "training_id" not in race_result_columns:
        await conn.execute("ALTER TABLE race_results ADD COLUMN training_id TEXT")


async def create_import_draft(
    conn: aiosqlite.Connection,
    *,
    title: str,
    date: str,
    training_type: str | None = None,
    location: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    now = utc_now_iso()
    draft_id = uuid4().hex
    await conn.execute(
        """
        INSERT INTO training_import_drafts (
            draft_id, title, date, training_type, location, notes, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (draft_id, title, date, training_type, location, notes, now, now),
    )
    await conn.commit()
    draft = await get_import_draft(conn, draft_id)
    if draft is None:
        raise RuntimeError("Import draft was not created")
    return draft


async def get_import_draft(conn: aiosqlite.Connection, draft_id: str) -> dict[str, Any] | None:
    cursor = await conn.execute(
        "SELECT * FROM training_import_drafts WHERE draft_id = ?",
        (draft_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return import_draft_from_row(row)


async def create_edit_import_draft(
    conn: aiosqlite.Connection,
    training_id: str,
) -> dict[str, Any] | None:
    training = await get_training_import_source(conn, training_id)
    if training is None:
        return None

    now = utc_now_iso()
    draft_id = uuid4().hex
    await conn.execute(
        """
        INSERT INTO training_import_drafts (
            draft_id, title, date, training_type, location, notes,
            map_image_path, map_image_filename,
            georef_method, georef_control_points, georef_transform, georef_residuals,
            course_controls, track_gpx_path, track_gpx_filename, track_points,
            edit_training_id, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            draft_id,
            training["title"],
            training["date"],
            training.get("training_type"),
            training.get("location"),
            training.get("notes"),
            training.get("map_image_path"),
            Path(training["map_image_path"]).name if training.get("map_image_path") else None,
            training.get("georef_method"),
            training.get("georef_control_points"),
            training.get("georef_transform"),
            training.get("georef_residuals"),
            training.get("course_controls"),
            training.get("gpx_path"),
            Path(training["gpx_path"]).name if training.get("gpx_path") else None,
            training.get("track_points"),
            training_id,
            now,
            now,
        ),
    )
    await conn.commit()
    return await get_import_draft(conn, draft_id)


async def update_import_draft_details(
    conn: aiosqlite.Connection,
    draft_id: str,
    *,
    title: str,
    date: str,
    training_type: str | None = None,
    location: str | None = None,
    notes: str | None = None,
) -> dict[str, Any] | None:
    await conn.execute(
        """
        UPDATE training_import_drafts
        SET title = ?,
            date = ?,
            training_type = ?,
            location = ?,
            notes = ?,
            updated_at = ?
        WHERE draft_id = ?
        """,
        (title, date, training_type, location, notes, utc_now_iso(), draft_id),
    )
    await conn.commit()
    return await get_import_draft(conn, draft_id)


async def list_trainings(conn: aiosqlite.Connection) -> list[dict[str, Any]]:
    cursor = await conn.execute("SELECT * FROM trainings ORDER BY date DESC, created_at DESC")
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def list_race_results(conn: aiosqlite.Connection) -> list[dict[str, Any]]:
    cursor = await conn.execute("SELECT * FROM race_results ORDER BY created_at DESC")
    rows = await cursor.fetchall()
    results = []
    for row in rows:
        result = race_result_from_row(row)
        result["participant_count"] = len(result["participants"])
        result["self_participant"] = _self_participant(result)
        results.append(result)
    return results


async def save_race_result(
    conn: aiosqlite.Connection,
    *,
    training_id: str | None = None,
    source_url: str,
    event_name: str,
    event_meta: str | None,
    group_name: str,
    group_subtitle: str | None,
    controls: list[dict[str, Any]],
    participants: list[dict[str, Any]],
    self_row_index: int,
) -> dict[str, Any]:
    now = utc_now_iso()
    race_result_id = uuid4().hex
    await conn.execute(
        """
        INSERT INTO race_results (
            race_result_id, training_id, source_url, event_name, event_meta,
            group_name, group_subtitle, controls, participants,
            self_row_index, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            race_result_id,
            training_id,
            source_url,
            event_name,
            event_meta,
            group_name,
            group_subtitle,
            serialize_json(controls),
            serialize_json(participants),
            self_row_index,
            now,
        ),
    )
    await conn.commit()
    result = await get_race_result(conn, race_result_id)
    if result is None:
        raise RuntimeError("Race result was not created")
    return result


async def get_race_result(conn: aiosqlite.Connection, race_result_id: str) -> dict[str, Any] | None:
    cursor = await conn.execute(
        "SELECT * FROM race_results WHERE race_result_id = ?",
        (race_result_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    result = race_result_from_row(row)
    result["participant_count"] = len(result["participants"])
    result["self_participant"] = _self_participant(result)
    return result


async def get_latest_race_result_for_training(conn: aiosqlite.Connection, training_id: str) -> dict[str, Any] | None:
    cursor = await conn.execute(
        """
        SELECT *
        FROM race_results
        WHERE training_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (training_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    result = race_result_from_row(row)
    result["participant_count"] = len(result["participants"])
    result["self_participant"] = _self_participant(result)
    return result


async def set_import_draft_map_image(
    conn: aiosqlite.Connection,
    draft_id: str,
    *,
    image_path: str,
    filename: str,
) -> dict[str, Any] | None:
    await conn.execute(
        """
        UPDATE training_import_drafts
        SET map_image_path = ?, map_image_filename = ?, updated_at = ?
        WHERE draft_id = ?
        """,
        (image_path, filename, utc_now_iso(), draft_id),
    )
    await conn.commit()
    return await get_import_draft(conn, draft_id)


async def set_import_draft_georef(
    conn: aiosqlite.Connection,
    draft_id: str,
    *,
    method: str,
    control_points: list[dict[str, Any]],
    transform: dict[str, Any],
    residuals: list[dict[str, Any]],
) -> dict[str, Any] | None:
    await conn.execute(
        """
        UPDATE training_import_drafts
        SET georef_method = ?,
            georef_control_points = ?,
            georef_transform = ?,
            georef_residuals = ?,
            updated_at = ?
        WHERE draft_id = ?
        """,
        (
            method,
            serialize_json(control_points),
            serialize_json(transform),
            serialize_json(residuals),
            utc_now_iso(),
            draft_id,
        ),
    )
    await conn.commit()
    return await get_import_draft(conn, draft_id)


async def set_import_draft_course_controls(
    conn: aiosqlite.Connection,
    draft_id: str,
    *,
    controls: list[dict[str, Any]],
) -> dict[str, Any] | None:
    await conn.execute(
        """
        UPDATE training_import_drafts
        SET course_controls = ?, updated_at = ?
        WHERE draft_id = ?
        """,
        (serialize_json(controls), utc_now_iso(), draft_id),
    )
    await conn.commit()
    return await get_import_draft(conn, draft_id)


async def set_import_draft_track(
    conn: aiosqlite.Connection,
    draft_id: str,
    *,
    gpx_path: str,
    filename: str,
    track_points: list[dict[str, Any]],
) -> dict[str, Any] | None:
    await conn.execute(
        """
        UPDATE training_import_drafts
        SET track_gpx_path = ?,
            track_gpx_filename = ?,
            track_points = ?,
            updated_at = ?
        WHERE draft_id = ?
        """,
        (gpx_path, filename, serialize_json(track_points), utc_now_iso(), draft_id),
    )
    await conn.commit()
    return await get_import_draft(conn, draft_id)


async def update_training_track_points(
    conn: aiosqlite.Connection,
    training_id: str,
    *,
    track_points: list[dict[str, Any]],
) -> dict[str, Any] | None:
    training = await get_training(conn, training_id)
    if training is None:
        return None
    await conn.execute(
        """
        UPDATE trainings
        SET track_points = ?
        WHERE training_id = ?
        """,
        (serialize_json(track_points), training_id),
    )
    await conn.commit()
    return await get_training(conn, training_id)


async def finalize_import_draft(
    conn: aiosqlite.Connection,
    draft_id: str,
) -> dict[str, Any] | None:
    draft = await get_import_draft(conn, draft_id)
    if draft is None:
        return None
    if draft.get("finalized_training_id") and not draft.get("edit_training_id"):
        return await get_training(conn, draft["finalized_training_id"])

    now = utc_now_iso()
    existing_training = None
    if draft.get("edit_training_id"):
        existing_training = await get_training(conn, draft["edit_training_id"])
        if existing_training is None:
            return None

    map_id = existing_training.get("map_id") if existing_training else None
    if map_id is None and draft.get("map_image_path"):
        map_id = uuid4().hex
    if map_id is not None:
        if existing_training and existing_training.get("map_id"):
            await conn.execute(
                "UPDATE maps SET title = ?, image_path = ? WHERE map_id = ?",
                (draft["title"], draft["map_image_path"], map_id),
            )
        else:
            await conn.execute(
                """
                INSERT INTO maps (map_id, title, image_path, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (map_id, draft["title"], draft["map_image_path"], now),
            )

    if map_id is not None and draft.get("georef_transform"):
        await conn.execute(
            """
            INSERT INTO map_georeferences (
                map_id, method, control_points, transform, residuals, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(map_id) DO UPDATE SET
                method = excluded.method,
                control_points = excluded.control_points,
                transform = excluded.transform,
                residuals = excluded.residuals
            """,
            (
                map_id,
                draft.get("georef_method") or "affine",
                serialize_json(draft.get("georef_control_points") or []),
                serialize_json(draft["georef_transform"]),
                serialize_json(draft.get("georef_residuals") or []),
                now,
            ),
        )

    if existing_training:
        training_id = draft["edit_training_id"]
        await conn.execute(
            """
            UPDATE trainings
            SET title = ?,
                date = ?,
                training_type = ?,
                location = ?,
                map_id = ?,
                gpx_path = ?,
                notes = ?,
                course_controls = ?,
                track_points = ?
            WHERE training_id = ?
            """,
            (
                draft["title"],
                draft["date"],
                draft.get("training_type"),
                draft.get("location"),
                map_id,
                draft.get("track_gpx_path"),
                draft.get("notes"),
                serialize_json(draft.get("course_controls") or []),
                serialize_json(draft.get("track_points") or []),
                training_id,
            ),
        )
        await conn.execute(
            """
            UPDATE training_import_drafts
            SET finalized_training_id = ?, updated_at = ?
            WHERE draft_id = ?
            """,
            (training_id, now, draft_id),
        )
        await conn.commit()
        return await get_training(conn, training_id)

    training_id = uuid4().hex
    await conn.execute(
        """
        INSERT INTO trainings (
            training_id, title, date, training_type, location, map_id, gpx_path,
            notes, course_controls, track_points, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            training_id,
            draft["title"],
            draft["date"],
            draft.get("training_type"),
            draft.get("location"),
            map_id,
            draft.get("track_gpx_path"),
            draft.get("notes"),
            serialize_json(draft.get("course_controls") or []),
            serialize_json(draft.get("track_points") or []),
            now,
        ),
    )
    await conn.execute(
        """
        UPDATE training_import_drafts
        SET finalized_training_id = ?, updated_at = ?
        WHERE draft_id = ?
        """,
        (training_id, now, draft_id),
    )
    await conn.commit()
    return await get_training(conn, training_id)


async def get_training(conn: aiosqlite.Connection, training_id: str) -> dict[str, Any] | None:
    cursor = await conn.execute("SELECT * FROM trainings WHERE training_id = ?", (training_id,))
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def get_training_import_source(conn: aiosqlite.Connection, training_id: str) -> dict[str, Any] | None:
    cursor = await conn.execute(
        """
        SELECT
            trainings.*,
            maps.image_path AS map_image_path,
            map_georeferences.method AS georef_method,
            map_georeferences.control_points AS georef_control_points,
            map_georeferences.transform AS georef_transform,
            map_georeferences.residuals AS georef_residuals
        FROM trainings
        LEFT JOIN maps ON maps.map_id = trainings.map_id
        LEFT JOIN map_georeferences ON map_georeferences.map_id = trainings.map_id
        WHERE trainings.training_id = ?
        """,
        (training_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def get_training_player(conn: aiosqlite.Connection, training_id: str) -> dict[str, Any] | None:
    cursor = await conn.execute(
        """
        SELECT
            trainings.*,
            maps.image_path AS map_image_path,
            map_georeferences.transform AS georef_transform
        FROM trainings
        LEFT JOIN maps ON maps.map_id = trainings.map_id
        LEFT JOIN map_georeferences ON map_georeferences.map_id = trainings.map_id
        WHERE trainings.training_id = ?
        """,
        (training_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    training = dict(row)
    training["course_controls"] = deserialize_json(training.get("course_controls"), [])
    training["track_points"] = deserialize_json(training.get("track_points"), [])
    training["georef_transform"] = deserialize_json(training.get("georef_transform"), None)
    return training


def import_draft_from_row(row: aiosqlite.Row) -> dict[str, Any]:
    draft = dict(row)
    draft["georef_control_points"] = deserialize_json(draft.get("georef_control_points"), [])
    draft["georef_transform"] = deserialize_json(draft.get("georef_transform"), None)
    draft["georef_residuals"] = deserialize_json(draft.get("georef_residuals"), [])
    draft["course_controls"] = deserialize_json(draft.get("course_controls"), [])
    draft["track_points"] = deserialize_json(draft.get("track_points"), [])
    return draft


def race_result_from_row(row: aiosqlite.Row) -> dict[str, Any]:
    result = dict(row)
    result["controls"] = deserialize_json(result.get("controls"), [])
    result["participants"] = deserialize_json(result.get("participants"), [])
    return result


def _self_participant(result: dict[str, Any]) -> dict[str, Any] | None:
    for participant in result["participants"]:
        if participant.get("row_index") == result.get("self_row_index"):
            return participant
    return None
