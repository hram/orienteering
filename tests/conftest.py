from __future__ import annotations

import os
import tempfile
from pathlib import Path


TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="orienteering-portal-tests-"))
(TEST_DATA_DIR / "uploads").mkdir(parents=True, exist_ok=True)
(TEST_DATA_DIR / "maps").mkdir(parents=True, exist_ok=True)

os.environ["ORIENTEERING_PORTAL_DB_PATH"] = str(TEST_DATA_DIR / "test.sqlite3")
os.environ["ORIENTEERING_PORTAL_UPLOAD_DIR"] = str(TEST_DATA_DIR / "uploads")
os.environ["ORIENTEERING_PORTAL_MAP_DIR"] = str(TEST_DATA_DIR / "maps")
os.environ["ORIENTEERING_PORTAL_AUTO_LOGIN"] = "evgeny"


def fetch_user_id(username: str) -> str:
    import sqlite3

    con = sqlite3.connect(os.environ["ORIENTEERING_PORTAL_DB_PATH"])
    try:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT user_id FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    finally:
        con.close()
    if row is None:
        raise RuntimeError(f"User {username} not found in test DB")
    return row["user_id"]
