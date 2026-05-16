from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiosqlite


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id      TEXT PRIMARY KEY,
    username     TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    is_admin     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);

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
    discipline      TEXT,
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
    discipline            TEXT,
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
    subject_user_id       TEXT,
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
    kind           TEXT NOT NULL DEFAULT 'course',
    created_at     TEXT NOT NULL,
    FOREIGN KEY (training_id) REFERENCES trainings(training_id)
);

CREATE TABLE IF NOT EXISTS training_visibility (
    training_id TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (training_id, user_id),
    FOREIGN KEY (training_id) REFERENCES trainings(training_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS race_result_visibility (
    race_result_id TEXT NOT NULL,
    user_id        TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    PRIMARY KEY (race_result_id, user_id),
    FOREIGN KEY (race_result_id) REFERENCES race_results(race_result_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS error_reasons (
    reason_id  TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    is_active  INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS split_error_reviews (
    review_id          TEXT PRIMARY KEY,
    training_id        TEXT NOT NULL,
    race_result_id     TEXT NOT NULL DEFAULT '',
    split_label        TEXT NOT NULL,
    from_control_label TEXT NOT NULL,
    to_control_label   TEXT NOT NULL,
    reason_id          TEXT,
    custom_reason      TEXT,
    reviewed_at        TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    UNIQUE (training_id, race_result_id, split_label, from_control_label, to_control_label),
    FOREIGN KEY (reason_id) REFERENCES error_reasons(reason_id)
);
"""


class _Unset:
    pass


_UNSET = _Unset()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_db_path(db_path: str) -> str:
    return str(Path(db_path).expanduser())


async def connect_db(db_path: str) -> aiosqlite.Connection:
    conn = await aiosqlite.connect(normalize_db_path(db_path))
    conn.row_factory = aiosqlite.Row
    return conn


DEFAULT_USERS: tuple[tuple[str, str, bool], ...] = (
    ("polina", "Полина", False),
    ("olga", "Ольга", False),
    ("evgeny", "Евгений", True),
)

DEFAULT_ERROR_REASONS: tuple[str, ...] = (
    "Ошибка направления",
    "Плохой выбор пути",
    "Долгий вход в КП",
    "Остановка на чтение карты",
    "Потеря контакта с картой",
    "Ошибка реализации варианта",
    "Низкий темп без ошибки",
    "Техническая проблема GPS/карты",
    "Другое",
)


async def init_db(db_path: str) -> None:
    normalized = normalize_db_path(db_path)
    Path(normalized).parent.mkdir(parents=True, exist_ok=True)
    conn = await connect_db(normalized)
    try:
        await conn.executescript(SCHEMA)
        await _migrate_schema(conn)
        await _seed_default_users(conn)
        await _seed_default_error_reasons(conn)
        await _seed_default_visibility(conn)
        await conn.commit()
    finally:
        await conn.close()


async def _seed_default_users(conn: aiosqlite.Connection) -> None:
    now = utc_now_iso()
    for username, display_name, is_admin in DEFAULT_USERS:
        admin_flag = 1 if is_admin else 0
        cursor = await conn.execute(
            "SELECT user_id, is_admin FROM users WHERE username = ?",
            (username,),
        )
        row = await cursor.fetchone()
        if row is None:
            await conn.execute(
                """
                INSERT INTO users (user_id, username, display_name, is_admin, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (uuid4().hex, username, display_name, admin_flag, now),
            )
        elif row["is_admin"] != admin_flag:
            await conn.execute(
                "UPDATE users SET is_admin = ? WHERE username = ?",
                (admin_flag, username),
            )


async def _seed_default_error_reasons(conn: aiosqlite.Connection) -> None:
    cursor = await conn.execute("SELECT COUNT(*) AS count FROM error_reasons")
    row = await cursor.fetchone()
    if row and row["count"] > 0:
        return
    now = utc_now_iso()
    for index, label in enumerate(DEFAULT_ERROR_REASONS):
        await conn.execute(
            """
            INSERT INTO error_reasons (
                reason_id, label, is_active, sort_order, created_at, updated_at
            )
            VALUES (?, ?, 1, ?, ?, ?)
            """,
            (uuid4().hex, label, index, now, now),
        )


async def _seed_default_visibility(conn: aiosqlite.Connection) -> None:
    cursor = await conn.execute("SELECT user_id, username FROM users")
    user_ids = {row["username"]: row["user_id"] for row in await cursor.fetchall()}
    polina_id = user_ids.get("polina")
    olga_id = user_ids.get("olga")
    evgeny_id = user_ids.get("evgeny")
    if not (polina_id and olga_id and evgeny_id):
        return
    now = utc_now_iso()

    cursor = await conn.execute(
        """
        SELECT t.training_id
        FROM trainings t
        WHERE NOT EXISTS (
            SELECT 1 FROM training_visibility v WHERE v.training_id = t.training_id
        )
        """
    )
    for row in await cursor.fetchall():
        for user_id in (evgeny_id, polina_id):
            await conn.execute(
                """
                INSERT OR IGNORE INTO training_visibility (training_id, user_id, created_at)
                VALUES (?, ?, ?)
                """,
                (row["training_id"], user_id, now),
            )

    cursor = await conn.execute(
        """
        SELECT r.race_result_id, r.self_row_index, r.participants
        FROM race_results r
        WHERE NOT EXISTS (
            SELECT 1 FROM race_result_visibility v WHERE v.race_result_id = r.race_result_id
        )
        """
    )
    for row in await cursor.fetchall():
        try:
            participants = json.loads(row["participants"]) if row["participants"] else []
        except (json.JSONDecodeError, TypeError):
            participants = []
        await _seed_race_result_visibility(
            conn,
            race_result_id=row["race_result_id"],
            participants=participants,
            self_row_index=row["self_row_index"],
            when=now,
        )


def serialize_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def deserialize_json(value: str | None, default: Any = None) -> Any:
    if value is None:
        return default
    return json.loads(value)


def error_reason_from_row(row: aiosqlite.Row) -> dict[str, Any]:
    result = dict(row)
    result["is_active"] = bool(result.get("is_active"))
    return result


def split_error_review_from_row(row: aiosqlite.Row) -> dict[str, Any]:
    result = dict(row)
    result["race_result_id"] = result.get("race_result_id") or None
    if "reason_is_active" in result and result["reason_is_active"] is not None:
        result["reason_is_active"] = bool(result["reason_is_active"])
    return result


async def _migrate_schema(conn: aiosqlite.Connection) -> None:
    cursor = await conn.execute("PRAGMA table_info(users)")
    user_columns = {row["name"] for row in await cursor.fetchall()}
    if user_columns and "is_admin" not in user_columns:
        await conn.execute(
            "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0"
        )

    cursor = await conn.execute("PRAGMA table_info(training_import_drafts)")
    draft_columns = {row["name"] for row in await cursor.fetchall()}
    if "discipline" not in draft_columns:
        await conn.execute("ALTER TABLE training_import_drafts ADD COLUMN discipline TEXT")
        await conn.execute("UPDATE training_import_drafts SET discipline = 'run' WHERE discipline IS NULL OR discipline = ''")
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
    if "subject_user_id" not in draft_columns:
        await conn.execute("ALTER TABLE training_import_drafts ADD COLUMN subject_user_id TEXT")

    cursor = await conn.execute("PRAGMA table_info(trainings)")
    training_columns = {row["name"] for row in await cursor.fetchall()}
    if "training_type" not in training_columns:
        await conn.execute("ALTER TABLE trainings ADD COLUMN training_type TEXT")
    if "discipline" not in training_columns:
        await conn.execute("ALTER TABLE trainings ADD COLUMN discipline TEXT")
        await conn.execute("UPDATE trainings SET discipline = 'run' WHERE discipline IS NULL OR discipline = ''")
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
    if "kind" not in race_result_columns:
        await conn.execute("ALTER TABLE race_results ADD COLUMN kind TEXT NOT NULL DEFAULT 'course'")

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS error_reasons (
            reason_id  TEXT PRIMARY KEY,
            label      TEXT NOT NULL,
            is_active  INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS split_error_reviews (
            review_id          TEXT PRIMARY KEY,
            training_id        TEXT NOT NULL,
            race_result_id     TEXT NOT NULL DEFAULT '',
            split_label        TEXT NOT NULL,
            from_control_label TEXT NOT NULL,
            to_control_label   TEXT NOT NULL,
            reason_id          TEXT,
            custom_reason      TEXT,
            reviewed_at        TEXT,
            created_at         TEXT NOT NULL,
            updated_at         TEXT NOT NULL,
            UNIQUE (training_id, race_result_id, split_label, from_control_label, to_control_label),
            FOREIGN KEY (reason_id) REFERENCES error_reasons(reason_id)
        )
        """
    )
    await _deduplicate_split_error_reviews(conn)
    await conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS split_error_reviews_training_split_unique
        ON split_error_reviews (
            training_id,
            split_label,
            from_control_label,
            to_control_label
        )
        """
    )


async def _deduplicate_split_error_reviews(conn: aiosqlite.Connection) -> None:
    await conn.execute(
        """
        DELETE FROM split_error_reviews
        WHERE review_id IN (
            SELECT review_id
            FROM (
                SELECT
                    review_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY training_id, split_label, from_control_label, to_control_label
                        ORDER BY
                            CASE WHEN race_result_id <> '' THEN 0 ELSE 1 END,
                            COALESCE(reviewed_at, updated_at, created_at) DESC,
                            updated_at DESC,
                            created_at DESC
                    ) AS duplicate_rank
                FROM split_error_reviews
            )
            WHERE duplicate_rank > 1
        )
        """
    )


async def create_import_draft(
    conn: aiosqlite.Connection,
    *,
    title: str,
    date: str,
    training_type: str | None = None,
    discipline: str | None = None,
    location: str | None = None,
    notes: str | None = None,
    subject_user_id: str | None = None,
) -> dict[str, Any]:
    now = utc_now_iso()
    draft_id = uuid4().hex
    await conn.execute(
        """
        INSERT INTO training_import_drafts (
            draft_id, title, date, training_type, discipline, location, notes,
            subject_user_id, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (draft_id, title, date, training_type, discipline, location, notes, subject_user_id, now, now),
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
            draft_id, title, date, training_type, discipline, location, notes,
            map_image_path, map_image_filename,
            georef_method, georef_control_points, georef_transform, georef_residuals,
            course_controls, track_gpx_path, track_gpx_filename, track_points,
            edit_training_id, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            draft_id,
            training["title"],
            training["date"],
            training.get("training_type"),
            training.get("discipline"),
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
    discipline: str | None = None,
    location: str | None = None,
    notes: str | None = None,
    subject_user_id: "str | None | _Unset" = _UNSET,
) -> dict[str, Any] | None:
    if isinstance(subject_user_id, _Unset):
        await conn.execute(
            """
            UPDATE training_import_drafts
            SET title = ?,
                date = ?,
                training_type = ?,
                discipline = ?,
                location = ?,
                notes = ?,
                updated_at = ?
            WHERE draft_id = ?
            """,
            (title, date, training_type, discipline, location, notes, utc_now_iso(), draft_id),
        )
    else:
        await conn.execute(
            """
            UPDATE training_import_drafts
            SET title = ?,
                date = ?,
                training_type = ?,
                discipline = ?,
                location = ?,
                notes = ?,
                subject_user_id = ?,
                updated_at = ?
            WHERE draft_id = ?
            """,
            (
                title,
                date,
                training_type,
                discipline,
                location,
                notes,
                subject_user_id,
                utc_now_iso(),
                draft_id,
            ),
        )
    await conn.commit()
    return await get_import_draft(conn, draft_id)


async def list_trainings(
    conn: aiosqlite.Connection,
    *,
    viewer_user_id: str | None = None,
) -> list[dict[str, Any]]:
    if viewer_user_id is None:
        cursor = await conn.execute(
            """
            SELECT
                trainings.*,
                (
                    SELECT race_results.race_result_id
                    FROM race_results
                    WHERE race_results.training_id = trainings.training_id
                    ORDER BY race_results.created_at DESC
                    LIMIT 1
                ) AS latest_race_result_id
            FROM trainings
            ORDER BY trainings.date DESC, trainings.created_at DESC
            """
        )
    else:
        cursor = await conn.execute(
            """
            SELECT
                trainings.*,
                (
                    SELECT race_results.race_result_id
                    FROM race_results
                    WHERE race_results.training_id = trainings.training_id
                    ORDER BY race_results.created_at DESC
                    LIMIT 1
                ) AS latest_race_result_id
            FROM trainings
            JOIN training_visibility v
              ON v.training_id = trainings.training_id AND v.user_id = ?
            ORDER BY trainings.date DESC, trainings.created_at DESC
            """,
            (viewer_user_id,),
        )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def list_race_results(
    conn: aiosqlite.Connection,
    *,
    viewer_user_id: str | None = None,
) -> list[dict[str, Any]]:
    if viewer_user_id is None:
        cursor = await conn.execute(
            "SELECT * FROM race_results ORDER BY created_at DESC"
        )
    else:
        cursor = await conn.execute(
            """
            SELECT race_results.*
            FROM race_results
            JOIN race_result_visibility v
              ON v.race_result_id = race_results.race_result_id AND v.user_id = ?
            ORDER BY race_results.created_at DESC
            """,
            (viewer_user_id,),
        )
    rows = await cursor.fetchall()
    results = []
    for row in rows:
        result = race_result_from_row(row)
        result["participant_count"] = len(result["participants"])
        result["self_participant"] = _self_participant(result)
        results.append(result)
    return results


async def list_dashboard_race_results(
    conn: aiosqlite.Connection,
    *,
    viewer_user_id: str | None = None,
) -> list[dict[str, Any]]:
    base_sql = """
        SELECT
            race_results.*,
            trainings.title AS training_title,
            trainings.date AS training_date,
            trainings.training_type AS training_type,
            trainings.course_controls AS training_course_controls,
            trainings.track_points AS training_track_points,
            maps.image_path AS map_image_path,
            map_georeferences.transform AS georef_transform
        FROM race_results
        JOIN trainings ON trainings.training_id = race_results.training_id
        LEFT JOIN maps ON maps.map_id = trainings.map_id
        LEFT JOIN map_georeferences ON map_georeferences.map_id = trainings.map_id
    """
    if viewer_user_id is None:
        cursor = await conn.execute(
            base_sql + " ORDER BY trainings.date DESC, race_results.created_at DESC"
        )
    else:
        cursor = await conn.execute(
            base_sql
            + """
            JOIN training_visibility tv
              ON tv.training_id = trainings.training_id AND tv.user_id = ?
            JOIN race_result_visibility rv
              ON rv.race_result_id = race_results.race_result_id AND rv.user_id = ?
            ORDER BY trainings.date DESC, race_results.created_at DESC
            """,
            (viewer_user_id, viewer_user_id),
        )
    rows = await cursor.fetchall()
    results = []
    for row in rows:
        result = race_result_from_row(row)
        result["participant_count"] = len(result["participants"])
        result["self_participant"] = _self_participant(result)
        result["training_title"] = row["training_title"]
        result["training_date"] = row["training_date"]
        result["training_type"] = row["training_type"]
        result["training_course_controls"] = deserialize_json(row["training_course_controls"], [])
        result["training_track_points"] = deserialize_json(row["training_track_points"], [])
        result["map_image_path"] = row["map_image_path"]
        result["georef_transform"] = deserialize_json(row["georef_transform"], None)
        result["reviewed_split_keys"] = await _list_reviewed_split_keys(
            conn,
            training_id=result["training_id"],
            race_result_id=result["race_result_id"],
        )
        results.append(result)
    return results


async def list_dashboard_error_reason_stats(
    conn: aiosqlite.Connection,
    *,
    viewer_user_id: str | None = None,
) -> list[dict[str, Any]]:
    base_sql = """
        SELECT
            er.reason_id AS reason_id,
            COALESCE(er.label, NULLIF(r.custom_reason, ''), 'Другое') AS reason_label,
            trainings.date AS training_date,
            COUNT(*) AS count
        FROM split_error_reviews r
        JOIN trainings ON trainings.training_id = r.training_id
        LEFT JOIN error_reasons er ON er.reason_id = r.reason_id
        WHERE r.reviewed_at IS NOT NULL
    """
    if viewer_user_id is None:
        cursor = await conn.execute(
            base_sql
            + """
            GROUP BY er.reason_id, reason_label, trainings.date
            ORDER BY trainings.date, reason_label
            """
        )
    else:
        cursor = await conn.execute(
            base_sql
            + """
              AND EXISTS (
                  SELECT 1
                  FROM training_visibility tv
                  WHERE tv.training_id = trainings.training_id
                    AND tv.user_id = ?
              )
            GROUP BY er.reason_id, reason_label, trainings.date
            ORDER BY trainings.date, reason_label
            """,
            (viewer_user_id,),
        )
    return [dict(row) for row in await cursor.fetchall()]


async def list_dashboard_split_error_reviews(
    conn: aiosqlite.Connection,
    *,
    viewer_user_id: str | None = None,
    reason_id: str | None = None,
    custom_reason: str | None = None,
) -> list[dict[str, Any]]:
    filters = ["r.reviewed_at IS NOT NULL"]
    params: list[Any] = []
    if reason_id:
        filters.append("r.reason_id = ?")
        params.append(reason_id)
    elif custom_reason:
        filters.append("r.reason_id IS NULL")
        filters.append("r.custom_reason = ?")
        params.append(custom_reason)

    visibility_sql = ""
    if viewer_user_id is not None:
        visibility_sql = """
          AND EXISTS (
              SELECT 1
              FROM training_visibility tv
              WHERE tv.training_id = trainings.training_id
                AND tv.user_id = ?
          )
        """
        params.append(viewer_user_id)

    cursor = await conn.execute(
        f"""
        SELECT
            r.review_id,
            r.training_id,
            r.race_result_id,
            r.split_label,
            r.from_control_label,
            r.to_control_label,
            r.reason_id,
            r.custom_reason,
            r.reviewed_at,
            er.label AS reason_label,
            er.is_active AS reason_is_active
        FROM split_error_reviews r
        JOIN trainings ON trainings.training_id = r.training_id
        LEFT JOIN error_reasons er ON er.reason_id = r.reason_id
        WHERE {" AND ".join(filters)}
        {visibility_sql}
        ORDER BY trainings.date DESC, r.reviewed_at DESC
        """,
        params,
    )
    return [split_error_review_from_row(row) for row in await cursor.fetchall()]


async def _list_reviewed_split_keys(
    conn: aiosqlite.Connection,
    *,
    training_id: str,
    race_result_id: str,
) -> set[tuple[str, str, str]]:
    cursor = await conn.execute(
        """
        SELECT split_label, from_control_label, to_control_label
        FROM split_error_reviews
        WHERE training_id = ?
          AND reviewed_at IS NOT NULL
        """,
        (training_id,),
    )
    return {
        (row["split_label"], row["from_control_label"], row["to_control_label"])
        for row in await cursor.fetchall()
    }


async def list_attachable_race_results(
    conn: aiosqlite.Connection,
    training_id: str,
) -> list[dict[str, Any]]:
    cursor = await conn.execute(
        """
        SELECT *
        FROM race_results
        WHERE training_id IS NULL OR training_id = ?
        ORDER BY created_at DESC
        """,
        (training_id,),
    )
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
    kind: str = "course",
) -> dict[str, Any]:
    now = utc_now_iso()
    race_result_id = uuid4().hex
    await conn.execute(
        """
        INSERT INTO race_results (
            race_result_id, training_id, source_url, event_name, event_meta,
            group_name, group_subtitle, controls, participants,
            self_row_index, kind, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            kind,
            now,
        ),
    )
    await _seed_race_result_visibility(
        conn,
        race_result_id=race_result_id,
        participants=participants,
        self_row_index=self_row_index,
        when=now,
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


async def delete_race_result(conn: aiosqlite.Connection, race_result_id: str) -> bool:
    cursor = await conn.execute(
        "DELETE FROM race_results WHERE race_result_id = ?",
        (race_result_id,),
    )
    await conn.commit()
    return cursor.rowcount > 0


async def delete_training(conn: aiosqlite.Connection, training_id: str) -> bool:
    """Delete a training and its tightly-coupled rows.

    Race results survive the training — they have their own lifecycle and own
    delete on /race-results — so we just detach them by clearing training_id.
    AI analysis and visibility rows are training-scoped and go with the training.
    """
    await conn.execute(
        "UPDATE race_results SET training_id = NULL WHERE training_id = ?",
        (training_id,),
    )
    await conn.execute("DELETE FROM ai_analysis WHERE training_id = ?", (training_id,))
    await conn.execute("DELETE FROM training_visibility WHERE training_id = ?", (training_id,))
    cursor = await conn.execute("DELETE FROM trainings WHERE training_id = ?", (training_id,))
    await conn.commit()
    return cursor.rowcount > 0


async def attach_race_result_to_training(
    conn: aiosqlite.Connection,
    *,
    race_result_id: str,
    training_id: str,
) -> dict[str, Any] | None:
    await conn.execute(
        """
        UPDATE race_results
        SET training_id = ?
        WHERE race_result_id = ?
          AND (training_id IS NULL OR training_id = ?)
        """,
        (training_id, race_result_id, training_id),
    )
    await conn.commit()
    return await get_race_result(conn, race_result_id)


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


async def clear_import_draft_track(
    conn: aiosqlite.Connection,
    draft_id: str,
) -> dict[str, Any] | None:
    await conn.execute(
        """
        UPDATE training_import_drafts
        SET track_gpx_path = NULL,
            track_gpx_filename = NULL,
            track_points = ?,
            updated_at = ?
        WHERE draft_id = ?
        """,
        (serialize_json([]), utc_now_iso(), draft_id),
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


async def list_error_reasons(conn: aiosqlite.Connection) -> list[dict[str, Any]]:
    cursor = await conn.execute(
        """
        SELECT reason_id, label, is_active, sort_order, created_at, updated_at
        FROM error_reasons
        ORDER BY sort_order, label
        """
    )
    return [error_reason_from_row(row) for row in await cursor.fetchall()]


async def create_error_reason(conn: aiosqlite.Connection, label: str) -> dict[str, Any]:
    now = utc_now_iso()
    cursor = await conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM error_reasons")
    row = await cursor.fetchone()
    reason_id = uuid4().hex
    await conn.execute(
        """
        INSERT INTO error_reasons (
            reason_id, label, is_active, sort_order, created_at, updated_at
        )
        VALUES (?, ?, 1, ?, ?, ?)
        """,
        (reason_id, label, row["next_order"] if row else 0, now, now),
    )
    await conn.commit()
    reason = await get_error_reason(conn, reason_id)
    if reason is None:
        raise RuntimeError("Error reason was not created")
    return reason


async def get_error_reason(conn: aiosqlite.Connection, reason_id: str) -> dict[str, Any] | None:
    cursor = await conn.execute(
        "SELECT * FROM error_reasons WHERE reason_id = ?",
        (reason_id,),
    )
    row = await cursor.fetchone()
    return error_reason_from_row(row) if row else None


async def update_error_reason(
    conn: aiosqlite.Connection,
    reason_id: str,
    *,
    label: str,
    is_active: bool,
) -> dict[str, Any] | None:
    await conn.execute(
        """
        UPDATE error_reasons
        SET label = ?, is_active = ?, updated_at = ?
        WHERE reason_id = ?
        """,
        (label, 1 if is_active else 0, utc_now_iso(), reason_id),
    )
    await conn.commit()
    return await get_error_reason(conn, reason_id)


async def get_split_error_review(
    conn: aiosqlite.Connection,
    *,
    training_id: str,
    race_result_id: str | None,
    split_label: str,
    from_control_label: str,
    to_control_label: str,
) -> dict[str, Any] | None:
    cursor = await conn.execute(
        """
        SELECT
            r.*,
            er.label AS reason_label,
            er.is_active AS reason_is_active
        FROM split_error_reviews r
        LEFT JOIN error_reasons er ON er.reason_id = r.reason_id
        WHERE r.training_id = ?
          AND r.split_label = ?
          AND r.from_control_label = ?
          AND r.to_control_label = ?
        ORDER BY
          CASE WHEN r.race_result_id <> '' THEN 0 ELSE 1 END,
          COALESCE(r.reviewed_at, r.updated_at, r.created_at) DESC
        LIMIT 1
        """,
        (
            training_id,
            split_label,
            from_control_label,
            to_control_label,
        ),
    )
    row = await cursor.fetchone()
    return split_error_review_from_row(row) if row else None


async def save_split_error_review(
    conn: aiosqlite.Connection,
    *,
    training_id: str,
    race_result_id: str | None,
    split_label: str,
    from_control_label: str,
    to_control_label: str,
    reason_id: str | None,
    custom_reason: str | None,
) -> dict[str, Any] | None:
    now = utc_now_iso()
    normalized_custom = custom_reason.strip() if custom_reason else None
    normalized_custom = normalized_custom or None
    normalized_reason_id = reason_id or None
    reviewed_at = now if (normalized_reason_id or normalized_custom) else None
    existing = await get_split_error_review(
        conn,
        training_id=training_id,
        race_result_id=race_result_id,
        split_label=split_label,
        from_control_label=from_control_label,
        to_control_label=to_control_label,
    )
    if existing is None:
        await conn.execute(
            """
            INSERT INTO split_error_reviews (
                review_id, training_id, race_result_id, split_label,
                from_control_label, to_control_label, reason_id, custom_reason,
                reviewed_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid4().hex,
                training_id,
                race_result_id or "",
                split_label,
                from_control_label,
                to_control_label,
                normalized_reason_id,
                normalized_custom,
                reviewed_at,
                now,
                now,
            ),
        )
    else:
        stored_race_result_id = existing.get("race_result_id") or ""
        next_race_result_id = stored_race_result_id or (race_result_id or "")
        await conn.execute(
            """
            UPDATE split_error_reviews
            SET race_result_id = ?,
                reason_id = ?,
                custom_reason = ?,
                reviewed_at = ?,
                updated_at = ?
            WHERE review_id = ?
            """,
            (
                next_race_result_id,
                normalized_reason_id,
                normalized_custom,
                reviewed_at,
                now,
                existing["review_id"],
            ),
        )
    await conn.commit()
    return await get_split_error_review(
        conn,
        training_id=training_id,
        race_result_id=race_result_id,
        split_label=split_label,
        from_control_label=from_control_label,
        to_control_label=to_control_label,
    )


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
                discipline = ?,
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
                draft.get("discipline"),
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
            training_id, title, date, training_type, discipline, location, map_id, gpx_path,
            notes, course_controls, track_points, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            training_id,
            draft["title"],
            draft["date"],
            draft.get("training_type"),
            draft.get("discipline"),
            draft.get("location"),
            map_id,
            draft.get("track_gpx_path"),
            draft.get("notes"),
            serialize_json(draft.get("course_controls") or []),
            serialize_json(draft.get("track_points") or []),
            now,
        ),
    )
    await _seed_training_visibility(
        conn,
        training_id=training_id,
        subject_user_id=draft.get("subject_user_id"),
        when=now,
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


async def _seed_training_visibility(
    conn: aiosqlite.Connection,
    *,
    training_id: str,
    subject_user_id: str | None,
    when: str,
) -> None:
    user_ids: set[str] = set()
    if subject_user_id:
        user_ids.add(subject_user_id)
    cursor = await conn.execute("SELECT user_id FROM users WHERE is_admin = 1")
    for row in await cursor.fetchall():
        user_ids.add(row["user_id"])
    for user_id in user_ids:
        await conn.execute(
            """
            INSERT OR IGNORE INTO training_visibility (training_id, user_id, created_at)
            VALUES (?, ?, ?)
            """,
            (training_id, user_id, when),
        )


async def _seed_race_result_visibility(
    conn: aiosqlite.Connection,
    *,
    race_result_id: str,
    participants: list[dict[str, Any]],
    self_row_index: int,
    when: str,
) -> None:
    user_ids: set[str] = set()
    self_participant = next(
        (participant for participant in participants if participant.get("row_index") == self_row_index),
        None,
    )
    self_name = str((self_participant or {}).get("name") or "").casefold()

    cursor = await conn.execute("SELECT user_id, username, display_name, is_admin FROM users")
    for row in await cursor.fetchall():
        if row["is_admin"]:
            user_ids.add(row["user_id"])
            continue
        username = str(row["username"] or "").casefold()
        display_name = str(row["display_name"] or "").casefold()
        if self_name and ((display_name and display_name in self_name) or (username and username in self_name)):
            user_ids.add(row["user_id"])

    for user_id in user_ids:
        await conn.execute(
            """
            INSERT OR IGNORE INTO race_result_visibility (race_result_id, user_id, created_at)
            VALUES (?, ?, ?)
            """,
            (race_result_id, user_id, when),
        )


async def list_non_admin_users(conn: aiosqlite.Connection) -> list[dict[str, Any]]:
    cursor = await conn.execute(
        """
        SELECT user_id, username, display_name
        FROM users
        WHERE is_admin = 0
        ORDER BY display_name
        """
    )
    return [dict(row) for row in await cursor.fetchall()]


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
    result["kind"] = result.get("kind") or "course"
    return result


def _self_participant(result: dict[str, Any]) -> dict[str, Any] | None:
    for participant in result["participants"]:
        if participant.get("row_index") == result.get("self_row_index"):
            return participant
    return None
