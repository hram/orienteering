from __future__ import annotations

import asyncio
import json
import re

from fastapi.testclient import TestClient

from portal.main import app
from portal.services.race_protocol import detect_protocol_format, parse_pdf_race_protocol, parse_race_protocol_html
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

RELAY_TWO_PERSON_PROTOCOL = """<!doctype html>
<script>
const eventName = "Кубок города. Эстафета";
const eventMeta = "Промежуточные времена";
const db = "Ж14| ||п/п|Фамилия, Имя|Номер|Результат|Место|Отст.|#1|#2|#3|#4|#F(240)||1|Аскарова<br>Екатерина|161.1|00:17:30|1| |2:40[40]<br>|4:06[34]<br>1:26|5:07[35]<br>1:01|6:10[37]<br>1:03|17:30<br>0:19||2|Марченко<br>Полина|165.1|00:18:42|4|+1:12|2:13[40]<br>|3:34[34]<br>1:21|4:31[36]<br>0:57|5:27[37]<br>0:56|18:42<br>0:24|||";
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

LEGACY_PROTOCOL_WITHOUT_TEAM = """<!doctype html>
<meta content='text/html'; charset='utf-8' http-equiv='Content-Type'>
<h1>День Победы. Промежуточные времена</h1>
<h3>Данный протокол не является официальным документом</h3>
<h2>Ж14</h2>
<table class='rezult'>
<tr><th>№ п/п </th><th>Номер </th><th>Фамилия, Имя </th><th>Результат </th><th>Место </th><th>Отставание </th><th>#1 (47) </th><th>#F(240) </th></tr>
<tr><td><nobr>1</td><td><nobr>169</td><td class='cr'><nobr>БАЗИЛЬ<br>ЕВА</td><td><nobr>00:34:36</td><td><nobr>1</td><td><nobr></td><td><nobr>1:30(3)<br></td><td><nobr>34:36(1)<br>0:30(1)</td></tr>
<tr><td><nobr>2</td><td><nobr>155</td><td class='cr'><nobr>НОВОКШЕНОВА<br>МАРИЯ</td><td><nobr>00:35:50</td><td><nobr>2</td><td><nobr>+1:14</td><td><nobr>1:25(2)<br></td><td><nobr>35:50(2)<br>0:40(2)</td></tr>
</table>"""

PDF_PROTOCOL_TEXT = """Чемпионат и Первенство Санкт-Петербурга по спортивному ориентированию10.05.2026 Ленинградская обл., п.ПоляныПРОТОКОЛ РЕЗУЛЬТАТОВ
Ж14, 9 КП, 2.6 км
№ Фамилия, имя Коллектив ГР Разряд Номер Результат Отставание Место 31 34 35 38 40 46 47 48 50 F
1 КАРПОВА АЛЕКСАНДРА ДЮНЫ-Сестрорецк, ГорСЮТур 2012 I 181 00:14:23 1 00:01:00 (2)00:01:00 (2) 00:01:05 (1)00:02:05 (1) 00:01:41 (1)00:03:46 (1) 00:01:04 (2)00:04:50 (1) 00:01:27 (1)00:06:17 (1) 00:04:28 (1)00:10:45 (1) 00:01:19 (1)00:12:04 (1) 00:01:05 (2)00:13:09 (1) 00:01:06 (1)00:14:15 (1) 00:00:0800:14:23 (1)
2 МАРЧЕНКО ПОЛИНА Сестрорецк ас 2013 I 176 00:20:22 00:05:59 2 00:00:59 (1)00:00:59 (1) 00:04:55 (9)00:05:54 (8) 00:01:53 (2)00:07:47 (5) 00:01:01 (1)00:08:48 (3) 00:01:56 (2)00:10:44 (3) 00:05:08 (2)00:15:52 (2) 00:01:19 (1)00:17:11 (2) 00:01:02 (1)00:18:13 (2) 00:01:59 (9)00:20:12 (2) 00:00:1000:20:22 (2)
Фитнес2, 9 КП, 2.6 км
№ Фамилия, имя Коллектив ГР Разряд Номер Результат Отставание Место 31 34 35 38 40 46 47 48 50 F
1 ЛЕКОНЦЕВ АЛЕКСАНДР ДЮНЫ-Сестрорецк, ГорСЮТур 1989 б/р 343 00:25:58 1 00:01:53 (1)00:01:53 (1) 00:02:05 (1)00:03:58 (1) 00:04:54 (1)00:08:52 (1) 00:02:25 (1)00:11:17 (1) 00:02:34 (1)00:13:51 (1) 00:06:25 (1)00:20:16 (1) 00:01:34 (1)00:21:50 (1) 00:01:33 (1)00:23:23 (1) 00:02:22 (1)00:25:45 (1) 00:00:1200:25:58 (1)
"""

ORGEO_INFO_HTML = """<!doctype html>
<html><head>
<meta itemprop="name" content="Кубок Белых Ночей 11 этап">
<meta itemprop="description" content="16.05.2026 состоится событие Кубок Белых Ночей 11 этап.">
</head><body></body></html>
"""

ORGEO_EXPORT_JSON = json.dumps(
    {
        "event_id": "52808",
        "sub_id": "1",
        "has_score": False,
        "finish": [
            {
                "group_name": "ЖС",
                "bib": "30",
                "name": "Гусак Алла",
                "team": "Белые Ночи - Гусаки",
                "start": "12:16:33",
                "finish": "00:42:08",
                "place": 1,
                "diff": "+00:00",
                "spl": "00:02:05|31|00:03:29|32|",
                "spl_comment": "10:47/km|31|15:45/km|32|",
            },
            {
                "group_name": "ЖС",
                "bib": "96",
                "name": "Семешкина Мария",
                "team": "WHITE WOLVES",
                "start": "12:00:12",
                "finish": "00:51:20",
                "place": 2,
                "diff": "+09:12",
                "spl": "00:02:06|31|00:03:26|32|",
                "spl_comment": "10:52/km|31|15:32/km|32|",
            },
            {
                "group_name": "ЖС",
                "bib": "155",
                "name": "Храмова Полина",
                "team": "ДТ Пушкин",
                "start": "12:18:00",
                "finish": "00:54:10",
                "place": 9,
                "diff": "+12:02",
                "spl": "00:02:30|31|00:04:00|32|",
                "spl_comment": "12:00/km|31|16:00/km|32|",
            },
            {
                "group_name": "ЖВ",
                "bib": "10",
                "name": "Иванова Анна",
                "team": "Команда",
                "start": "12:10:00",
                "finish": "00:40:00",
                "place": 1,
                "diff": "+00:00",
                "spl": "00:01:50|31|00:02:30|32|",
                "spl_comment": "11:00/km|31|14:00/km|32|",
            },
        ],
    },
    ensure_ascii=False,
)

ORGEO_LIVE_JSON = json.dumps(
    {
        "event_id": "52808",
        "sub_id": "1",
        "finish": [
            {
                "dist": "ЖС",
                "number": "30",
                "name": "Гусак Алла",
                "team": "Белые Ночи - Гусаки",
                "start": "12:16:33",
                "finish": "00:42:08",
                "place": 1,
                "diff": "+00:00",
                "spl": "00:02:05|31|00:03:29|32|",
                "spl_comment": "10:47/km|31|15:45/km|32|",
            },
            {
                "dist": "ЖС",
                "number": "96",
                "name": "Семешкина Мария",
                "team": "WHITE WOLVES",
                "start": "12:00:12",
                "finish": "00:51:20",
                "place": 2,
                "diff": "+09:12",
                "spl": "00:02:06|31|00:03:26|32|",
                "spl_comment": "10:52/km|31|15:32/km|32|",
            },
            {
                "dist": "ЖС",
                "number": "155",
                "name": "Храмова Полина",
                "team": "ДТ Пушкин",
                "start": "12:18:00",
                "finish": "00:54:10",
                "place": 9,
                "diff": "+12:02",
                "spl": "00:02:30|31|00:04:00|32|",
                "spl_comment": "12:00/km|31|16:00/km|32|",
            },
            {
                "dist": "ЖВ",
                "number": "10",
                "name": "Иванова Анна",
                "team": "Команда",
                "start": "12:10:00",
                "finish": "00:40:00",
                "place": 1,
                "diff": "+00:00",
                "spl": "00:01:50|31|00:02:30|32|",
                "spl_comment": "11:00/km|31|14:00/km|32|",
            },
        ],
    },
    ensure_ascii=False,
)

ORGEO_RELAY_INFO_HTML = """<!doctype html>
<html><head>
<meta itemprop="name" content="Relay test">
<meta itemprop="description" content="Relay test">
</head><body></body></html>
"""

ORGEO_RELAY_EXPORT_JSON = json.dumps(
    {
        "101.1": {
            "group_name": "Ж14",
            "bib": "101.1",
            "name": "Зекова Анастасия",
            "team": "Команда А",
            "lap": "1",
            "place": 1,
            "finish": "00:10:00",
            "spl": "00:02:00|31|00:03:00|32|",
            "spl_comment": "10:00/km|31|10:00/km|32|",
        },
        "102.1": {
            "group_name": "Ж14",
            "bib": "102.1",
            "name": "Иванова Анна",
            "team": "Команда А",
            "lap": "1",
            "place": 2,
            "finish": "00:11:00",
            "spl": "00:02:10|31|00:03:10|32|",
            "spl_comment": "10:30/km|31|10:30/km|32|",
        },
        "201.2": {
            "group_name": "Ж14",
            "bib": "201.2",
            "name": "Храмова Полина",
            "team": "Команда Б",
            "lap": "2",
            "place": 3,
            "finish": "00:12:00",
            "spl": "00:02:20|31|00:03:20|32|",
            "spl_comment": "11:00/km|31|11:00/km|32|",
        },
        "202.2": {
            "group_name": "Ж14",
            "bib": "202.2",
            "name": "Доронина Полина",
            "team": "Команда Б",
            "lap": "2",
            "place": 4,
            "finish": "00:13:00",
            "spl": "00:02:30|31|00:03:30|32|",
            "spl_comment": "11:30/km|31|11:30/km|32|",
        },
    },
    ensure_ascii=False,
)

ORGEO_RELAY_LIVE_JSON = json.dumps(
    {
        "event_id": "53000",
        "sub_id": "1",
        "is_relay": True,
        "has_score": False,
        "dist": "Ж14",
        "finish": [
            {
                "dist": "Ж14",
                "number": "101.1",
                "name": "Зекова Анастасия",
                "team": "Команда А",
                "lap": "1",
                "place": 1,
                "diff": "+00:00",
                "spl": "00:02:00|31|00:03:00|32|",
                "spl_comment": "10:00/km|31|10:00/km|32|",
            },
            {
                "dist": "Ж14",
                "number": "102.1",
                "name": "Иванова Анна",
                "team": "Команда А",
                "lap": "1",
                "place": 2,
                "diff": "+01:00",
                "spl": "00:02:10|31|00:03:10|32|",
                "spl_comment": "10:30/km|31|10:30/km|32|",
            },
            {
                "dist": "Ж14",
                "number": "201.2",
                "name": "Храмова Полина",
                "team": "Команда Б",
                "lap": "2",
                "place": 3,
                "diff": "+02:00",
                "spl": "00:02:20|31|00:03:20|32|",
                "spl_comment": "11:00/km|31|11:00/km|32|",
            },
            {
                "dist": "Ж14",
                "number": "202.2",
                "name": "Доронина Полина",
                "team": "Команда Б",
                "lap": "2",
                "place": 4,
                "diff": "+03:00",
                "spl": "00:02:30|31|00:03:30|32|",
                "spl_comment": "11:30/km|31|11:30/km|32|",
            },
        ],
    },
    ensure_ascii=False,
)


def test_detect_protocol_format() -> None:
    assert detect_protocol_format(SAMPLE_PROTOCOL) == "js_course"
    assert detect_protocol_format(LEGACY_PROTOCOL) == "legacy_html"
    assert detect_protocol_format(SCORE_PROTOCOL) == "js_score"
    assert detect_protocol_format(PDF_PROTOCOL_TEXT) == "pdf_text"


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


def test_parse_two_person_relay_protocol_with_codes_in_split_cells() -> None:
    protocol = parse_race_protocol_html(RELAY_TWO_PERSON_PROTOCOL)

    assert protocol.kind == "course"
    assert protocol.event_name == "Кубок города. Эстафета"
    group = protocol.groups[0]
    assert group["name"] == "Ж14"
    assert [control["label"] for control in group["controls"]] == ["1", "2", "3", "4", "F"]
    assert [control["code"] for control in group["controls"]] == ["", "", "", "", "240"]

    leader = group["participants"][0]
    assert leader["name"] == "Аскарова Екатерина"
    assert leader["bib"] == "161.1"
    assert leader["lap"] == "1"
    assert len(leader["splits"]) == 5
    assert leader["splits"][0]["code"] == "40"
    assert leader["splits"][0]["cumulative"]["seconds"] == 160
    assert leader["splits"][0]["split"]["seconds"] == 160
    assert leader["splits"][1]["code"] == "34"
    assert leader["splits"][1]["split"]["seconds"] == 86
    assert leader["splits"][-1]["code"] == "240"
    assert leader["splits"][-1]["split"]["seconds"] == 19

    forked = group["participants"][1]
    assert forked["lap"] == "1"
    assert forked["splits"][2]["code"] == "36"
    assert forked["splits"][2]["split"]["seconds"] == 57


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


def test_player_split_gaps_use_score_visits_for_rogaine_protocol() -> None:
    from portal.routers.imports import _race_result_split_gaps

    result = {
        "kind": "score",
        "self_row_index": 0,
        "participants": [
            {
                "row_index": 0,
                "visits": [
                    {"code": "55", "split": {"seconds": 300}},
                    {"code": "60", "split": {"seconds": 300}},
                ],
            },
            {
                "row_index": 1,
                "visits": [
                    {"code": "55", "split": {"seconds": 240}},
                    {"code": "70", "split": {"seconds": 240}},
                ],
            },
        ],
    }
    result["self_participant"] = result["participants"][0]

    gaps = _race_result_split_gaps(result)

    assert gaps["1"] == {"text": "+01:00", "tone": "good"}
    assert "2" not in gaps


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


def test_score_protocol_attached_to_rogaine_training_has_split_analysis_buttons(monkeypatch) -> None:
    from portal.routers import race_results

    monkeypatch.setattr(race_results, "fetch_race_protocol", lambda _url: SCORE_PROTOCOL)

    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={
                "title": "Rogaine protocol",
                "date": "2026-04-29",
                "training_type": "rogaine",
                "discipline": "run",
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
        client.post(
            f"/api/imports/{draft_id}/course-controls",
            json={
                "controls": [
                    {"index": 1, "pixel_x": 0, "pixel_y": 0, "lat": 60.0, "lon": 30.0},
                    {"index": 2, "pixel_x": 100, "pixel_y": 0, "lat": 60.0, "lon": 30.001},
                    {"index": 3, "pixel_x": 200, "pixel_y": 0, "lat": 60.0, "lon": 30.002},
                    {"index": 4, "pixel_x": 300, "pixel_y": 0, "lat": 60.0, "lon": 30.003},
                    {"index": 5, "pixel_x": 400, "pixel_y": 0, "lat": 60.0, "lon": 30.004},
                ]
            },
        )
        client.post(f"/trainings/imports/{draft_id}/finish", follow_redirects=False)
        trainings = client.get("/trainings")
        training_match = re.search(
            r"Rogaine protocol.*?/trainings/([0-9a-f]+)/race-result/import",
            trainings.text,
            re.S,
        )
        assert training_match is not None
        training_id = training_match.group(1)

        save = client.post(
            f"/trainings/{training_id}/race-result/import/save",
            data={
                "url": "https://example.test/score.html",
                "group_name": "ЖВ",
                "self_row_index": "0",
            },
            follow_redirects=False,
        )
        detail = client.get(save.headers["location"])

    assert save.status_code == 303
    assert detail.status_code == 200
    assert 'data-training-type="rogaine"' in detail.text
    assert "race-score-table" in detail.text
    assert "race-split-analysis-button" in detail.text
    assert 'data-score-visit-index="0"' in detail.text
    assert 'data-score-visit-index="1"' in detail.text
    assert 'data-score-visit-index="2"' in detail.text
    assert "split-view-modal" in detail.text
    assert "race_result.js" in detail.text


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


def test_parse_legacy_race_protocol_html_without_team_column() -> None:
    protocol = parse_race_protocol_html(LEGACY_PROTOCOL_WITHOUT_TEAM)

    group = protocol.groups[0]
    assert group["controls"][0] == {
        "column_index": 6,
        "label": "1",
        "code": "47",
        "distance_meters": None,
    }
    participant = group["participants"][0]
    assert participant["name"] == "БАЗИЛЬ ЕВА"
    assert participant["bib"] == "169"
    assert participant["result"] == "00:34:36"
    assert participant["place"] == "1"
    assert participant["gap"] == ""
    assert participant["splits"][0]["cumulative"]["time"] == "1:30"


def test_parse_pdf_race_protocol() -> None:
    protocol = parse_pdf_race_protocol(PDF_PROTOCOL_TEXT)

    assert protocol.kind == "course"
    assert protocol.event_name == "Чемпионат и Первенство Санкт-Петербурга по спортивному ориентированию 10.05.2026 Ленинградская обл., п. Поляны"
    assert protocol.event_meta == "ПРОТОКОЛ РЕЗУЛЬТАТОВ"
    assert [group["name"] for group in protocol.groups] == ["Ж14", "Фитнес2"]

    group = protocol.groups[0]
    assert group["subtitle"] == "9 КП, 2.6 км"
    assert len(group["controls"]) == 10
    assert group["controls"][0] == {
        "column_index": 0,
        "label": "1",
        "code": "31",
        "distance_meters": None,
    }
    assert group["controls"][-1]["label"] == "F"
    assert group["controls"][-1]["code"] == "F"

    participant = group["participants"][1]
    assert participant["name"] == "МАРЧЕНКО ПОЛИНА"
    assert participant["bib"] == "176"
    assert participant["result"] == "00:20:22"
    assert participant["place"] == "2"
    assert participant["gap"] == "00:05:59"
    assert participant["splits"][0]["split"]["seconds"] == 59
    assert participant["splits"][0]["split"]["rank"] == 1
    assert participant["splits"][-1]["split"]["seconds"] == 10
    assert participant["splits"][-1]["split"]["rank"] == 2
    assert participant["splits"][-1]["cumulative"]["time"] == "00:20:22"
    assert participant["splits"][-1]["cumulative"]["rank"] == 2

    leader = group["participants"][0]
    assert leader["splits"][-1]["split"]["seconds"] == 8
    assert leader["splits"][-1]["split"]["rank"] == 1


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


def test_pace_distribution_uses_virtual_leader_splits() -> None:
    from portal.routers.race_results import _prepare_race_result_view

    result = {
        "self_row_index": 0,
        "controls": [
            {"distance_meters": 100},
            {"distance_meters": 200},
            {"distance_meters": 300},
        ],
        "participants": [
            {
                "row_index": 0,
                "name": "Я",
                "result": "00:05:00",
                "splits": [
                    {"label": "1", "cumulative": {"time": "1:00", "seconds": 60}},
                    {"label": "2", "split": {"time": "2:00", "seconds": 120}},
                    {"label": "Ф", "split": {"time": "2:00", "seconds": 120}},
                ],
            },
            {
                "row_index": 1,
                "name": "Лидер",
                "result": "00:03:30",
                "splits": [
                    {"label": "1", "cumulative": {"time": "0:30", "seconds": 30}},
                    {"label": "2", "split": {"time": "1:00", "seconds": 60}},
                    {"label": "Ф", "split": {"time": "2:00", "seconds": 120}},
                ],
            },
        ],
    }

    _prepare_race_result_view(result)

    distribution = result["pace_distribution"]
    assert distribution["leader_name"] == "Идеальный лидер"
    assert distribution["split_count"] == 3
    assert [point["pace_seconds"] for point in distribution["points"]] == [300, 300, 400]
    assert distribution["min"] == 300
    assert distribution["max"] == 400
    assert distribution["mean"] == 333
    assert distribution["median"] == 300


def test_pace_distribution_buckets_match_mockup_range() -> None:
    from portal.routers.race_results import _pace_distribution_view

    leader = {
        "name": "Идеальный лидер",
        "splits": [
            {"label": str(index + 1), "split": {"seconds": seconds}}
            for index, seconds in enumerate([429, 512, 535, 473, 643, 300, 391, 337, 349, 330, 408, 541, 476, 426])
        ],
    }
    controls = [{"distance_meters": 1000} for _ in leader["splits"]]

    distribution = _pace_distribution_view(leader, controls)

    assert distribution["bucket_size"] == 60
    assert [bucket["from"] for bucket in distribution["buckets"]] == [270, 330, 390, 450, 510, 570, 630]


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


def test_load_orgeo_live_protocol(monkeypatch) -> None:
    from portal.routers import race_results

    def fake_fetch(url: str) -> str:
        if url == "https://orgeo.ru/event/info/52808":
            return ORGEO_INFO_HTML
        if url == "https://orgeo.ru/event/export/event_id/52808/sub_id/1/format/json":
            return ORGEO_EXPORT_JSON
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(race_results, "fetch_race_protocol", fake_fetch)

    protocol = asyncio.run(race_results._load_protocol("https://orgeo.ru/event/info/52808"))

    assert protocol.event_name == "Кубок Белых Ночей 11 этап"
    assert protocol.kind == "course"
    assert [group["name"] for group in protocol.groups] == ["ЖС", "ЖВ"]
    group = protocol.groups[0]
    assert len(group["participants"]) == 3
    assert group["participants"][2]["name"] == "Храмова Полина"
    assert group["participants"][2]["result"] == "00:54:10"


def test_race_protocol_import_flow(monkeypatch) -> None:
    from portal.routers import race_results

    monkeypatch.setattr(race_results, "fetch_race_protocol", lambda _url: SAMPLE_PROTOCOL)

    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={"title": "Race with protocol", "date": "2026-04-26", "discipline": "run", "subject_user_id": fetch_user_id("polina")},
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
    assert detail.text.count("race-virtual-leader-row") >= 2
    assert "Идеальный лидер" in detail.text
    assert "problem-cell-pace" in detail.text
    assert f"/trainings/{training_id}/play" in detail.text
    assert "split-analysis-modal" in detail.text
    assert "split-view-modal" in detail.text
    assert "split_analysis_dialog.js" in detail.text
    assert "split_view_dialog.js" in detail.text
    assert "race_result.js" in detail.text
    assert "Анализ достижимости" in detail.text
    assert "Анализ темпа" in detail.text
    assert "reachability-modal" in detail.text
    assert "pace-distribution-modal" in detail.text
    assert "race_reachability_dialog.js" in detail.text
    assert "pace_distribution_dialog.js" in detail.text
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


def test_race_result_page_without_map_does_not_render_none_image_src(monkeypatch) -> None:
    from portal.routers import race_results

    class DummyConn:
        async def close(self) -> None:
            pass

    parsed = parse_race_protocol_html(SAMPLE_PROTOCOL)
    group = parsed.groups[0]
    result = {
        "race_result_id": "race-result-1",
        "training_id": "training-1",
        "source_url": "https://example.test/splits.html",
        "event_name": parsed.event_name,
        "event_meta": parsed.event_meta,
        "group_name": group["name"],
        "group_subtitle": group.get("subtitle") or "",
        "controls": json.loads(json.dumps(group["controls"])),
        "participants": json.loads(json.dumps(group["participants"])),
        "self_row_index": 0,
        "kind": parsed.kind,
    }
    training = {
        "training_id": "training-1",
        "training_type": "race",
        "map_image_path": None,
        "georef_transform": None,
        "course_controls": [],
        "track_points": [],
    }

    async def fake_connect_db(_db_path: str) -> DummyConn:
        return DummyConn()

    async def fake_get_race_result(_conn: DummyConn, _race_result_id: str) -> dict:
        return json.loads(json.dumps(result))

    async def fake_get_training_player(_conn: DummyConn, _training_id: str) -> dict:
        return training

    monkeypatch.setattr(race_results, "connect_db", fake_connect_db)
    monkeypatch.setattr(race_results, "get_race_result", fake_get_race_result)
    monkeypatch.setattr(race_results, "get_training_player", fake_get_training_player)

    with TestClient(app) as client:
        detail = client.get("/race-results/race-result-1")

    assert detail.status_code == 200
    assert 'data-map-image-url=""' in detail.text
    assert "race-analysis-map-image" not in detail.text
    assert 'src="None"' not in detail.text


def test_orgeo_import_flow(monkeypatch) -> None:
    from portal.routers import race_results

    def fake_fetch(url: str) -> str:
        if url == "https://orgeo.ru/event/info/52808":
            return ORGEO_INFO_HTML
        if url == "https://orgeo.ru/event/export/event_id/52808/sub_id/1/format/json":
            return ORGEO_EXPORT_JSON
        if url == "https://orgeo.ru/online/finish/52808?s=1&d=%D0%96%D0%A1&api=json&test_time=&phone=0":
            return ORGEO_LIVE_JSON
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(race_results, "fetch_race_protocol", fake_fetch)

    with TestClient(app) as client:
        preview = client.post(
            "/race-results/import/preview",
            data={"url": "https://orgeo.ru/event/info/52808"},
        )
        options = re.findall(r'<option value="([^"]+)"[^>]*>(.*?)</option>', preview.text, re.S)
        match = next((value for value, text in options if "Храмова Полина" in text), None)
        assert match is not None
        save = client.post(
            "/race-results/import/save",
            data={
                "url": "https://orgeo.ru/event/info/52808",
                "group_name": "ЖС",
                "self_row_index": match,
            },
            follow_redirects=False,
        )
        detail = client.get(save.headers["location"])

    assert preview.status_code == 200
    assert "Кубок Белых Ночей 11 этап" in preview.text
    assert "ЖС" in preview.text
    assert "Храмова Полина" in preview.text
    assert save.status_code == 303
    assert detail.status_code == 200
    assert "Кубок Белых Ночей 11 этап" in detail.text
    assert "ЖС" in detail.text
    assert "Храмова Полина" in detail.text
    assert "Анализ темпа" in detail.text


def test_orgeo_relay_import_keeps_full_field_with_lap_filter_toggle(monkeypatch) -> None:
    from portal.routers import race_results

    def fake_fetch(url: str) -> str:
        if url == "https://orgeo.ru/event/info/53000":
            return ORGEO_RELAY_INFO_HTML
        if url == "https://orgeo.ru/event/export/event_id/53000/sub_id/1/format/json":
            return ORGEO_RELAY_EXPORT_JSON
        if url == "https://orgeo.ru/online/finish/53000?s=1&d=%D0%9614&api=json&test_time=&phone=0":
            return ORGEO_RELAY_LIVE_JSON
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(race_results, "fetch_race_protocol", fake_fetch)

    with TestClient(app) as client:
        preview = client.post(
            "/race-results/import/preview",
            data={"url": "https://orgeo.ru/event/info/53000"},
        )
        options = re.findall(r'<option value="([^"]+)"[^>]*>(.*?)</option>', preview.text, re.S)
        match = next((value for value, text in options if "Храмова Полина" in text), None)
        assert match is not None
        save = client.post(
            "/race-results/import/save",
            data={
                "url": "https://orgeo.ru/event/info/53000",
                "group_name": "Ж14",
                "self_row_index": match,
            },
            follow_redirects=False,
        )
        detail = client.get(save.headers["location"])

    assert preview.status_code == 200
    assert "Храмова Полина · этап 2" in preview.text
    assert save.status_code == 303
    assert detail.status_code == 200
    assert "Храмова" in detail.text
    assert "Полина" in detail.text
    assert "<strong>Участников</strong>\n            <span>4</span>" in detail.text
    assert "Только мой забег" in detail.text
    assert "этап 2" in detail.text
    assert "Зекова" in detail.text
    assert "Иванова" in detail.text
    assert "Доронина" in detail.text
    assert detail.text.count('data-other-lap="true" hidden') == 2


def test_display_place_falls_back_to_bib() -> None:
    from portal.routers.race_results import _display_place_text

    assert _display_place_text({"place": "", "bib": "290.2", "row_index": 31}) == "290.2"
    assert _display_place_text({"place": "", "bib": "", "relay": "290", "row_index": 31}) == "290"


def test_display_result_uses_split_total_for_relay() -> None:
    from portal.routers.race_results import _display_result_text

    participant = {
        "lap": "2",
        "result": "01:09:13",
        "splits": [
            {"split": {"seconds": 180}},
            {"split": {"seconds": 305}},
            {"split": {"seconds": 133}},
            {"split": {"seconds": 268}},
            {"split": {"seconds": 191}},
            {"split": {"seconds": 326}},
            {"split": {"seconds": 196}},
            {"split": {"seconds": 83}},
            {"split": {"seconds": 136}},
            {"split": {"seconds": 86}},
        ],
    }

    assert _display_result_text(participant, "course") == "31:44"


def test_course_relay_participants_are_sorted_by_display_result() -> None:
    from portal.routers.race_results import _prepare_race_result_view

    result = {
        "kind": "course",
        "participants": [
            {"row_index": 0, "name": "Быстрая", "place": "1", "lap": "1", "result": "00:30:00", "splits": [{"split": {"seconds": 1800}}]},
            {"row_index": 1, "name": "Медленная", "place": "2", "lap": "2", "result": "00:40:00", "splits": [{"split": {"seconds": 2400}}]},
            {"row_index": 2, "name": "Еще медленнее", "place": "3", "lap": "2", "result": "00:45:00", "splits": [{"split": {"seconds": 2700}}]},
        ],
        "controls": [],
        "self_row_index": 1,
    }

    _prepare_race_result_view(result)

    assert [participant["name"] for participant in result["participants"]] == ["Быстрая", "Медленная", "Еще медленнее"]
    assert result["participants"][0]["relative_gap_text"] == ""
    assert result["participants"][0]["is_same_lap_as_self"] is False
    assert result["participants"][2]["relative_gap_text"] == "+05:00"
    assert result["participants"][2]["relative_gap_tone"] == "hot"


def test_course_relay_gap_uses_self_display_result_even_if_self_is_later_in_list() -> None:
    from portal.routers.race_results import _prepare_race_result_view

    result = {
        "kind": "course",
        "participants": [
            {"row_index": 0, "name": "Аскарова", "place": "1", "lap": "1", "result": "00:30:08", "splits": [{"split": {"seconds": 1808}}]},
            {"row_index": 1, "name": "Храмова", "place": "2", "lap": "2", "result": "01:09:13", "splits": [{"split": {"seconds": 1904}}]},
            {"row_index": 2, "name": "Доронина", "place": "3", "lap": "2", "result": "01:10:20", "splits": [{"split": {"seconds": 1980}}]},
        ],
        "controls": [],
        "self_row_index": 1,
    }

    _prepare_race_result_view(result)

    rival = next(participant for participant in result["participants"] if participant["name"] == "Аскарова")
    same_lap_rival = next(participant for participant in result["participants"] if participant["name"] == "Доронина")
    self_participant = next(participant for participant in result["participants"] if participant["name"] == "Храмова")
    assert self_participant["display_result"] == "31:44"
    assert rival["relative_gap_text"] == ""
    assert same_lap_rival["relative_gap_text"] == "+01:16"


def test_course_relay_virtual_leader_uses_bib_lap_when_lap_is_missing() -> None:
    from portal.routers.race_results import _prepare_race_result_view

    result = {
        "kind": "course",
        "participants": [
            {"row_index": 0, "name": "Первый этап", "bib": "101.1", "result": "00:10:00", "splits": [{"split": {"seconds": 10}}, {"split": {"seconds": 10}}]},
            {"row_index": 1, "name": "Я", "bib": "201.2", "result": "00:30:00", "splits": [{"split": {"seconds": 30}}, {"split": {"seconds": 30}}]},
            {"row_index": 2, "name": "Мой этап", "bib": "202.2", "result": "00:24:00", "splits": [{"split": {"seconds": 20}}, {"split": {"seconds": 40}}]},
        ],
        "controls": [{}, {}],
        "self_row_index": 1,
    }

    _prepare_race_result_view(result)

    assert result["is_relay_lap_scoped"] is True
    assert result["self_lap"] == "2"
    assert result["virtual_leader"]["display_result"] == "00:50"
    assert [split["split"]["seconds"] for split in result["virtual_leader"]["splits"]] == [20, 30]
    first_lap = next(participant for participant in result["participants"] if participant["name"] == "Первый этап")
    assert first_lap["is_same_lap_as_self"] is False


def test_course_relay_display_place_is_sorted_position() -> None:
    from portal.routers.race_results import _prepare_race_result_view

    result = {
        "kind": "course",
        "participants": [
            {"row_index": 0, "name": "Третья", "place": "10", "lap": "1", "result": "00:40:00", "splits": [{"split": {"seconds": 2400}}]},
            {"row_index": 1, "name": "Первая", "place": "1", "lap": "1", "result": "00:30:00", "splits": [{"split": {"seconds": 1800}}]},
            {"row_index": 2, "name": "Вторая", "place": "2", "lap": "1", "result": "00:35:00", "splits": [{"split": {"seconds": 2100}}]},
        ],
        "controls": [],
        "self_row_index": 1,
    }

    _prepare_race_result_view(result)

    assert [participant["place"] for participant in result["participants"]] == ["1", "2", "3"]
    assert [participant["display_place"] for participant in result["participants"]] == ["1", "2", "3"]


def test_js_relay_import_keeps_full_field_with_bib_lap_filter_toggle(monkeypatch) -> None:
    from portal.routers import race_results

    relay_protocol = RELAY_TWO_PERSON_PROTOCOL.replace(
        "2|Марченко<br>Полина|165.1|00:18:42|4|+1:12",
        "2|Марченко<br>Полина|165.2|00:18:42|4|+1:12",
    )
    monkeypatch.setattr(race_results, "fetch_race_protocol", lambda _url: relay_protocol)

    with TestClient(app) as client:
        preview = client.post(
            "/race-results/import/preview",
            data={"url": "https://example.test/relay-splits.html"},
        )
        options = re.findall(r'<option value="([^"]+)"[^>]*>(.*?)</option>', preview.text, re.S)
        match = next((value for value, text in options if "Марченко Полина" in text), None)
        assert match is not None
        save = client.post(
            "/race-results/import/save",
            data={
                "url": "https://example.test/relay-splits.html",
                "group_name": "Ж14",
                "self_row_index": match,
            },
            follow_redirects=False,
        )
        detail = client.get(save.headers["location"])

    assert preview.status_code == 200
    assert "Марченко Полина · этап 2" in preview.text
    assert save.status_code == 303
    assert "Только мой забег" in detail.text
    assert "этап 2" in detail.text
    assert "Марченко" in detail.text
    assert "Аскарова" in detail.text
    assert 'data-other-lap="true" hidden' in detail.text
    assert 'id="race-virtual-leader-row"' in detail.text
    assert "data-virtual-split-index" in detail.text
    assert "data-race-split-seconds" in detail.text


def test_dashboard_problem_splits_panel_renders(monkeypatch) -> None:
    from portal.routers import race_results

    monkeypatch.setattr(race_results, "fetch_race_protocol", lambda _url: SAMPLE_PROTOCOL)
    controls = [
        {"index": index + 1, "pixel_x": index * 100, "pixel_y": 0, "lat": 60.0, "lon": 30.0 + index * 0.001}
        for index in range(11)
    ]
    track_points = [
        {"lat": 60.0, "lon": 30.0 + index * 0.001, "ele": 10.0, "time": f"2026-04-29T10:00:{index:02d}Z"}
        for index in range(11)
    ]

    with TestClient(app) as client:
        create_response = client.post(
            "/trainings/imports",
            data={"title": "Dashboard problems", "date": "2026-04-29", "discipline": "run", "subject_user_id": fetch_user_id("polina")},
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
        client.post(f"/api/imports/{draft_id}/course-controls", json={"controls": controls})
        client.post(f"/trainings/imports/{draft_id}/finish", follow_redirects=False)
        trainings = client.get("/trainings")
        match = re.search(
            r"Dashboard problems.*?/trainings/([0-9a-f]+)/race-result/import",
            trainings.text,
            re.S,
        )
        assert match is not None
        training_id = match.group(1)
        client.post(f"/api/trainings/{training_id}/track-points", json={"track_points": track_points})
        save = client.post(
            f"/trainings/{training_id}/race-result/import/save",
            data={
                "url": "https://example.test/splits.html",
                "group_name": "Ж14",
                "self_row_index": "0",
            },
            follow_redirects=False,
        )
        dashboard = client.get("/")
        all_splits = client.get("/problem-splits")

    assert save.status_code == 303
    assert dashboard.status_code == 200
    assert "dashboard-grid" in dashboard.text
    assert "Причины ошибок" in dashboard.text
    assert "dashboard_error_reasons.js" in dashboard.text
    assert "Места на соревнованиях" in dashboard.text
    assert "dashboard_race_positions.js" in dashboard.text
    assert "Сплиты на анализ" in dashboard.text
    assert "Все сплиты" in dashboard.text
    assert "Dashboard problems" in dashboard.text
    assert "split-analysis-button" in dashboard.text
    assert "dashboard_problem_splits.js" in dashboard.text
    assert "split-analysis-modal" in dashboard.text
    assert all_splits.status_code == 200
    assert "Все проблемные сплиты" in all_splits.text
    assert "problem-split-table" in all_splits.text
    assert "split-analysis-button" in all_splits.text


def test_dashboard_problem_splits_excludes_reviewed_split() -> None:
    from portal.main import _build_problem_splits, _build_reviewed_splits

    controls = [
        {"lat": 60.0, "lon": 30.0 + index * 0.001}
        for index in range(7)
    ]
    track_points = [
        {"lat": 60.0, "lon": 30.0 + index * 0.001, "time": f"2026-04-29T10:00:{index:02d}Z"}
        for index in range(7)
    ]
    result = {
        "training_id": "training-1",
        "race_result_id": "race-result-1",
        "source_url": "https://example.test/splits.html",
        "event_name": "Dashboard review",
        "event_meta": "",
        "group_name": "Ж14",
        "group_subtitle": "",
        "controls": [],
        "participants": [
            {
                "row_index": 0,
                "result": "00:02:30",
                "splits": [
                    {"label": "1", "cumulative": {"seconds": 10}},
                    {"label": "2", "split": {"seconds": 10}},
                    {"label": "3", "split": {"seconds": 10}},
                    {"label": "4", "split": {"seconds": 110}},
                    {"label": "Ф", "split": {"seconds": 10}},
                ],
            },
            {
                "row_index": 1,
                "result": "00:00:50",
                "splits": [
                    {"label": "1", "cumulative": {"seconds": 10}},
                    {"label": "2", "split": {"seconds": 10}},
                    {"label": "3", "split": {"seconds": 10}},
                    {"label": "4", "split": {"seconds": 10}},
                    {"label": "Ф", "split": {"seconds": 10}},
                ],
            },
        ],
        "self_row_index": 0,
        "kind": "course",
        "training_title": "Dashboard problems",
        "training_date": "2026-04-29",
        "training_type": "race",
        "training_course_controls": controls,
        "training_track_points": track_points,
        "map_image_path": "/tmp/map.png",
        "georef_transform": {"lon_a": 1, "lon_b": 0, "lon_c": 0, "lat_a": 0, "lat_b": 1, "lat_c": 0},
        "self_participant": None,
    }
    result["self_participant"] = result["participants"][0]

    problem_splits, _ = _build_problem_splits([result])
    reviewed_result = {**result, "reviewed_split_keys": {("4", "3", "4")}}
    reviewed_problem_splits, _ = _build_problem_splits([reviewed_result])
    reviewed_splits, _ = _build_reviewed_splits(
        [result],
        [
            {
                "training_id": "training-1",
                "race_result_id": "race-result-1",
                "split_label": "4",
                "from_control_label": "3",
                "to_control_label": "4",
                "reason_label": "Низкий темп без ошибки",
                "custom_reason": None,
                "reviewed_at": "2026-04-30T10:00:00+00:00",
            }
        ],
    )

    assert [split["split_label"] for split in problem_splits] == ["4"]
    assert reviewed_problem_splits == []
    assert [split["split_label"] for split in reviewed_splits] == ["4"]
    assert reviewed_splits[0]["reason_text"] == "Низкий темп без ошибки"


def test_dashboard_error_reason_stats_builds_top_and_trend() -> None:
    from portal.main import _build_error_reason_stats

    stats = _build_error_reason_stats(
        [
            {"reason_label": "Плохой выбор пути", "training_date": "2026-04-01", "count": 3},
            {"reason_label": "Плохой выбор пути", "training_date": "2026-04-10", "count": 1},
            {"reason_label": "Ошибка направления", "training_date": "2026-04-10", "count": 2},
        ]
    )

    assert stats["total"] == 6
    assert stats["start_count"] == 2
    assert stats["dates"] == ["01.04", "10.04"]
    assert stats["top_reason"]["label"] == "Плохой выбор пути"
    assert stats["top_reason"]["trend"] == [3, 1]
    assert stats["top_reason"]["url"].startswith("/reviewed-splits?")
    assert "встречается реже" in stats["insight"]


def test_dashboard_race_position_stats_builds_place_trend() -> None:
    from portal.main import _build_race_position_stats

    stats = _build_race_position_stats(
        [
            {
                "training_date": "2026-05-03",
                "training_title": "Первый старт",
                "event_name": "Первый старт",
                "group_name": "Ж14",
                "participants": [{} for _ in range(20)],
                "self_participant": {"place": "16"},
            },
            {
                "training_date": "2026-05-10",
                "training_title": "Второй старт",
                "event_name": "Второй старт",
                "group_name": "Ж14",
                "participants": [{} for _ in range(40)],
                "self_participant": {"place": "7"},
            },
            {
                "race_date": "2026-05-11",
                "training_title": "Свободный старт",
                "event_name": "Соревнование без тренировки",
                "group_name": "Ж14",
                "participants": [{} for _ in range(50)],
                "self_participant": {"place": "5"},
            },
        ]
    )

    assert stats["race_count"] == 3
    assert stats["latest_place"] == 5
    assert stats["latest_participant_count"] == 50
    assert stats["best_place"] == 5
    assert stats["best_participant_count"] == 50
    assert stats["max_place"] == 16
    assert stats["points"][0]["position_ratio"] == 0.8
    assert stats["points"][1]["position_ratio"] == 0.175
    assert stats["points"][2]["position_ratio"] == 0.1
    assert [point["date_label"] for point in stats["points"]] == ["03.05", "10.05", "11.05"]


def test_dashboard_race_position_stats_uses_relay_result_rank() -> None:
    from portal.main import _build_race_position_stats

    participants = [
        {"row_index": index, "name": f"Участник {index + 1}", "place": str(index + 1), "lap": "1" if index < 6 else "2", "result": f"00:{20 + index:02d}:00", "splits": [{"split": {"seconds": 1200 + index * 10}}]}
        for index in range(12)
    ]
    participants.append(
        {"row_index": 12, "name": "Храмова", "place": "6", "lap": "2", "result": "01:09:13", "splits": [{"split": {"seconds": 1904}}]}
    )

    stats = _build_race_position_stats(
        [
            {
                "race_date": "2026-05-17",
                "training_title": "Relay",
                "event_name": "Relay",
                "group_name": "Ж14",
                "kind": "course",
                "participants": participants,
                "self_participant": participants[-1],
            }
        ]
    )

    assert stats["points"][0]["place"] == 13
    assert stats["latest_place"] == 13
    assert stats["latest_participant_count"] == 13
    assert stats["points"][0]["position_ratio"] == round(13 / 13, 4)


def test_reviewed_splits_page_renders_empty_state() -> None:
    with TestClient(app) as client:
        response = client.get("/reviewed-splits")

    assert response.status_code == 200
    assert "Разобранные сплиты" in response.text
    assert "Пока нет разобранных сплитов" in response.text


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


def test_race_result_import_is_visible_to_self_participant_user(monkeypatch) -> None:
    from portal.auth import USER_COOKIE_NAME
    from portal.routers import race_results

    monkeypatch.setattr(race_results, "fetch_race_protocol", lambda _url: SAMPLE_PROTOCOL)

    with TestClient(app) as client:
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

        client.cookies.set(USER_COOKIE_NAME, fetch_user_id("polina"))
        listing = client.get("/race-results")

    assert save.status_code == 303
    assert listing.status_code == 200
    assert f"/race-results/{race_result_id}" in listing.text
    assert "Храмова Полина" in listing.text


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
            data={"title": "Attach protocol", "date": "2026-04-26", "discipline": "run", "subject_user_id": fetch_user_id("polina")},
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


def test_pdf_race_protocol_import_flow(monkeypatch) -> None:
    from portal.routers import race_results

    monkeypatch.setattr(race_results, "fetch_race_protocol", lambda _url: PDF_PROTOCOL_TEXT)

    with TestClient(app) as client:
        preview = client.post(
            "/race-results/import/preview",
            data={"url": "https://example.test/splits.pdf"},
        )
        save = client.post(
            "/race-results/import/save",
            data={
                "url": "https://example.test/splits.pdf",
                "group_name": "Ж14",
                "self_row_index": "1",
            },
            follow_redirects=False,
        )
        detail = client.get(save.headers["location"])

    assert preview.status_code == 200
    assert "Ж14" in preview.text
    assert "МАРЧЕНКО ПОЛИНА" in preview.text
    assert "Фитнес2" in preview.text
    assert save.status_code == 303
    assert detail.status_code == 200
    assert "Чемпионат и Первенство Санкт-Петербурга" in detail.text
    assert "Ж14" in detail.text
    assert re.search(r"МАРЧЕНКО\s+ПОЛИНА", detail.text)
    assert "00:20:22" in detail.text
