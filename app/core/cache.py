from typing import Any, Optional

from cachetools import TTLCache

_store: TTLCache = TTLCache(maxsize=64, ttl=3600)


def _rebuild(ttl: int):
    global _store
    if _store.ttl != ttl:
        new = TTLCache(maxsize=64, ttl=ttl)
        new.update(_store)
        _store = new


def get_cached(key: str) -> Optional[Any]:
    from app.core.config import get_settings
    _rebuild(get_settings().cache_ttl_seconds)
    return _store.get(key)


def set_cached(key: str, value: Any) -> None:
    from app.core.config import get_settings
    _rebuild(get_settings().cache_ttl_seconds)
    _store[key] = value


def clear_all() -> None:
    _store.clear()
