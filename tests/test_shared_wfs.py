"""How shared/wfs.py turns an upstream HTTP error into a typed error."""

import httpx
import pytest

from maplestats_mcp.shared import wfs
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable


def _error(status: int, text: str) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://wfs.example/ows")
    body = (
        '<ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1">'
        f"<ows:Exception><ows:ExceptionText>{text}</ows:ExceptionText></ows:Exception>"
        "</ows:ExceptionReport>"
    )
    response = httpx.Response(status, content=body.encode(), request=request)
    return httpx.HTTPStatusError("error", request=request, response=response)


@pytest.mark.parametrize(
    ("status", "text", "expected"),
    [
        (400, "Unknown property name", InvalidInput),
        (404, "No such layer", NotFound),
        (500, "Internal error", UpstreamError),
        # A server-side database pool failure is the service being down, not a bad request.
        (
            400,
            (
                "Unable to obtain connection: HikariPool idwprod1 ORA-02391: exceeded "
                "simultaneous SESSIONS_PER_USER limit"
            ),
            UpstreamUnavailable,
        ),
        (429, "Too many requests", UpstreamUnavailable),
    ],
)
def test_wfs_http_errors_are_typed(status, text, expected):
    with pytest.raises(expected):
        wfs._raise_for_status_error(_error(status, text), "layer query")
