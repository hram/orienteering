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


def test_path_without_uploads_segment_returns_none(prod_upload_dir):
    assert media.map_image_url("/some/other/place/map.jpg") is None
