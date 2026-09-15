"""Template prompts.py."""

from __future__ import annotations

from typing import Annotated, Literal

from fastmcp.prompts import prompt

Lang = Annotated[Literal["en", "fr"], "Language: 'en' or 'fr'"]


@prompt
def example_guided_workflow(topic: str, lang: Lang = "en") -> str:
    """A multi-step guided-workflow prompt, e.g. 'find X then fetch Y'."""
    return f"1. Call example_echo(message='{topic}').\n2. Read the result's provenance block."


@prompt
def example_quick_lookup(lang: Lang = "en") -> str:
    """A single-purpose quick-lookup prompt."""
    return "Call example_echo(message='hello') to verify the module loaded correctly."
