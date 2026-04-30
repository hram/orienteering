from __future__ import annotations

import os


DB_PATH = os.getenv("ORIENTEERING_PORTAL_DB_PATH", "./data/orienteering.sqlite3")
UPLOAD_DIR = os.getenv("ORIENTEERING_PORTAL_UPLOAD_DIR", "./data/uploads")
MAP_DIR = os.getenv("ORIENTEERING_PORTAL_MAP_DIR", "./data/maps")
CLAUDE_CLI_PATH = os.getenv("CLAUDE_CLI_PATH", "/home/hram/.local/bin/claude")
