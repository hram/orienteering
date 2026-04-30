from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for JS split tests")
def test_championship_splits_regression() -> None:
    actual, expected = calculate_fixture_splits("championship_splits.json")

    assert actual["count"] == expected["split_count"]
    assert [row["label"] for row in actual["rows"]] == expected["labels"]
    assert actual["rows"][0] == expected["first_split"]
    assert next(row for row in actual["rows"] if row["label"] == "14") == expected["split_14"]
    assert actual["rows"][-1] == expected["last_split"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for JS split tests")
def test_kislovodsk_late_started_track_splits_regression() -> None:
    actual, expected = calculate_fixture_splits("kislovodsk_splits.json")

    assert actual["count"] == 14
    assert actual["count"] == expected["split_count"]
    assert [row["label"] for row in actual["rows"]] == expected["labels"]
    assert actual["rows"] == expected["rows"]


def calculate_fixture_splits(fixture_name: str) -> tuple[dict, dict]:
    fixture_path = ROOT_DIR / "tests" / "fixtures" / fixture_name
    script = """
const fs = require("node:fs");
const splits = require("./static/splits.js");
const fixture = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const controls = splits.normalizeCourseControls(fixture.course_controls);
const track = fixture.track_points.map((point, index) => ({
  ...point,
  seconds: splits.parsePointSeconds(point, index),
}));
const rows = splits.calculateSplits(controls, track);
const compact = rows.map((row) => ({
  label: row.label,
  absolute_seconds: Math.round(row.absoluteSeconds),
  split_seconds: Math.round(row.splitSeconds),
  distance_meters: Math.round(row.distanceMeters),
  pace_seconds_per_meter: Number(row.paceSecondsPerMeter.toFixed(2)),
  from: row.fromControl.label,
  via: row.viaControls.map((control) => control.label),
  to: row.toControl.label,
  from_track_index: row.fromTrackIndex,
  to_track_index: row.toTrackIndex,
}));
console.log(JSON.stringify({count: rows.length, rows: compact}));
"""

    result = subprocess.run(
        ["node", "-e", script, str(fixture_path)],
        cwd=ROOT_DIR,
        check=True,
        text=True,
        capture_output=True,
    )
    actual = json.loads(result.stdout)
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))["expected"]
    return actual, expected
