from __future__ import annotations

import os
from dataclasses import dataclass

import aiosqlite


USER_COOKIE_NAME = "portal_user_id"
USER_COOKIE_MAX_AGE = 60 * 60 * 24 * 365
AUTO_LOGIN_ENV = "ORIENTEERING_PORTAL_AUTO_LOGIN"


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    username: str
    display_name: str
    is_admin: bool = False


def _row_to_user(row: aiosqlite.Row | None) -> CurrentUser | None:
    if row is None:
        return None
    return CurrentUser(
        user_id=row["user_id"],
        username=row["username"],
        display_name=row["display_name"],
        is_admin=bool(row["is_admin"]),
    )


async def fetch_user_by_id(conn: aiosqlite.Connection, user_id: str) -> CurrentUser | None:
    cursor = await conn.execute(
        "SELECT user_id, username, display_name, is_admin FROM users WHERE user_id = ?",
        (user_id,),
    )
    return _row_to_user(await cursor.fetchone())


async def fetch_user_by_username(conn: aiosqlite.Connection, username: str) -> CurrentUser | None:
    cursor = await conn.execute(
        "SELECT user_id, username, display_name, is_admin FROM users WHERE username = ?",
        (username,),
    )
    return _row_to_user(await cursor.fetchone())


async def list_all_users(conn: aiosqlite.Connection) -> list[CurrentUser]:
    cursor = await conn.execute(
        "SELECT user_id, username, display_name, is_admin FROM users ORDER BY display_name"
    )
    rows = await cursor.fetchall()
    return [_row_to_user(row) for row in rows]


def auto_login_username() -> str | None:
    return os.environ.get(AUTO_LOGIN_ENV) or None
