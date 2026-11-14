"""error_code and hint_for go by the error actually raised, not by what it chains."""

from __future__ import annotations

from fastmcp.exceptions import NotFoundError, ToolError

from maplestats_mcp.shared.error_hints import error_code, hint_for, with_hint
from maplestats_mcp.shared.errors import (
    InvalidInput,
    ModuleUnavailable,
    UpstreamError,
    UpstreamUnavailable,
)


def _raised_inside(outer: Exception, inner: Exception, *, cause: bool = False) -> Exception:
    try:
        try:
            raise inner
        except type(inner) as handled:
            if cause:
                raise outer from handled
            # The implicit __context__ is what is tested.
            raise outer
    except type(outer) as caught:
        return caught


def test_invalid_input_raised_while_handling_an_outage_is_coded_invalid_input():
    exc = _raised_inside(InvalidInput("year must be 2020 or later"), UpstreamUnavailable("down"))
    assert error_code(exc) == "invalid_input"
    assert "source is down" not in hint_for(exc, "en")


def test_the_same_holds_for_an_explicit_cause():
    exc = _raised_inside(InvalidInput("bad"), UpstreamUnavailable("down"), cause=True)
    assert error_code(exc) == "invalid_input"


def test_a_toolerror_wrapper_defers_to_the_error_it_wraps():
    inner = _raised_inside(InvalidInput("bad"), UpstreamUnavailable("down"))
    wrapped = _raised_inside(ToolError("Error calling tool"), inner, cause=True)
    assert error_code(wrapped) == "invalid_input"


def test_an_upstream_error_reporting_a_5xx_is_still_an_outage():
    exc = UpstreamError("the portal returned HTTP 503")
    assert error_code(exc) == "upstream_unavailable"


def test_module_unavailable_keeps_its_code_and_its_own_fix():
    # PR #247: raised while handling the "Unknown tool" NotFoundError it replaces.
    exc = _raised_inside(
        ModuleUnavailable("cdc_x cannot run on this server: ... Fix: this is a fault"),
        NotFoundError("Unknown tool: 'cdc_x'"),
    )
    assert error_code(exc) == "module_unavailable"
    hinted = with_hint(exc, "en")
    assert hinted is not None
    assert str(hinted).startswith("[module_unavailable]")
    assert "call search_tools with a plain-language" not in str(hinted)
