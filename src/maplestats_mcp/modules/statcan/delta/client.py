"""Client for StatCan's Delta File bulk daily-update archive.

Confirmed live 2026-09-21. Existence is checked with a HEAD request
(not a full download -- these files are large: 20261001.zip is 3.9 GB) against a
dedicated `httpx.AsyncClient` with `http2=True` and
`follow_redirects=True`: `www150.statcan.gc.ca` needs HTTP/2 offered
in the handshake (see `shared/http.py`'s own docstring for the
underlying reason), and the Delta File path itself 301s to a
`/n1/...` canonical URL before answering.
"""

from __future__ import annotations

from datetime import date as date_cls

import httpx

from maplestats_mcp.modules.statcan.delta import constants
from maplestats_mcp.modules.statcan.delta.schemas import DeltaFileLink
from maplestats_mcp.modules.statcan.lang import current_lang, say
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, UpstreamUnavailable
from maplestats_mcp.shared.http import new_client, send_with_retry
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

_client = new_client(timeout=15.0, follow_redirects=True)

FILE_NOTES = [
    (
        "Released on business days about 8:30 ET; a correction arrives in the next day's file and "
        "nothing is deleted. About 47 business days are kept (statcan_delta_list_files)."
    ),
    (
        "Each zip holds codeSet.xml, YYYYMMDD.xml (cube metadata) and YYYYMMDD.csv (data, "
        "sorted by productId, scalar factors not applied); read one table without "
        "downloading with statcan_delta_read_table. Metadata schema: "
        "https://www.statcan.gc.ca/en/developers-developpeurs/df-fd/cubemetadata.zip"
    ),
]

FILE_NOTES_FR = [
    (
        "Publié les jours ouvrables vers 8 h 30, heure de l'Est ; une correction arrive dans le fichier du "
        "lendemain et rien n'est supprimé. Environ 47 jours ouvrables sont conservés "
        "(statcan_delta_list_files)."
    ),
    (
        "Chaque fichier zip contient codeSet.xml, AAAAMMJJ.xml (métadonnées des tableaux) et "
        "AAAAMMJJ.csv (données, triées par productId, sans application des facteurs "
        "scalaires) ; statcan_delta_read_table lit un tableau sans télécharger le fichier. "
        "Schéma des métadonnées (en anglais) : "
        "https://www.statcan.gc.ca/en/developers-developpeurs/df-fd/cubemetadata.zip"
    ),
]


async def get_file_link(date: str) -> DeltaFileLink:
    """Resolve the Delta File URL for one date and confirm whether it exists."""
    try:
        parsed = date_cls.fromisoformat(date)
    except ValueError as exc:
        raise InvalidInput(
            say(
                f"statcan_delta:get_file_link: expected a YYYY-MM-DD date, got {date!r}.",
                f"statcan_delta:get_file_link : date attendue au format AAAA-MM-JJ, reçu {date!r}.",
            )
        ) from exc

    url = constants.BASE_URL.format(date=parsed.strftime("%Y%m%d"))

    await _LIMITER.acquire()
    # Retried like every other StatCan call: one live HEAD timed out after
    # 15.5 s and the next answered in 0.3 s (2026-10-02).
    try:
        response = await send_with_retry(_client, "HEAD", url, timeout=15.0)
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            say(
                "statcan_delta:get_file_link did not respond in time. Try again shortly.",
                "statcan_delta:get_file_link n'a pas répondu à temps. Réessayez dans un moment.",
            )
        ) from exc

    exists = response.status_code == 200
    size_raw = response.headers.get("content-length")
    size_bytes = int(size_raw) if exists and size_raw is not None and size_raw.isdigit() else None

    return DeltaFileLink(
        date=date,
        url=url,
        exists=exists,
        size_bytes=size_bytes,
        last_modified=response.headers.get("last-modified") if exists else None,
        etag=response.headers.get("etag") if exists else None,
        notes=[say(en, fr) for en, fr in zip(FILE_NOTES, FILE_NOTES_FR, strict=True)],
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=False,
            schema_name="statcan_delta.DeltaFileLink",
            lang=current_lang(),
        ),
    )
