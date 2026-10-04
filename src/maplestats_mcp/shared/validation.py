"""Turn argument validation failures into one readable InvalidInput line.

FastMCP validates a tool's arguments with pydantic before the tool runs,
and a failure used to reach the client as pydantic's own text: several
lines naming an internal `call[tool]` model, the error type in brackets,
and a link to errors.pydantic.dev. An agent reading that has to guess
which argument was wrong and what would be accepted. This middleware
catches the ValidationError once, for every tool and for calls made
through call_tool, and raises InvalidInput naming each argument, what it
accepts, and what was sent, in French when the call has lang="fr".
"""

from __future__ import annotations

from typing import Any

from fastmcp.exceptions import DisabledError, NotFoundError, ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from pydantic import ValidationError

from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.i18n import reset_call_lang, set_call_lang, t

_TEMPLATES: dict[str, dict[str, str]] = {
    "literal": {
        "en": "{field} must be one of {expected} (got {got})",
        "fr": "{field} doit valoir {expected} (reçu {got})",
    },
    "missing": {
        "en": "{field} is required",
        "fr": "{field} est obligatoire",
    },
    "unexpected": {
        "en": "{field} is not a parameter of this tool",
        "fr": "{field} n'est pas un paramètre de cet outil",
    },
    "date": {
        "en": "{field} must be a real date as YYYY-MM-DD (got {got})",
        "fr": "{field} doit être une date réelle au format AAAA-MM-JJ (reçu {got})",
    },
    "int": {
        "en": "{field} must be a whole number (got {got})",
        "fr": "{field} doit être un nombre entier (reçu {got})",
    },
    "number": {
        "en": "{field} must be a number (got {got})",
        "fr": "{field} doit être un nombre (reçu {got})",
    },
    "bool": {
        "en": "{field} must be true or false (got {got})",
        "fr": "{field} doit valoir true ou false (reçu {got})",
    },
    "other": {
        "en": "{field}: {message} (got {got})",
        "fr": "{field} : valeur non valide, {message} (reçu {got})",
    },
}
_OR = {"en": " or ", "fr": " ou "}
_PARAMETERS = {"en": "parameters: {names}", "fr": "paramètres : {names}"}


class InvalidArguments(ToolError, InvalidInput):
    """InvalidInput raised from middleware.

    A plain exception raised outside the tool body reaches the client as an
    internal server error; FastMCP turns only ToolError into an isError
    result there, so this is both.
    """


def _kind(error_type: str) -> str:
    if error_type in ("literal_error", "enum"):
        return "literal"
    if error_type in ("missing", "missing_argument"):
        return "missing"
    if error_type in ("unexpected_keyword_argument", "extra_forbidden"):
        return "unexpected"
    if error_type.startswith(("date", "datetime")):
        return "date"
    if error_type.startswith("int"):
        return "int"
    if error_type.startswith(("float", "decimal")):
        return "number"
    if error_type.startswith("bool"):
        return "bool"
    return "other"


def _field(loc: tuple[Any, ...]) -> str:
    # The first element can be the synthetic "call[tool]" model; skip it.
    parts = [str(p) for p in loc if not str(p).startswith("call[")]
    return ".".join(parts) or "arguments"


def _got(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


def describe(exc: ValidationError, lang: str = "en", parameters: list[str] | None = None) -> str:
    """One line listing every failed argument (the message InvalidInput carries)."""
    lang = lang if lang in ("en", "fr") else "en"
    parts: list[str] = []
    unexpected = False
    for error in exc.errors(include_url=False):
        kind = _kind(error.get("type", ""))
        unexpected = unexpected or kind == "unexpected"
        context = error.get("ctx") or {}
        field = _field(tuple(error.get("loc", ())))
        if kind == "unexpected":
            # loc ends at the stray keyword itself.
            field = _field(tuple(error.get("loc", ()))[-1:])
        expected = str(context.get("expected", "")).replace(" or ", _OR[lang])
        parts.append(
            _TEMPLATES[kind][lang].format(
                field=field,
                expected=expected,
                got=_got(error.get("input")),
                message=str(error.get("msg", "")).rstrip("."),
            )
        )
    detail = "; ".join(dict.fromkeys(parts))
    if unexpected and parameters:
        detail += "; " + _PARAMETERS[lang].format(names=", ".join(parameters))
    return detail


def _validation_error(exc: BaseException) -> ValidationError | None:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, ValidationError):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


class ValidationErrorMiddleware(Middleware):
    """Re-raise a tool's argument ValidationError as a one-line InvalidInput."""

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext) -> Any:
        try:
            return await call_next(context)
        except Exception as exc:
            validation = _validation_error(exc)
            if validation is None:
                raise
            params = context.message
            name = str(getattr(params, "name", "tool"))
            arguments = getattr(params, "arguments", None) or {}
            if name == "call_tool" and isinstance(arguments, dict):
                name = str(arguments.get("name", name))
                inner = arguments.get("arguments")
                arguments = inner if isinstance(inner, dict) else {}
            lang = str(arguments.get("lang", "en")) if isinstance(arguments, dict) else "en"
            parameters = await _parameter_names(context, name)
            separator = " : " if lang == "fr" else ": "
            detail = f"{name}{separator}{describe(validation, lang, parameters)}"
            raise InvalidArguments(t("error.invalid_input", lang, detail=detail)) from None


def call_arguments(context: MiddlewareContext) -> tuple[str, dict[str, Any]]:
    """The tool's name and arguments, unwrapped from the call_tool meta-tool."""
    params = context.message
    name = str(getattr(params, "name", "tool"))
    arguments = getattr(params, "arguments", None) or {}
    if name == "call_tool" and isinstance(arguments, dict):
        name = str(arguments.get("name", name))
        inner = arguments.get("arguments")
        arguments = inner if isinstance(inner, dict) else {}
    return name, arguments if isinstance(arguments, dict) else {}


class CallLanguageMiddleware(Middleware):
    """Set i18n.call_lang() from the call's `lang` argument while the tool runs.

    Shared helpers (file downloads, ZIP and WFS readers, argument checks)
    read it to raise their errors in French on a lang="fr" call.
    """

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext) -> Any:
        _, arguments = call_arguments(context)
        token = set_call_lang(str(arguments.get("lang", "en")))
        try:
            return await call_next(context)
        finally:
            reset_call_lang(token)


async def _parameter_names(context: MiddlewareContext, name: str) -> list[str] | None:
    server = getattr(context.fastmcp_context, "fastmcp", None)
    if server is None:
        return None
    try:
        tool = await server.get_tool(name)
    except (NotFoundError, DisabledError):  # reported by the call's own error
        return None
    if tool is None:
        return None
    return sorted(tool.parameters.get("properties", {}))
