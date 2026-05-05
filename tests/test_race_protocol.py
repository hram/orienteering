from __future__ import annotations

import re

from fastapi.testclient import TestClient

from portal.main import app
from portal.services.race_protocol import detect_protocol_format, parse_race_protocol_html
from tests.conftest import fetch_user_id


SAMPLE_PROTOCOL = """<!doctype html>
<script>
const eventName = "Тестовый старт";
const eventMeta = "Черновой протокол";
const db = "Ж14| ||п/п|Фамилия, Имя|Номер|Результат|Место|Отст.|#1 (31)<br>100 m|#2 (32)<br>110 m|#3 (33)<br>120 m|#4 (34)<br>130 m|#5 (35)<br>140 m|#6 (36)<br>150 m|#7 (37)<br>160 m|#8 (38)<br>170 m|#F(240)||1|Храмова<br>Полина|1566|00:02:15|2|+0:45|0:19(2)<br>0:19(2)|0:37(2)<br>0:18(2)|0:54(2)<br>0:17(2)|1:10(2)<br>0:16(2)|1:25(2)<br>0:15(2)|1:39(2)<br>0:14(2)|1:52(2)<br>0:13(2)|2:04(2)<br>0:12(2)|2:15(2)<br>0:11(2)||2|Иванова<br>Анна|1501|00:01:30|1| |0:10(1)<br>0:10(1)|0:20(1)<br>0:10(1)|0:30(1)<br>0:10(1)|0:40(1)<br>0:10(1)|0:50(1)<br>0:10(1)|1:00(1)<br>0:10(1)|1:10(1)<br>0:10(1)|1:20(1)<br>0:10(1)|1:30(1)<br>0:10(1)|||М14| ||п/п|Фамилия, Имя|Номер|Результат|Место|Отст.|#1 (54)<br>149 m|#F(240)||1|Петров<br>Иван|201|00:10:00|1| |1:00(1)<br>1:00(1)|10:00(1)<br>0:25(1)|||";
</script>"""

SCORE_PROTOCOL = """<!doctype html>
<script>
const eventName = "100КП тест";
const eventMeta = "Не официальный";
const db = "ЖВ| ||п/п|Фамилия, Имя|Номер|Баллы|Штраф|Итог|Результат|Место|#1|#2|#3||1|Иванова<br>Анна|10|3| |3|00:50:00|1|5:00[55]<br>|10:00[60]<br>5:00|15:00[65]<br>5:00||2|Петрова<br>Мария|11|2| |2|00:55:00|2|4:00[55]<br>|11:00[70]<br>7:00| |||";
</script>"""

# Three participants who all run the same five legs through 31→32→33→34→35.
# Per-leg splits give Anna the "good" tier on legs where she's fastest or close,
# and "hot" tier on legs 2 and 4 where she loses by 2:00 to the leg leader —
# enough to populate the problem panel with two columns.
SCORE_PROTOCOL_PROBLEMS = """<!doctype html>
<script>
const eventName = "100КП проблемы";
const eventMeta = "Не официальный";
const db = "ЖВ| ||п/п|Фамилия, Имя|Номер|Баллы|Штраф|Итог|Результат|Место|#1|#2|#3|#4|#5||1|Иванова<br>Анна|10|5| |5|00:25:00|2|5:00[31]<br>|10:00[32]<br>5:00|15:00[33]<br>5:00|20:00[34]<br>5:00|25:00[35]<br>5:00||2|Петрова<br>Мария|11|5| |5|00:22:00|1|4:00[31]<br>|8:00[32]<br>4:00|14:00[33]<br>6:00|17:00[34]<br>3:00|22:00[35]<br>5:00||3|Сидорова<br>Ольга|12|5| |5|00:25:00|3|6:00[31]<br>|9:00[32]<br>3:00|16:00[33]<br>7:00|21:00[34]<br>5:00|25:00[35]<br>4:00|||";
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


def test_detect_protocol_format() -> None:
    assert detect_protocol_format(SAMPLE_PROTOCOL) == "js_course"
    assert detect_protocol_format(LEGACY_PROTOCOL) == "legacy_html"
    assert detect_protocol_format(SCORE_PROTOCOL) == "js_score"


def test_parse_score_race_protocol_html() -> None:
    protocol = parse_race_protocol_html(SCORE_PROTOCOL)

    assert protocol.kind == "score"
    assert protocol.event_name == "100КП тест"
    assert len(protocol.groups) == 1
    group = protocol.groups[0]
    assert group["name"] == "ЖВ"
    assert group["controls"] == []

    leader = group["participants"][0]
    assert leader["name"] == "Иванова Анна"
    assert leader["bib"] == "10"
    assert leader["points"] == "3"
    assert leader["penalty"] == ""
    assert leader["total_points"] == "3"
    assert leader["result"] == "00:50:00"
    assert leader["place"] == "1"

    assert len(leader["visits"]) == 3
    first_visit = leader["visits"][0]
    assert first_visit["order"] == 1
    assert first_visit["code"] == "55"
    assert first_visit["cumulative"]["seconds"] == 300
    # First visit's split mirrors cumulative — there's no prior leg.
    assert first_visit["split"]["seconds"] == 300
    second_visit = leader["visits"][1]
    assert second_visit["code"] == "60"
    assert second_visit["cumulative"]["seconds"] == 600
    assert second_visit["split"]["seconds"] == 300

    runner_up = group["participants"][1]
    # Trailing empty visit cells are skipped, not stored as None.
    assert len(runner_up["visits"]) == 2


def test_prepare_score_result_view_marks_best_legs_and_self_gap() -> None:
    from portal.routers.race_results import _prepare_score_result_view

    result = {
        "kind": "score",
        "self_row_index": 0,
        "participants": [
            {
                "row_index": 0,
                "name": "Я",
                "result": "00:10:00",
                "total_points": "2",
                "visits": [
                    {
                        "code": "55",
                        "cumulative": {"time": "5:00", "seconds": 300},
                        "split": {"time": "5:00", "seconds": 300},
                    },
                    {
                        "code": "60",
                        "cumulative": {"time": "10:00", "seconds": 600},
                        "split": {"time": "5:00", "seconds": 300},
                    },
                ],
            },
            {
                "row_index": 1,
                "name": "Соперница",
                "result": "00:08:00",
                "total_points": "2",
                "visits": [
                    {
                        "code": "55",
                        "cumulative": {"time": "4:00", "seconds": 240},
                        "split": {"time": "4:00", "seconds": 240},
                    },
                    {
                        "code": "70",
                        "cumulative": {"time": "8:00", "seconds": 480},
                        "split": {"time": "4:00", "seconds": 240},
                    },
                ],
            },
        ],
    }

    _prepare_score_result_view(result)

    me = result["participants"][0]
    rival = result["participants"][1]

    # Leg (start → 55): both ran it, rival faster — rival owns the green cell, I get the gap.
    assert rival["visits"][0]["is_best_leg"] is True
    assert me["visits"][0]["is_best_leg"] is False
    assert me["visits"][0]["leader_gap_text"] == "+01:00"

    # Leg (55 → 60): only I ran it — no comparison, no green, no gap line.
    assert me["visits"][1]["is_best_leg"] is False
    assert me["visits"][1]["leader_gap_text"] == ""

    # Rival's second leg (55 → 70) wasn't on my route — never marked.
    assert rival["visits"][1]["is_best_leg"] is False
    assert rival["visits"][1]["leader_gap_text"] == ""


def test_prepare_score_result_view_classifies_problem_legs() -> None:
    from portal.routers.race_results import _prepare_score_result_view

    # Anna's gaps to leg-best: leg1 +1:00, leg2 +2:00, leg3 0, leg4 +2:00, leg5 +1:00.
    # Sort asc by gap → [(2,0),(0,60),(4,60),(1,120),(3,120)]. Top-3 → good = {0,2,4}.
    # Remaining positives → hot = {1,3}, warm empty.
    result = {
        "kind": "score",
        "self_row_index": 0,
        "participants": [
            {
                "row_index": 0,
                "name": "Я",
                "result": "00:25:00",
                "total_points": "5",
                "visits": [
                    {"code": "31", "cumulative": {"time": "5:00", "seconds": 300}, "split": {"time": "5:00", "seconds": 300}},
                    {"code": "32", "cumulative": {"time": "10:00", "seconds": 600}, "split": {"time": "5:00", "seconds": 300}},
                    {"code": "33", "cumulative": {"time": "15:00", "seconds": 900}, "split": {"time": "5:00", "seconds": 300}},
                    {"code": "34", "cumulative": {"time": "20:00", "seconds": 1200}, "split": {"time": "5:00", "seconds": 300}},
                    {"code": "35", "cumulative": {"time": "25:00", "seconds": 1500}, "split": {"time": "5:00", "seconds": 300}},
                ],
            },
            {
                "row_index": 1,
                "name": "М",
                "result": "00:22:00",
                "total_points": "5",
                "visits": [
                    {"code": "31", "cumulative": {"time": "4:00", "seconds": 240}, "split": {"time": "4:00", "seconds": 240}},
                    {"code": "32", "cumulative": {"time": "8:00", "seconds": 480}, "split": {"time": "4:00", "seconds": 240}},
                    {"code": "33", "cumulative": {"time": "14:00", "seconds": 840}, "split": {"time": "6:00", "seconds": 360}},
                    {"code": "34", "cumulative": {"time": "17:00", "seconds": 1020}, "split": {"time": "3:00", "seconds": 180}},
                    {"code": "35", "cumulative": {"time": "22:00", "seconds": 1320}, "split": {"time": "5:00", "seconds": 300}},
                ],
            },
            {
                "row_index": 2,
                "name": "О",
                "result": "00:25:00",
                "total_points": "5",
                "visits": [
                    {"code": "31", "cumulative": {"time": "6:00", "seconds": 360}, "split": {"time": "6:00", "seconds": 360}},
                    {"code": "32", "cumulative": {"time": "9:00", "seconds": 540}, "split": {"time": "3:00", "seconds": 180}},
                    {"code": "33", "cumulative": {"time": "16:00", "seconds": 960}, "split": {"time": "7:00", "seconds": 420}},
                    {"code": "34", "cumulative": {"time": "21:00", "seconds": 1260}, "split": {"time": "5:00", "seconds": 300}},
                    {"code": "35", "cumulative": {"time": "25:00", "seconds": 1500}, "split": {"time": "4:00", "seconds": 240}},
                ],
            },
        ],
    }

    _prepare_score_result_view(result)

    assert result["problem_visit_indexes"] == [1, 3]
    me = result["participants"][0]
    tones = [visit["leader_gap_tone"] for visit in me["visits"]]
    assert tones == ["good", "hot", "good", "hot", "good"]

    # Best leg times: leg 2 (31→32) = Olya's 3:00; leg 4 (33→34) = Maria's 3:00.
    assert me["visits"][1]["best_leg_text"] == "03:00"
    assert me["visits"][3]["best_leg_text"] == "03:00"
    # Anna ran each problem leg in 5:00, leader did each in 3:00 → +04:00 total.
    assert result["self_problem_total_gap"] == "+04:00"


def test_score_protocol_problem_panel_renders(monkeypatch) -> None:
    from portal.routers import race_results

    monkeypatch.setattr(race_results, "fetch_race_protocol", lambda _url: SCORE_PROTOCOL_PROBLEMS)

    with TestClient(app) as client:
        client.post(
            "/race-results/import/preview",
            data={"url": "https://example.test/score-problems.html"},
        )
        save = client.post(
            "/race-results/import/save",
            data={
                "url": "https://example.test/score-problems.html",
                "group_name": "ЖВ",
                "self_row_index": "0",
            },
            follow_redirects=False,
        )
        detail = client.get(save.headers["location"])

    assert save.status_code == 303
    assert detail.status_code == 200
    # Toggle re-uses the existing #race-problem-toggle id so the same JS works.
    assert 'id="race-problem-toggle"' in detail.text
    assert "Только проблемы" in detail.text
    # Problem panel with the "Идеальный лидер" row appears.
    assert 'id="race-problem-panel"' in detail.text
    assert "Идеальный лидер" in detail.text
    # Best leg time on a problem leg (Olya's 3:00 on leg 31→32, Maria's 3:00 on 33→34).
    assert "03:00" in detail.text
    # Self problem total gap rendered (two +2:00 → +04:00).
    assert "+04:00" in detail.text


def test_score_protocol_import_flow(monkeypatch) -> None:
    from portal.routers import race_results

    monkeypatch.setattr(race_results, "fetch_race_protocol", lambda _url: SCORE_PROTOCOL)

    with TestClient(app) as client:
        preview = client.post(
            "/race-results/import/preview",
            data={"url": "https://example.test/score.html"},
        )
        save = client.post(
            "/race-results/import/save",
            data={
                "url": "https://example.test/score.html",
                "group_name": "ЖВ",
                "self_row_index": "0",
            },
            follow_redirects=False,
        )
        detail = client.get(save.headers["location"])

    assert preview.status_code == 200
    assert "100КП тест" in preview.text
    assert "Иванова Анна" in preview.text
    # Preview shows max-visit hint instead of "КП" for score group.
    assert "взятий" in preview.text
    assert save.status_code == 303
    assert detail.status_code == 200
    # Score-table specific markers — the third table type.
    assert "race-score-table" in detail.text
    assert "race-score-visit-cell" in detail.text
    # Score header columns — distinguishing the table type.
    assert "Очки" in detail.text
    assert "Штраф" in detail.text
    assert "Итог" in detail.text
    # KP code from the data must appear (visit cell content).
    assert "55" in detail.text
    # Course-only chrome must NOT leak into a score result.
    assert "Анализ достижимости" not in detail.text
    # Score-leg analysis: Maria wins leg (start → 55), so the green-best class
    # is rendered somewhere and self gets a +01:00 gap line on that visit.
    assert "race-best-split-cell" in detail.text
    assert "+01:00" in detail.text


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
            data={"title": "Race with protocol", "date": "2026-04-26", "subject_user_id": fetch_user_id("polina")},
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
            data={"title": "Attach protocol", "date": "2026-04-26", "subject_user_id": fetch_user_id("polina")},
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
