"""Argument checks every module shares, so a bad request fails the same way everywhere.

Two mistakes kept producing an empty *success* instead of an error: a
range whose start is after its end (a date range, a year range), and a
filter value the source does not know (a recall class, a vehicle make, a
geography). An agent reads an empty success as "there is no data", which
is the wrong conclusion in both cases. These helpers raise `InvalidInput`
with the valid values listed, so the caller can correct the request.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.fr_typography import call_error
from maplestats_mcp.shared.i18n import pick

# A long list of valid values is still useful, but past this many the
# message stops being readable; the rest are counted, not printed.
_MAX_LISTED = 40


def check_range(
    start: Any,
    end: Any,
    start_name: str = "start",
    end_name: str = "end",
) -> None:
    """Raise InvalidInput when both bounds are given and `start` is after `end`.

    Works for dates, datetimes, years (int) and ISO date strings of the
    same shape. Either bound may be None (an open range).
    """
    if start is None or end is None:
        return
    if start > end:
        raise call_error(
            InvalidInput,
            f"{start_name} ({start}) is after {end_name} ({end}); swap them or widen the range.",
            f"{start_name} ({start}) est postérieur à {end_name} ({end}) ; inversez-les ou "
            "élargissez la plage.",
        )


def format_choices(valid: Iterable[object], lang: str = "en") -> str:
    """List valid values for an error message, capped so the message stays readable."""
    values = [str(value) for value in valid]
    shown = ", ".join(values[:_MAX_LISTED])
    if len(values) > _MAX_LISTED:
        more = len(values) - _MAX_LISTED
        shown += pick(lang, f", ... ({more} more)", f", ... ({more} de plus)")
    return shown


def check_choice(
    value: str | None,
    valid: Iterable[str],
    name: str,
    *,
    case_sensitive: bool = False,
) -> str | None:
    """Return the canonical spelling of `value` from `valid`, or raise InvalidInput.

    None passes through (the filter is optional). Matching ignores case
    and surrounding spaces unless `case_sensitive` is set.
    """
    if value is None:
        return None
    options = list(valid)
    wanted = value.strip()
    for option in options:
        if option == wanted or (not case_sensitive and option.casefold() == wanted.casefold()):
            return option
    raise call_error(
        InvalidInput,
        f"{name} {value!r} is not a known value. Valid values: {format_choices(options)}.",
        f"{name} {value!r} n'est pas une valeur connue. Valeurs valides : "
        f"{format_choices(options, 'fr')}.",
    )
