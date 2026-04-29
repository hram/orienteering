from __future__ import annotations

import pytest

from portal.services.gpx import parse_gpx_track_points


def test_parse_gpx_track_points() -> None:
    content = b"""<?xml version="1.0" encoding="UTF-8"?>
    <gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
      <trk>
        <trkseg>
          <trkpt lat="59.1" lon="30.1"><ele>12.5</ele><time>2026-04-29T10:00:00Z</time></trkpt>
          <trkpt lat="59.2" lon="30.2"><time>2026-04-29T10:00:05Z</time></trkpt>
        </trkseg>
      </trk>
    </gpx>
    """

    points = parse_gpx_track_points(content)

    assert len(points) == 2
    assert points[0].lat == pytest.approx(59.1)
    assert points[0].lon == pytest.approx(30.1)
    assert points[0].ele == pytest.approx(12.5)
    assert points[0].time == "2026-04-29T10:00:00Z"


def test_parse_gpx_track_points_rejects_empty_track() -> None:
    with pytest.raises(ValueError, match="does not contain track points"):
        parse_gpx_track_points(b"<gpx></gpx>")
