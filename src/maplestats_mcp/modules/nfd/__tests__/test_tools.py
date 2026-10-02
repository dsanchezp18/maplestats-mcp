from __future__ import annotations

import inspect

import pytest

from maplestats_mcp.modules.nfd import tools

TOOLS = [
    tools.nfd_list_tables,
    tools.nfd_describe_table,
    tools.nfd_query_table,
    tools.nfd_table_comments,
]


@pytest.mark.parametrize("fn", TOOLS, ids=lambda f: f.__name__)
def test_docstring_has_use_for_and_keywords(fn):
    doc = inspect.getdoc(fn) or ""
    assert "Use for:" in doc
    keywords = doc.split("Keywords:")[1].split("Mots-clés :")[0]
    assert len([k for k in keywords.replace(".", "").split(",") if k.strip()]) >= 8
    mots = doc.split("Mots-clés :")[1]
    assert len([k for k in mots.replace(".", "").split(",") if k.strip()]) >= 8


@pytest.mark.parametrize("fn", TOOLS, ids=lambda f: f.__name__)
def test_every_tool_takes_lang(fn):
    assert "lang" in inspect.signature(fn).parameters
