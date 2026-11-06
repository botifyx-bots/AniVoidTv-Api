"""Tiny JSON-file storage: atomic writes + mtime-aware in-memory read cache."""
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .config import settings


def path_of(name: str) -> Path:
    return settings.data_dir / name


def write_json(name: str, obj: Any) -> None:
    """Write atomically: readers either see the old file or the complete new one."""
    path = path_of(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            if settings.json_pretty:
                json.dump(obj, f, ensure_ascii=False, indent=2)
            else:
                json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


_cache: dict[str, tuple[float, Any]] = {}


def read_json(name: str) -> Any | None:
    path = path_of(name)
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        _cache.pop(name, None)
        return None
    hit = _cache.get(name)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    _cache[name] = (mtime, obj)
    return obj
