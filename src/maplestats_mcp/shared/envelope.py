"""How a tool attaches provenance and signals failure.

Confirmed directly against the installed fastmcp==4.0.3 this session:
when a @tool function's return type annotation is a Pydantic BaseModel,
FastMCP derives outputSchema from the model's JSON schema and populates
structuredContent from the returned instance automatically — a tool
just needs to `return SomeModel(...)`, no manual envelope-building
required. Likewise, raising a plain exception from a tool propagates as
`isError: true` with the exception message as the content, confirmed via
an in-memory Client call. So this module's job is narrow: build the
`Provenance` block every response model embeds, and raise the right
typed error (see shared/errors.py) with a bilingual message instead of
returning an error-shaped dict that looks like a success — a
recognized anti-pattern in MCP servers generally, not just here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import NoReturn

from maplestats_mcp.shared.i18n import t
from maplestats_mcp.shared.models import Provenance


def make_provenance(
    *,
    source: str,
    url: str,
    cached: bool,
    schema_name: str,
    as_of: datetime | None = None,
    freshness: str | None = None,
    coverage: str | None = None,
    limits: str | None = None,
) -> Provenance:
    """Build the Provenance block every response model embeds."""
    return Provenance(
        source=source,
        url=url,
        queried_at=datetime.now(UTC),
        as_of=as_of,
        freshness=freshness,
        coverage=coverage,
        limits=limits,
        cached=cached,
        schema_name=schema_name,
    )


def raise_error(
    exc_cls: type[ValueError],
    key: str,
    lang: str = "en",
    **kwargs: object,
) -> NoReturn:
    """Format the bilingual message for `key` and raise `exc_cls` with it.

    Raising (not returning) is deliberate: FastMCP turns this into a real
    MCP `isError: true` result, which is what lets an agent distinguish
    "the query failed" from "the query succeeded with an empty result."
    """
    raise exc_cls(t(key, lang, **kwargs))
