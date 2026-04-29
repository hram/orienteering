# Orienteering Portal

Локальный портал для анализа тренировок по спортивному ориентированию.

Стек намеренно повторяет `running-portal`: FastAPI, Jinja2 templates, static JS/CSS,
SQLite через `aiosqlite`, тесты на `pytest`.

## Setup

```bash
pip install -e ".[dev]"
cp .env.example .env
```

## Run

```bash
uvicorn portal.main:app --reload --port 8002
```

## Test

```bash
python -m pytest tests/ -v
```
