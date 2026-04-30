from __future__ import annotations

import re

from fastapi.testclient import TestClient

from portal.main import app


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


def test_training_import_form_creates_draft_and_redirects_to_map_step() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/trainings/imports",
            data={
                "title": "Лесная тренировка",
                "date": "2026-04-29",
                "training_type": "training",
                "location": "Парк",
                "notes": "Азимут и вход в КП",
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/trainings/imports/")
    assert response.headers["location"].endswith("/map")


def test_import_track_page_renders() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={"title": "Track test", "date": "2026-04-29"},
            follow_redirects=False,
        )
        draft_id = create_response.headers["location"].split("/")[3]
        response = client.get(f"/trainings/imports/{draft_id}/track")

    assert response.status_code == 200
    assert "Загрузить GPX" in response.text
    assert "splits-table-body" not in response.text


def test_finish_training_import_redirects_to_trainings() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={"title": "Finish test", "date": "2026-04-29"},
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


def test_training_player_page_renders_after_import_finish() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={"title": "Player test", "date": "2026-04-29"},
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
    assert "splits-table-body" in response.text
    assert "Темп" in response.text


def test_training_edit_wizard_prefills_existing_training() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={
                "title": "Edit me",
                "date": "2026-04-29",
                "training_type": "race",
                "location": "Forest",
                "notes": "Original notes",
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
            data={"title": "Before edit", "date": "2026-04-29"},
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
            data={"title": "Trim save", "date": "2026-04-29"},
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
