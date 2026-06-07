---
project_id: orienteering
path: /home/hram/projects/orienteering
---

## Что делает
Локальный веб-портал для анализа тренировок и стартов по спортивному ориентированию: тренировки, карты, GPX-треки, сплиты и протоколы соревнований.

## Стек
- Python 3.12+
- FastAPI, uvicorn, Jinja2
- SQLite через `aiosqlite`
- pytest и pytest-asyncio

## Архитектура
- `portal/main.py` — приложение, middleware авторизации, HTML-страницы
- `portal/db.py` — схема SQLite и доступ к данным
- `portal/services/` — GPX, georef, race protocol и импорт результатов
- `portal/routers/` — API и страницы для imports, race_results, georef, ai, auth, settings
- `templates/` и `static/` — frontend

## Текущее состояние
- Активная разработка
- Стек и структура намеренно близки к `running-portal`
- Используется для импорта тренировок, геопривязки карт, GPX-плеера и разбора сплитов

## Запуск
```bash
pip install -e ".[dev]"
cp .env.example .env
uvicorn portal.main:app --reload --port 8002
python -m pytest tests/ -v
```
