"""Canned bilingual labels for error messages and shared prompt text.

Not a replacement for gettext, just a flat dict — tool bodies carry
their own EN/FR text directly via a `lang: Literal["en", "fr"]`
parameter; this module is for the shared, reused strings: the typed
error templates (raised through envelope.raise_error/raise_typed), the
provenance phrases make_provenance adds, and any templates a module
registers for itself with register().
"""

from __future__ import annotations

import re
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
        "fr": "La source amont a renvoyé une réponse inattendue : {detail}",
    },
    "error.upstream_unavailable": {
        "en": "The upstream source is temporarily unreachable: {detail}",
        "fr": "La source amont est temporairement inaccessible : {detail}",
    },
    "error.data_locked": {
        "en": "StatCan data is locked for its daily update (data returns at 8:30am ET): {detail}",
        "fr": "Les données de StatCan sont verrouillées pour leur mise à jour quotidienne (retour à 8 h 30, HE) : {detail}",
    },
    "provenance.reproduce": {
        "en": (
            "For R, Python, Stata and Julia scripts that fetch and clean this data, call "
            "reproduce_code with this tool's name and arguments."
        ),
        "fr": (
            "Pour obtenir des scripts R, Python, Stata et Julia qui récupèrent et nettoient "
            "ces données, appelez reproduce_code avec le nom de cet outil et ses arguments."
        ),
    },
    "provenance.statcan_licence": {
        "en": (
            "Source: Statistics Canada. Contains information licensed under the Statistics "
            "Canada Open Licence (https://www.statcan.gc.ca/en/reference/licence). Adapted or "
            "summarised data must not be presented as endorsed by Statistics Canada."
        ),
        "fr": (
            "Source : Statistique Canada. Contient des renseignements visés par la Licence "
            "ouverte de Statistique Canada (https://www.statcan.gc.ca/fr/reference/licence). "
            "Les données adaptées ou résumées ne doivent pas être présentées comme approuvées "
            "par Statistique Canada."
        ),
    },
}

# The template key for each typed error, so a module can raise with only a
# detail and a language (envelope.raise_typed). Keyed by class name to keep
# this module free of imports from errors.py.
ERROR_KEYS: dict[str, str] = {
    "InvalidInput": "error.invalid_input",
    "NotFound": "error.not_found",
    "UpstreamError": "error.upstream_error",
    "UpstreamUnavailable": "error.upstream_unavailable",
    "DataLocked": "error.data_locked",
}


def normalize_lang(lang: str | None) -> str:
    """'fr' for any French tag ('fr', 'fr-CA', 'FR'), else 'en'."""
    return "fr" if (lang or "").strip().lower().startswith("fr") else "en"


NBSP = " "
# French puts a space before : ; ? ! % and » and after «; the space must not
# break. Only a space already there is changed, so URLs ("https://", "?q=")
# and English text are left as they are, and running it twice changes nothing.
_FRENCH_SPACE_BEFORE = re.compile(r" ([:;?!%»])")
_FRENCH_SPACE_AFTER = re.compile(r"« ")


def french_spacing(text: str) -> str:
    """French text with no-break spaces before : ; ? ! % » and after «."""
    text = _FRENCH_SPACE_BEFORE.sub(NBSP + r"\1", text)
    return _FRENCH_SPACE_AFTER.sub("«" + NBSP, text)


def pick(lang: str | None, en: str, fr: str) -> str:
    """`en` as written, or `fr` with french_spacing when `lang` is French.

    For the text a module writes itself (notes, provenance freshness,
    coverage and limits, field descriptions), so the English output stays
    exactly as it was.
    """
    return french_spacing(fr) if normalize_lang(lang) == "fr" else en


def t(key: str, lang: str = "en", **kwargs: Any) -> str:
    """The `lang` text for `key`, formatted; English when no French exists.

    An unknown key is returned as is, so a module can pass a literal
    message where a template is expected. French text gets no-break
    spaces before its punctuation (french_spacing).
    """
    entry = LABELS.get(key)
    if entry is None:
        return key
    lang = normalize_lang(lang)
    template = entry.get(lang, entry.get("en", key))
    text = template.format(**kwargs)
    return french_spacing(text) if lang == "fr" and "fr" in entry else text


def register(labels: dict[str, dict[str, str]]) -> None:
    """Add a module's own bilingual templates, e.g. {"cmhc.no_rows": {"en": ..., "fr": ...}}.

    Keys should start with the module's name. Re-registering a key with the
    same text is allowed (module reloads in tests); different text is an
    error, because two modules would otherwise overwrite each other.
    """
    for key, entry in labels.items():
        if "en" not in entry:
            raise ValueError(f"i18n label {key!r} has no English text.")
        existing = LABELS.get(key)
        if existing is not None and existing != entry:
            raise ValueError(f"i18n label {key!r} is already registered with other text.")
        LABELS[key] = dict(entry)
