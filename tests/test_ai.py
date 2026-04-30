from __future__ import annotations

from fastapi.testclient import TestClient

from portal.main import app
from portal.infrastructure import config
from portal.routers import ai


def test_split_analysis_chat_returns_answer(monkeypatch) -> None:
    async def fake_run_claude_prompt(prompt: str, allowed_dir=None) -> str:
        assert '"label": "1"' in prompt
        assert "Где я потеряла время?" in prompt
        return "Посмотри на выбор обхода. В следующий раз заранее проверь проход."

    monkeypatch.setattr(ai, "run_claude_prompt", fake_run_claude_prompt)

    with TestClient(app) as client:
        response = client.post(
            "/api/split-analysis/chat",
            json={
                "training_id": "training-1",
                "split": {"label": "1", "from": "С", "via": ["К"], "to": "1"},
                "messages": [],
                "question": "Где я потеряла время?",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "answer": "Посмотри на выбор обхода. В следующий раз заранее проверь проход."
    }


def test_split_analysis_chat_saves_snapshot(monkeypatch, tmp_path) -> None:
    seen = {}

    async def fake_run_claude_prompt(prompt: str, allowed_dir=None) -> str:
        seen["prompt"] = prompt
        seen["allowed_dir"] = allowed_dir
        return "Вижу карту сплита."

    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(ai, "run_claude_prompt", fake_run_claude_prompt)

    with TestClient(app) as client:
        response = client.post(
            "/api/split-analysis/chat",
            json={
                "training_id": "training-1",
                "split": {"label": "1", "from": "С", "via": ["К"], "to": "1"},
                "messages": [],
                "question": "Что видно на карте?",
                "image_data_url": "data:image/png;base64,iVBORw0KGgo=",
            },
        )

    assert response.status_code == 200
    assert response.json()["answer"] == "Вижу карту сплита."
    assert "Карта выбранного сплита сохранена" in seen["prompt"]
    assert seen["allowed_dir"] == (tmp_path / "split-analysis").resolve()
