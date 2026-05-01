from __future__ import annotations

import html
import re
from datetime import datetime
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from portal.services.race_protocol import fetch_race_protocol, parse_race_protocol_html


CALENDAR_URL = "https://o-site.spb.ru/calendar.php"
ARCHIVE_URL = "https://o-site.spb.ru/archive.php"
ARCHIVE_YEARS_LIMIT = 3


def find_participant_races(participant_query: str, include_archive: bool = False) -> dict:
    query = _normalize_text(participant_query)
    if not query:
        return {
            "query": participant_query,
            "matches": [],
            "calendar_page_count": 0,
            "race_page_count": 0,
            "split_page_count": 0,
        }

    matches: list[dict] = []
    race_page_urls: set[str] = set()
    split_page_count = 0

    source_urls = [CALENDAR_URL]
    if include_archive:
        source_urls.extend(_discover_recent_archive_year_urls(ARCHIVE_URL, ARCHIVE_YEARS_LIMIT))

    index_pages: list[str] = []
    for source_url in source_urls:
        index_pages.extend(_discover_index_pages(source_url))

    for index_url in index_pages:
        race_page_urls.update(_extract_race_links(fetch_race_protocol(index_url), index_url))

    for race_page_url in sorted(race_page_urls):
        race_html = fetch_race_protocol(race_page_url)
        event_name = _extract_race_title(race_html)
        split_links = _extract_split_links(race_html, race_page_url)
        for split_link in split_links:
            split_page_count += 1
            try:
                protocol = parse_race_protocol_html(fetch_race_protocol(split_link["url"]))
            except Exception:
                continue
            for group in protocol.groups:
                for participant in group.get("participants", []):
                    participant_name = participant.get("name", "")
                    if query not in _normalize_text(participant_name):
                        continue
                    matches.append(
                        {
                            "report_id": build_report_id(split_link["url"]),
                            "event_name": protocol.event_name or event_name,
                            "race_page_url": race_page_url,
                            "split_url": split_link["url"],
                            "split_label": split_link["label"],
                            "group_name": group.get("name", ""),
                            "participant_name": participant_name,
                        }
                    )

    return {
        "query": participant_query.strip(),
        "matches": matches,
        "calendar_page_count": len(index_pages),
        "race_page_count": len(race_page_urls),
        "split_page_count": split_page_count,
    }


def _discover_index_pages(root_url: str) -> list[str]:
    first_page = fetch_race_protocol(root_url)
    page_urls = {root_url}
    root_name = "archive.php" if "archive.php" in root_url else "calendar.php"
    for href in _extract_hrefs(first_page):
        if root_name not in href or "page=" not in href:
            continue
        if "year=" in root_url and "year=" not in href:
            continue
        page_urls.add(urljoin(root_url, href))
    return sorted(page_urls)


def _extract_race_links(content: str, base_url: str) -> set[str]:
    links: set[str] = set()
    for match in re.finditer(r'href=([\'"]?)(race\.php\?id=[^\'" >]+)\1', content, re.I):
        links.add(urljoin(base_url, match.group(2)))
    return links


def _extract_split_links(content: str, base_url: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for match in re.finditer(r"<a\b([^>]*)>(.*?)</a>", content, re.I | re.S):
        href = _extract_href_from_attrs(match.group(1))
        if not href:
            continue
        label = _normalize_text(_strip_tags(match.group(2)))
        if "сплит" not in label and "split" not in label:
            continue
        links.append(
            {
                "url": _normalize_url(urljoin(base_url, href)),
                "label": _clean_label(_strip_tags(match.group(2))),
            }
        )
    unique_links: dict[str, dict[str, str]] = {}
    for link in links:
        unique_links.setdefault(link["url"], link)
    return list(unique_links.values())


def _extract_race_title(content: str) -> str:
    match = re.search(r"<title>(.*?)</title>", content, re.I | re.S)
    return _clean_label(_strip_tags(match.group(1))) if match else ""


def _clean_label(value: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", value)).strip()


def _normalize_text(value: str) -> str:
    return _clean_label(value).casefold()


def _strip_tags(value: str) -> str:
    normalized = re.sub(r"(?i)<br\s*/?>", " ", value)
    return re.sub(r"<[^>]+>", "", normalized)


def _normalize_url(value: str) -> str:
    parts = urlsplit(value)
    path = quote(parts.path, safe="/:%._-()")
    query = quote(parts.query, safe="=&:%._-()[]")
    return urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))


def _extract_hrefs(content: str) -> list[str]:
    hrefs: list[str] = []
    for match in re.finditer(r"<a\b([^>]*)>", content, re.I | re.S):
        href = _extract_href_from_attrs(match.group(1))
        if href:
            hrefs.append(href)
    return hrefs


def _extract_href_from_attrs(attrs: str) -> str | None:
    quoted = re.search(r'href\s*=\s*["\']([^"\']+)["\']', attrs, re.I)
    if quoted:
        return quoted.group(1).strip()
    bare = re.search(r'href\s*=\s*([^\'" >]+)', attrs, re.I)
    if bare:
        return bare.group(1).strip()
    return None


def build_report_id(split_url: str) -> str:
    parts = urlsplit(split_url)
    path = parts.path.strip("/")
    if "." in path.rsplit("/", 1)[-1]:
        head, tail = path.rsplit("/", 1)
        tail = tail.rsplit(".", 1)[0]
        path = f"{head}/{tail}" if head else tail
    return path


def _discover_recent_archive_year_urls(root_url: str, limit: int) -> list[str]:
    content = fetch_race_protocol(root_url)
    current_year = datetime.now().year
    candidates: list[tuple[int, str]] = []
    for href in _extract_hrefs(content):
        year_match = re.search(r"[?&]year=(\d{4})\b", href)
        if not year_match:
            continue
        year = int(year_match.group(1))
        if year > current_year - 1:
            continue
        candidates.append((year, urljoin(root_url, href)))

    unique_by_year: dict[int, str] = {}
    for year, url in candidates:
        unique_by_year.setdefault(year, url)

    selected_years = sorted(unique_by_year, reverse=True)[:limit]
    return [unique_by_year[year] for year in selected_years]
