"""The hosted server preloads every module at startup; stdio stays lazy.

The lazy providers import a module the first time one of its tools is called,
on the event loop, which held every other request on the hosted server after a
start. asgi.py runs server.preload() in the lifespan startup, before uvicorn
opens the port, when MAPLE_PRELOAD allows (on for HTTP, off for stdio).
"""

from __future__ import annotations

import logging

import pytest

from maplestats_mcp import config, server


def _lazy(mcp) -> list[server.LazyModuleProvider]:
    return [p for p in mcp.providers if isinstance(p, server.LazyModuleProvider)]


def _transform(mcp) -> server.AnnotatedBM25SearchTransform:
    return next(t for t in mcp.transforms if isinstance(t, server.AnnotatedBM25SearchTransform))


async def test_preload_loads_every_module_and_builds_the_index():
    built = server.build_server()
    providers = _lazy(built)
    assert len(providers) == len(server.module_dirs())
    assert not any(p.loaded for p in providers)
    assert _transform(built)._indexed == []

    await server.preload(built)

    assert all(p.loaded for p in providers)
    # Every catalogued tool now resolves to its imported function.
    for provider in providers:
        for name in provider._names:
            tool = await super(server.LazyModuleProvider, provider)._get_tool(name)
            assert tool is not None, f"{name} was not imported by preload"
    # The index covers what search_tools ranks, so the first search reuses it.
    searchable = await server.searchable_tools(built)
    assert {t.name for t in _transform(built)._indexed} == {t.name for t in searchable}
    indexed_hash = _transform(built)._last_hash
    await _transform(built)._search(searchable, "unemployment rate")
    assert _transform(built)._last_hash == indexed_hash


async def test_without_preload_a_module_loads_on_its_first_call():
    built = server.build_server()
    provider = next(p for p in _lazy(built) if p._root.name == "boc")
    other = next(p for p in _lazy(built) if p._root.name == "cdc")
    assert not provider.loaded

    tool = await built.get_tool("boc_get_observations")

    assert tool is not None
    assert provider._tools_loaded
    assert not other._tools_loaded


@pytest.mark.parametrize(
    ("transport", "raw", "expected"),
    [
        ("http", None, True),
        ("stdio", None, False),
        ("http", "0", False),
        ("http", "off", False),
        ("stdio", "1", True),
        ("stdio", " TRUE ", True),
    ],
)
def test_preload_is_on_for_http_and_off_for_stdio_unless_set(
    monkeypatch: pytest.MonkeyPatch, transport: str, raw: str | None, expected: bool
):
    monkeypatch.setattr(config, "_serves_http", False)
    monkeypatch.setenv("MAPLE_TRANSPORT", transport)
    if raw is None:
        monkeypatch.delenv("MAPLE_PRELOAD", raising=False)
    else:
        monkeypatch.setenv("MAPLE_PRELOAD", raw)
    assert config.get_preload_enabled() is expected


def _lifespan_app(seen: list[str]):
    async def inner(scope, receive, send):
        while True:
            message = await receive()
            seen.append(message["type"])
            if message["type"] == "lifespan.shutdown":
                return

    messages = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

    async def receive():
        return next(messages)

    async def send(message):  # pragma: no cover - the inner app sends nothing
        pass

    return inner, receive, send


async def test_the_http_app_preloads_before_its_own_startup():
    from maplestats_mcp.asgi import with_startup_preload

    seen: list[str] = []
    inner, receive, send = _lifespan_app(seen)

    async def preload():
        seen.append("preload")

    app = with_startup_preload(inner, preload)
    await app({"type": "lifespan"}, receive, send)
    assert seen == ["preload", "lifespan.startup", "lifespan.shutdown"]


async def test_a_failed_preload_still_starts_the_server(caplog: pytest.LogCaptureFixture):
    from maplestats_mcp.asgi import with_startup_preload

    seen: list[str] = []
    inner, receive, send = _lifespan_app(seen)

    async def preload():
        raise RuntimeError("boom")

    app = with_startup_preload(inner, preload)
    with caplog.at_level(logging.ERROR, logger="maplestats_mcp.asgi"):
        await app({"type": "lifespan"}, receive, send)
    assert seen == ["lifespan.startup", "lifespan.shutdown"]
    assert "Preloading the modules failed" in caplog.text
