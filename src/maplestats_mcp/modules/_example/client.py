"""Client stub. A real client.py calls shared/http.py's api_get/api_post
through shared/rate_limiter.py's get_limiter, and either returns a typed
model or raises a shared/errors.py exception — never both, and never a
dict shaped like an error that looks like a success.

Every client function takes `lang` (the tool passes its own `lang` through)
and words its errors with `raise_localized(exc_cls, english, french, lang)`
and its provenance with `make_provenance(..., lang=lang)`, so a French call
gets French errors and a French licence line. A copy of this module keeps
that wiring; dropping `lang` from the client leaves the tool's `lang`
parameter doing nothing.
"""

from __future__ import annotations

from maplestats_mcp.modules._example import constants
from maplestats_mcp.modules._example.schemas import EchoResult
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput


async def echo(message: str, *, lang: str = "en") -> EchoResult:
    if not message.strip():
        raise_localized(
            InvalidInput,
            "message must not be empty.",
            "message ne doit pas être vide.",
            lang,
        )
    return EchoResult(
        message=message,
        provenance=make_provenance(
            source="example",
            url=constants.BASE_URL,
            cached=False,
            schema_name="example.EchoResult",
            lang=lang,
        ),
    )
