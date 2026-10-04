"""How a tool attaches provenance and signals failure.

Confirmed directly against the installed fastmcp==4.0.3 this session:
when a @tool function's return type annotation is a Pydantic BaseModel,
FastMCP derives outputSchema from the model's JSON schema and populates
structuredContent from the returned instance automatically — a tool
just needs to `return SomeModel(...)`, no manual envelope-building
required. Likewise, raising a plain exception from a tool propagates as
`isError: true` with the exception message as the content, confirmed via
an in-memory Client call. So this module's job is narrow: build the
`Provenance` block every response model embeds, and raise the right
typed error (see shared/errors.py) with a bilingual message instead of
returning an error-shaped dict that looks like a success — a
recognized anti-pattern in MCP servers generally, not just here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import NoReturn

from maplestats_mcp.shared.i18n import ERROR_KEYS, french_spacing, normalize_lang, t
from maplestats_mcp.shared.licences import licence_for
from maplestats_mcp.shared.models import Provenance

# Statistics Canada Open Licence (https://www.statcan.gc.ca/en/reference/licence):
# attribution is required, and adapted data must not imply StatCan endorsed the
# adaptation. Added to every result whose source or URL is a StatCan service,
# in French for a call made with lang="fr".
STATCAN_LICENCE = t("provenance.statcan_licence", "en")
STATCAN_LICENCE_FR = t("provenance.statcan_licence", "fr")


def _licence_for(source: str, url: str, lang: str = "en") -> str | None:
    """StatCan's licence in the call's language; every other source from shared/licences."""
    if source.lower().startswith("statcan") or "statcan.gc.ca" in url.lower():
        return t("provenance.statcan_licence", lang)
    return licence_for(source, url, lang)


def make_provenance(
    *,
    source: str,
    url: str,
    cached: bool,
    schema_name: str,
    as_of: datetime | None = None,
    freshness: str | None = None,
    coverage: str | None = None,
    limits: str | None = None,
    licence: str | None = None,
    lang: str = "en",
) -> Provenance:
    """Build the Provenance block every response model embeds.

    `lang="fr"` gives the shared phrases (the reproduce_code note and the
    licence, where shared/licences has French text for the source) in
    French; the caller's own freshness, coverage and limits text is used
    as given (shared.i18n.pick writes it in the call's language).
    """
    lang = normalize_lang(lang)
    return Provenance(
        source=source,
        url=url,
        queried_at=datetime.now(UTC),
        as_of=as_of,
        freshness=freshness,
        coverage=coverage,
        limits=limits,
        cached=cached,
        schema_name=schema_name,
        licence=licence or _licence_for(source, url, lang),
        reproduce=t("provenance.reproduce", lang),
    )


def raise_error(
    exc_cls: type[ValueError],
    key: str,
    lang: str = "en",
    **kwargs: object,
) -> NoReturn:
    """Format the bilingual message for `key` and raise `exc_cls` with it.

    `key` is an i18n template (see shared/i18n.LABELS, or one a module
    added with i18n.register()); `lang` picks its French text. Raising
    (not returning) is deliberate: FastMCP turns this into a real MCP
    `isError: true` result, which is what lets an agent distinguish "the
    query failed" from "the query succeeded with an empty result."
    """
    raise exc_cls(t(key, lang, **kwargs))


def raise_typed(exc_cls: type[ValueError], detail: str, lang: str = "en") -> NoReturn:
    """Raise `exc_cls` with its own template ("Invalid input: ...", "Entrée invalide : ...").

    The shortest path for a module: the class picks the template, so only
    the detail and the call's `lang` are needed.
    """
    key = next(
        (ERROR_KEYS[cls.__name__] for cls in exc_cls.__mro__ if cls.__name__ in ERROR_KEYS),
        None,
    )
    raise exc_cls(t(key, lang, detail=detail) if key else detail)


def raise_localized(exc_cls: type[ValueError], en: str, fr: str, lang: str = "en") -> NoReturn:
    """Raise `exc_cls` with `en` as written, or in French through its typed template.

    English stays exactly the module's own message; with `lang="fr"` the
    French detail goes through raise_typed's template ("Entrée invalide :
    ...") with French typography.
    """
    if normalize_lang(lang) != "fr":
        raise exc_cls(en)
    key = next(
        (ERROR_KEYS[cls.__name__] for cls in exc_cls.__mro__ if cls.__name__ in ERROR_KEYS),
        None,
    )
    raise exc_cls(french_spacing(t(key, "fr", detail=fr) if key else fr))
