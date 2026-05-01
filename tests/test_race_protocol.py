from __future__ import annotations

import re

from fastapi.testclient import TestClient

from portal.main import app
from portal.services.race_protocol import parse_race_protocol_html


SAMPLE_PROTOCOL = """<!doctype html>
<script>
const eventName = "Тестовый старт";
const eventMeta = "Черновой протокол";
const db = "Ж14| ||п/п|Фамилия, Имя|Номер|Результат|Место|Отст.|#1 (58)<br>234 m|#2 (39)<br>301 m|#F(240)||1|Храмова<br>Полина|1566|00:21:00|4|+1:50|4:46(4)<br>4:46(4)|7:31(10)<br>2:45(16)|21:00(4)<br>0:36(15)||2|Иванова<br>Анна|1501|00:20:30|1| |4:30(1)<br>4:30(1)|7:00(1)<br>2:30(1)|20:30(1)<br>0:30(1)|||М14| ||п/п|Фамилия, Имя|Номер|Результат|Место|Отст.|#1 (54)<br>149 m|#F(240)||1|Петров<br>Иван|201|00:10:00|1| |1:00(1)<br>1:00(1)|10:00(1)<br>0:25(1)|||";
</script>"""


def test_parse_race_protocol_html() -> None:
    protocol = parse_race_protocol_html(SAMPLE_PROTOCOL)

    assert protocol.event_name == "Тестовый старт"
    assert len(protocol.groups) == 2
    group = protocol.groups[0]
    assert group["name"] == "Ж14"
    assert group["controls"][0] == {
        "column_index": 6,
        "label": "1",
        "code": "58",
        "distance_meters": 234,
    }
    participant = group["participants"][0]
    assert participant["name"] == "Храмова Полина"
    assert participant["splits"][1]["split"]["seconds"] == 165
    assert participant["splits"][1]["split"]["rank"] == 16


def test_race_protocol_import_flow(monkeypatch) -> None:
    from portal.routers import race_results

    monkeypatch.setattr(race_results, "fetch_race_protocol", lambda _url: SAMPLE_PROTOCOL)

    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={"title": "Race with protocol", "date": "2026-04-26"},
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
        trainings = client.get("/trainings")
        match = re.search(r"/trainings/([0-9a-f]+)/race-result/import", trainings.text)
        assert match is not None
        training_id = match.group(1)
        assert f"/trainings/{training_id}/race-result/import" in trainings.text

        preview = client.post(
            f"/trainings/{training_id}/race-result/import/preview",
            data={"url": "https://example.test/splits.html"},
        )
        save = client.post(
            f"/trainings/{training_id}/race-result/import/save",
            data={
                "url": "https://example.test/splits.html",
                "group_name": "Ж14",
                "self_row_index": "0",
            },
            follow_redirects=False,
        )
        assert save.headers["location"].startswith("/race-results/")
        detail = client.get(save.headers["location"])
        listing = client.get("/race-results")

    assert preview.status_code == 200
    assert "Храмова Полина" in preview.text
    assert save.status_code == 303
    assert detail.status_code == 200
    assert "Тестовый старт" in detail.text
    assert "race-self-row" in detail.text
    assert f"/trainings/{training_id}/play" in detail.text
    assert "split-analysis-modal" in detail.text
    assert "split_analysis_dialog.js" in detail.text
    assert "race_result.js" in detail.text
    assert 'data-split-label="1"' in detail.text
    assert "race-split-analysis-button" in detail.text
    assert re.search(r"Храмова\s+Полина", detail.text)
    assert "Ж14" in listing.text
