from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from portal.auth import (
    USER_COOKIE_MAX_AGE,
    USER_COOKIE_NAME,
    fetch_user_by_id,
    list_all_users,
)
from portal.db import connect_db, normalize_db_path
from portal.infrastructure import config


router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        users = await list_all_users(conn)
    finally:
        await conn.close()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "login.html",
        {"users": users},
    )


@router.post("/login")
async def login_submit(user_id: str = Form(...)) -> RedirectResponse:
    conn = await connect_db(normalize_db_path(config.DB_PATH))
    try:
        user = await fetch_user_by_id(conn, user_id)
    finally:
        await conn.close()
    if user is None:
        return RedirectResponse("/login", status_code=303)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        key=USER_COOKIE_NAME,
        value=user.user_id,
        max_age=USER_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(USER_COOKIE_NAME)
    return response
