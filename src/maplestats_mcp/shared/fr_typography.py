"""French spacing for the plain text a module writes itself (notes, errors, provenance).

French puts a no-break space before ":" and inside « », and a narrow
no-break space before ";", "?", "!" and "%" (the same rules the website
applies in scripts/build_site.py::french_punctuation). Source strings
are written with ordinary spaces, which are readable in an editor, and
passed through `french_spacing()` before they reach the user. A colon
with no space before it (a URL, "12:30") is left alone.
"""

from __future__ import annotations

import re

from maplestats_mcp.shared.i18n import ERROR_KEYS, t
from maplestats_mcp.shared.limits import Order, truncation_note

NBSP, NNBSP = "\u00a0", "\u202f"

_NARROW = re.compile(r"(?<=\S)[ \u00a0\u202f]([;?!])(?=\s|\)|»|$)")
_COLON = re.compile(r"(?<=\S)[ \u00a0\u202f](:)(?=\s|$)")
_PERCENT = re.compile(r"(?<=\d)[ \u00a0\u202f]%")
_OPEN = re.compile(r"«[ \u00a0\u202f]?")
_CLOSE = re.compile(r"[ \u00a0\u202f]?»")


def french_spacing(text: str) -> str:
    """`text` with French no-break spaces before : ; ? ! % and inside « »."""
    text = _NARROW.sub(NNBSP + r"\1", text)
    text = _COLON.sub(NBSP + r"\1", text)
    text = _PERCENT.sub(NNBSP + "%", text)
    text = _OPEN.sub("«" + NBSP, text)
    return _CLOSE.sub(NBSP + "»", text)


def fr_or_en(lang: str, english: str, french: str) -> str:
    """`english` for lang="en", else `french` with French spacing."""
    return french_spacing(french) if lang.lower().startswith("fr") else english


def lang_error[E: Exception](exc_cls: type[E], lang: str, english: str, french: str) -> E:
    """`exc_cls` with `english` as is for lang="en"; for French, the class's
    French template ("Entrée invalide : ...") around `french`, French-spaced.

    Returned, not raised, so the caller keeps `raise ... from exc`. The
    English message carries no template prefix, so English output is
    the same as a plain `raise exc_cls(english)`.
    """
    if not lang.lower().startswith("fr"):
        return exc_cls(english)
    key = next((ERROR_KEYS[c.__name__] for c in exc_cls.__mro__ if c.__name__ in ERROR_KEYS), None)
    return exc_cls(french_spacing(t(key, "fr", detail=french) if key else french))


# Noun phrases, so the wording agrees with any unit ("lignes", "points").
_ORDER_FR = {
    "first": "en début de liste",
    "latest": "période la plus récente",
    "top": "en tête du classement",
}


def truncation_note_lang(
    lang: str,
    *,
    returned: int,
    total: int | None,
    unit: str = "rows",
    unit_fr: str = "lignes",
    order: Order = "first",
    how_to_get_more: str | None = None,
    how_to_get_more_fr: str | None = None,
) -> str | None:
    """shared/limits.truncation_note, in French for lang="fr" (English unchanged)."""
    if not lang.lower().startswith("fr"):
        return truncation_note(
            returned=returned, total=total, unit=unit, order=order, how_to_get_more=how_to_get_more
        )
    if total is not None and returned >= total:
        return None
    count = f"{total:,}".replace(",", NNBSP) if total is not None else "davantage"
    shown = f"{returned:,}".replace(",", NNBSP)
    note = f"Résultat limité à {shown} {unit_fr} sur {count} ({_ORDER_FR[order]})"
    how = how_to_get_more_fr or ""
    note += "." if not how else f" ; {how.rstrip('.')}."
    return french_spacing(note)
