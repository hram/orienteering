from __future__ import annotations

import asyncio
import os
import re
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from portal.db import connect_db, get_training_player, init_db, normalize_db_path, save_race_result
from portal.main import app
from tests.conftest import fetch_user_id


def test_import_draft_supports_second_map_layer() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={
                "title": "Two maps",
                "date": "2026-06-07",
                "discipline": "run",
                "subject_user_id": fetch_user_id("polina"),
            },
            follow_redirects=False,
        )
        draft_id = create_response.headers["location"].split("/")[3]

        add_layer = client.post(
            f"/trainings/imports/{draft_id}/map-layers",
            follow_redirects=False,
        )
        upload_second = client.post(
            f"/api/imports/{draft_id}/map-layers/map-2/map-image",
            files={"file": ("second.png", b"fake-second-map", "image/png")},
        )
        save_second_georef = client.post(
            f"/api/imports/{draft_id}/map-layers/map-2/georef",
            json={
                "control_points": [
                    {"pixel_x": 0, "pixel_y": 0, "lat": 60.0, "lon": 30.0},
                    {"pixel_x": 1000, "pixel_y": 0, "lat": 60.0, "lon": 30.01},
                    {"pixel_x": 0, "pixel_y": 1000, "lat": 59.99, "lon": 30.0},
                ]
            },
        )
        save_second_controls = client.post(
            f"/api/imports/{draft_id}/map-layers/map-2/course-controls",
            json={
                "controls": [
                    {"index": 1, "pixel_x": 100, "pixel_y": 100, "lat": 60.0, "lon": 30.0},
                    {"index": 2, "pixel_x": 200, "pixel_y": 200, "lat": 60.001, "lon": 30.001},
                ]
            },
        )
        draft_response = client.get(f"/api/imports/{draft_id}")

    assert add_layer.status_code == 303
    assert add_layer.headers["location"].endswith(f"/map?layer=map-2")
    assert upload_second.status_code == 200
    assert save_second_georef.status_code == 200
    assert save_second_controls.status_code == 200

    layers = draft_response.json()["draft"]["map_layers"]
    assert [layer["id"] for layer in layers] == ["map-1", "map-2"]
    assert layers[1]["map_image_url"].endswith("/imports/" + draft_id + "/map-2.png")
    assert layers[1]["course_controls"][0]["map_layer_id"] == "map-2"


def test_import_map_layers_are_client_side_tabs() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={
                "title": "Client layers",
                "date": "2026-06-07",
                "discipline": "run",
                "subject_user_id": fetch_user_id("polina"),
            },
            follow_redirects=False,
        )
        draft_id = create_response.headers["location"].split("/")[3]
        client.post(f"/api/imports/{draft_id}/map-layers")
        page = client.get(f"/trainings/imports/{draft_id}/map")

    assert page.status_code == 200
    assert 'data-map-layers=' in page.text
    assert 'data-layer-id="map-1"' in page.text
    assert 'data-layer-id="map-2"' in page.text
    assert '<div id="image-viewport" class="image-viewport">' in page.text
    assert 'class="map-layer-tabs image-layer-tabs"' in page.text
    assert page.text.index('id="image-viewport"') < page.text.index('class="map-layer-tabs image-layer-tabs"')
    assert f'/trainings/imports/{draft_id}/map?layer=map-2' not in page.text


def test_race_result_page_exposes_training_map_layers() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={
                "title": "Race result layers",
                "date": "2026-06-07",
                "discipline": "run",
                "subject_user_id": fetch_user_id("polina"),
            },
            follow_redirects=False,
        )
        draft_id = create_response.headers["location"].split("/")[3]
        client.post(
            f"/api/imports/{draft_id}/map-image",
            files={"file": ("first.png", b"fake-first-map", "image/png")},
        )
        client.post(
            f"/api/imports/{draft_id}/georef",
            json={
                "control_points": [
                    {"pixel_x": 0, "pixel_y": 0, "lat": 60.0, "lon": 30.0},
                    {"pixel_x": 1000, "pixel_y": 0, "lat": 60.0, "lon": 30.01},
                    {"pixel_x": 0, "pixel_y": 1000, "lat": 59.99, "lon": 30.0},
                ]
            },
        )
        client.post(
            f"/api/imports/{draft_id}/course-controls",
            json={
                "controls": [
                    {"index": 1, "pixel_x": 0, "pixel_y": 0, "lat": 60.0, "lon": 30.0},
                    {"index": 2, "pixel_x": 100, "pixel_y": 0, "lat": 60.0, "lon": 30.001},
                ]
            },
        )
        client.post(f"/api/imports/{draft_id}/map-layers")
        client.post(
            f"/api/imports/{draft_id}/map-layers/map-2/map-image",
            files={"file": ("second.png", b"fake-second-map", "image/png")},
        )
        client.post(
            f"/api/imports/{draft_id}/map-layers/map-2/georef",
            json={
                "control_points": [
                    {"pixel_x": 0, "pixel_y": 0, "lat": 60.1, "lon": 30.1},
                    {"pixel_x": 1000, "pixel_y": 0, "lat": 60.1, "lon": 30.11},
                    {"pixel_x": 0, "pixel_y": 1000, "lat": 60.09, "lon": 30.1},
                ]
            },
        )
        client.post(
            f"/api/imports/{draft_id}/map-layers/map-2/course-controls",
            json={
                "controls": [
                    {"index": 1, "pixel_x": 100, "pixel_y": 100, "lat": 60.1, "lon": 30.1},
                    {"index": 2, "pixel_x": 200, "pixel_y": 200, "lat": 60.101, "lon": 30.101},
                ]
            },
        )
        finish = client.post(f"/trainings/imports/{draft_id}/finish", follow_redirects=False)
        assert finish.status_code == 303
        trainings = client.get("/trainings")
        match = re.search(
            r"Race result layers.*?/trainings/([0-9a-f]+)/race-result/import",
            trainings.text,
            re.S,
        )
        assert match is not None
        training_id = match.group(1)

        race_result = asyncio.run(_save_layered_race_result(training_id))
        page = client.get(f"/race-results/{race_result['race_result_id']}")

    assert page.status_code == 200
    assert "data-map-layers=" in page.text
    assert '"id": "map-2"' in page.text
    assert '"map_layer_id": "map-2"' in page.text
    assert "race_result.js" in page.text


async def _save_layered_race_result(training_id: str) -> dict:
    conn = await connect_db(normalize_db_path(os.environ["ORIENTEERING_PORTAL_DB_PATH"]))
    try:
        return await save_race_result(
            conn,
            training_id=training_id,
            race_date="2026-06-07",
            source_url="https://example.test/_races/layered/split.htm",
            event_name="Layered event",
            event_meta="",
            group_name="Ж14",
            group_subtitle=None,
            controls=[
                {"label": "1", "code": "31", "distance_meters": None},
                {"label": "Ф", "code": "240", "distance_meters": None},
            ],
            participants=[
                {
                    "row_index": 0,
                    "name": "Храмова Полина",
                    "bib": "411",
                    "result": "00:10:00",
                    "place": "1",
                    "gap": "",
                    "splits": [
                        {"label": "1", "split": {"time": "05:00", "seconds": 300}},
                        {"label": "Ф", "split": {"time": "05:00", "seconds": 300}},
                    ],
                }
            ],
            self_row_index=0,
            kind="course",
        )
    finally:
        await conn.close()


def test_old_single_map_training_migrates_to_map_layers(tmp_path: Path) -> None:
    db_path = tmp_path / "old.sqlite3"
    with sqlite3.connect(db_path) as con:
        con.executescript(
            """
            CREATE TABLE maps (
                map_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                image_path TEXT NOT NULL,
                image_width INTEGER,
                image_height INTEGER,
                created_at TEXT NOT NULL
            );
            CREATE TABLE map_georeferences (
                map_id TEXT PRIMARY KEY,
                method TEXT NOT NULL,
                control_points TEXT NOT NULL,
                transform TEXT NOT NULL,
                residuals TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE trainings (
                training_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                date TEXT NOT NULL,
                training_type TEXT,
                discipline TEXT,
                location TEXT,
                map_id TEXT,
                gpx_path TEXT,
                notes TEXT,
                course_controls TEXT,
                track_points TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        con.execute(
            "INSERT INTO maps (map_id, title, image_path, created_at) VALUES (?, ?, ?, ?)",
            ("map-old", "Old map", "data/uploads/imports/old/map.png", "2026-06-07T00:00:00Z"),
        )
        con.execute(
            """
            INSERT INTO map_georeferences (
                map_id, method, control_points, transform, residuals, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "map-old",
                "affine",
                '[{"pixel_x":0,"pixel_y":0,"lat":60.0,"lon":30.0}]',
                '{"lat_a":0,"lat_b":-0.00001,"lat_c":60,"lon_a":0.00001,"lon_b":0,"lon_c":30}',
                "[]",
                "2026-06-07T00:00:00Z",
            ),
        )
        con.execute(
            """
            INSERT INTO trainings (
                training_id, title, date, map_id, course_controls, track_points, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "training-old",
                "Old training",
                "2026-06-07",
                "map-old",
                '[{"index":1,"pixel_x":10,"pixel_y":20,"lat":60.0,"lon":30.0}]',
                "[]",
                "2026-06-07T00:00:00Z",
            ),
        )

    async def load_training() -> dict:
        await init_db(str(db_path))
        conn = await connect_db(normalize_db_path(str(db_path)))
        try:
            training = await get_training_player(conn, "training-old")
        finally:
            await conn.close()
        assert training is not None
        return training

    training = asyncio.run(load_training())

    with sqlite3.connect(db_path) as con:
        stored_map_layers = con.execute(
            "SELECT map_layers FROM trainings WHERE training_id = ?",
            ("training-old",),
        ).fetchone()[0]

    assert training["map_layers"][0]["id"] == "map-1"
    assert training["map_layers"][0]["image_path"] == "data/uploads/imports/old/map.png"
    assert training["map_layers"][0]["georef_transform"]["lat_c"] == 60
    assert training["map_layers"][0]["course_controls"][0]["pixel_x"] == 10
    assert stored_map_layers is not None
    assert "data/uploads/imports/old/map.png" in stored_map_layers
