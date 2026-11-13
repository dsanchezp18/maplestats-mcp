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


async def test_a_module_that_fails_to_import_says_so(monkeypatch):
    # fastmcp logs a provider's error and answers "Unknown tool", which reached the
    # caller as "Unknown tool: 'call_tool'" (a missing pypdf, 2026-11-10).
    from fastmcp import Client
    from mcp.types import TextContent

    built = server.build_server()
    provider = next(p for p in _lazy(built) if p._root.name == "cdc")

    def broken(files):
        raise ModuleNotFoundError("No module named 'pypdf'")

    monkeypatch.setattr(provider, "_import", broken)
    monkeypatch.setattr(server, "_LOAD_ERRORS", {})
    name = next(iter(provider._names))
    async with Client(built) as client:
        result = await client.call_tool(
            "call_tool", {"name": name, "arguments": {}}, raise_on_error=False
        )
    block = result.content[0]
    assert isinstance(block, TextContent)
    text = block.text
    assert result.is_error
    assert text.startswith("[module_unavailable]"), text
    assert "the cdc module failed to load (ModuleNotFoundError: No module named 'pypdf')" in text
    assert "Unknown tool" not in text


async def test_preload_skips_a_broken_module_and_still_builds_the_index(monkeypatch, caplog):
    built = server.build_server()
    providers = _lazy(built)
    broken = next(p for p in providers if p._root.name == "cdc")

    def fail(files):
        raise ImportError("boom")

    monkeypatch.setattr(broken, "_import", fail)
    monkeypatch.setattr(server, "_LOAD_ERRORS", {})
    with caplog.at_level(logging.WARNING, logger="maplestats_mcp.server"):
        await server.preload(built)

    assert not broken.loaded
    assert all(p.loaded for p in providers if p is not broken)
    assert _transform(built)._indexed
    assert "failed to load" in caplog.text


async def test_a_failed_import_is_remembered_and_not_retried(monkeypatch):
    built = server.build_server()
    provider = next(p for p in _lazy(built) if p._root.name == "cdc")
    calls: list[int] = []

    def fail(files):
        calls.append(1)
        raise ImportError("boom")

    monkeypatch.setattr(provider, "_import", fail)
    monkeypatch.setattr(server, "_LOAD_ERRORS", {})
    for _ in range(3):
        with pytest.raises(server.ModuleUnavailable, match="cdc module failed to load"):
            provider._load_tools()
    assert len(calls) == 1


async def test_a_failed_extras_import_is_remembered_and_recorded(monkeypatch):
    built = server.build_server()
    provider = next(p for p in _lazy(built) if p._extra_files)
    calls: list[int] = []

    def fail(files):
        calls.append(1)
        raise ImportError("boom")

    monkeypatch.setattr(provider, "_import", fail)
    monkeypatch.setattr(server, "_LOAD_ERRORS", {})
    for _ in range(3):
        with pytest.raises(server.ModuleUnavailable, match="module failed to load"):
            await provider._list_resources()
    assert len(calls) == 1
    assert set(server._LOAD_ERRORS) == set(provider._names)


async def test_the_load_error_callers_see_has_no_server_paths(monkeypatch, caplog):
    built = server.build_server()
    provider = next(p for p in _lazy(built) if p._root.name == "cdc")
    raw = "cannot import name 'x' from 'y' (/app/src/maplestats_mcp/modules/cdc/client.py)"

    def fail(files):
        raise ImportError(raw)

    monkeypatch.setattr(provider, "_import", fail)
    monkeypatch.setattr(server, "_LOAD_ERRORS", {})
    with (
        caplog.at_level(logging.ERROR, logger="maplestats_mcp.server"),
        pytest.raises(server.ModuleUnavailable) as caught,
    ):
        provider._load_tools()
    message = str(caught.value)
    assert "/app/src" not in message
    assert "ImportError: cannot import name 'x' from 'y'" in message
    assert all("/app/src" not in reason for reason in server._LOAD_ERRORS.values())
    # The server log keeps the full text for whoever fixes the deployment.
    assert raw in caplog.text
