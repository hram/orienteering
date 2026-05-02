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

LEGACY_PROTOCOL = """<!doctype html>
<meta content='text/html'; charset='utf-8' http-equiv='Content-Type'>
<h1>Снежная тропа. Кросс-спринт. Промежуточные времена</h1>
<h3>Данный протокол не является официальным документом</h3>
<h2>Ж10</h2>
<table class='rezult'>
<tr><th>№ п/п </th><th>Номер </th><th>Фамилия, Имя </th><th>Команда </th><th>Результат </th><th>Место </th><th>Отставание </th><th>#1 (54) </th><th>#2 (55) </th><th>#F(240) </th></tr>
<tr><td><nobr>1</td><td><nobr>3242</td><td class='cr'><nobr>Яковлева<br>Мария</td><td class='cr'><nobr>ДТ Пушкин</td><td><nobr>00:11:51</td><td><nobr>1</td><td><nobr></td><td><b><nobr>1:28(1)</b><br></td><td><b><nobr>3:24(1)</b><br>1:56(6)</td><td><b><nobr>11:51(1)</b><br>0:15(1)</td></tr>
<tr><td><nobr>2</td><td><nobr>3307</td><td class='cr'><nobr>Болдина<br>Мария</td><td class='cr'><nobr>ГБУ ДО СШ Экран дельта</td><td><nobr>00:12:39</td><td><nobr>2</td><td><nobr>+0:48</td><td><nobr>4:00(16)<br></td><td><nobr>5:35(10)<br>1:35(1)</td><td><nobr>12:39(2)</td></tr>
</table>
<h2>М10</h2>
<table class='rezult'>
<tr><th>№ п/п </th><th>Номер </th><th>Фамилия, Имя </th><th>Команда </th><th>Результат </th><th>Место </th><th>Отставание </th><th>#1 (31) </th><th>#F(240) </th></tr>
<tr><td><nobr>1</td><td><nobr>5001</td><td class='cr'><nobr>Иванов<br>Пётр</td><td class='cr'><nobr>Личное</td><td><nobr>00:09:10</td><td><nobr>1</td><td><nobr></td><td><nobr>1:05(1)<br></td><td><nobr>9:10(1)<br>0:14(1)</td></tr>
</table>"""


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


def test_parse_legacy_race_protocol_html() -> None:
    protocol = parse_race_protocol_html(LEGACY_PROTOCOL)

    assert protocol.event_name == "Снежная тропа. Кросс-спринт. Промежуточные времена"
    assert protocol.event_meta == "Данный протокол не является официальным документом"
    assert len(protocol.groups) == 2
    group = protocol.groups[0]
    assert group["name"] == "Ж10"
    assert group["controls"][0] == {
        "column_index": 7,
        "label": "1",
        "code": "54",
        "distance_meters": None,
    }
    participant = group["participants"][0]
    assert participant["name"] == "Яковлева Мария"
    assert participant["bib"] == "3242"
    assert participant["result"] == "00:11:51"
    assert participant["splits"][0]["cumulative"]["time"] == "1:28"
    assert participant["splits"][0]["split"]["seconds"] == 88
    assert participant["splits"][1]["split"]["seconds"] == 116
    assert participant["splits"][1]["split"]["rank"] == 6
    assert participant["splits"][1]["cumulative"]["time"] == "3:24"


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


def test_prepare_race_result_view_uses_first_cumulative_as_split_for_virtual_leader() -> None:
    from portal.routers.race_results import _prepare_race_result_view

    result = {
        "self_row_index": 0,
        "controls": [{}, {}, {}],
        "participants": [
            {
                "row_index": 0,
                "result": "00:07:00",
                "splits": [
                    {
                        "label": "1",
                        "cumulative": {"time": "2:00", "seconds": 120, "rank": 2},
                        "split": None,
                    },
                    {
                        "label": "2",
                        "cumulative": {"time": "4:30", "seconds": 270, "rank": 2},
                        "split": {"time": "2:30", "seconds": 150, "rank": 2},
                    },
                    {
                        "label": "F",
                        "cumulative": {"time": "7:00", "seconds": 420, "rank": 2},
                        "split": {"time": "2:30", "seconds": 150, "rank": 2},
                    },
                ],
            },
            {
                "row_index": 1,
                "result": "00:06:00",
                "splits": [
                    {
                        "label": "1",
                        "cumulative": {"time": "1:30", "seconds": 90, "rank": 1},
                        "split": None,
                    },
                    {
                        "label": "2",
                        "cumulative": {"time": "3:30", "seconds": 210, "rank": 1},
                        "split": {"time": "2:00", "seconds": 120, "rank": 1},
                    },
                    {
                        "label": "F",
                        "cumulative": {"time": "6:00", "seconds": 360, "rank": 1},
                        "split": {"time": "2:30", "seconds": 150, "rank": 1},
                    },
                ],
            },
        ],
    }

    _prepare_race_result_view(result)

    assert result["virtual_leader"] is not None
    assert result["virtual_leader"]["name"] == "Идеальный лидер"
    assert result["virtual_leader"]["splits"][0]["split"]["seconds"] == 90
    assert result["participants"][0]["splits"][0]["leader_gap_text"] == "+00:30"


def test_prepare_race_result_view_marks_relative_place_gaps() -> None:
    from portal.routers.race_results import _prepare_race_result_view

    result = {
        "self_row_index": 1,
        "participants": [
            {"row_index": 0, "result": "00:10:00", "splits": []},
            {"row_index": 1, "result": "00:10:10", "splits": []},
            {"row_index": 2, "result": "00:10:40", "splits": []},
        ],
    }

    _prepare_race_result_view(result)

    assert result["participants"][0]["relative_gap_text"] == "+00:10"
    assert result["participants"][0]["relative_gap_tone"] == "hot"
    assert result["participants"][1]["relative_gap_text"] == ""
    assert result["participants"][2]["relative_gap_text"] == "-00:30"
    assert result["participants"][2]["relative_gap_tone"] == "good"


def test_prepare_race_result_view_builds_reachability_chart() -> None:
    from portal.routers.race_results import _prepare_race_result_view

    result = {
        "self_row_index": 1,
        "participants": [
            {"row_index": 0, "place": "1", "name": "Лидер", "result": "00:10:00", "gap": "+00:30", "splits": []},
            {"row_index": 1, "place": "19", "name": "Я", "result": "00:10:30", "gap": "+01:10", "splits": []},
            {"row_index": 2, "place": "20", "name": "Ниже", "result": "00:11:20", "gap": "+02:00", "splits": []},
        ],
    }

    _prepare_race_result_view(result)

    chart = result["reachability_chart"]
    assert chart["self_name"] == "Я"
    assert chart["self_place"] == 19
    assert chart["self_gap_seconds"] == 70
    assert len(chart["points"]) == 2
    assert chart["points"][0]["x_seconds"] == 40
    assert chart["points"][1]["is_self"] is True
    assert all(point["place"] <= 19 for point in chart["points"])


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
        match = re.search(
            r"Race with protocol.*?/trainings/([0-9a-f]+)/race-result/import",
            trainings.text,
            re.S,
        )
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
        trainings_after_save = client.get("/trainings")

    assert preview.status_code == 200
    assert "Храмова Полина" in preview.text
    assert save.status_code == 303
    assert detail.status_code == 200
    assert "Тестовый старт" in detail.text
    assert "race-self-row" in detail.text
    assert f"/trainings/{training_id}/play" in detail.text
    assert "split-analysis-modal" in detail.text
    assert "split-view-modal" in detail.text
    assert "split_analysis_dialog.js" in detail.text
    assert "split_view_dialog.js" in detail.text
    assert "race_result.js" in detail.text
    assert "Анализ достижимости" in detail.text
    assert "reachability-modal" in detail.text
    assert "race_reachability_dialog.js" in detail.text
    assert 'data-split-label="1"' in detail.text
    assert "race-split-analysis-button" in detail.text
    assert "Просмотр" in detail.text
    assert "race-split-gap-hot" in detail.text
    assert "race-split-gap-warm" in detail.text
    assert "race-split-gap-good" in detail.text
    assert "+00:09" in detail.text
    assert re.search(r"Храмова\s+Полина", detail.text)
    assert "Ж14" in listing.text
    assert player.status_code == 200
    assert "split-problems-only" in player.text
    assert "Проблемы" in player.text
    assert f'/race-results/{save.headers["location"].split("/")[-1]}' in trainings_after_save.text
    assert f"/trainings/{training_id}/race-result/import" not in trainings_after_save.text


def test_race_result_can_be_deleted_from_listing(monkeypatch) -> None:
    from portal.routers import race_results

    monkeypatch.setattr(race_results, "fetch_race_protocol", lambda _url: SAMPLE_PROTOCOL)

    with TestClient(app) as client:
        preview = client.post(
            "/race-results/import/preview",
            data={"url": "https://example.test/splits.html"},
        )
        save = client.post(
            "/race-results/import/save",
            data={
                "url": "https://example.test/splits.html",
                "group_name": "Ж14",
                "self_row_index": "0",
            },
            follow_redirects=False,
        )
        race_result_id = save.headers["location"].split("/")[-1]
        listing_before = client.get("/race-results")
        delete_response = client.post(f"/race-results/{race_result_id}/delete", follow_redirects=False)
        listing_after = client.get("/race-results")
        detail_after = client.get(f"/race-results/{race_result_id}")

    assert preview.status_code == 200
    assert save.status_code == 303
    assert f"/race-results/{race_result_id}" in listing_before.text
    assert "Удалить" in listing_before.text
    assert delete_response.status_code == 303
    assert delete_response.headers["location"] == "/race-results"
    assert f"/race-results/{race_result_id}" not in listing_after.text
    assert detail_after.status_code == 404


def test_training_can_attach_previously_imported_race_result(monkeypatch) -> None:
    from portal.routers import race_results

    monkeypatch.setattr(race_results, "fetch_race_protocol", lambda _url: SAMPLE_PROTOCOL)

    with TestClient(app) as client:
        imported = client.post(
            "/race-results/import/save",
            data={
                "url": "https://example.test/splits.html",
                "group_name": "Ж14",
                "self_row_index": "0",
            },
            follow_redirects=False,
        )
        race_result_id = imported.headers["location"].split("/")[-1]

        create_response = client.post(
            "/trainings/imports",
            data={"title": "Attach protocol", "date": "2026-04-26"},
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
        training_match = re.search(r"/trainings/([0-9a-f]+)/race-result/import", trainings.text)
        assert training_match is not None
        training_id = training_match.group(1)

        import_page = client.get(f"/trainings/{training_id}/race-result/import")
        attach = client.post(
            f"/trainings/{training_id}/race-result/attach",
            data={"race_result_id": race_result_id},
            follow_redirects=False,
        )
        detail = client.get(f"/race-results/{race_result_id}")
        trainings_after_attach = client.get("/trainings")

    assert imported.status_code == 303
    assert import_page.status_code == 200
    assert "Ранее импортированные протоколы" in import_page.text
    assert "Тестовый старт" in import_page.text
    assert "Храмова Полина" in import_page.text
    assert "Привязать" in import_page.text
    assert attach.status_code == 303
    assert attach.headers["location"] == f"/race-results/{race_result_id}"
    assert detail.status_code == 200
    assert f"/trainings/{training_id}/play" in detail.text
    assert f'/race-results/{race_result_id}' in trainings_after_attach.text
    assert f"/trainings/{training_id}/race-result/import" not in trainings_after_attach.text


def test_legacy_race_protocol_import_flow(monkeypatch) -> None:
    from portal.routers import race_results

    monkeypatch.setattr(race_results, "fetch_race_protocol", lambda _url: LEGACY_PROTOCOL)

    with TestClient(app) as client:
        preview = client.post(
            "/race-results/import/preview",
            data={"url": "https://example.test/legacy-splits.htm"},
        )
        save = client.post(
            "/race-results/import/save",
            data={
                "url": "https://example.test/legacy-splits.htm",
                "group_name": "Ж10",
                "self_row_index": "1",
            },
            follow_redirects=False,
        )
        detail = client.get(save.headers["location"])

    assert preview.status_code == 200
    assert "Яковлева Мария" in preview.text
    assert "Болдина Мария" in preview.text
    assert save.status_code == 303
    assert detail.status_code == 200
    assert "Снежная тропа. Кросс-спринт. Промежуточные времена" in detail.text
    assert "Ж10" in detail.text
    assert re.search(r"Болдина\s+Мария", detail.text)
    assert "<nobr>" not in detail.text
