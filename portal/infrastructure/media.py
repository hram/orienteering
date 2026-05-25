from __future__ import annotations

from pathlib import Path

from portal.infrastructure import config


def map_image_url(image_path: str | None) -> str | None:
    """Build the public ``/uploads/...`` URL for a stored map-image path.

    Stored paths may be absolute or relative to the project root (e.g.
    ``data/uploads/imports/<id>/map.jpg``). A relative path resolves against
    the process CWD, which differs between local dev and the deployed
    container, so matching it against the resolved ``UPLOAD_DIR`` fails after
    a data migration. When that happens, fall back to the path tail after the
    ``uploads`` segment, which always equals the file's path relative to the
    uploads directory mounted at ``/uploads``.
    """
    if not image_path:
        return None
    upload_root = Path(config.UPLOAD_DIR).expanduser().resolve()
    resolved_image = Path(image_path).expanduser().resolve()
    try:
        relative = resolved_image.relative_to(upload_root)
    except ValueError:
        parts = Path(image_path).parts
        if "uploads" not in parts:
            return None
        last_uploads = len(parts) - 1 - parts[::-1].index("uploads")
        relative = Path(*parts[last_uploads + 1:])
        if not relative.parts:
            return None
    return f"/uploads/{relative.as_posix()}"
