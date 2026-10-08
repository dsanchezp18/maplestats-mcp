"""Template prompts.py.

Each prompt picks its body from a dict keyed by ``lang``; write a real
French body (not a word-for-word translation), never ignore ``lang``.
"""

# No `from __future__ import annotations`: FastMCP resolves a prompt's
# parameter types by name, and the stringified `Lang` alias does not resolve.
from typing import Annotated, Literal

from fastmcp.prompts import prompt

Lang = Annotated[Literal["en", "fr"], "Language: 'en' or 'fr'"]

_GUIDED_WORKFLOW = {
    "en": "1. Call example_echo(message='{topic}').\n2. Read the result's provenance block.",
    "fr": "1. Appelez example_echo(message='{topic}').\n2. Lisez le bloc de provenance du résultat.",
}

_QUICK_LOOKUP = {
    "en": "Call example_echo(message='hello') to verify the module loaded correctly.",
    "fr": "Appelez example_echo(message='bonjour') pour vérifier que le module est bien chargé.",
}


@prompt
def example_guided_workflow(topic: str, lang: Lang = "en") -> str:
    """A multi-step guided-workflow prompt, e.g. 'find X then fetch Y'."""
    return _GUIDED_WORKFLOW[lang].format(topic=topic)


@prompt
def example_quick_lookup(lang: Lang = "en") -> str:
    """A single-purpose quick-lookup prompt."""
    return _QUICK_LOOKUP[lang]
