"""Constants for StatCan's Delta File bulk daily-update archive.

Confirmed live 2026-09-21, found via StatCan's official "Developers"
hub (statcan.gc.ca/en/developers/df). The Delta File is a ZIP
containing every table/vector data and metadata update StatCan
released on one business day -- "the preferred mechanism for users
who want to obtain large updates" per StatCan's own description.
Files are named by date (`{YYYYMMDD}.zip`) at a deterministic URL and
only exist for business days that had a release (confirmed live: a
weekend date 404s cleanly). The `www150.statcan.gc.ca` host needs
HTTP/2 offered in the TLS handshake -- see `shared/http.py`'s own
docstring for why -- which is why this module keeps a small dedicated
`httpx.AsyncClient` rather than a bare one-off request.
"""

BASE_URL = "https://www150.statcan.gc.ca/delta/{date}.zip"

RATE_LIMIT_SOURCE = "statcan-delta"
RATE_LIMIT_PER_SECOND = 5.0
RATE_LIMIT_CAPACITY = 10.0
