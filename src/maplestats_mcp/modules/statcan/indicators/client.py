"""Client for StatCan's official Indicators JSON feeds.

Confirmed live 2026-09-21. Most text fields are bilingual objects
(`{"en": ..., "fr": ...}`); this client resolves each to the
requested `lang` rather than exposing the raw bilingual shape.
`daily_url` is a root-relative path (e.g.
"/daily-quotidien/260617/dq260617a-eng.htm") and is resolved to an
absolute URL. `geo_code` is an int on each indicator but a string in
the response's own `geo` lookup array -- this client matches them by
string value to build a geo_code -> name map, then looks up each
indicator's name from it.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import httpx

from maplestats_mcp.modules.statcan.indicators import constants
from maplestats_mcp.modules.statcan.indicators.schemas import Indicator, IndicatorList
from maplestats_mcp.modules.statcan.lang import say, use_lang
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)


def _localized(value: Any, lang: str) -> str | None:
    if isinstance(value, dict):
        return value.get(lang) or value.get("en")
    if isinstance(value, str):
        return value
    return None


def _fold(text: str) -> str:
    """Lower case without accents, so "Québec" and "quebec" compare equal."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _geo_from_text(value: str) -> int | None:
    """A feed code from a number, a province name or an abbreviation, else None."""
    text = value.strip()
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return constants.GEO_NAMES_TO_FEED_CODE.get(_fold(text).replace(".", ""))


def _geo_in_query(query: str) -> tuple[int | None, str]:
    """Find a place named in `query`; return its feed code and the query without it.

    Full names match in any case. Two-letter abbreviations match only in capitals
    ("AB", "ON"), since "on" and "pe" are also ordinary words.
    """
    folded = _fold(query)
    names = sorted(
        (name for name in constants.GEO_NAMES_TO_FEED_CODE if len(name) > 3),
        key=len,
        reverse=True,
    )
    for name in names:
        match = re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", folded)
        if match:
            rest = query[: match.start()] + " " + query[match.end() :]
            return constants.GEO_NAMES_TO_FEED_CODE[name], rest
    for token in re.findall(r"[A-Za-z.]+", query):
        key = token.replace(".", "")
        if key.isupper() and key.lower() in constants.GEO_NAMES_TO_FEED_CODE:
            rest = re.sub(rf"(?<!\w){re.escape(token)}(?!\w)", " ", query, count=1)
            return constants.GEO_NAMES_TO_FEED_CODE[key.lower()], rest
    return None, query


def _query_terms(query: str) -> list[tuple[str, ...]]:
    """Each meaningful query word, with the forms a title may use for it."""
    terms: list[tuple[str, ...]] = []
    for word in re.findall(r"[\w%]+", _fold(query)):
        if word in constants.QUERY_STOPWORDS:
            continue
        forms = constants.QUERY_ALIASES.get(word, (word,))
        # "estimates" finds "estimate", "prices" finds "price".
        if word not in constants.QUERY_ALIASES and len(word) > 4 and word.endswith("s"):
            forms = (word, word[:-1])
        terms.append(forms)
    return terms


def _matches(title: str, terms: list[tuple[str, ...]]) -> bool:
    folded = _fold(title)
    return all(any(form in folded for form in forms) for forms in terms)


async def get_indicators(
    dataset: str = "all",
    query: str = "",
    *,
    geo_code: int | str | None = None,
    lang: str = "en",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
) -> IndicatorList:
    """Fetch current StatCan indicators, optionally filtered by keyword and geography."""
    use_lang(lang)
    url = constants.DATASET_URLS.get(dataset)
    if url is None:
        raise InvalidInput(
            say(
                f"statcan_indicators:get_indicators: dataset must be one of "
                f"{sorted(constants.DATASET_URLS)}, got {dataset!r}.",
                f"statcan_indicators:get_indicators : dataset doit être l'une des valeurs {sorted(constants.DATASET_URLS)}, reçu {dataset!r}.",
            )
        )
    if limit < 1:
        raise InvalidInput(
            say(
                f"statcan_indicators:get_indicators: limit must be between 1 and "
                f"{constants.SEARCH_LIMIT_MAX}, got {limit}.",
                f"statcan_indicators:get_indicators : limit doit être entre 1 et {constants.SEARCH_LIMIT_MAX}, reçu {limit}.",
            )
        )
    notes: list[str] = []
    # A model asking for "all of them" passes 500 or 1000; return the most
    # allowed and say so rather than failing the call.
    if limit > constants.SEARCH_LIMIT_MAX:
        notes.append(
            say(
                f"limit {limit} lowered to the maximum, {constants.SEARCH_LIMIT_MAX}",
                f"limit {limit} ramené au maximum, {constants.SEARCH_LIMIT_MAX}",
            )
        )
        limit = constants.SEARCH_LIMIT_MAX

    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise UpstreamError(
                say(
                    f"statcan_indicators:get_indicators returned HTTP {status}.",
                    f"statcan_indicators:get_indicators a renvoyé HTTP {status}.",
                )
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                say(
                    "statcan_indicators:get_indicators did not respond in time. Try again shortly.",
                    "statcan_indicators:get_indicators n'a pas répondu à temps. Réessayez sous peu.",
                )
            ) from exc

    cache_key = f"statcan-indicators:{dataset}"
    payload, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SECONDS, fetch)
    results = (payload or {}).get("results") or {}
    if "indicators" not in results:
        raise UpstreamError(
            say(
                "statcan_indicators:get_indicators: unexpected response shape (missing indicators).",
                "statcan_indicators:get_indicators : réponse de forme inattendue (indicators absent).",
            )
        )

    geo_names = {
        str(entry.get("geo_code")): _localized(entry.get("label"), lang)
        for entry in results.get("geo") or []
    }

    # The feed numbers geographies 0-13 (0 Canada, 1 NL ... 9 AB, 10 BC, 11 YT,
    # 12 NT, 13 NU), not SGC province codes: geo_code=48 matched nothing and
    # returned an empty list with no hint. A code the feed does not use but
    # that is a province/territory SGC code is mapped; 10-13 are valid feed
    # codes and are never reinterpreted as SGC.
    if isinstance(geo_code, str):
        parsed = _geo_from_text(geo_code)
        if parsed is None:
            valid = ", ".join(f"{code}={name}" for code, name in geo_names.items())
            raise InvalidInput(
                say(
                    f"statcan_indicators:get_indicators: geo_code {geo_code!r} is not a place "
                    f'this feed knows. Use a province name or abbreviation ("AB", '
                    f'"Alberta") or one of: {valid}.',
                    f"statcan_indicators:get_indicators : geo_code {geo_code!r} n'est pas un lieu "
                    f"connu de ce fil. Utilisez le nom ou l'abréviation d'une province "
                    f"(« AB », « Alberta ») ou l'un de ces codes : {valid}.",
                )
            )
        geo_code = parsed
    elif geo_code is None and query:
        found, rest = _geo_in_query(query)
        if found is not None and str(found) in geo_names:
            notes.append(
                say(
                    f"the place named in the query was read as geo_code {found} "
                    f"({geo_names[str(found)]})",
                    f"le lieu nommé dans la requête a été lu comme geo_code {found} "
                    f"({geo_names[str(found)]})",
                )
            )
            geo_code, query = found, rest
    if geo_code is not None and str(geo_code) not in geo_names:
        mapped = constants.SGC_TO_FEED_GEO_CODE.get(geo_code)
        if mapped is None or str(mapped) not in geo_names:
            valid = ", ".join(f"{code}={name}" for code, name in geo_names.items())
            raise InvalidInput(
                say(
                    f"statcan_indicators:get_indicators: geo_code {geo_code} is not in this feed. "
                    f"Use one of: {valid} (or a province SGC code such as 48 for Alberta).",
                    f"statcan_indicators:get_indicators : geo_code {geo_code} ne figure pas dans ce fil. Utilisez l'un de ces codes : {valid} (ou un code de province de la CGT, comme 48 pour l'Alberta).",
                )
            )
        notes.append(
            say(
                f"geo_code {geo_code} read as SGC code and mapped to feed code {mapped}",
                f"geo_code {geo_code} lu comme un code de la CGT et associé au code {mapped} du fil",
            )
        )
        geo_code = mapped

    # Every meaningful word must appear in the title (in any order, accents ignored),
    # not the whole query as one phrase: "unemployment rate Alberta", "inflation" and
    # "GDP" all found nothing before (live, 2026-11-06). A title holding the whole
    # phrase is listed first.
    terms = _query_terms(query)
    phrase = _fold(query.strip())
    matched: list[Indicator] = []
    elsewhere: dict[str, set[str]] = {}
    for entry in results["indicators"]:
        title = _localized(entry.get("title"), lang) or ""
        if terms and not _matches(title, terms):
            continue
        entry_geo_code = entry.get("geo_code")
        if geo_code is not None and entry_geo_code != geo_code:
            name = geo_names.get(str(entry_geo_code))
            if name:
                elsewhere.setdefault(title, set()).add(name)
            continue

        growth_rate = entry.get("growth_rate") or {}
        daily_url_raw = _localized(entry.get("daily_url"), lang)
        daily_url = (
            f"https://www.statcan.gc.ca{daily_url_raw}"
            if daily_url_raw and daily_url_raw.startswith("/")
            else daily_url_raw
        )

        matched.append(
            Indicator(
                registry_number=entry.get("registry_number") or 0,
                indicator_number=entry.get("indicator_number") or 0,
                geo_code=entry_geo_code or 0,
                geo_name=geo_names.get(str(entry_geo_code)),
                title=title,
                value=_localized(entry.get("value"), lang) or "",
                reference_period=_localized(entry.get("refper"), lang),
                daily_url=daily_url,
                daily_title=_localized(entry.get("daily_title"), lang),
                source_table=entry.get("source"),
                release_date=entry.get("release_date"),
                growth=_localized(growth_rate.get("growth"), lang),
                growth_details=_localized(growth_rate.get("details"), lang),
            )
        )

    if phrase:
        matched.sort(key=lambda item: phrase not in _fold(item.title))
    if not matched:
        notes.append(
            _empty_hint(results["indicators"], terms, elsewhere, geo_names, geo_code, lang)
        )

    page = matched[:limit]
    return IndicatorList(
        dataset=dataset,
        indicators=page,
        returned_count=len(page),
        total_matched=len(matched),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_indicators.IndicatorList",
            limits="; ".join(notes) or None,
            lang=lang,
        ),
    )


def _empty_hint(
    indicators: list[dict[str, Any]],
    terms: list[tuple[str, ...]],
    elsewhere: dict[str, set[str]],
    geo_names: dict[str, str | None],
    geo_code: int | None,
    lang: str,
) -> str:
    """Say why nothing matched: another geography has it, or which titles come close."""
    if elsewhere:
        title, places = next(iter(elsewhere.items()))
        where = geo_names.get(str(geo_code)) or str(geo_code)
        listed = ", ".join(sorted(places)[:5])
        return say(
            f"no match for {where}; {title!r} is published for {listed} in this feed. "
            "For other geographies, search the StatCan tables (wds_search_cubes)",
            f"aucun résultat pour {where} ; {title!r} est publié pour {listed} dans ce fil. "
            "Pour d'autres géographies, cherchez dans les tableaux de StatCan (wds_search_cubes)",
        )
    near: list[str] = []
    for entry in indicators:
        title = _localized(entry.get("title"), lang) or ""
        folded = _fold(title)
        if title not in near and any(form in folded for forms in terms for form in forms):
            near.append(title)
        if len(near) == 5:
            break
    if near:
        return say(
            "no title holds every word of the query; titles holding some of them: "
            + "; ".join(near),
            "aucun titre ne contient tous les mots de la requête ; titres qui en contiennent : "
            + " ; ".join(near),
        )
    return say(
        "no indicator title matches the query; this feed holds headline indicators only, "
        "so search the StatCan tables (wds_search_cubes) instead",
        "aucun titre d'indicateur ne correspond à la requête ; ce fil ne contient que les "
        "indicateurs phares, cherchez plutôt dans les tableaux de StatCan (wds_search_cubes)",
    )
