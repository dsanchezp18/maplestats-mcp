"""Typed exceptions every module raises instead of returning a fake-success dict.

Each maps to a distinct MCP error code in envelope.make_error's isError
response. A bare ValueError (including json.JSONDecodeError and
pydantic.ValidationError, which subclass it) is treated as UpstreamError,
not InvalidInput — the caller's input was fine, the upstream response was
not shaped as documented.
"""

from __future__ import annotations


class InvalidInput(ValueError):
    """The caller supplied an argument this tool cannot act on."""


class NotFound(ValueError):
    """The upstream source has no record matching the request."""


class UpstreamError(ValueError):
    """The upstream API responded, but not in the documented shape."""


class UpstreamUnavailable(ValueError):
    """The upstream API is temporarily unreachable (network/5xx/timeout)."""


class CloudflareChallenge(UpstreamUnavailable):
    """The host answered with a Cloudflare bot challenge, which only a browser can pass.

    A kind of UpstreamUnavailable (so callers handling that keep working);
    modules catch this one to add where else the same data can be had.
    MapleStats never tries to defeat the challenge.
    """


class DataLocked(ValueError):
    """StatCan's WDS returns HTTP 409 during its 12am-8:30am ET update window.

    This is not a transient failure worth retrying — it is a documented,
    scheduled maintenance signal. Callers should be told when data will be
    available again, not shown a generic upstream error.
    """
