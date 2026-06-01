from __future__ import annotations

import os
import re
import sqlite3
from uuid import uuid4

from fastapi.testclient import TestClient

from portal.auth import USER_COOKIE_NAME
from portal.main import app
from tests.conftest import fetch_user_id


def test_index_page() -> None:
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Orienteering Portal" in response.text


def test_fit_georef_api() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/georef/fit",
            json={
                "control_points": [
                    {"pixel_x": 0, "pixel_y": 0, "lat": 60.0, "lon": 30.0},
                    {"pixel_x": 1000, "pixel_y": 0, "lat": 60.0, "lon": 30.01},
                    {"pixel_x": 0, "pixel_y": 1000, "lat": 59.99, "lon": 30.0},
                ]
            },
        )

    assert response.status_code == 200
    assert response.json()["method"] == "affine"


def test_training_import_wizard_starts_with_details_step() -> None:
    with TestClient(app) as client:
        response = client.get("/trainings/new")

    assert response.status_code == 200
    assert "Шаг 1 из 3" in response.text
    assert 'action="/trainings/imports"' in response.text
    assert 'name="discipline" required' in response.text
    assert "Бег" in response.text
    assert "Велосипед" in response.text
    assert "Лыжи" in response.text
    assert 'form="training-details-form">К карте' in response.text


def test_race_result_import_page_has_race_date_field() -> None:
    with TestClient(app) as client:
        response = client.get("/race-results/import")

    assert response.status_code == 200
    assert 'name="race_date" type="date"' in response.text
    assert "Дата соревнования" in response.text


def test_training_import_requires_discipline() -> None:
    with TestClient(app) as client:
        missing = client.post(
            "/trainings/imports",
            data={"title": "No discipline", "date": "2026-04-29", "subject_user_id": fetch_user_id("polina")},
            follow_redirects=False,
        )
        invalid = client.post(
            "/trainings/imports",
            data={
                "title": "Bad discipline",
                "date": "2026-04-29",
                "discipline": "swim",
                "subject_user_id": fetch_user_id("polina"),
            },
            follow_redirects=False,
        )

    assert missing.status_code == 422
    assert invalid.status_code == 422


def test_error_reason_settings_page_renders_and_creates_reason() -> None:
    with TestClient(app) as client:
        page = client.get("/settings/error-reasons")
        create = client.post(
            "/settings/error-reasons",
            data={"label": "Проверочная причина"},
            follow_redirects=False,
        )
        after = client.get("/settings/error-reasons")

    assert page.status_code == 200
    assert "Причины ошибок" in page.text
    assert "Плохой выбор пути" in page.text
    assert create.status_code == 303
    assert create.headers["location"] == "/settings/error-reasons"
    assert "Проверочная причина" in after.text


def test_error_reason_settings_button_is_hidden_for_non_admin() -> None:
    with TestClient(app) as client:
        client.post("/login", data={"user_id": fetch_user_id("polina")}, follow_redirects=False)
        page = client.get("/")
        settings = client.get("/settings/error-reasons")

    assert page.status_code == 200
    assert "Настройки" not in page.text
    assert settings.status_code == 403


def test_user_settings_page_renders_and_crud_users() -> None:
    username = f"testuser_{uuid4().hex[:8]}"
    updated_username = f"{username}_2"
    display_name = "Тестовый Пользователь"
    updated_display_name = "Обновленный Пользователь"
    db_path = os.environ["ORIENTEERING_PORTAL_DB_PATH"]

    with TestClient(app) as client:
        page = client.get("/settings/users")
        create = client.post(
            "/settings/users",
            data={"username": username, "display_name": display_name},
            follow_redirects=False,
        )

        con = sqlite3.connect(db_path)
        try:
            con.row_factory = sqlite3.Row
            created_row = con.execute(
                "SELECT user_id FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        finally:
            con.close()
        assert created_row is not None
        user_id = created_row["user_id"]

        update = client.post(
            f"/settings/users/{user_id}",
            data={"username": updated_username, "display_name": updated_display_name},
            follow_redirects=False,
        )
        delete = client.post(f"/settings/users/{user_id}/delete", follow_redirects=False)

    con = sqlite3.connect(db_path)
    try:
        con.row_factory = sqlite3.Row
        deleted_row = con.execute(
            "SELECT user_id FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    finally:
        con.close()

    assert page.status_code == 200
    assert "Пользователи" in page.text
    assert "Евгений" in page.text
    assert create.status_code == 303
    assert create.headers["location"] == "/settings/users"
    assert update.status_code == 303
    assert delete.status_code == 303
    assert deleted_row is None


def test_user_settings_page_blocks_admin_delete_and_non_admin_access() -> None:
    admin_id = fetch_user_id("evgeny")

    with TestClient(app) as client:
        admin_page = client.get("/settings/users")
        admin_delete = client.post(f"/settings/users/{admin_id}/delete", follow_redirects=False)
        client.post("/login", data={"user_id": fetch_user_id("polina")}, follow_redirects=False)
        non_admin_page = client.get("/settings/users")

    assert admin_page.status_code == 200
    assert admin_delete.status_code == 403
    assert non_admin_page.status_code == 403


def test_split_error_review_api_saves_catalog_and_custom_reason() -> None:
    with TestClient(app) as client:
        reasons_response = client.get("/api/error-reasons")
        reason_id = reasons_response.json()["reasons"][0]["reason_id"]
        key = {
            "training_id": "training-1",
            "race_result_id": None,
            "split_label": "7",
            "from_control_label": "6",
            "to_control_label": "7",
        }
        save_catalog = client.put(
            "/api/split-error-review",
            json={**key, "reason_id": reason_id, "custom_reason": None},
        )
        loaded_catalog = client.post("/api/split-error-review/get", json=key)
        save_custom = client.put(
            "/api/split-error-review",
            json={**key, "reason_id": None, "custom_reason": "Свой выбор"},
        )
        loaded_custom = client.post("/api/split-error-review/get", json=key)

    assert reasons_response.status_code == 200
    assert save_catalog.status_code == 200
    assert loaded_catalog.json()["review"]["reason_id"] == reason_id
    assert save_custom.status_code == 200
    assert loaded_custom.json()["review"]["reason_id"] is None
    assert loaded_custom.json()["review"]["custom_reason"] == "Свой выбор"


def test_split_error_review_uses_training_split_as_identity() -> None:
    with TestClient(app) as client:
        reasons_response = client.get("/api/error-reasons")
        first_reason_id = reasons_response.json()["reasons"][0]["reason_id"]
        second_reason_id = reasons_response.json()["reasons"][1]["reason_id"]
        key = {
            "training_id": "identity-training",
            "split_label": "5",
            "from_control_label": "4",
            "to_control_label": "5",
        }
        first_save = client.put(
            "/api/split-error-review",
            json={**key, "race_result_id": None, "reason_id": first_reason_id, "custom_reason": None},
        )
        second_save = client.put(
            "/api/split-error-review",
            json={**key, "race_result_id": "race-result-actual", "reason_id": second_reason_id, "custom_reason": None},
        )
        loaded = client.post(
            "/api/split-error-review/get",
            json={**key, "race_result_id": None},
        )

    con = sqlite3.connect(os.environ["ORIENTEERING_PORTAL_DB_PATH"])
    try:
        count = con.execute(
            """
            SELECT COUNT(*)
            FROM split_error_reviews
            WHERE training_id = ?
              AND split_label = ?
              AND from_control_label = ?
              AND to_control_label = ?
            """,
            ("identity-training", "5", "4", "5"),
        ).fetchone()[0]
    finally:
        con.close()

    assert first_save.status_code == 200
    assert second_save.status_code == 200
    assert loaded.json()["review"]["reason_id"] == second_reason_id
    assert loaded.json()["review"]["race_result_id"] == "race-result-actual"
    assert count == 1


def test_training_import_form_creates_draft_and_redirects_to_map_step() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/trainings/imports",
            data={
                "title": "Лесная тренировка",
                "date": "2026-04-29",
                "training_type": "training",
                "discipline": "run",
                "location": "Парк",
                "notes": "Азимут и вход в КП",
                "subject_user_id": fetch_user_id("polina"),
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/trainings/imports/")
    assert response.headers["location"].endswith("/map")


def test_training_new_page_includes_relay_type_option() -> None:
    with TestClient(app) as client:
        response = client.get("/trainings/new")

    assert response.status_code == 200
    assert 'value="relay"' in response.text
    assert "Эстафета" in response.text


def test_import_map_page_shows_second_step_of_three() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={"title": "Map test", "date": "2026-04-29", "discipline": "run", "subject_user_id": fetch_user_id("polina")},
            follow_redirects=False,
        )
        response = client.get(create_response.headers["location"])

    assert response.status_code == 200
    assert "Шаг 2 из 3" in response.text
    assert 'data-mode="file">Файл' in response.text
    assert 'id="map-upload-form"' in response.text
    assert 'class="panel form-stack"' not in response.text
    assert f'href="{create_response.headers["location"].replace("/map", "/details")}">К деталям' in response.text
    assert f'href="{create_response.headers["location"].replace("/map", "/track")}">К загрузке трека' in response.text


def test_import_track_page_renders() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={"title": "Track test", "date": "2026-04-29", "discipline": "run", "subject_user_id": fetch_user_id("polina")},
            follow_redirects=False,
        )
        draft_id = create_response.headers["location"].split("/")[3]
        response = client.get(f"/trainings/imports/{draft_id}/track")

    assert response.status_code == 200
    assert "Шаг 3 из 3" in response.text
    assert 'class="shell wide track-shell"' in response.text
    assert f'href="/trainings/imports/{draft_id}/map">К карте' in response.text
    assert 'form="finish-import-form">Завершить импорт' in response.text
    assert "Загрузить GPX" in response.text
    assert "splits-table-body" not in response.text


def test_import_track_can_be_deleted_from_draft() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={"title": "Bad track", "date": "2026-04-29", "discipline": "run", "subject_user_id": fetch_user_id("polina")},
            follow_redirects=False,
        )
        draft_id = create_response.headers["location"].split("/")[3]
        client.post(
            f"/api/imports/{draft_id}/map-image",
            files={"file": ("map.png", b"fake-map", "image/png")},
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
        upload_response = client.post(
            f"/api/imports/{draft_id}/track-gpx",
            files={
                "file": (
                    "track.gpx",
                    b"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk><name>Test</name><trkseg>
    <trkpt lat="60.0" lon="30.0"><ele>10</ele><time>2026-04-29T10:00:00Z</time></trkpt>
    <trkpt lat="60.001" lon="30.001"><ele>11</ele><time>2026-04-29T10:00:05Z</time></trkpt>
  </trkseg></trk>
</gpx>""",
                    "application/gpx+xml",
                )
            },
        )
        before_delete = client.get(f"/trainings/imports/{draft_id}/track")
        delete_response = client.post(
            f"/trainings/imports/{draft_id}/track/delete",
            follow_redirects=False,
        )
        after_delete = client.get(f"/trainings/imports/{draft_id}/track")
        draft_api = client.get(f"/api/imports/{draft_id}")

    assert upload_response.status_code == 200
    assert upload_response.json()["point_count"] == 2
    assert before_delete.status_code == 200
    assert "Удалить трек" in before_delete.text
    assert delete_response.status_code == 303
    assert delete_response.headers["location"] == f"/trainings/imports/{draft_id}/track"
    assert after_delete.status_code == 200
    assert "Удалить трек" not in after_delete.text
    assert "track.gpx" not in after_delete.text
    assert draft_api.status_code == 200
    assert draft_api.json()["draft"]["track_points"] == []
    assert draft_api.json()["draft"]["track_gpx_filename"] is None


def test_import_track_points_can_save_split_markers_to_draft() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={"title": "Split markers", "date": "2026-04-29", "discipline": "run", "subject_user_id": fetch_user_id("polina")},
            follow_redirects=False,
        )
        draft_id = create_response.headers["location"].split("/")[3]
        save_response = client.post(
            f"/api/imports/{draft_id}/track-points",
            json={
                "track_points": [
                    {
                        "lat": 60.0,
                        "lon": 30.0,
                        "time": "2026-04-29T10:00:00Z",
                        "split_control_index": 1,
                        "split_control_label": "С",
                        "split_control_kind": "start",
                        "split_control_order": 0,
                    },
                    {
                        "lat": 60.001,
                        "lon": 30.001,
                        "time": "2026-04-29T10:00:05Z",
                        "split_control_index": 3,
                        "split_control_label": "Ф",
                        "split_control_kind": "finish",
                        "split_control_order": 1,
                    },
                ]
            },
        )
        draft_response = client.get(f"/api/imports/{draft_id}")

    assert save_response.status_code == 200
    assert save_response.json()["point_count"] == 2
    track_points = draft_response.json()["draft"]["track_points"]
    assert track_points[0]["split_control_label"] == "С"
    assert track_points[1]["split_control_order"] == 1


def test_finish_training_import_redirects_to_trainings() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={"title": "Finish test", "date": "2026-04-29", "discipline": "run", "subject_user_id": fetch_user_id("polina")},
            follow_redirects=False,
        )
        draft_id = create_response.headers["location"].split("/")[3]
        upload_response = client.post(
            f"/api/imports/{draft_id}/map-image",
            files={"file": ("map.png", b"not-a-real-image-but-ok-for-upload-test", "image/png")},
        )
        georef_response = client.post(
            f"/api/imports/{draft_id}/georef",
            json={
                "control_points": [
                    {"pixel_x": 0, "pixel_y": 0, "lat": 60.0, "lon": 30.0},
                    {"pixel_x": 1000, "pixel_y": 0, "lat": 60.0, "lon": 30.01},
                    {"pixel_x": 0, "pixel_y": 1000, "lat": 59.99, "lon": 30.0},
                ]
            },
        )
        response = client.post(
            f"/trainings/imports/{draft_id}/finish",
            follow_redirects=False,
        )
        list_response = client.get("/trainings")

    assert upload_response.status_code == 200
    assert georef_response.status_code == 200
    assert response.status_code == 303
    assert response.headers["location"] == "/trainings"
    assert "Finish test" in list_response.text
    training_id = re.search(r'href="/trainings/([0-9a-f]+)/race-result/import"', list_response.text)
    assert training_id is not None


def test_trainings_page_shows_clone_button_for_admin() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={"title": "Clone button test", "date": "2026-04-29", "discipline": "run", "subject_user_id": fetch_user_id("polina")},
            follow_redirects=False,
        )
        draft_id = create_response.headers["location"].split("/")[3]
        client.post(
            f"/api/imports/{draft_id}/map-image",
            files={"file": ("map.png", b"fake-map", "image/png")},
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
                    {"index": 1, "pixel_x": 100, "pixel_y": 100, "lat": 60.0, "lon": 30.0},
                    {"index": 2, "pixel_x": 200, "pixel_y": 200, "lat": 60.001, "lon": 30.001},
                ]
            },
        )
        finish_response = client.post(f"/trainings/imports/{draft_id}/finish", follow_redirects=False)
        list_response = client.get("/trainings")

    assert finish_response.status_code == 303
    assert list_response.status_code == 200
    assert "Клонировать" in list_response.text
    assert "/clone" in list_response.text


def test_trainings_page_shows_owner_for_admin_only() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={"title": "Owner label test", "date": "2026-04-29", "discipline": "run", "subject_user_id": fetch_user_id("polina")},
            follow_redirects=False,
        )
        draft_id = create_response.headers["location"].split("/")[3]
        client.post(
            f"/api/imports/{draft_id}/map-image",
            files={"file": ("map.png", b"fake-map", "image/png")},
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
                    {"index": 1, "pixel_x": 100, "pixel_y": 100, "lat": 60.0, "lon": 30.0},
                    {"index": 2, "pixel_x": 200, "pixel_y": 200, "lat": 60.001, "lon": 30.001},
                ]
            },
        )
        client.post(f"/trainings/imports/{draft_id}/finish", follow_redirects=False)

        admin_page = client.get("/trainings")
        client.post("/login", data={"user_id": fetch_user_id("polina")}, follow_redirects=False)
        non_admin_page = client.get("/trainings")

    assert admin_page.status_code == 200
    assert "· Полина" in admin_page.text
    assert non_admin_page.status_code == 200
    assert "· Полина" not in non_admin_page.text


def test_clone_training_creates_draft_without_track_and_opens_details() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={"title": "Clone source", "date": "2026-04-29", "discipline": "run", "subject_user_id": fetch_user_id("polina")},
            follow_redirects=False,
        )
        draft_id = create_response.headers["location"].split("/")[3]
        client.post(
            f"/api/imports/{draft_id}/map-image",
            files={"file": ("map.png", b"fake-map", "image/png")},
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
                    {"index": 1, "pixel_x": 100, "pixel_y": 100, "lat": 60.0, "lon": 30.0},
                    {"index": 2, "pixel_x": 200, "pixel_y": 200, "lat": 60.001, "lon": 30.001},
                ]
            },
        )
        client.post(f"/trainings/imports/{draft_id}/finish", follow_redirects=False)

        con = sqlite3.connect(os.environ["ORIENTEERING_PORTAL_DB_PATH"])
        try:
            con.row_factory = sqlite3.Row
            training_row = con.execute(
                "SELECT training_id FROM trainings WHERE title = ? ORDER BY created_at DESC",
                ("Clone source",),
            ).fetchone()
        finally:
            con.close()
        assert training_row is not None

        clone_response = client.get(f"/trainings/{training_row['training_id']}/clone", follow_redirects=False)
        assert clone_response.status_code == 303
        assert clone_response.headers["location"].endswith("/details")
        details_response = client.get(clone_response.headers["location"])

        draft_id = clone_response.headers["location"].split("/")[3]
        draft_response = client.get(f"/api/imports/{draft_id}")

    assert draft_response.status_code == 200
    assert details_response.status_code == 200
    assert "Видимость" in details_response.text
    draft = draft_response.json()["draft"]
    assert draft["edit_training_id"] is None
    assert draft["track_gpx_path"] is None
    assert draft["track_gpx_filename"] is None
    assert draft["track_points"] == []
    assert draft["map_image_path"] is not None
    assert draft["georef_transform"] is not None
    assert draft["course_controls"]
    assert draft["title"] == "Clone source"


def test_training_player_page_renders_after_import_finish() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={"title": "Player test", "date": "2026-04-29", "discipline": "run", "subject_user_id": fetch_user_id("polina")},
            follow_redirects=False,
        )
        draft_id = create_response.headers["location"].split("/")[3]
        client.post(
            f"/api/imports/{draft_id}/map-image",
            files={"file": ("map.png", b"fake-map", "image/png")},
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
        client.post(f"/trainings/imports/{draft_id}/finish", follow_redirects=False)
        list_response = client.get("/trainings")
        match = re.search(r'href="/trainings/([0-9a-f]+)/play"', list_response.text)
        assert match is not None
        training_id = match.group(1)
        response = client.get(f"/trainings/{training_id}/play")

    assert response.status_code == 200
    assert "player-workspace" in response.text
    assert "player.js" in response.text
    assert "split_analysis_dialog.js" in response.text
    assert "splits-table-body" in response.text
    assert "split-analysis-modal" in response.text
    assert "split-analysis-prev" in response.text
    assert "split-analysis-next" in response.text
    assert "split-review-reason" in response.text
    assert "split-review-custom" in response.text
    assert "split-orient-toggle" in response.text
    assert "split-debug-snapshot" in response.text
    assert "split-pace-chart" in response.text
    assert "Темп" in response.text


def test_training_can_be_deleted_from_listing() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={"title": "Disposable training", "date": "2026-04-29", "discipline": "run", "subject_user_id": fetch_user_id("polina")},
            follow_redirects=False,
        )
        draft_id = create_response.headers["location"].split("/")[3]
        client.post(
            f"/api/imports/{draft_id}/map-image",
            files={"file": ("map.png", b"fake-map", "image/png")},
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
        client.post(f"/trainings/imports/{draft_id}/finish", follow_redirects=False)
        listing_before = client.get("/trainings")
        match = re.search(r'/trainings/([0-9a-f]+)/race-result/import', listing_before.text)
        assert match is not None
        training_id = match.group(1)

        delete_response = client.post(
            f"/trainings/{training_id}/delete",
            follow_redirects=False,
        )
        listing_after = client.get("/trainings")
        play_after = client.get(f"/trainings/{training_id}/play")
        delete_missing = client.post(
            f"/trainings/{training_id}/delete",
            follow_redirects=False,
        )

    assert "Disposable training" in listing_before.text
    # Listing must show a delete form per training.
    assert f'action="/trainings/{training_id}/delete"' in listing_before.text
    assert delete_response.status_code == 303
    assert delete_response.headers["location"] == "/trainings"
    assert "Disposable training" not in listing_after.text
    assert play_after.status_code == 404
    # Second delete on a vanished training is a 404, not a silent 303.
    assert delete_missing.status_code == 404


def test_deleting_training_with_attached_race_result_keeps_result() -> None:
    with TestClient(app) as client:
        # Save a race result against a fresh training.
        from portal.routers import race_results
        from tests.test_race_protocol import SAMPLE_PROTOCOL

        original_fetch = race_results.fetch_race_protocol
        race_results.fetch_race_protocol = lambda _url: SAMPLE_PROTOCOL
        try:
            create_response = client.post(
                "/trainings/imports",
                data={"title": "Training with protocol", "date": "2026-04-29", "discipline": "run", "subject_user_id": fetch_user_id("polina")},
                follow_redirects=False,
            )
            draft_id = create_response.headers["location"].split("/")[3]
            client.post(
                f"/api/imports/{draft_id}/map-image",
                files={"file": ("map.png", b"fake-map", "image/png")},
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
            client.post(f"/trainings/imports/{draft_id}/finish", follow_redirects=False)
            listing = client.get("/trainings")
            training_id = re.search(r'/trainings/([0-9a-f]+)/race-result/import', listing.text).group(1)

            save = client.post(
                f"/trainings/{training_id}/race-result/import/save",
                data={
                    "url": "https://example.test/race/splits.html",
                    "group_name": "Ж14",
                    "self_row_index": "0",
                },
                follow_redirects=False,
            )
            race_result_id = save.headers["location"].split("/")[-1]

            delete_response = client.post(
                f"/trainings/{training_id}/delete",
                follow_redirects=False,
            )
            race_result_detail = client.get(f"/race-results/{race_result_id}")
        finally:
            race_results.fetch_race_protocol = original_fetch

    import sqlite3

    db_row = sqlite3.connect(os.environ["ORIENTEERING_PORTAL_DB_PATH"]).execute(
        "SELECT training_id FROM race_results WHERE race_result_id = ?",
        (race_result_id,),
    ).fetchone()

    assert delete_response.status_code == 303
    # The race result outlives the training — only its training_id is detached.
    assert race_result_detail.status_code == 200
    assert "Тестовый старт" in race_result_detail.text
    # Direct DB check: training_id must be NULL after detach (not the deleted id).
    assert db_row is not None
    assert db_row[0] is None


def test_training_edit_wizard_prefills_existing_training() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={
                "title": "Edit me",
                "date": "2026-04-29",
                "training_type": "race",
                "discipline": "bike",
                "location": "Forest",
                "notes": "Original notes",
                "subject_user_id": fetch_user_id("polina"),
            },
            follow_redirects=False,
        )
        draft_id = create_response.headers["location"].split("/")[3]
        client.post(
            f"/api/imports/{draft_id}/map-image",
            files={"file": ("map.png", b"fake-map", "image/png")},
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
        client.post(f"/trainings/imports/{draft_id}/finish", follow_redirects=False)
        list_response = client.get("/trainings")
        match = re.search(r'href="/trainings/([0-9a-f]+)/edit"', list_response.text)
        assert match is not None

        edit_response = client.get(f"/trainings/{match.group(1)}/edit", follow_redirects=False)
        edit_draft_id = edit_response.headers["location"].split("/")[3]
        details_response = client.get(edit_response.headers["location"])

    assert edit_response.status_code == 303
    assert edit_response.headers["location"].endswith("/details")
    assert details_response.status_code == 200
    assert f'action="/trainings/imports/{edit_draft_id}/details"' in details_response.text
    assert 'value="Edit me"' in details_response.text
    assert 'value="2026-04-29"' in details_response.text
    assert 'value="Forest"' in details_response.text
    assert ">Original notes</textarea>" in details_response.text


def test_training_edit_finish_updates_existing_training() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={"title": "Before edit", "date": "2026-04-29", "discipline": "run", "subject_user_id": fetch_user_id("polina")},
            follow_redirects=False,
        )
        draft_id = create_response.headers["location"].split("/")[3]
        client.post(
            f"/api/imports/{draft_id}/map-image",
            files={"file": ("map.png", b"fake-map", "image/png")},
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
        client.post(f"/trainings/imports/{draft_id}/finish", follow_redirects=False)
        list_response = client.get("/trainings")
        training_id = re.search(r'href="/trainings/([0-9a-f]+)/edit"', list_response.text).group(1)  # type: ignore[union-attr]

        edit_response = client.get(f"/trainings/{training_id}/edit", follow_redirects=False)
        edit_draft_id = edit_response.headers["location"].split("/")[3]
        client.post(
            f"/trainings/imports/{edit_draft_id}/details",
            data={
                "title": "After edit",
                "date": "2026-04-30",
                "training_type": "control",
                "discipline": "ski",
                "location": "Updated forest",
                "notes": "Updated notes",
            },
            follow_redirects=False,
        )
        client.post(
            f"/api/imports/{edit_draft_id}/course-controls",
            json={
                "controls": [
                    {"index": 1, "pixel_x": 0, "pixel_y": 0, "lat": 60.0, "lon": 30.0},
                    {"index": 2, "pixel_x": 10, "pixel_y": 10, "lat": 59.999, "lon": 30.001},
                    {"index": 3, "pixel_x": 20, "pixel_y": 20, "lat": 59.998, "lon": 30.002},
                    {"index": 4, "pixel_x": 30, "pixel_y": 30, "lat": 59.997, "lon": 30.003},
                ]
            },
        )
        finish_response = client.post(f"/trainings/imports/{edit_draft_id}/finish", follow_redirects=False)
        list_after = client.get("/trainings")
        player_response = client.get(f"/trainings/{training_id}/play")

    assert finish_response.status_code == 303
    assert list_after.text.count(f'/trainings/{training_id}/edit') == 1
    assert "After edit" in list_after.text
    assert "Before edit" not in list_after.text
    assert "Updated forest" in list_after.text
    assert player_response.status_code == 200


def test_save_training_track_points_updates_player_data() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={"title": "Trim save", "date": "2026-04-29", "discipline": "run", "subject_user_id": fetch_user_id("polina")},
            follow_redirects=False,
        )
        draft_id = create_response.headers["location"].split("/")[3]
        client.post(
            f"/api/imports/{draft_id}/map-image",
            files={"file": ("map.png", b"fake-map", "image/png")},
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
        client.post(f"/trainings/imports/{draft_id}/finish", follow_redirects=False)
        list_response = client.get("/trainings")
        training_id = re.search(r'href="/trainings/([0-9a-f]+)/play"', list_response.text).group(1)  # type: ignore[union-attr]

        save_response = client.post(
            f"/api/trainings/{training_id}/track-points",
            json={
                "track_points": [
                    {"lat": 60.0, "lon": 30.0, "ele": 10.0, "time": "2026-04-29T10:00:00Z"},
                    {"lat": 60.001, "lon": 30.001, "ele": 11.0, "time": "2026-04-29T10:00:05Z"},
                ]
            },
        )
        player_response = client.get(f"/trainings/{training_id}/play")

    assert save_response.status_code == 200
    assert save_response.json()["point_count"] == 2
    assert player_response.status_code == 200
    assert "60.001" in player_response.text
    assert "2026-04-29T10:00:05Z" in player_response.text
