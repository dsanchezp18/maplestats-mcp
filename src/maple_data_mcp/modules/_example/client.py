"""Client stub. A real client.py calls shared/http.py's api_get/api_post
through shared/rate_limiter.py's get_limiter, and either returns a typed
model or raises a shared/errors.py exception — never both, and never a
dict shaped like an error that looks like a success.
"""

from __future__ import annotations

from maple_data_mcp.modules._example import constants
from maple_data_mcp.modules._example.schemas import EchoResult
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput


async def echo(message: str) -> EchoResult:
    if not message.strip():
        raise InvalidInput("message must not be empty.")
    return EchoResult(
        message=message,
        provenance=make_provenance(
            source="example",
            url=constants.BASE_URL,
            cached=False,
            schema_name="example.EchoResult",
        ),
    )
