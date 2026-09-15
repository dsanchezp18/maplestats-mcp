"""Canned bilingual labels for error messages and shared prompt text.

Not a replacement for gettext, just a flat dict — tool bodies carry
their own EN/FR text directly via a `lang: Literal["en", "fr"]`
parameter; this module is only for the handful of shared, reused
strings (error messages) that every module's errors.py exceptions
render through.
"""

from __future__ import annotations

from typing import Any

LABELS: dict[str, dict[str, str]] = {
    "error.invalid_input": {
        "en": "Invalid input: {detail}",
        "fr": "Entrée invalide : {detail}",
    },
    "error.not_found": {
        "en": "No match found: {detail}",
        "fr": "Aucune correspondance trouvée : {detail}",
    },
    "error.upstream_error": {
        "en": "The upstream source returned something unexpected: {detail}",
        "fr": "La source amont a retourné une réponse inattendue : {detail}",
    },
    "error.upstream_unavailable": {
        "en": "The upstream source is temporarily unreachable: {detail}",
        "fr": "La source amont est temporairement inaccessible : {detail}",
    },
    "error.data_locked": {
        "en": "StatCan data is locked for its daily update (data returns at 8:30am ET): {detail}",
        "fr": "Les données de StatCan sont verrouillées pour leur mise à jour quotidienne (retour à 8h30 HE) : {detail}",
    },
}


def t(key: str, lang: str = "en", **kwargs: Any) -> str:
    entry = LABELS.get(key)
    if entry is None:
        return key
    template = entry.get(lang, entry.get("en", key))
    return template.format(**kwargs)
