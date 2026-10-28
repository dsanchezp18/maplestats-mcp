"""The fastmcp APIs the server relies on, checked by name.

pyproject.toml used to cap fastmcp below 4.2 because server.py overrode
private methods of BM25SearchTransform and shared/search.py replaced
fastmcp's private tokenizer. Both are gone: the search transform overrides
only public Transform hooks, and the BM25 index is shared/search.py's own.
What is left is the provider hooks fastmcp documents for overriding
("Private list/get methods (override these to provide components)" in
fastmcp/server/providers/base.py), which LazyModuleProvider replaces. If an
upgrade renames one, the override silently stops being called and every
lazily listed tool vanishes; these tests say which hook moved instead.
.github/workflows/fastmcp-latest.yml runs them against the newest fastmcp.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from pathlib import Path

import pytest
from fastmcp.server.providers import Provider
from fastmcp.server.providers.local_provider import LocalProvider
from fastmcp.server.transforms.catalog import CatalogTransform
from fastmcp.server.transforms.search import BM25SearchTransform

from maplestats_mcp import server

SRC = Path(server.__file__).parent

# The Provider hooks LazyModuleProvider overrides, and their parameters.
PROVIDER_HOOKS = {
    "_list_tools": ["self"],
    "_get_tool": ["self", "name", "version"],
    "_list_resources": ["self"],
    "_get_resource": ["self", "uri", "version"],
    "_list_resource_templates": ["self"],
    "_get_resource_template": ["self", "uri", "version"],
    "_list_prompts": ["self"],
    "_get_prompt": ["self", "name", "version"],
    "get_tasks": ["self"],
}


def _params(function: Callable[..., object]) -> list[str]:
    return list(inspect.signature(function).parameters)


@pytest.mark.parametrize(("hook", "params"), sorted(PROVIDER_HOOKS.items()))
def test_fastmcp_still_has_the_provider_hooks_the_lazy_loader_overrides(hook, params):
    for base in (Provider, LocalProvider):
        assert hasattr(base, hook), f"fastmcp's {base.__name__} no longer has {hook}"
        assert _params(getattr(base, hook)) == params, f"{base.__name__}.{hook} changed"
    assert hook in vars(server.LazyModuleProvider)


def test_fastmcp_still_has_the_transform_hooks_search_overrides():
    assert _params(CatalogTransform.transform_tools) == ["self", "tools"]
    assert _params(CatalogTransform.get_tool) == ["self", "name", "call_next", "version"]
    assert _params(CatalogTransform.get_tool_catalog) == ["self", "ctx", "run_middleware"]


def test_the_search_transform_keeps_what_build_site_reads():
    # scripts/build_site.py finds it by isinstance and ships these to the browser.
    (transform,) = [t for t in server.mcp.transforms if isinstance(t, BM25SearchTransform)]
    assert isinstance(transform, server.AnnotatedBM25SearchTransform)
    assert (transform._index.k1, transform._index.b, transform._max_results) == (1.5, 0.75, 5)
    assert transform._always_visible == set(server.SEARCH_ALWAYS_VISIBLE)


def _private_fastmcp_imports(path: Path) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("fastmcp"):
            parts = [*(node.module or "").split("."), *(alias.name for alias in node.names)]
            if any(part.startswith("_") for part in parts):
                found.append(f"{path.relative_to(SRC)}:{node.lineno}")
    return found


def test_the_server_imports_nothing_private_from_fastmcp():
    found = [hit for path in sorted(SRC.rglob("*.py")) for hit in _private_fastmcp_imports(path)]
    assert not found, f"private fastmcp imports: {found}"
