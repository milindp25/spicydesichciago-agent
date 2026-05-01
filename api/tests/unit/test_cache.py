import asyncio

from app.infrastructure.cache import TtlCache


async def test_returns_cached_within_ttl() -> None:
    cache: TtlCache[str] = TtlCache(ttl_seconds=10)
    calls = 0

    async def loader() -> str:
        nonlocal calls
        calls += 1
        return "v1"

    assert await cache.get_or_load("k", loader) == "v1"
    assert await cache.get_or_load("k", loader) == "v1"
    assert calls == 1


async def test_reloads_after_expiry() -> None:
    cache: TtlCache[str] = TtlCache(ttl_seconds=0.01)
    calls = 0

    async def loader() -> str:
        nonlocal calls
        calls += 1
        return f"v{calls}"

    await cache.get_or_load("k", loader)
    await asyncio.sleep(0.05)
    assert await cache.get_or_load("k", loader) == "v2"


async def test_invalidate_one_key() -> None:
    cache: TtlCache[str] = TtlCache(ttl_seconds=10)
    calls = 0

    async def loader() -> str:
        nonlocal calls
        calls += 1
        return f"v{calls}"

    await cache.get_or_load("k", loader)
    cache.invalidate("k")
    await cache.get_or_load("k", loader)
    assert calls == 2


async def test_clear_all() -> None:
    cache: TtlCache[str] = TtlCache(ttl_seconds=10)
    calls = 0

    async def loader_a() -> str:
        nonlocal calls
        calls += 1
        return "a"

    async def loader_b() -> str:
        nonlocal calls
        calls += 1
        return "b"

    await cache.get_or_load("a", loader_a)
    await cache.get_or_load("b", loader_b)
    cache.clear()
    await cache.get_or_load("a", loader_a)
    assert calls == 3
