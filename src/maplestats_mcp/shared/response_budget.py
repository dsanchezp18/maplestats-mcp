"""One byte budget for every tool result, and fitness-for-use caveats in its provenance.

Modules bound their own rows (shared/limits.py), but each picks its own
cap and some tools had none: a whole-table call could still send
megabytes into a model's context. This middleware is the server-wide
last line. When a result's structured content serialises to more than
MAPLE_RESPONSE_MAX_BYTES (default 200,000), it keeps a prefix of the
largest lists (limits.trim_payload: only list lengths change, so the
result still matches the tool's output schema) and says in
provenance.limits what it cut and how to get the rest. A result within
the budget is returned untouched.

The same pass fills provenance.caveats from shared/fitness.py's rules
for the tool and arguments, so every module gets them without a change.
The text content is rebuilt from the structured content whenever either
changes, so the two never disagree.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from typing import Any

import pydantic_core
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp.types import TextContent

from maplestats_mcp.shared.i18n import normalize_lang, pick
from maplestats_mcp.shared.limits import Trimmed, join_limits, response_max_bytes, trim_payload
from maplestats_mcp.shared.validation import call_arguments

logger = logging.getLogger("maplestats_mcp.response_budget")

# True while a budgeted call runs. reproduce_code and reproduce_workbook call the
# server again in-process (the context reaches that inner call); they need every
# row, and the outer call's own result is budgeted on the way out.
_inside_call: ContextVar[bool] = ContextVar("maplestats_budget_inside_call", default=False)

# Room left under the budget for the note and caveats added after trimming.
_RESERVE = 2_000

NotesFor = Callable[[str, Mapping[str, Any], str], list[str]]
_notes_for: NotesFor | None = None
_notes_loaded = False


def _fitness_rules() -> NotesFor | None:
    """shared.fitness.notes_for, imported once; None when the module is absent."""
    global _notes_for, _notes_loaded
    if not _notes_loaded:
        _notes_loaded = True
        # Imported by name: the rules module is optional, and a server without it
        # simply adds no caveats.
        try:
            module = importlib.import_module("maplestats_mcp.shared.fitness")
        except ImportError:
            module = None
        _notes_for = getattr(module, "notes_for", None)
    return _notes_for


def caveats_for(tool: str, arguments: Mapping[str, Any], lang: str) -> list[str]:
    """The fitness-for-use notes for this call, [] when no rule applies or none exist."""
    rules = _fitness_rules()
    if rules is None:
        return []
    try:
        return [str(note) for note in rules(tool, arguments, lang) if note]
    except Exception:
        # A broken rule must not fail a data call that otherwise succeeded.
        logger.exception("fitness rules failed for %s", tool)
        return []


def _provenance(payload: dict[str, Any]) -> dict[str, Any] | None:
    found = payload.get("provenance")
    if isinstance(found, dict):
        return found
    # A tool whose output schema FastMCP wraps under "result".
    inner = payload.get("result")
    if isinstance(inner, dict) and isinstance(inner.get("provenance"), dict):
        return inner["provenance"]
    return None


def trim_note(trimmed: list[Trimmed], max_bytes: int, tool: str, lang: str) -> str:
    """One sentence on what the budget cut and how to get the rest."""
    parts_en: list[str] = []
    parts_fr: list[str] = []
    for item in trimmed:
        each_en = " (across all of them)" if item.lists > 1 else ""
        each_fr = " (toutes listes confondues)" if item.lists > 1 else ""
        which = "most recent" if item.latest else "first"
        parts_en.append(
            f"the {which} {item.kept:,} of {item.total:,} items in `{item.pattern}`{each_en}"
        )
        kept_fr = f"{item.kept:,}".replace(",", " ")
        total_fr = f"{item.total:,}".replace(",", " ")
        items_fr = (
            f"{kept_fr} éléments les plus récents"
            if item.latest
            else f"{kept_fr} premiers éléments"
        )
        parts_fr.append(f"les {items_fr} sur {total_fr} de `{item.pattern}`{each_fr}")
    budget_fr = f"{max_bytes:,}".replace(",", " ")
    return pick(
        lang,
        f"Trimmed to fit MapleStats' {max_bytes:,}-byte response budget: kept "
        + "; ".join(parts_en)
        + ". For the rest, narrow the arguments (fewer series or members, a shorter "
        "period, a filter or a smaller limit), use the source's download tool "
        "(e.g. wds_get_full_table_download for a whole StatCan table), or call "
        f"reproduce_code with tool_name={tool!r} and these arguments for a script that "
        "fetches everything.",
        f"Réponse réduite au budget de {budget_fr} octets de MapleStats : seuls "
        + " ; ".join(parts_fr)
        + " sont conservés. Pour le reste, restreignez les arguments (moins de séries ou "
        "de membres, une période plus courte, un filtre ou une limite plus petite), "
        "utilisez l'outil de téléchargement de la source (par exemple "
        "wds_get_full_table_download pour un tableau entier de Statistique Canada), ou "
        f"appelez reproduce_code avec tool_name={tool!r} et ces arguments pour obtenir un "
        "script qui récupère tout.",
    )


def apply_budget(
    result: ToolResult, tool: str, arguments: Mapping[str, Any], max_bytes: int
) -> ToolResult:
    """`result` with its caveats filled and its lists trimmed to `max_bytes`.

    Returns `result` itself when nothing changes. Only a result whose
    content is the one text block FastMCP writes from the structured
    content is changed; anything else (an error, an image, a tool that
    builds its own content) passes through.
    """
    payload = result.structured_content
    if result.is_error or not isinstance(payload, dict):
        return result
    if len(result.content) != 1 or not isinstance(result.content[0], TextContent):
        return result
    lang = normalize_lang(str(arguments.get("lang", "en")))
    provenance = _provenance(payload)
    changed = False
    if provenance is not None:
        notes = caveats_for(tool, arguments, lang)
        if notes:
            existing = provenance.get("caveats")
            current = [str(n) for n in existing] if isinstance(existing, list) else []
            provenance["caveats"] = list(dict.fromkeys([*current, *notes]))
            changed = True
    # The text block is the structured content serialised; its length is the
    # cheap first check, so a result within budget is never walked.
    if len(result.content[0].text.encode()) > max_bytes:
        trimmed = trim_payload(payload, max_bytes, reserve=_RESERVE)
        if trimmed:
            changed = True
            note = trim_note(trimmed, max_bytes, tool, lang)
            if provenance is not None:
                provenance["limits"] = join_limits(provenance.get("limits"), note)
            logger.info("trimmed %s to %d bytes: %s", tool, max_bytes, trimmed)
    if not changed:
        return result
    # A wrapped result's text block is the bare value, not the {"result": ...} envelope.
    wrapped = ((result.meta or {}).get("fastmcp") or {}).get("wrap_result")
    body = payload.get("result") if wrapped else payload
    text = pydantic_core.to_json(body, fallback=str).decode()
    return ToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=payload,
        meta=result.meta,
    )


class ResponseBudgetMiddleware(Middleware):
    """Trim every tool result to the response budget and add its fitness caveats."""

    def __init__(self, max_bytes: int | None = None) -> None:
        self.max_bytes = max_bytes if max_bytes is not None else response_max_bytes()

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext) -> Any:
        # The call_tool meta-tool runs its target through this middleware again;
        # the target's own pass does the work, once.
        if getattr(context.message, "name", None) == "call_tool" or _inside_call.get():
            return await call_next(context)
        token = _inside_call.set(True)
        try:
            result = await call_next(context)
        finally:
            _inside_call.reset(token)
        if not isinstance(result, ToolResult):
            return result
        tool, arguments = call_arguments(context)
        return apply_budget(result, tool, arguments, self.max_bytes)
