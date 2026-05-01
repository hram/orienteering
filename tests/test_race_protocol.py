from __future__ import annotations

import re

from fastapi.testclient import TestClient

from portal.main import app
from portal.services.race_protocol import parse_race_protocol_html


SAMPLE_PROTOCOL = """<!doctype html>
<script>
const eventName = "Тестовый старт";
const eventMeta = "Черновой протокол";
const db = "Ж14| ||п/п|Фамилия, Имя|Номер|Результат|Место|Отст.|#1 (31)<br>100 m|#2 (32)<br>110 m|#3 (33)<br>120 m|#4 (34)<br>130 m|#5 (35)<br>140 m|#6 (36)<br>150 m|#7 (37)<br>160 m|#8 (38)<br>170 m|#F(240)||1|Храмова<br>Полина|1566|00:02:15|2|+0:45|0:19(2)<br>0:19(2)|0:37(2)<br>0:18(2)|0:54(2)<br>0:17(2)|1:10(2)<br>0:16(2)|1:25(2)<br>0:15(2)|1:39(2)<br>0:14(2)|1:52(2)<br>0:13(2)|2:04(2)<br>0:12(2)|2:15(2)<br>0:11(2)||2|Иванова<br>Анна|1501|00:01:30|1| |0:10(1)<br>0:10(1)|0:20(1)<br>0:10(1)|0:30(1)<br>0:10(1)|0:40(1)<br>0:10(1)|0:50(1)<br>0:10(1)|1:00(1)<br>0:10(1)|1:10(1)<br>0:10(1)|1:20(1)<br>0:10(1)|1:30(1)<br>0:10(1)|||М14| ||п/п|Фамилия, Имя|Номер|Результат|Место|Отст.|#1 (54)<br>149 m|#F(240)||1|Петров<br>Иван|201|00:10:00|1| |1:00(1)<br>1:00(1)|10:00(1)<br>0:25(1)|||";
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
        "code": "31",
        "distance_meters": 100,
    }
    participant = group["participants"][0]
    assert participant["name"] == "Храмова Полина"
    assert participant["splits"][1]["split"]["seconds"] == 18
    assert participant["splits"][1]["split"]["rank"] == 2


def test_prepare_race_result_view_marks_top_gap_tiers() -> None:
    from portal.routers.race_results import _prepare_race_result_view

    result = {
        "self_row_index": 0,
        "participants": [
            {
                "row_index": 0,
                "result": "00:10:00",
                "splits": [
                    {"split": {"seconds": 30}},
                    {"split": {"seconds": 28}},
                    {"split": {"seconds": 26}},
                    {"split": {"seconds": 24}},
                    {"split": {"seconds": 22}},
                    {"split": {"seconds": 20}},
                    {"split": {"seconds": 18}},
                    {"split": {"seconds": 16}},
                    {"split": {"seconds": 14}},
                ],
            },
            {
                "row_index": 1,
                "result": "00:09:00",
                "splits": [
                    {"split": {"seconds": 10}},
                    {"split": {"seconds": 10}},
                    {"split": {"seconds": 10}},
                    {"split": {"seconds": 10}},
                    {"split": {"seconds": 10}},
                    {"split": {"seconds": 10}},
                    {"split": {"seconds": 10}},
                    {"split": {"seconds": 10}},
                    {"split": {"seconds": 10}},
                ],
            },
        ],
    }

    _prepare_race_result_view(result)

    tones = [split["leader_gap_tone"] for split in result["participants"][0]["splits"]]
    assert tones == ["hot", "hot", "hot", "warm", "warm", "warm", "good", "good", "good"]


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
        player = client.get(f"/trainings/{training_id}/play")
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
    assert "race-split-gap-hot" in detail.text
    assert "race-split-gap-warm" in detail.text
    assert "race-split-gap-good" in detail.text
    assert "+00:09" in detail.text
    assert re.search(r"Храмова\s+Полина", detail.text)
    assert "Ж14" in listing.text
    assert player.status_code == 200
    assert "split-problems-only" in player.text
    assert "Проблемы" in player.text
