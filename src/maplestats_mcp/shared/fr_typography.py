"""Bilingual helpers for the text a module writes itself (notes, errors, provenance).

French spacing comes from shared/i18n.french_spacing (no-break spaces
before : ; ? ! % » and after «). Source strings are written with
ordinary spaces, readable in an editor, and passed through these helpers
before they reach the user. English text is returned exactly as given,
so a module's English output does not change.
"""

from __future__ import annotations

from maplestats_mcp.shared.i18n import ERROR_KEYS, NBSP, french_spacing, t
from maplestats_mcp.shared.limits import Order, truncation_note

__all__ = ["NBSP", "fr_or_en", "french_spacing", "lang_error", "truncation_note_lang"]


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
    # t() spaces the French template and its detail.
    return exc_cls(t(key, "fr", detail=french) if key else french_spacing(french))


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
    count = f"{total:,}".replace(",", NBSP) if total is not None else "davantage"
    shown = f"{returned:,}".replace(",", NBSP)
    note = f"Résultat limité à {shown} {unit_fr} sur {count} ({_ORDER_FR[order]})"
    how = how_to_get_more_fr or ""
    note += "." if not how else f" ; {how.rstrip('.')}."
    return french_spacing(note)
