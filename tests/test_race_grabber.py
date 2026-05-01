from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from portal.main import app
from portal.db import connect_db, normalize_db_path, save_race_result
from portal.infrastructure import config
from portal.services import race_grabber


CALENDAR_PAGE_1 = """
<html><body>
<a href="race.php?id=event1">Event 1</a>
<a href=/calendar.php?page=2>2</a>
</body></html>
"""

CALENDAR_PAGE_2 = """
<html><body>
<a href="race.php?id=event2">Event 2</a>
</body></html>
"""

RACE_PAGE_1 = """
<html><head><title>Event 1</title></head><body>
<a class="race-desc-link" href="_races/event1/split.htm">Сплиты</a>
</body></html>
"""

RACE_PAGE_2 = """
<html><head><title>Event 2</title></head><body>
<a class="race-desc-link" href="_races/event2/split file.htm">Сплиты классики</a>
</body></html>
"""

SPLIT_PAGE_MATCH = """<!doctype html>
<script>
const eventName = "Событие 1";
const eventMeta = "meta";
const db = "Ж14| ||п/п|Фамилия, Имя|Номер|Результат|Место|Отст.|#1 (31)<br>100 m|#F(240)||1|Храмова<br>Полина|1566|00:02:15|2|+0:45|0:19(2)<br>0:19(2)|2:15(2)<br>0:11(2)||2|Храмова<br>Ольга|1501|00:02:30|3|+1:00|0:20(3)<br>0:20(3)|2:30(3)<br>0:12(3)|||";
</script>"""

SPLIT_PAGE_NO_MATCH = """<!doctype html>
<script>
const eventName = "Событие 2";
const eventMeta = "meta";
const db = "М14| ||п/п|Фамилия, Имя|Номер|Результат|Место|Отст.|#1 (31)<br>100 m|#F(240)||1|Петров<br>Иван|201|00:10:00|1| |1:00(1)<br>1:00(1)|10:00(1)<br>0:25(1)|||";
</script>"""

ARCHIVE_ROOT = """
<html><body>
<a href=archive.php?year=2025>2025</a>
<a href=archive.php?year=2024>2024</a>
<a href=archive.php?year=2023>2023</a>
<a href=archive.php?year=2022>2022</a>
</body></html>
"""


def test_find_participant_races_scans_calendar_and_returns_matches(monkeypatch) -> None:
    url_map = {
        race_grabber.CALENDAR_URL: CALENDAR_PAGE_1,
        "https://o-site.spb.ru/calendar.php?page=2": CALENDAR_PAGE_2,
        "https://o-site.spb.ru/race.php?id=event1": RACE_PAGE_1,
        "https://o-site.spb.ru/race.php?id=event2": RACE_PAGE_2,
        "https://o-site.spb.ru/_races/event1/split.htm": SPLIT_PAGE_MATCH,
        "https://o-site.spb.ru/_races/event2/split%20file.htm": SPLIT_PAGE_NO_MATCH,
    }

    monkeypatch.setattr(race_grabber, "fetch_race_protocol", lambda url: url_map[url])

    result = race_grabber.find_participant_races("храмова")

    assert result["calendar_page_count"] == 2
    assert result["race_page_count"] == 2
    assert result["split_page_count"] == 2
    assert len(result["matches"]) == 2
    assert result["matches"][0]["event_name"] == "Событие 1"
    assert result["matches"][0]["group_name"] == "Ж14"
    assert result["matches"][0]["report_id"] == "_races/event1/split"
    assert result["matches"][0]["participant_name"] == "Храмова Полина"
    assert result["matches"][1]["participant_name"] == "Храмова Ольга"


def test_race_results_grabber_page_renders_matches(monkeypatch) -> None:
    monkeypatch.setattr(
        race_grabber,
        "find_participant_races",
        lambda query, include_archive=False: {
            "query": query,
            "matches": [
                {
                    "report_id": "_races/event1/split",
                    "event_name": "Снежная тропа",
                    "race_page_url": "https://o-site.spb.ru/race.php?id=event1",
                    "split_url": "https://o-site.spb.ru/_races/event1/split.htm",
                    "split_label": "Сплиты",
                    "group_name": "Ж14",
                    "participant_name": "Храмова Полина",
                    "imported": False,
                    "import_url": "/race-results/import/open?url=https%3A%2F%2Fo-site.spb.ru%2F_races%2Fevent1%2Fsplit.htm&group_name=%D0%96%D0%1414&participant_name=%D0%A5%D1%80%D0%B0%D0%BC%D0%BE%D0%B2%D0%B0+%D0%9F%D0%BE%D0%BB%D0%B8%D0%BD%D0%B0",
                }
            ],
            "calendar_page_count": 2,
            "race_page_count": 5,
            "split_page_count": 3,
        },
    )

    with TestClient(app) as client:
        response = client.post(
            "/race-results/grabber",
            data={"participant_query": "Храмова", "include_archive": "1"},
        )

    assert response.status_code == 200
    assert "Грабер протоколов" in response.text
    assert "Снежная тропа" in response.text
    assert "Храмова Полина" in response.text
    assert "Импорт" in response.text
    assert "target=\"_blank\"" in response.text
    assert "Поиск по календарю может занять" in response.text
    assert "Архив за последние 3 года" in response.text
    assert "race-grabber-form" in response.text


def test_discover_recent_archive_year_urls_limits_to_last_three_years(monkeypatch) -> None:
    monkeypatch.setattr(race_grabber, "fetch_race_protocol", lambda url: ARCHIVE_ROOT)

    urls = race_grabber._discover_recent_archive_year_urls(race_grabber.ARCHIVE_URL, 3)

    assert urls == [
        "https://o-site.spb.ru/archive.php?year=2025",
        "https://o-site.spb.ru/archive.php?year=2024",
        "https://o-site.spb.ru/archive.php?year=2023",
    ]


def test_grabber_marks_already_imported_participant(monkeypatch) -> None:
    monkeypatch.setattr(
        race_grabber,
        "find_participant_races",
        lambda query, include_archive=False: {
            "query": query,
            "matches": [
                {
                    "report_id": "_races/event1/split",
                    "event_name": "Снежная тропа",
                    "race_page_url": "https://o-site.spb.ru/race.php?id=event1",
                    "split_url": "https://o-site.spb.ru/_races/event1/split.htm",
                    "split_label": "Сплиты",
                    "group_name": "Ж14",
                    "participant_name": "Храмова Полина",
                }
            ],
            "calendar_page_count": 1,
            "race_page_count": 1,
            "split_page_count": 1,
        },
    )

    conn = asyncio.run(connect_db(normalize_db_path(config.DB_PATH)))
    try:
        asyncio.run(
            save_race_result(
                conn,
                source_url="https://o-site.spb.ru/_races/event1/split.htm",
                event_name="Снежная тропа",
                event_meta=None,
                group_name="Ж14",
                group_subtitle=None,
                controls=[],
                participants=[{"row_index": 0, "name": "Храмова Полина", "splits": []}],
                self_row_index=0,
            )
        )
    finally:
        asyncio.run(conn.close())

    with TestClient(app) as client:
        response = client.post("/race-results/grabber", data={"participant_query": "Храмова"})

    assert response.status_code == 200
    assert "Импортировано" in response.text


def test_import_open_prefills_selected_participant(monkeypatch) -> None:
    from portal.routers import race_results

    monkeypatch.setattr(race_results, "fetch_race_protocol", lambda _url: SPLIT_PAGE_MATCH)

    with TestClient(app) as client:
        response = client.get(
            "/race-results/import/open",
            params={
                "url": "https://o-site.spb.ru/_races/event1/split.htm",
                "group_name": "Ж14",
                "participant_name": "Храмова Ольга",
            },
        )

    assert response.status_code == 200
    assert "Выбор группы" in response.text
    assert 'value="Ж14"' in response.text
    assert "Храмова Ольга" in response.text
