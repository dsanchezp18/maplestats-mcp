"""A note for a date-bounded request that stops before the newest published data.

Agents choose date ranges from their own sense of today, which can lag by a
year or more: in November 2026 ChatGPT and Copilot sessions asked for 2024
windows when the question was about the latest figure. The sources answer
that range without complaint, and the response, with its fresh-looking
citation, read as current. This note says newer data exist, gives today's
date (Eastern Time, StatCan's and the Bank's reference zone) and names the
argument that returns the latest values. It leads `provenance.limits`.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from maplestats_mcp.shared.i18n import pick

_EASTERN = ZoneInfo("America/Toronto")


def today() -> date:
    """Today's date in Eastern Time."""
    return datetime.now(_EASTERN).date()


def newer_data_note(
    *,
    requested_end: date | None,
    latest: date | None,
    latest_args: str,
    released: str | None = None,
    lang: str = "en",
) -> str | None:
    """One sentence when `latest` is after `requested_end`, else None.

    `latest_args` names what to pass instead of the date range, e.g.
    "latest_n" or "recent=12". `released` is the release date of the newest
    data, when the source gives one.
    """
    if requested_end is None or latest is None or latest <= requested_end:
        return None
    released_en = f", released {released}" if released else ""
    released_fr = f", publiée le {released}" if released else ""
    now = today().isoformat()
    return pick(
        lang,
        f"Newer data exist: the series runs to {latest.isoformat()}{released_en}, after the "
        f"end of the range asked for ({requested_end.isoformat()}). Today is {now}; for the "
        f"latest values pass {latest_args} instead of a date range.",
        f"Des données plus récentes existent : la série va jusqu'à {latest.isoformat()}"
        f"{released_fr}, après la fin de la période demandée ({requested_end.isoformat()}). "
        f"Nous sommes le {now} ; pour les valeurs les plus récentes, passez {latest_args} "
        "au lieu d'une plage de dates.",
    )
