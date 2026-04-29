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
