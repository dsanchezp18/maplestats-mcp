"""The call's language for StatCan error messages and notes.

A tool calls use_lang(lang) once; client code deep below it then words a
message with say(en, fr) without passing `lang` through every signature
(the same ContextVar pattern as wds/client.py). A client function that
already receives `lang` can pass it to say() directly. Messages keep their
English wording unchanged; only `lang="fr"` switches to the French text.
"""

from __future__ import annotations

from contextvars import ContextVar

from maplestats_mcp.shared.i18n import french_spacing, normalize_lang

_LANG: ContextVar[str] = ContextVar("statcan_lang", default="en")


def use_lang(lang: str | None) -> None:
    """Set the language for the rest of this tool call."""
    _LANG.set(normalize_lang(lang))


def current_lang() -> str:
    return _LANG.get()


def say(en: str, fr: str, lang: str | None = None) -> str:
    """`fr` (French-spaced) when the call (or the given `lang`) is French, else `en`."""
    chosen = normalize_lang(lang) if lang is not None else _LANG.get()
    return french_spacing(fr) if chosen == "fr" else en
