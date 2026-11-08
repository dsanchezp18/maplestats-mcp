"""Client for the Federal Reserve Board's statistical release data files.

Checked live on 2026-11-07 with the project's User-Agent, no key:

- The Data Download Program (DDP, /datadownload/) is being retired: its
  "Build Your Package" page goes the week of 2026-11-09, its preformatted
  packages later in 2026-2027, and then the DDP itself
  (/data/data-download-fred-information.htm, 2026-07-16). The same page
  says historical data stay downloadable as XML files on the release pages,
  so this module reads only those: one zip per release at
  /releases/{code}/data/FRB_{code}_xml.zip (lower-case code), holding
  `{CODE}_data.xml` (SDMX-ML 1.0 compact data) and `{CODE}_struct.xml`
  (code lists, concepts and key families). H.3 and E.2 have no such file
  (404) and are left out.
- Data: one `DataSet` per group of the release (H.15 has `H15` and
  `discontinued`), `Series` elements whose attributes are the frequency
  (`FREQ`, a numeric code: 9 business day, 8 daily, 129 monthly, 162
  quarterly, 203 annual), `UNIT`, `UNIT_MULT` (1, 1000000, 1e+09),
  `CURRENCY`, `SERIES_NAME` and the group's own dimensions; short and long
  descriptions are annotations. `Obs` carry `TIME_PERIOD` (always a full
  date: a month is its last day), `OBS_VALUE` and `OBS_STATUS`; status ND
  (no data) comes with the value -9999, so such observations are dropped.
- A series can appear in several groups (G.17's total index sits in four,
  H.6's M1 in two); the first copy is kept.
- The largest file kept, H.4.1, is a 9.1 MB zip holding a 127 MB XML file
  (1.7 million observations), parsed in about 7 s; G.17 in 2 s, H.15 in 4 s.
  A release is parsed once and kept for hours as typed arrays of values
  and date indexes (about 12 bytes an observation), not as text. The Financial Accounts (Z.1, 620 MB of XML) are not read.
- Terms: public domain, cite the Board (federalreserve.gov/disclaimer.htm).
"""

from __future__ import annotations

import asyncio
import io
import math
import re
import zipfile
from array import array
from dataclasses import dataclass, field
from datetime import datetime
from typing import IO, Any, NoReturn

import httpx
from defusedxml import DefusedXmlException
from defusedxml import ElementTree as DefusedET

from maplestats_mcp.modules.fed import constants
from maplestats_mcp.modules.fed.schemas import (
    Code,
    Dimension,
    DimensionValue,
    Group,
    Release,
    ReleaseList,
    ReleaseStructure,
    Row,
    SearchResult,
    SeriesData,
    SeriesInfo,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.i18n import fr_number, normalize_lang, pick
from maplestats_mcp.shared.rate_limiter import get_limiter

_FRESHNESS = {
    "en": (
        "Each release file is replaced when the Board publishes the release (H.15, H.10 and "
        "policy rates every business day, G.17 and G.19 monthly); read again after 6 hours."
    ),
    "fr": (
        "Chaque fichier est remplacé quand le Conseil publie la publication (H.15, H.10 et "
        "taux directeurs chaque jour ouvrable, G.17 et G.19 chaque mois) ; relu après 6 heures."
    ),
}

_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
_WORD = re.compile(r"[a-z0-9]+")
# Series-level attributes that are not dimensions of the series.
_SERIES_ATTRIBUTES = frozenset({"SERIES_NAME", "UNIT", "UNIT_MULT", "CURRENCY", "FREQ"})
_FREQUENCY_WORDS = {
    "daily": ("daily", "business day"),
    "weekly": ("weekly",),
    "monthly": ("monthly",),
    "quarterly": ("quarterly",),
    "annual": ("annual",),
}
# Default window when no dates or last_n are given, by frequency label word.
_DEFAULT_LAST_N = (
    ("business day", 260),
    ("daily", 365),
    ("weekly", 104),
    ("week", 104),
    ("month", 60),
    ("quarter", 40),
    ("annual", 30),
)


def _lang(lang: str) -> str:
    return normalize_lang(lang)


def _licence(lang: str) -> str:
    return constants.LICENCE_FR if lang == "fr" else constants.LICENCE


# ------------------------------------------------------------------ parsing


@dataclass
class _Series:
    name: str
    group: str
    description: str
    long_description: str | None
    attributes: dict[str, str]
    dates: array  # array('i'): indexes into _Release.periods
    values: array  # array('d')


@dataclass
class _Release:
    code: str
    name: str
    prepared: datetime | None
    periods: list[str]
    series: dict[str, _Series]
    group_names: dict[str, str] = field(default_factory=dict)
    group_components: dict[str, list[str]] = field(default_factory=dict)
    concepts: dict[str, str] = field(default_factory=dict)
    codelists: dict[str, dict[str, str]] = field(default_factory=dict)
    concept_codelist: dict[str, str] = field(default_factory=dict)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: Any, name: str) -> str | None:
    for child in element:
        if _local(child.tag) == name:
            return (child.text or "").strip() or None
    return None


def _parse_structure(release: _Release, body: bytes) -> None:
    root = DefusedET.fromstring(body)
    for element in root.iter():
        tag = _local(element.tag)
        if tag == "CodeList":
            codes = {}
            for code in element:
                if _local(code.tag) == "Code" and code.get("value") is not None:
                    codes[str(code.get("value"))] = _child_text(code, "Description") or str(
                        code.get("value")
                    )
            release.codelists[str(element.get("id"))] = codes
        elif tag == "Concept" and element.get("id"):
            release.concepts.setdefault(str(element.get("id")), _child_text(element, "Name") or "")
        elif tag == "KeyFamily" and element.get("id"):
            family = str(element.get("id"))
            release.group_names[family] = _child_text(element, "Name") or family
            components = []
            for component in element.iter():
                kind = _local(component.tag)
                concept = component.get("concept")
                if kind in ("Dimension", "Attribute") and concept:
                    components.append(concept)
                    if component.get("codelist"):
                        release.concept_codelist.setdefault(concept, str(component.get("codelist")))
            release.group_components[family] = components


def _parse_data(code: str, stream: IO[bytes]) -> _Release:
    release = _Release(code=code, name=code, prepared=None, periods=[], series={})
    period_index: dict[str, int] = {}
    group = ""
    attrs: dict[str, str] = {}
    descriptions: dict[str, str] = {}
    note_type: str | None = None
    dates: list[int] = []
    values: list[float] = []
    for event, element in DefusedET.iterparse(stream, events=("start", "end")):
        tag = _local(element.tag)
        if event == "start":
            if tag == "DataSet":
                group = str(element.get("id") or "")
            elif tag == "Series":
                attrs = {k: str(v) for k, v in element.attrib.items()}
                descriptions = {}
                dates, values = [], []
            continue
        if tag == "Obs":
            status = element.get("OBS_STATUS") or ""
            raw = element.get("OBS_VALUE")
            period = element.get("TIME_PERIOD")
            element.clear()
            if status in constants.EMPTY_STATUSES or raw is None or not period:
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            if not math.isfinite(value) or value == -9999:
                continue
            index = period_index.get(period)
            if index is None:
                index = period_index[period] = len(release.periods)
                release.periods.append(period)
            dates.append(index)
            values.append(value)
        elif tag == "AnnotationType":
            note_type = (element.text or "").strip()
        elif tag == "AnnotationText":
            if note_type:
                descriptions.setdefault(note_type, (element.text or "").strip())
            note_type = None
        elif tag == "Series":
            name = attrs.get("SERIES_NAME", "")
            if name and name not in release.series:
                release.series[name] = _Series(
                    name=name,
                    group=group,
                    description=descriptions.get("Short Description")
                    or descriptions.get("Long Description")
                    or name,
                    long_description=descriptions.get("Long Description"),
                    attributes=attrs,
                    dates=array("i", dates),
                    values=array("d", values),
                )
            element.clear()
        elif tag == "Name" and release.name == code and element.text:
            # The header's message:Name, e.g. "H.15 Selected Interest Rates".
            release.name = element.text.strip()
        elif tag == "Prepared" and release.prepared is None and element.text:
            try:
                release.prepared = datetime.fromisoformat(element.text.strip().replace("Z", ""))
            except ValueError:
                pass
    return release


def parse_release(code: str, body: bytes) -> _Release:
    """Parse a release zip (as downloaded) into series arrays and its structure."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile as exc:
        raise UpstreamError(f"the {code} file is not a zip archive") from exc
    members = {info.filename.upper(): info for info in archive.infolist()}
    data = members.get(f"{code}_DATA.XML")
    structure = members.get(f"{code}_STRUCT.XML")
    if data is None:
        raise UpstreamError(f"the {code} zip has no {code}_data.xml")
    for info in (data, structure):
        if info is not None and info.file_size > constants.MAX_XML_BYTES:
            raise UpstreamError(f"{info.filename} is {info.file_size:,} bytes, over the cap")
    try:
        with archive.open(data) as stream:
            release = _parse_data(code, stream)
        if structure is not None:
            _parse_structure(release, archive.read(structure))
    except (DefusedXmlException, SyntaxError) as exc:
        raise UpstreamError(f"the {code} XML could not be read: {exc}") from exc
    return release


# ------------------------------------------------------------------ fetching


def _raise_unavailable(url: str, exc: Exception, lang: str) -> NoReturn:
    raise_localized(
        UpstreamUnavailable,
        f"The Federal Reserve Board site did not answer ({url}): {exc}. Try again in a minute.",
        f"le site du Conseil de la Réserve fédérale n'a pas répondu ({url}) : {exc}. Réessayez "
        "dans une minute.",
        lang,
    )


async def _download(url: str, lang: str) -> bytes:
    await get_limiter(
        constants.RATE_LIMIT_SOURCE,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    ).acquire()
    try:
        response = await get_raw(url, timeout=constants.DOWNLOAD_TIMEOUT_SECONDS)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            raise_localized(
                NotFound,
                f"The Board no longer publishes {url} (HTTP 404).",
                f"le Conseil ne publie plus {url} (HTTP 404).",
                lang,
            )
        if status >= 500 or status == 429:
            _raise_unavailable(url, exc, lang)
        raise_localized(
            UpstreamError,
            f"The Federal Reserve Board site answered HTTP {status} for {url}.",
            f"le site du Conseil de la Réserve fédérale a répondu HTTP {status} pour {url}.",
            lang,
        )
    except httpx.HTTPError as exc:
        _raise_unavailable(url, exc, lang)
    body = response.content
    if len(body) > constants.MAX_ZIP_BYTES:
        raise_localized(
            UpstreamError,
            f"{url} is {len(body):,} bytes, more than this server reads.",
            f"{url} fait {fr_number(len(body))} octets, plus que ce que ce serveur lit.",
            lang,
        )
    return body


def _release_spec(release: str, lang: str) -> constants.Release:
    code = re.sub(r"[^A-Z0-9]", "", release.strip().upper())
    spec = constants.RELEASES.get(code)
    if spec is None:
        choices = ", ".join(constants.RELEASES)
        raise_localized(
            InvalidInput,
            f"{release!r} is not a release this server reads. Releases: {choices} "
            "(fed_list_releases describes them).",
            f"{release!r} n'est pas une publication que ce serveur lit. Publications : "
            f"{choices} (fed_list_releases les décrit).",
            lang,
        )
    return spec


async def _load(spec: constants.Release, lang: str) -> tuple[_Release, bool]:
    async def fetch() -> _Release:
        body = await _download(spec.data_url, lang)
        try:
            return await asyncio.to_thread(parse_release, spec.code, body)
        except UpstreamError as exc:
            raise_localized(
                UpstreamError,
                f"{spec.data_url}: {exc}",
                f"{spec.data_url} : fichier illisible ({exc}).",
                lang,
            )

    return await cached_fetch(
        f"fed:release:{spec.code}", constants.CACHE_TTL_RELEASE_SECONDS, fetch
    )


# ------------------------------------------------------------------ helpers


def _label(release: _Release, concept: str, code: str) -> str:
    codelist = release.concept_codelist.get(concept) or f"CL_{concept}"
    return release.codelists.get(codelist, {}).get(code) or code


def _unit(release: _Release, code: str) -> str:
    label = _label(release, "UNIT", code)
    return label if label != code else code.replace("_", " ").replace(":  ", ": ")


def _multiplier_word(release: _Release, code: str | None) -> str | None:
    """'1e+09' -> 'billions' through CL_UNIT_MULT (whose codes are written 1000000000)."""
    if not code:
        return None
    try:
        number = float(code)
    except ValueError:
        return None
    if number == 1:
        return None
    key = str(int(number)) if number >= 1 and number.is_integer() else code
    word = release.codelists.get("CL_UNIT_MULT", {}).get(key)
    return word.lower() if word else f"x {code}"


def _display_unit(release: _Release, series: _Series) -> str:
    """The unit as a reader needs it: 'CAD per USD', 'USD, billions', 'Percent: Per Year'.

    H.10 marks exchange rates only as 'Currency' with the foreign currency in
    CURRENCY; RXI$US series are quoted in US dollars per unit of it (the euro,
    the pound, the Australian and New Zealand dollars), the rest the other way.
    """
    attrs = series.attributes
    unit = _unit(release, attrs.get("UNIT", ""))
    currency = attrs.get("CURRENCY")
    currency = currency if currency not in (None, "", "NA") else None
    if unit.startswith("Currency") and currency:
        if series.name.startswith("RXI$US"):
            unit = f"USD per {currency}"
        elif series.name.startswith("RXI"):
            unit = f"{currency} per USD"
        else:
            unit = currency
    word = _multiplier_word(release, attrs.get("UNIT_MULT"))
    return f"{unit}, {word}" if word else unit


def _frequency(release: _Release, series: _Series) -> str:
    code = series.attributes.get("FREQ", "")
    return _label(release, "FREQ", code) if code else ""


def _info(release: _Release, series: _Series) -> SeriesInfo:
    attrs = series.attributes
    multiplier = attrs.get("UNIT_MULT")
    currency = attrs.get("CURRENCY")
    group_name = release.group_names.get(series.group, series.group)
    dimensions = [
        DimensionValue(id=key, code=value, label=_label(release, key, value))
        for key, value in attrs.items()
        if key not in _SERIES_ATTRIBUTES
    ]
    count = len(series.values)
    return SeriesInfo(
        series_id=series.name,
        release=release.code,
        description=series.description,
        long_description=(
            series.long_description
            if series.long_description and series.long_description != series.description
            else None
        ),
        group=group_name,
        discontinued="discontinu" in f"{series.group} {group_name} {series.description}".lower(),
        frequency=_frequency(release, series),
        unit=_display_unit(release, series),
        unit_multiplier=multiplier if multiplier not in (None, "", "1") else None,
        currency=currency if currency not in (None, "", "NA") else None,
        dimensions=dimensions,
        first_date=release.periods[series.dates[0]] if count else None,
        last_date=release.periods[series.dates[-1]] if count else None,
        last_value=float(series.values[-1]) if count else None,
        observations=count,
    )


def _provenance(
    spec: constants.Release, release: _Release, cached: bool, schema: str, lang: str, coverage: str
):
    return make_provenance(
        source=constants.SOURCE,
        url=spec.data_url,
        cached=cached,
        schema_name=schema,
        as_of=release.prepared,
        freshness=_FRESHNESS[lang],
        coverage=coverage,
        licence=_licence(lang),
        lang=lang,
    )


def _check_dates(
    start_date: str | None, end_date: str | None, last_n: int | None, lang: str
) -> tuple[str | None, str | None]:
    for name, value in (("start_date", start_date), ("end_date", end_date)):
        if value is not None and not _DATE.match(value.strip()):
            raise_localized(
                InvalidInput,
                f"{name} {value!r} is not a date (2024, 2024-06 or 2024-06-30).",
                f"{name} {value!r} n'est pas une date (2024, 2024-06 ou 2024-06-30).",
                lang,
            )
    if last_n is not None and not 1 <= last_n <= constants.MAX_LAST_N:
        raise_localized(
            InvalidInput,
            f"last_n must be between 1 and {constants.MAX_LAST_N}.",
            f"last_n doit être compris entre 1 et {constants.MAX_LAST_N}.",
            lang,
        )
    start = start_date.strip() if start_date else None
    end = end_date.strip() if end_date else None
    # Dates are compared as text: an end year or month covers its last day.
    if end and len(end) == 4:
        end += "-12-31"
    elif end and len(end) == 7:
        end += "-31"
    return start, end


def _default_last_n(frequency: str) -> int:
    lowered = frequency.lower()
    return next((n for word, n in _DEFAULT_LAST_N if word in lowered), 60)


# ------------------------------------------------------------------ releases


async def list_releases(lang: str = "en") -> ReleaseList:
    lang = _lang(lang)
    releases = [
        Release(
            code=spec.code,
            name=pick(lang, spec.name_en, spec.name_fr),
            description=pick(lang, spec.about_en, spec.about_fr),
            release_page=spec.page_url,
            data_url=spec.data_url,
        )
        for spec in constants.RELEASES.values()
    ]
    return ReleaseList(
        releases=releases,
        notes=[
            pick(
                lang,
                "The Financial Accounts of the United States (Z.1) are not read: the file "
                "holds 620 MB of XML.",
                "Les comptes financiers des États-Unis (Z.1) ne sont pas lus : le fichier "
                "contient 620 Mo de XML.",
            )
        ],
        provenance=make_provenance(
            source=constants.SOURCE,
            url=f"{constants.SITE}/data.htm",
            cached=True,
            schema_name="fed.ReleaseList",
            freshness=_FRESHNESS[lang],
            coverage=pick(
                lang,
                "Board releases whose release page offers the complete data as one XML file.",
                "Publications du Conseil dont la page offre toutes les données dans un seul "
                "fichier XML.",
            ),
            licence=_licence(lang),
            lang=lang,
        ),
    )


async def describe_release(release: str, lang: str = "en") -> ReleaseStructure:
    lang = _lang(lang)
    spec = _release_spec(release, lang)
    data, cached = await _load(spec, lang)
    used: dict[str, dict[str, set[str]]] = {}
    counts: dict[str, int] = {}
    frequencies: list[str] = []
    for series in data.series.values():
        counts[series.group] = counts.get(series.group, 0) + 1
        for key, value in series.attributes.items():
            if key not in _SERIES_ATTRIBUTES:
                used.setdefault(series.group, {}).setdefault(key, set()).add(value)
        frequency = _frequency(data, series)
        if frequency and frequency not in frequencies:
            frequencies.append(frequency)
    groups = []
    for group, count in counts.items():
        order = [c for c in data.group_components.get(group, []) if c in used.get(group, {})]
        order += [c for c in used.get(group, {}) if c not in order]
        groups.append(
            Group(
                id=group,
                name=data.group_names.get(group, group),
                series_count=count,
                dimensions=[
                    Dimension(
                        id=concept,
                        name=data.concepts.get(concept) or concept,
                        codes=[
                            Code(code=c, label=_label(data, concept, c))
                            for c in sorted(used[group][concept])
                        ],
                    )
                    for concept in order
                ],
            )
        )
    examples = [
        name
        for name in (i.series for i in constants.INDICATORS.values() if i.release == spec.code)
        if name in data.series
    ] or list(data.series)[:5]
    return ReleaseStructure(
        code=spec.code,
        name=pick(lang, spec.name_en, spec.name_fr),
        description=pick(lang, spec.about_en, spec.about_fr),
        prepared=data.prepared,
        series_count=len(data.series),
        frequencies=frequencies,
        groups=groups,
        example_series=examples,
        provenance=_provenance(
            spec,
            data,
            cached,
            "fed.ReleaseStructure",
            lang,
            pick(
                lang,
                "Groups, dimensions and codes as the release's series use them. Labels are "
                "English only.",
                "Groupes, dimensions et codes tels que les séries de la publication les "
                "utilisent. Libellés en anglais seulement.",
            ),
        ),
    )


# ------------------------------------------------------------------ search


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


async def search_series(
    query: str,
    release: str | None = None,
    frequency: str | None = None,
    include_discontinued: bool = False,
    limit: int = 25,
    lang: str = "en",
) -> SearchResult:
    lang = _lang(lang)
    tokens = _words(query)
    if not tokens:
        raise_localized(
            InvalidInput,
            "query needs at least one word, e.g. 'treasury 10-year' or 'canada dollar'.",
            "query doit contenir au moins un mot, p. ex. « treasury 10-year » ou « canada "
            "dollar » (libellés en anglais).",
            lang,
        )
    if not 1 <= limit <= constants.MAX_SEARCH_RESULTS:
        raise_localized(
            InvalidInput,
            f"limit must be between 1 and {constants.MAX_SEARCH_RESULTS}.",
            f"limit doit être compris entre 1 et {constants.MAX_SEARCH_RESULTS}.",
            lang,
        )
    wanted = None
    if frequency:
        wanted = _FREQUENCY_WORDS.get(frequency.strip().lower())
        if wanted is None:
            raise_localized(
                InvalidInput,
                f"frequency must be one of {', '.join(_FREQUENCY_WORDS)}.",
                f"frequency doit être l'une des valeurs {', '.join(_FREQUENCY_WORDS)}.",
                lang,
            )
    specs = (
        [_release_spec(release, lang)]
        if release
        else [constants.RELEASES[c] for c in constants.DEFAULT_SEARCH]
    )
    exact = query.strip().upper()
    scored: list[tuple[int, bool, str, SeriesInfo]] = []
    newest: _Release | None = None
    all_cached = True
    for spec in specs:
        data, cached = await _load(spec, lang)
        all_cached &= cached
        if newest is None or (
            data.prepared and newest.prepared and data.prepared > newest.prepared
        ):
            newest = data
        for series in data.series.values():
            info = _info(data, series)
            if info.discontinued and not include_discontinued:
                continue
            if wanted and not any(w in info.frequency.lower() for w in wanted):
                continue
            if series.name.upper() == exact:
                score = 1000
            else:
                hay = set(
                    _words(
                        " ".join(
                            [
                                series.name,
                                info.description,
                                info.long_description or "",
                                info.group,
                                info.frequency,
                                *(d.label for d in info.dimensions),
                            ]
                        )
                    )
                )
                score = sum(1 for t in tokens if any(w.startswith(t) for w in hay))
            if score:
                scored.append((score, info.discontinued, series.name, info))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    best = scored[0][0] if scored else 0
    # Keep only the best-scoring tier when the query names several words, so a
    # search for "canada dollar" does not list every series that says "dollar".
    if len(tokens) > 1 and best < 1000:
        scored = [s for s in scored if s[0] == best]
    notes = []
    if not release:
        notes.append(
            pick(
                lang,
                f"Searched {', '.join(constants.DEFAULT_SEARCH)}; name a release (fed_list_releases) "
                "to search another one.",
                f"Recherche dans {', '.join(constants.DEFAULT_SEARCH)} ; nommez une publication "
                "(fed_list_releases) pour en chercher une autre.",
            )
        )
    if not scored:
        notes.append(
            pick(
                lang,
                "No series matched. Descriptions are English (e.g. 'Treasury', 'Canada', "
                "'industrial production').",
                "Aucune série trouvée. Les descriptions sont en anglais (p. ex. « Treasury », "
                "« Canada », « industrial production »).",
            )
        )
    assert newest is not None
    spec = specs[0]
    return SearchResult(
        query=query,
        releases_searched=[s.code for s in specs],
        total_matches=len(scored),
        series=[item[3] for item in scored[:limit]],
        notes=notes,
        provenance=_provenance(
            spec,
            newest,
            all_cached,
            "fed.SearchResult",
            lang,
            pick(
                lang,
                "Series descriptions are English only. Discontinued series are left out unless "
                "include_discontinued is set.",
                "Descriptions des séries en anglais seulement. Les séries abandonnées sont omises "
                "sauf avec include_discontinued.",
            ),
        ),
    )


# ------------------------------------------------------------------ data


def _rows(
    data: _Release,
    names: list[str],
    start: str | None,
    end: str | None,
    last_n: int | None,
    lang: str,
) -> tuple[list[SeriesInfo], list[Row], list[str]]:
    infos: list[SeriesInfo] = []
    per_series: list[list[Row]] = []
    notes: list[str] = []
    defaulted = start is None and end is None and last_n is None
    for name in names:
        series = data.series[name]
        info = _info(data, series)
        infos.append(info)
        dates = [data.periods[i] for i in series.dates]
        values = series.values.tolist()
        pairs = [
            (d, v)
            for d, v in zip(dates, values, strict=True)
            if (start is None or d >= start) and (end is None or d <= end)
        ]
        take = (
            last_n
            if last_n is not None
            else (_default_last_n(info.frequency) if defaulted else None)
        )
        if take is not None:
            pairs = pairs[-take:]
        per_series.append(
            [
                Row(date=d, value=v, series_id=name, unit=info.unit, frequency=info.frequency)
                for d, v in pairs
            ]
        )
    if defaulted:
        notes.append(
            pick(
                lang,
                "No dates given: the latest observations only (a year of daily data, five years "
                "of monthly data). Pass start_date or last_n for more.",
                "Aucune date donnée : les dernières observations seulement (un an de données "
                "quotidiennes, cinq ans de données mensuelles). Passez start_date ou last_n "
                "pour en avoir plus.",
            )
        )
    total = sum(len(r) for r in per_series)
    if total > constants.MAX_ROWS:
        keep = max(1, constants.MAX_ROWS // len(per_series))
        per_series = [r[-keep:] for r in per_series]
        notes.append(
            pick(
                lang,
                f"{total:,} rows; only the last {keep:,} of each series are returned. Narrow "
                "the dates, or read the release file (provenance.url) for everything.",
                f"{fr_number(total)} lignes ; seules les {fr_number(keep)} dernières de chaque "
                "série sont renvoyées. Réduisez les dates, ou lisez le fichier de la "
                "publication (provenance.url) pour tout obtenir.",
            )
        )
    rows = [row for chunk in per_series for row in chunk]
    if not rows:
        raise_localized(
            NotFound,
            f"No values for {', '.join(names)} in the dates asked for.",
            f"aucune valeur pour {', '.join(names)} pour les dates demandées.",
            lang,
        )
    return infos, rows, notes


async def get_series(
    release: str,
    series: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
    last_n: int | None = None,
    lang: str = "en",
) -> SeriesData:
    lang = _lang(lang)
    start, end = _check_dates(start_date, end_date, last_n, lang)
    names = list(dict.fromkeys(s.strip() for s in series if s and s.strip()))
    if not names or len(names) > constants.MAX_SERIES:
        raise_localized(
            InvalidInput,
            f"series takes 1 to {constants.MAX_SERIES} series ids (fed_search_series finds them).",
            f"series accepte de 1 à {constants.MAX_SERIES} identifiants de série "
            "(fed_search_series les trouve).",
            lang,
        )
    spec = _release_spec(release, lang)
    data, cached = await _load(spec, lang)
    by_upper = {name.upper(): name for name in data.series}
    resolved = []
    for name in names:
        found = by_upper.get(name.upper())
        if found is None:
            raise_localized(
                NotFound,
                f"{name} is not a series of {spec.code}. fed_search_series finds series ids "
                f"(e.g. {', '.join(list(data.series)[:3])}).",
                f"{name} n'est pas une série de {spec.code}. fed_search_series trouve les "
                f"identifiants (p. ex. {', '.join(list(data.series)[:3])}).",
                lang,
            )
        resolved.append(found)
    infos, rows, notes = _rows(data, resolved, start, end, last_n, lang)
    # The policy-rates file runs a few days past the day it was prepared (IORB
    # dated 2026-11-09 in the file of 2026-11-06): the rate already in effect.
    if data.prepared and rows[-1].date > data.prepared.date().isoformat():
        notes.append(
            pick(
                lang,
                "Some dates are after the file was prepared: the Board lists the rate already "
                "set for the next days.",
                "Certaines dates suivent la préparation du fichier : le Conseil indique le taux "
                "déjà fixé pour les jours suivants.",
            )
        )
    return SeriesData(
        release=spec.code,
        series=infos,
        rows=rows,
        notes=notes,
        provenance=_provenance(
            spec,
            data,
            cached,
            "fed.SeriesData",
            lang,
            pick(
                lang,
                f"{pick(lang, spec.name_en, spec.name_fr)}. Dates are period ends; days without "
                "a value (holidays, 'ND') are left out.",
                f"{pick(lang, spec.name_en, spec.name_fr)}. Les dates sont des fins de période ; "
                "les jours sans valeur (fériés, « ND ») sont omis.",
            ),
        ),
    )


async def get_indicator(
    indicator: str,
    start_date: str | None = None,
    end_date: str | None = None,
    last_n: int | None = None,
    lang: str = "en",
) -> SeriesData:
    lang = _lang(lang)
    name = indicator.strip().lower()
    spec_indicator = constants.INDICATORS.get(name)
    if spec_indicator is None:
        choices = ", ".join(constants.INDICATORS)
        raise_localized(
            InvalidInput,
            f"Unknown indicator {indicator!r}. Indicators: {choices}. For any other series "
            "use fed_search_series and fed_get_series.",
            f"indicateur inconnu {indicator!r}. Indicateurs : {choices}. Pour toute autre "
            "série, utilisez fed_search_series et fed_get_series.",
            lang,
        )
    result = await get_series(
        spec_indicator.release,
        [spec_indicator.series],
        start_date=start_date,
        end_date=end_date,
        last_n=last_n,
        lang=lang,
    )
    result.indicator = name
    result.indicator_label = pick(lang, spec_indicator.label_en, spec_indicator.label_fr)
    result.compare_with_canada = pick(lang, spec_indicator.pair_en, spec_indicator.pair_fr)
    return result
