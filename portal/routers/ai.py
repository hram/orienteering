from __future__ import annotations

import json
import base64
import subprocess
import uuid
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from portal.infrastructure import config


router = APIRouter()


class SplitChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1)


class SplitChatRequest(BaseModel):
    training_id: str
    split: dict
    messages: list[SplitChatMessage] = Field(default_factory=list, max_length=12)
    question: str = Field(..., min_length=1, max_length=2000)
    image_data_url: str | None = None


@router.post("/split-analysis/chat")
async def split_analysis_chat(body: SplitChatRequest) -> dict[str, str]:
    image_path = save_split_snapshot(body.image_data_url)
    prompt = build_split_chat_prompt(body, image_path)
    try:
        answer = await run_claude_prompt(prompt, image_path.parent if image_path else None)
    except FileNotFoundError:
        answer = f"Claude CLI не найден: {config.CLAUDE_CLI_PATH}"
    except Exception as exc:
        answer = f"Не удалось получить ответ тренера: {exc}"
    return {"answer": answer}


def build_split_chat_prompt(body: SplitChatRequest, image_path: Path | None = None) -> str:
    split = body.split
    messages = "\n".join(
        f"{'Юная спортсменка' if item.role == 'user' else 'Тренер'}: {item.content}"
        for item in body.messages[-8:]
    )
    context = json.dumps(split, ensure_ascii=False, indent=2)
    image_section = (
        f"""Карта выбранного сплита сохранена в файле:
{image_path}

Обязательно открой это изображение и используй карту как главный источник для разбора.
На картинке: фон — спортивная карта, синяя линия — путь спортсменки по GPS, розовая линия со стрелкой — направление сплита, круги — контрольные точки.
"""
        if image_path
        else "Изображение карты не передано. Не делай выводы о препятствиях и выборе пути по карте.\n"
    )
    return f"""Ты AI-тренер по спортивному ориентированию для девочки 13 лет.
Говори по-русски, спокойно, коротко и поддерживающе. Не ругай.
Разбирай только выбранный сплит, не всю дистанцию.
Если карта передана, анализируй выбор пути по карте: здания, заборы, зелёнку, дороги, открытые места, обходы и возможные варианты.

Формат ответа:
- 2-5 коротких предложений;
- без markdown-таблиц;
- один конкретный совет в конце.

Визуальный контекст:
{image_section}

Контекст сплита:
{context}

История диалога:
{messages or "пока нет"}

Новый вопрос:
{body.question}
"""


def save_split_snapshot(image_data_url: str | None) -> Path | None:
    if not image_data_url:
        return None
    prefix = "data:image/png;base64,"
    if not image_data_url.startswith(prefix):
        return None
    raw = base64.b64decode(image_data_url[len(prefix) :], validate=True)
    output_dir = Path(config.UPLOAD_DIR).expanduser() / "split-analysis"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{uuid.uuid4().hex}.png"
    output_path.write_bytes(raw)
    return output_path.resolve()


async def run_claude_prompt(prompt: str, allowed_dir: Path | None = None) -> str:
    command = [
        config.CLAUDE_CLI_PATH,
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    if allowed_dir:
        command.extend(["--add-dir", str(allowed_dir)])
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    full_text: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    full_text.append(block.get("text", ""))
    process.wait(timeout=120)
    answer = "".join(full_text).strip()
    if answer:
        return answer
    stderr = process.stderr.read().strip() if process.stderr else ""
    return stderr or "Тренер не вернул ответ."
