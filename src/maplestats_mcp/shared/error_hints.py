"""Every failed tool call says what to do next, not only what went wrong.

A message such as "No match found: getCubeMetadata: ..." tells an agent the
call failed but not how to recover, and in CanData's public GTA benchmark
(2026-10-22) agents given bare errors declined questions they could have
answered. Modules write their own fix where they know one (WDS names the
member or the table to look up); this middleware adds a generic one, by
error class, to any error that has none, for every tool and for calls made
through call_tool.

The error keeps its class: it is re-raised as a subclass of both the
original class and fastmcp's ToolError (only a ToolError raised outside a
tool body becomes an isError result rather than an internal error), so
logging and usage counting still see NotFound, UpstreamUnavailable and so on.
"""

from __future__ import annotations

from typing import Any

from fastmcp.exceptions import NotFoundError, ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from maplestats_mcp.shared.errors import (
    DataLocked,
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)
from maplestats_mcp.shared.i18n import french_spacing, normalize_lang
from maplestats_mcp.shared.validation import call_arguments

# Already carries a next step: a module's own fix, or this middleware's on an
# inner call (call_tool runs its target through the middleware again).
_MARKERS = ("Fix:", "Solution :", "Solution :")

# Most specific first: DataLocked and UpstreamUnavailable before their bases.
_HINTS: tuple[tuple[type[BaseException], str, str], ...] = (
    (
        DataLocked,
        (
            "Fix: retry after 8:30 a.m. Eastern, when StatCan's daily update ends; until then "
            "say the data are temporarily locked rather than answering from memory."
        ),
        (
            "Solution : réessayez après 8 h 30 (heure de l'Est), à la fin de la mise à jour "
            "quotidienne de Statistique Canada ; d'ici là, dites que les données sont "
            "verrouillées plutôt que de répondre de mémoire."
        ),
    ),
    (
        UpstreamUnavailable,
        (
            "Fix: the source is down or slow. Retry once in a minute; if it still fails, say the "
            "source is unavailable. Do not answer from memory."
        ),
        (
            "Solution : la source est hors service ou lente. Réessayez une fois dans une minute ; "
            "si l'échec persiste, dites que la source est indisponible. Ne répondez pas de mémoire."
        ),
    ),
    (
        InvalidInput,
        (
            "Fix: correct the argument named above. search_tools returns this tool's inputSchema "
            "with the accepted values, and plan_query suggests the arguments for a question."
        ),
        (
            "Solution : corrigez l'argument nommé ci-dessus. search_tools renvoie l'inputSchema de "
            "cet outil avec les valeurs acceptées, et plan_query propose les arguments d'une "
            "question."
        ),
    ),
    (
        NotFound,
        (
            "Fix: check the identifier with the source's search or list tool (search_tools finds "
            "it), or widen the query. If the data do not exist, say so; do not estimate them."
        ),
        (
            "Solution : vérifiez l'identifiant avec l'outil de recherche ou de liste de la source "
            "(search_tools le trouve), ou élargissez la requête. Si les données n'existent pas, "
            "dites-le ; ne les estimez pas."
        ),
    ),
    (
        UpstreamError,
        (
            "Fix: retry once. If it fails again, find another tool for the same data with "
            "search_tools, or say the source answered with an error."
        ),
        (
            "Solution : réessayez une fois. En cas de nouvel échec, cherchez un autre outil pour "
            "les mêmes données avec search_tools, ou dites que la source a renvoyé une erreur."
        ),
    ),
    (
        NotFoundError,
        (
            "Fix: call search_tools with a plain-language description of the data, and use a "
            "tool name it returns."
        ),
        (
            "Solution : appelez search_tools avec une description des données en langage courant, "
            "et utilisez un nom d'outil qu'il renvoie."
        ),
    ),
)

_FALLBACK = (
    (
        "Fix: retry once with the same arguments. If it fails again, find another tool for the "
        "same data with search_tools, or report the failure. Do not answer from memory."
    ),
    (
        "Solution : réessayez une fois avec les mêmes arguments. En cas de nouvel échec, cherchez "
        "un autre outil pour les mêmes données avec search_tools, ou signalez l'échec. Ne répondez "
        "pas de mémoire."
    ),
)

_HINTED: dict[type[BaseException], type[BaseException]] = {}


def _chain(exc: BaseException) -> list[BaseException]:
    """`exc` and its causes: FastMCP wraps a tool's own error in a ToolError."""
    found: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in found and len(found) < 8:
        found.append(current)
        current = current.__cause__ or current.__context__
    return found


def hint_for(exc: BaseException, lang: str) -> str:
    french = normalize_lang(lang) == "fr"
    chain = _chain(exc)
    for cls, en, fr in _HINTS:
        if any(isinstance(item, cls) for item in chain):
            return french_spacing(fr) if french else en
    return french_spacing(_FALLBACK[1]) if french else _FALLBACK[0]


# A stable, machine-readable code for each error class, first in the message: an agent can
# branch on "[not_found]" without parsing the sentence, and MCP clients show the text.
# Most specific first, as in _HINTS.
_CODES: tuple[tuple[type[BaseException], str], ...] = (
    (DataLocked, "data_locked"),
    (UpstreamUnavailable, "upstream_unavailable"),
    (InvalidInput, "invalid_input"),
    (NotFound, "not_found"),
    (UpstreamError, "upstream_error"),
    (NotFoundError, "unknown_tool"),
)


def error_code(exc: BaseException) -> str:
    chain = _chain(exc)
    for cls, code in _CODES:
        if any(isinstance(item, cls) for item in chain):
            return code
    return "error"


def with_hint(exc: BaseException, lang: str) -> BaseException | None:
    """`exc` again with its code first and a next step last, or None when it has both.

    call_tool runs its target through this middleware a second time; the code and the fix
    are each added once.
    """
    message = str(exc).strip()
    coded = message.startswith("[")
    hinted = any(marker in message for marker in _MARKERS)
    if coded and hinted:
        return None
    text = message if hinted else f"{message} {hint_for(exc, lang)}"
    text = text if coded else f"[{error_code(exc)}] {text}"
    cls = type(exc)
    if isinstance(exc, ToolError):
        return cls(text)
    hinted = _HINTED.get(cls)
    if hinted is None:
        hinted = type(cls.__name__, (ToolError, cls), {"__module__": cls.__module__})
        _HINTED[cls] = hinted
    return hinted(text)


class ErrorHintMiddleware(Middleware):
    """Put a code first and a suggested fix last on every tool error, each once."""

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext) -> Any:
        try:
            return await call_next(context)
        except Exception as exc:
            _, arguments = call_arguments(context)
            hinted = with_hint(exc, str(arguments.get("lang", "en")))
            if hinted is None:
                raise
            raise hinted from exc
