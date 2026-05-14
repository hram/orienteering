from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from portal.db import (
    connect_db,
    create_error_reason,
    get_error_reason,
    get_split_error_review,
    list_error_reasons,
    normalize_db_path,
    save_split_error_review,
    update_error_reason,
)
from portal.infrastructure import config


BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter()


class SplitReviewKey(BaseModel):
    training_id: str
    race_result_id: str | None = None
    split_label: str
    from_control_label: str
    to_control_label: str


class SaveSplitReviewPayload(SplitReviewKey):
    reason_id: str | None = None
    custom_reason: str | None = None


@router.get("/settings/error-reasons", response_class=HTMLResponse)
async def error_reasons_page(request: Request) -> HTMLResponse:
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        reasons = await list_error_reasons(conn)
    finally:
        await conn.close()
    return templates.TemplateResponse(
        request,
        "settings_error_reasons.html",
        {"reasons": reasons},
    )


@router.post("/settings/error-reasons")
async def create_error_reason_route(label: str = Form(...)) -> RedirectResponse:
    normalized_label = label.strip()
    if not normalized_label:
        raise HTTPException(status_code=400, detail="Reason label is required")
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        await create_error_reason(conn, normalized_label)
    finally:
        await conn.close()
    return RedirectResponse("/settings/error-reasons", status_code=303)


@router.post("/settings/error-reasons/{reason_id}")
async def update_error_reason_route(
    reason_id: str,
    label: str = Form(...),
    is_active: str | None = Form(None),
) -> RedirectResponse:
    normalized_label = label.strip()
    if not normalized_label:
        raise HTTPException(status_code=400, detail="Reason label is required")
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        reason = await update_error_reason(
            conn,
            reason_id,
            label=normalized_label,
            is_active=is_active == "1",
        )
    finally:
        await conn.close()
    if reason is None:
        raise HTTPException(status_code=404, detail="Reason not found")
    return RedirectResponse("/settings/error-reasons", status_code=303)


@router.get("/api/error-reasons")
async def list_error_reasons_api() -> dict:
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        reasons = await list_error_reasons(conn)
    finally:
        await conn.close()
    return {"reasons": reasons}


@router.post("/api/split-error-review/get")
async def get_split_error_review_api(payload: SplitReviewKey) -> dict:
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        review = await get_split_error_review(conn, **_model_to_dict(payload))
    finally:
        await conn.close()
    return {"review": review}


def _model_to_dict(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


@router.put("/api/split-error-review")
async def save_split_error_review_api(payload: SaveSplitReviewPayload) -> dict:
    reason_id = payload.reason_id or None
    custom_reason = payload.custom_reason.strip() if payload.custom_reason else None
    custom_reason = custom_reason or None
    if reason_id:
        conn = await connect_db(normalize_db_path(config.DB_PATH))
        try:
            reason = await get_error_reason(conn, reason_id)
            if reason is None:
                raise HTTPException(status_code=404, detail="Reason not found")
            review = await save_split_error_review(
                conn,
                training_id=payload.training_id,
                race_result_id=payload.race_result_id,
                split_label=payload.split_label,
                from_control_label=payload.from_control_label,
                to_control_label=payload.to_control_label,
                reason_id=reason_id,
                custom_reason=custom_reason,
            )
        finally:
            await conn.close()
    else:
        conn = await connect_db(normalize_db_path(config.DB_PATH))
        try:
            review = await save_split_error_review(
                conn,
                training_id=payload.training_id,
                race_result_id=payload.race_result_id,
                split_label=payload.split_label,
                from_control_label=payload.from_control_label,
                to_control_label=payload.to_control_label,
                reason_id=None,
                custom_reason=custom_reason,
            )
        finally:
            await conn.close()
    return {"review": review}
