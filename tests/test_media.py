from __future__ import annotations

import pytest

from portal.infrastructure import config, media


@pytest.fixture
def prod_upload_dir(monkeypatch):
    # Mirror the deployed container layout.
    monkeypatch.setattr(config, "UPLOAD_DIR", "/data/orienteering/uploads")


def test_none_returns_none(prod_upload_dir):
    assert media.map_image_url(None) is None
    assert media.map_image_url("") is None


def test_absolute_path_under_upload_dir(prod_upload_dir):
    path = "/data/orienteering/uploads/imports/abc/map.jpg"
    assert media.map_image_url(path) == "/uploads/imports/abc/map.jpg"


def test_relative_migrated_path_resolves_via_uploads_tail(prod_upload_dir):
    # Paths created on the dev machine are stored relative to the project root
    # and would otherwise resolve against the container CWD (/app).
    path = "data/uploads/imports/abc/map.jpg"
    assert media.map_image_url(path) == "/uploads/imports/abc/map.jpg"


def test_foreign_absolute_path_with_uploads_segment(prod_upload_dir):
    path = "/home/hram/projects/orienteering/data/uploads/imports/abc/map.png"
    assert media.map_image_url(path) == "/uploads/imports/abc/map.png"


def test_race_result_training_view_model_uses_shared_media_url(prod_upload_dir):
    from portal.routers.race_results import _training_view_model

    training = {"map_image_path": "data/uploads/imports/abc/map.jpg"}

    assert _training_view_model(training)["map_image_url"] == "/uploads/imports/abc/map.jpg"


def test_dashboard_training_payload_exposes_map_layers(prod_upload_dir):
    from portal.main import _dashboard_training_payload

    result = {
        "training_id": "training-1",
        "training_type": "race",
        "map_image_path": "data/uploads/imports/abc/map-1.jpg",
        "georef_transform": {"lon_a": 1},
        "training_course_controls": [],
        "training_track_points": [],
        "training_map_layers": [
            {
                "id": "map-1",
                "title": "Карта 1",
                "image_path": "data/uploads/imports/abc/map-1.jpg",
                "georef_transform": {"lon_a": 1},
                "course_controls": [{"label": "С", "map_layer_id": "map-1"}],
            },
            {
                "id": "map-2",
                "title": "Карта 2",
                "image_path": "data/uploads/imports/abc/map-2.jpg",
                "georef_transform": {"lon_a": 2},
                "course_controls": [{"label": "10", "map_layer_id": "map-2"}],
            },
        ],
    }

    payload = _dashboard_training_payload(result)

    assert payload["map_image_url"] == "/uploads/imports/abc/map-1.jpg"
    assert [layer["map_image_url"] for layer in payload["map_layers"]] == [
        "/uploads/imports/abc/map-1.jpg",
        "/uploads/imports/abc/map-2.jpg",
    ]
    assert payload["map_layers"][1]["course_controls"][0]["map_layer_id"] == "map-2"


def test_path_without_uploads_segment_returns_none(prod_upload_dir):
    assert media.map_image_url("/some/other/place/map.jpg") is None
