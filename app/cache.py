"""Small in-memory TTL cache for scraped responses."""
import time
from typing import Any

_store: dict[str, tuple[float, Any]] = {}
_MAX = 500


def get(key: str) -> Any | None:
    hit = _store.get(key)
    if not hit:
        return None
    if hit[0] < time.monotonic():
        _store.pop(key, None)
        return None
    return hit[1]


def set(key: str, value: Any, ttl: float) -> None:
    if len(_store) >= _MAX:
        for k in sorted(_store, key=lambda k: _store[k][0])[: _MAX // 5]:
            _store.pop(k, None)
    _store[key] = (time.monotonic() + ttl, value)
