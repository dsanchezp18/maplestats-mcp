"""Client for First Nation Profiles and ISC's drinking water advisory pages.

Checked live 2026-10-26:

1. First Nation Profiles (fnp-ppn.aadnc-aandc.gc.ca) answer a plain GET per
   tab: FNMain, FNReserves, FNGovernance, FNGeography and FNRegPopulation
   .aspx?BAND_NUMBER=<n>&lang=eng|fra. The tab buttons on the main page are
   ASP.NET postbacks, but the pages behind them need no session. Values sit
   in elements with stable ids (plcMain_txtBandName, plcMain_hlTCName,
   plcMain_dgReservesList...), the same in both languages, so the parser
   reads ids, not labels. An unknown band number answers 302 to
   http://www.ainc-inac.gc.ca/error/404.html, which the reader refuses as a
   redirect off the host and this client reports as not found.
2. The name search (SearchFN.aspx) is a postback that redirects to a grid
   held in the server session, so the search here reads ISC's open dataset
   of registered population instead: one CSV, every registry group for
   each year from 2023 (646 a year), names in English and French, encoded
   cp1252 (Île-du-Prince-Édouard), "NA" where a district does not apply.
   The CSV link is found through the dataset's CKAN record and answers 302
   to a signed blob URL.
3. Profile numbers: "1,526" in English and "1 526" (no-break space) in
   French; reserve hectares "27040.10" and "27040,10"; officials' dates are
   MM/DD/YYYY in both languages.
4. The long-term advisory page sets window["App_config"] with
   "LinkAjaxSource" pointing at
   /DAM/DAM-ISC-SAC/DAM-WTR/STAGING/texte-text/lTDWA_map_data_<ms>_eng.txt
   (_fra.txt on the French page). The timestamp changes when ISC replaces
   the file, so the name is read from the page on every refresh. The file
   is JSON (UTF-8): {"data": [755 communities], "Ressources": [labels],
   "GenerateDate": "2026-10-20"}; each community has LTDWACurrent and
   LTDWALifted lists. A lifted advisory's DateExpected holds the date it
   was lifted (every one is 2015-11-17 or later, when the count began);
   current ones have it empty. Province names can carry no-break spaces,
   and 7 communities have no province.
5. The short-term page has one table per ISC region (Atlantic, Quebec,
   Ontario, Manitoba, Saskatchewan, Alberta) under an h3, and a sentence
   "As of October 25, 2026, there were 39 short-term drinking water
   advisories in place ... excluding those in the British Columbia region".
   An advisory still in effect has "None" ("Aucune") as its revoked date.
   The English Ontario table used the code "DWA", absent from the legend.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import unicodedata
from datetime import UTC, date, datetime
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from maplestats_mcp.modules.isc import constants
from maplestats_mcp.modules.isc.schemas import (
    AdvisoryKind,
    AnnualPopulation,
    FirstNationList,
    FirstNationProfile,
    FirstNationSummary,
    Geography,
    Governance,
    LongTermAdvisory,
    LongTermAdvisoryList,
    Official,
    RegisteredPopulation,
    Reserve,
    ResidenceCount,
    ShortTermAdvisory,
    ShortTermAdvisoryList,
    TribalCouncil,
)
from maplestats_mcp.shared import file_download
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError
from maplestats_mcp.shared.i18n import french_spacing
from maplestats_mcp.shared.licences import CANADA_CA_TERMS, OGL_CANADA
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_HOSTS = frozenset(
    {constants.FNP_HOST, constants.SAC_HOST, constants.OPEN_HOST, constants.BLOB_HOST}
)
_APP_CONFIG_SOURCE = re.compile(r'"LinkAjaxSource"\s*:\s*"([^"]+)"')
_EN_MONTHS = {
    name: number
    for number, name in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        start=1,
    )
}
_FR_MONTHS = {
    name: number
    for number, name in enumerate(
        (
            "janvier",
            "février",
            "mars",
            "avril",
            "mai",
            "juin",
            "juillet",
            "août",
            "septembre",
            "octobre",
            "novembre",
            "décembre",
        ),
        start=1,
    )
}
_STDWA_NOTE = (
    "South of 60 only, and not British Columbia: the First Nations Health Authority "
    "reports advisories for First Nations in British Columbia. Advisories revoked during "
    "the month stay listed until the month ends."
)
_STDWA_NOTE_FR = (
    "Au sud du 60e parallèle seulement, sans la Colombie-Britannique : l'Autorité "
    "sanitaire des Premières Nations publie les avis des Premières Nations de la "
    "Colombie-Britannique. Les avis levés au cours du mois restent affichés jusqu'à la "
    "fin du mois."
)
_LTDWA_NOTE = (
    "Long-term advisories are on public water systems financially supported by ISC and "
    "have been in place for more than a year; lifted ones are those lifted since "
    "November 2015. First Nations in British Columbia are included."
)
_LTDWA_NOTE_FR = (
    "Les avis à long terme visent les réseaux publics financés par SAC et sont en vigueur "
    "depuis plus d'un an ; les avis levés sont ceux levés depuis novembre 2015. Les "
    "Premières Nations de la Colombie-Britannique sont incluses."
)
_ANNUAL_NOTE = (
    "Yearly figures are ISC's counts at December 31 under the Indian Act; the monthly "
    "profile figure is more recent and can differ."
)
_ANNUAL_NOTE_FR = (
    "Les chiffres annuels sont ceux de SAC au 31 décembre en vertu de la Loi sur les "
    "Indiens ; le chiffre mensuel du profil est plus récent et peut différer."
)
_REGPOP_LICENCE_FR = (
    "Chiffres mensuels : Avis du site Web du gouvernement du Canada "
    "(https://www.canada.ca/fr/transparence/avis.html). Chiffres annuels : Licence du "
    "gouvernement ouvert – Canada "
    "(https://ouvert.canada.ca/fr/licence-du-gouvernement-ouvert-canada)."
)


def _text(en: str, fr: str, lang: str) -> str:
    return french_spacing(fr) if lang == "fr" else en


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


def _clean(text: Any) -> str | None:
    if text is None:
        return None
    value = " ".join(str(text).replace("\xa0", " ").split())
    return value or None


def _to_int(text: Any) -> int | None:
    if text is None:
        return None
    digits = re.sub(r"\D", "", str(text))
    return int(digits) if digits else None


def _to_float(text: str | None) -> float | None:
    value = _clean(text)
    if value is None:
        return None
    try:
        return float(value.replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _iso_date(text: Any) -> date | None:
    value = _clean(text)
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _midnight(day: date | None) -> datetime | None:
    return datetime(day.year, day.month, day.day, tzinfo=UTC) if day else None


def _decode(body: bytes) -> str:
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return body.decode("cp1252")


def _page_lang(lang: str) -> str:
    return "fra" if lang == "fr" else "eng"


def province_code(value: str, lang: str = "en") -> str:
    """A province code from a code or an English or French name; '' for none."""
    wanted = _fold(value)
    if not wanted:
        return ""
    for code, (en, fr) in constants.PROVINCES.items():
        if wanted in (code.lower(), _fold(en), _fold(fr)):
            return code
    raise_localized(
        InvalidInput,
        f"isc: unknown province or territory {value!r}; use a code such as ON or BC, or a name.",
        f"isc : province ou territoire inconnu {value!r} ; utilisez un code comme ON ou BC, "
        "ou un nom.",
        lang,
    )


def _code_for_name(name: str | None) -> str | None:
    if not name:
        return None
    wanted = _fold(name)
    for code, (en, fr) in constants.PROVINCES.items():
        if wanted in (_fold(en), _fold(fr)):
            return code
    return None


def _check_band(band_number: int, lang: str) -> None:
    if band_number < 1:
        raise_localized(
            InvalidInput,
            "isc: band_number must be a positive number (Musqueam is 550).",
            "isc : band_number doit être un nombre positif (Musqueam est 550).",
            lang,
        )


async def _fetch(url: str, max_bytes: int, lang: str) -> bytes:
    try:
        downloaded = await file_download.download(
            url,
            allow_host=lambda host: host in _HOSTS,
            limiter_for=lambda _host: _LIMITER,
            max_bytes=max_bytes,
            context="isc",
            timeout=60.0,
        )
    except file_download.RedirectRefused:
        # An unknown band number answers 302 to www.ainc-inac.gc.ca's 404 page.
        raise_localized(
            NotFound,
            f"isc: no page at {url} (it redirects to an error page).",
            f"isc : aucune page à {url} (redirection vers une page d'erreur).",
            lang,
        )
    return downloaded.body


# --- First Nation Profiles -------------------------------------------------


def fnp_url(page: str, band_number: int, lang: str) -> str:
    name = constants.FNP_PAGES[page]
    return f"{constants.FNP_SEARCH}{name}?BAND_NUMBER={band_number}&lang={_page_lang(lang)}"


def _by_id(soup: BeautifulSoup, element_id: str) -> str | None:
    element = soup.find(id=f"plcMain_{element_id}")
    return _clean(element.get_text(" ", strip=True)) if element else None


def _rows(soup: BeautifulSoup, table_id: str) -> list[list[str]]:
    table = soup.find("table", id=f"plcMain_{table_id}")
    if not isinstance(table, Tag):
        return []
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if cells:
            rows.append([_clean(td.get_text(" ", strip=True)) or "" for td in cells])
    return rows


async def _fnp_page(page: str, band_number: int, lang: str) -> tuple[BeautifulSoup, bool]:
    url = fnp_url(page, band_number, lang)

    async def fetch() -> str:
        return _decode(await _fetch(url, constants.MAX_PAGE_BYTES, lang))

    html, cached = await cached_fetch(f"isc:fnp:{url}", constants.PROFILE_TTL_SECONDS, fetch)
    soup = BeautifulSoup(html, "html.parser")
    if _by_id(soup, "txtBandName") is None:
        raise_localized(
            UpstreamError,
            f"isc: {url} has no official name; the page layout may have changed.",
            f"isc : {url} n'a pas de nom officiel ; la mise en page a peut-être changé.",
            lang,
        )
    return soup, cached


def parse_main(soup: BeautifulSoup) -> dict[str, Any]:
    website = soup.find(id="plcMain_anchor1")
    href = str(website.get("href") or "").strip() if isinstance(website, Tag) else ""
    council = None
    number = _to_int(_by_id(soup, "hlTCNumber"))
    council_name = _by_id(soup, "hlTCName")
    if number is not None and council_name:
        council = TribalCouncil(number=number, name=council_name)
    return {
        "name": _by_id(soup, "txtBandName") or "",
        "phonetic_spelling": _by_id(soup, "txtPhoneticSpelling"),
        "address": _by_id(soup, "txtAddress"),
        "postal_code": _by_id(soup, "txtPostalCode"),
        "phone": _by_id(soup, "txtPhone"),
        "fax": _by_id(soup, "txtFax"),
        "website": href or None,
        "tribal_council": council,
    }


def parse_reserves(soup: BeautifulSoup) -> list[Reserve]:
    return [
        Reserve(
            number=cells[0],
            name=cells[1],
            location=cells[2] or None,
            hectares=_to_float(cells[3]),
        )
        for cells in _rows(soup, "dgReservesList")
        if len(cells) >= 4
    ]


def parse_governance(soup: BeautifulSoup) -> Governance:
    officials = [
        Official(
            title=cells[0],
            surname=cells[1],
            given_name=cells[2],
            appointment_date=_iso_date(cells[3]),
            expiry_date=_iso_date(cells[4]),
        )
        for cells in _rows(soup, "dgOfficialsList")
        if len(cells) >= 5
    ]
    return Governance(
        membership_authority=_by_id(soup, "txtAuthority"),
        election_system=_by_id(soup, "txtElection"),
        council_quorum=_by_id(soup, "txtQuorum"),
        officials=officials,
    )


def parse_geography(soup: BeautifulSoup) -> Geography:
    sub_zone = _by_id(soup, "txtSubZone")
    return Geography(
        region=_by_id(soup, "txtRegion"),
        zone=_by_id(soup, "txtZone"),
        zone_description=_by_id(soup, "txtZoneDesc"),
        sub_zone=sub_zone,
        # Without a sub-zone the page puts "Not applicable for this zone" in a label.
        sub_zone_description=_by_id(soup, "txtSubZoneDesc")
        or (None if sub_zone else _by_id(soup, "lblColon2")),
        environmental_index=_by_id(soup, "txtEnvironmentalIndex"),
        environmental_index_description=_by_id(soup, "txtEnvIndexDesc"),
        city=_by_id(soup, "txtCity"),
        service_centre=_by_id(soup, "txtCityCenter"),
        most_populated_site=_by_id(soup, "lbReserve"),
    )


async def get_first_nation_profile(band_number: int, *, lang: str = "en") -> FirstNationProfile:
    _check_band(band_number, lang)
    # The main page first: an unknown number fails there without three more requests.
    main, main_cached = await _fnp_page("main", band_number, lang)
    pages = await asyncio.gather(
        _fnp_page("reserves", band_number, lang),
        _fnp_page("governance", band_number, lang),
        _fnp_page("geography", band_number, lang),
    )
    (reserves_page, _), (governance_page, _), (geography_page, _) = pages
    reserves = parse_reserves(reserves_page)
    hectares = [r.hectares for r in reserves if r.hectares is not None]
    url = fnp_url("main", band_number, lang)
    return FirstNationProfile(
        band_number=band_number,
        **parse_main(main),
        reserves=reserves,
        total_reserve_hectares=round(sum(hectares), 2) if hectares else None,
        governance=parse_governance(governance_page),
        geography=parse_geography(geography_page),
        profile_url=url,
        provenance=make_provenance(
            source="isc",
            url=url,
            cached=main_cached and all(cached for _, cached in pages),
            schema_name="isc.FirstNationProfile",
            freshness=_text(
                "Updated by CIRNAC as records change; officials as last reported by the "
                "First Nation.",
                "Mis à jour par RCAANC selon les changements ; représentants tels que "
                "déclarés en dernier par la Première Nation.",
                lang,
            ),
            licence=CANADA_CA_TERMS,
            lang=lang,
        ),
    )


_RESIDENCES = (
    ("own_reserve", "OnReserve"),
    ("other_reserve", "OnOtherReserves"),
    ("own_crown_land", "OnOwnCrownLand"),
    ("other_band_crown_land", "OnOtherCrownLand"),
    ("no_band_crown_land", "OnNoBandCrownLand"),
    ("off_reserve", "OffReserve"),
)
_SEX_PREFIX = re.compile(r"^(Registered Males|Hommes inscrits)\s*", re.IGNORECASE)


def as_of_month(text: str | None) -> str | None:
    """'September, 2026' or 'septembre, 2026' as '2026-09'."""
    match = re.match(r"^\s*([^\W\d_]+)\s*,?\s*(\d{4})\s*$", text or "")
    if not match:
        return None
    name = match.group(1).lower()
    month = _EN_MONTHS.get(name) or _FR_MONTHS.get(name)
    return f"{match.group(2)}-{month:02d}" if month else None


def parse_population(soup: BeautifulSoup) -> dict[str, Any]:
    rows = []
    for residence, suffix in _RESIDENCES:
        men = _to_int(_by_id(soup, f"txtMales{suffix}"))
        women = _to_int(_by_id(soup, f"txtFemales{suffix}"))
        label = _SEX_PREFIX.sub("", _by_id(soup, f"lblMales{suffix}") or residence)
        total = None if men is None and women is None else (men or 0) + (women or 0)
        rows.append(
            ResidenceCount(residence=residence, label=label, men=men, women=women, total=total)
        )
    as_of = _by_id(soup, "txtExtractDate")
    men = [r.men for r in rows if r.men is not None]
    women = [r.women for r in rows if r.women is not None]
    return {
        "name": _by_id(soup, "txtBandName") or "",
        "as_of": as_of,
        "as_of_month": as_of_month(as_of),
        "by_residence": rows,
        "men": sum(men) if men else None,
        "women": sum(women) if women else None,
        "total": _to_int(_by_id(soup, "txtTotalPopulation")),
    }


# --- Registered population dataset (open.canada.ca) --------------------------


def _column(row: dict[str, str], name: str) -> str | None:
    value = row.get(name.lower())
    if value is None:
        return None
    value = value.strip()
    return None if value in ("", "NA") else value


def parse_regpop_csv(text: str) -> list[dict[str, Any]]:
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    keys = [h.strip().lower() for h in header or []]
    if "registry_group_number" not in keys:
        raise UpstreamError(
            "isc: the registered population CSV has no registry_group_number column."
        )
    records = []
    for values in reader:
        row = dict(zip(keys, values, strict=False))
        number = _to_int(_column(row, "registry_group_number"))
        year = _to_int(_column(row, "year"))
        if number is None or year is None:
            continue
        records.append(
            {
                "year": year,
                "number": number,
                "name_en": _column(row, "registry_group_name EN") or "",
                "name_fr": _column(row, "registry_group_name FR") or "",
                "region_en": _column(row, "region EN"),
                "region_fr": _column(row, "region FR"),
                "province_en": _column(row, "prov_terr EN"),
                "province_fr": _column(row, "prov_terr FR"),
                "district_en": _column(row, "district EN"),
                "district_fr": _column(row, "district FR"),
                "on_men": _to_int(_column(row, "pop_on_reserve_crown_land_men")),
                "on_women": _to_int(_column(row, "pop_on_reserve_crown_land_women")),
                "on_total": _to_int(_column(row, "pop_on_reserve_crown_land_total")),
                "off_men": _to_int(_column(row, "pop_off_reserve_men")),
                "off_women": _to_int(_column(row, "pop_off_reserve_women")),
                "off_total": _to_int(_column(row, "pop_off_reserve_total")),
                "men": _to_int(_column(row, "pop_total_men")),
                "women": _to_int(_column(row, "pop_total_women")),
                "total": _to_int(_column(row, "pop_total_total")),
            }
        )
    if not records:
        raise UpstreamError("isc: the registered population CSV has no data rows.")
    return records


async def _regpop(lang: str) -> tuple[list[dict[str, Any]], str, bool]:
    """Every row of the yearly dataset, and the CSV's URL."""

    async def fetch() -> tuple[list[dict[str, Any]], str]:
        package = json.loads(
            _decode(await _fetch(constants.REGPOP_PACKAGE, constants.MAX_PAGE_BYTES, lang))
        )
        resources = (package.get("result") or {}).get("resources") or []
        csv_url = next(
            (
                str(r["url"])
                for r in resources
                if str(r.get("format") or "").upper() == "CSV" and r.get("url")
            ),
            None,
        )
        if csv_url is None:
            raise_localized(
                UpstreamError,
                f"isc: dataset {constants.REGPOP_DATASET} lists no CSV resource.",
                f"isc : le jeu de données {constants.REGPOP_DATASET} n'a aucune ressource CSV.",
                lang,
            )
        body = await _fetch(csv_url, constants.MAX_MAP_BYTES, lang)
        return parse_regpop_csv(_decode(body)), csv_url

    (rows, csv_url), cached = await cached_fetch("isc:regpop", constants.REGPOP_TTL_SECONDS, fetch)
    return rows, csv_url, cached


def _summary(row: dict[str, Any], lang: str) -> FirstNationSummary:
    fr = lang == "fr"
    return FirstNationSummary(
        band_number=row["number"],
        name=(row["name_fr"] if fr else row["name_en"]) or row["name_en"],
        region=row["region_fr"] if fr else row["region_en"],
        province=row["province_fr"] if fr else row["province_en"],
        province_code=_code_for_name(row["province_en"]),
        district=row["district_fr"] if fr else row["district_en"],
        year=row["year"],
        registered_population=row["total"],
        on_reserve=row["on_total"],
        off_reserve=row["off_total"],
    )


async def search_first_nations(
    query: str = "",
    *,
    province: str = "",
    limit: int = constants.SEARCH_DEFAULT_LIMIT,
    lang: str = "en",
) -> FirstNationList:
    code = province_code(province, lang)
    limit = max(1, min(limit, constants.SEARCH_MAX_LIMIT))
    rows, csv_url, cached = await _regpop(lang)
    latest = max(r["year"] for r in rows)
    current = [r for r in rows if r["year"] == latest]
    wanted = _fold(query)
    if wanted.isdigit():
        matches = [r for r in current if r["number"] == int(wanted)]
    else:
        words = wanted.split()
        matches = [
            r for r in current if all(w in _fold(f"{r['name_en']} {r['name_fr']}") for w in words)
        ]
    if code:
        matches = [r for r in matches if _code_for_name(r["province_en"]) == code]
    matches.sort(key=lambda r: _fold(r["name_en"]))
    page = matches[:limit]
    return FirstNationList(
        first_nations=[_summary(r, lang) for r in page],
        returned_count=len(page),
        total_matched=len(matches),
        year=latest,
        provenance=make_provenance(
            source="isc",
            url=csv_url,
            cached=cached,
            schema_name="isc.FirstNationList",
            freshness=_text(
                "Yearly (registered population at December 31).",
                "Annuelle (population inscrite au 31 décembre).",
                lang,
            ),
            limits=(
                _text(
                    f"First {len(page)} of {len(matches)} matches.",
                    f"{len(page)} premiers résultats sur {len(matches)}.",
                    lang,
                )
                if len(matches) > len(page)
                else None
            ),
            licence=OGL_CANADA,
            lang=lang,
        ),
    )


async def get_registered_population(band_number: int, *, lang: str = "en") -> RegisteredPopulation:
    _check_band(band_number, lang)
    (soup, page_cached), (rows, csv_url, csv_cached) = await asyncio.gather(
        _fnp_page("population", band_number, lang), _regpop(lang)
    )
    annual = [
        AnnualPopulation(
            year=r["year"],
            on_reserve_men=r["on_men"],
            on_reserve_women=r["on_women"],
            on_reserve=r["on_total"],
            off_reserve_men=r["off_men"],
            off_reserve_women=r["off_women"],
            off_reserve=r["off_total"],
            men=r["men"],
            women=r["women"],
            total=r["total"],
        )
        for r in sorted(rows, key=lambda r: r["year"])
        if r["number"] == band_number
    ]
    url = fnp_url("population", band_number, lang)
    return RegisteredPopulation(
        band_number=band_number,
        **parse_population(soup),
        annual=annual,
        annual_source=csv_url,
        notes=[_text(_ANNUAL_NOTE, _ANNUAL_NOTE_FR, lang)],
        provenance=make_provenance(
            source="isc",
            url=url,
            cached=page_cached and csv_cached,
            schema_name="isc.RegisteredPopulation",
            freshness=_text(
                "Monthly on the profile; yearly in the open dataset.",
                "Mensuelle dans le profil ; annuelle dans le jeu de données ouvert.",
                lang,
            ),
            licence=_text(
                f"Monthly figures: {CANADA_CA_TERMS} Yearly figures: {OGL_CANADA}",
                _REGPOP_LICENCE_FR,
                lang,
            ),
            lang=lang,
        ),
    )


# --- Long-term drinking water advisories -------------------------------------


def find_map_source(html: str, page_url: str) -> str | None:
    match = _APP_CONFIG_SOURCE.search(html)
    if not match:
        return None
    url = urljoin(page_url, match.group(1).replace("\\/", "/"))
    return url if urlparse(url).hostname == constants.SAC_HOST else None


def _kind(advisory_type: str) -> AdvisoryKind:
    folded = _fold(advisory_type)
    if "boil" in folded or "ebullition" in folded:
        return "boil_water"
    if "consume" in folded or "consommer" in folded or "boire" in folded:
        return "do_not_consume"
    if "not use" in folded or "utilisation" in folded:
        return "do_not_use"
    return "other"


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _advisory(
    item: dict[str, Any], community: dict[str, Any], status: Literal["current", "lifted"]
) -> LongTermAdvisory:
    advisory_type = _clean(item.get("AdvisoryType")) or ""
    return LongTermAdvisory(
        advisory_id=str(item.get("AdvisoryID") or ""),
        status=status,
        band_number=_to_int(item.get("CommunityNum") or community.get("CommunityNum")),
        community=_clean(item.get("CommunityName")) or _clean(community.get("CommunityName")) or "",
        province=_clean(community.get("Province")),
        province_code=_clean(community.get("ProvinceAcronym")),
        region=_clean(item.get("Region") or community.get("Region")),
        water_system=_clean(item.get("WaterSystemName")),
        advisory_type=advisory_type,
        kind=_kind(advisory_type),
        date_set=_iso_date(item.get("DateSet")),
        date_long_term=_iso_date(item.get("DateLTDWASet")),
        # DateExpected holds the lift date on lifted advisories (see the docstring).
        date_lifted=_iso_date(item.get("DateExpected")) if status == "lifted" else None,
        population_affected=_clean(item.get("PopulatioEstimated")),
        corrective_measure=_clean(item.get("CorrectiveMeasure")),
        project_phase=_clean(item.get("LongPhase")),
        recommended_to_lift=str(item.get("RecommendedEPHO")).lower() == "yes",
        latitude=_float(item.get("Lattitude")),
        longitude=_float(item.get("Longitude")),
    )


_MAP_LISTS: tuple[tuple[Literal["current", "lifted"], str], ...] = (
    ("current", "LTDWACurrent"),
    ("lifted", "LTDWALifted"),
)


def parse_map(payload: dict[str, Any]) -> tuple[date | None, list[LongTermAdvisory]]:
    communities = payload.get("data")
    if not isinstance(communities, list):
        raise UpstreamError("isc: the advisory map file has no 'data' list.")
    advisories = [
        _advisory(item, community, status)
        for community in communities
        for status, key in _MAP_LISTS
        for item in community.get(key) or []
    ]
    return _iso_date(payload.get("GenerateDate")), advisories


async def _map(lang: str) -> tuple[date | None, list[LongTermAdvisory], str, bool]:
    page_url = constants.LTDWA_PAGE.format(lang=_page_lang(lang))

    async def fetch() -> tuple[date | None, list[LongTermAdvisory], str]:
        html = _decode(await _fetch(page_url, constants.MAX_PAGE_BYTES, lang))
        source = find_map_source(html, page_url)
        if source is None:
            raise_localized(
                UpstreamError,
                f"isc: {page_url} no longer names the advisory map file (App_config "
                "LinkAjaxSource).",
                f"isc : {page_url} ne nomme plus le fichier de la carte des avis "
                "(App_config LinkAjaxSource).",
                lang,
            )
        body = await _fetch(source, constants.MAX_MAP_BYTES, lang)
        try:
            payload = json.loads(_decode(body))
        except json.JSONDecodeError as exc:
            raise UpstreamError(f"isc: {source} is not JSON ({exc}).") from exc
        generated, advisories = parse_map(payload)
        return generated, advisories, source

    (generated, advisories, source), cached = await cached_fetch(
        f"isc:ltdwa:{lang}", constants.ADVISORY_TTL_SECONDS, fetch
    )
    return generated, advisories, source, cached


async def list_drinking_water_advisories(
    status: Literal["current", "lifted", "all"] = "current",
    *,
    province: str = "",
    community: str = "",
    limit: int = constants.ADVISORY_DEFAULT_LIMIT,
    lang: str = "en",
) -> LongTermAdvisoryList:
    code = province_code(province, lang)
    limit = max(1, min(limit, constants.ADVISORY_MAX_LIMIT))
    generated, advisories, source, cached = await _map(lang)
    current = [a for a in advisories if a.status == "current"]
    matches = [a for a in advisories if status == "all" or a.status == status]
    if code:
        matches = [a for a in matches if a.province_code == code]
    wanted = _fold(community)
    if wanted.isdigit():
        matches = [a for a in matches if a.band_number == int(wanted)]
    elif wanted:
        matches = [a for a in matches if wanted in _fold(a.community)]
    matches.sort(key=lambda a: (a.status, _fold(a.community), a.date_set or date.min))
    page = matches[:limit]
    return LongTermAdvisoryList(
        generated=generated,
        status=status,
        current_count=len(current),
        lifted_count=len(advisories) - len(current),
        communities_with_current=len({a.band_number or a.community for a in current}),
        advisories=page,
        returned_count=len(page),
        total_matched=len(matches),
        data_url=source,
        notes=[_text(_LTDWA_NOTE, _LTDWA_NOTE_FR, lang)],
        provenance=make_provenance(
            source="isc",
            url=constants.LTDWA_PAGE.format(lang=_page_lang(lang)),
            cached=cached,
            schema_name="isc.LongTermAdvisoryList",
            as_of=_midnight(generated),
            freshness=_text(
                "ISC regenerates the map file about weekly.",
                "SAC régénère le fichier de la carte environ chaque semaine.",
                lang,
            ),
            limits=(
                _text(
                    f"First {len(page)} of {len(matches)} advisories.",
                    f"{len(page)} premiers avis sur {len(matches)}.",
                    lang,
                )
                if len(matches) > len(page)
                else None
            ),
            licence=CANADA_CA_TERMS,
            lang=lang,
        ),
    )


# --- Short-term drinking water advisories ------------------------------------


def _yes_no(text: str) -> bool | None:
    folded = _fold(text)
    if folded in ("yes", "oui"):
        return True
    if folded in ("no", "non"):
        return False
    return None


def parse_as_of(text: str) -> tuple[date | None, int | None]:
    """The page's 'As of October 25, 2026, there were 39 ...' sentence (or its French)."""
    clean = " ".join(text.replace("\xa0", " ").split())
    found: date | None = None
    english = re.search(r"As of ([A-Za-z]+) (\d{1,2}) ?, (\d{4})", clean)
    french = re.search(r"En date du (\d{1,2})(?:er)? ([^\W\d_]+) (\d{4})", clean)
    if english and english.group(1).lower() in _EN_MONTHS:
        month = _EN_MONTHS[english.group(1).lower()]
        found = date(int(english.group(3)), month, int(english.group(2)))
    elif french and french.group(2).lower() in _FR_MONTHS:
        month = _FR_MONTHS[french.group(2).lower()]
        found = date(int(french.group(3)), month, int(french.group(1)))
    count = re.search(r"there were (\d+)", clean) or re.search(r", (\d+) avis", clean)
    return found, int(count.group(1)) if count else None


def parse_short_term(html: str) -> tuple[date | None, int | None, list[ShortTermAdvisory]]:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main") or soup
    as_of: date | None = None
    count: int | None = None
    for paragraph in main.find_all("p"):
        as_of, count = parse_as_of(paragraph.get_text(" ", strip=True))
        if as_of is not None:
            break
    # A region with nothing listed shows "All short-term drinking water advisories
    # have been lifted" instead of a table (a variant kept commented out in the
    # page), so no tables at all is only a layout change when the "As of"
    # sentence is gone too.
    tables = main.find_all("table")
    if not tables and as_of is None:
        raise UpstreamError("isc: the short-term advisory page has no tables.")
    advisories = []
    for table in tables:
        heading = table.find_previous("h3")
        name = _fold(heading.get_text(" ", strip=True)) if heading else ""
        region = constants.STDWA_REGION_NAMES.get(name, name.upper())
        for tr in table.find_all("tr"):
            cells = [_clean(td.get_text(" ", strip=True)) or "" for td in tr.find_all("td")]
            if len(cells) < 8:
                continue
            code = cells[3].upper()
            kind: AdvisoryKind = constants.ADVISORY_CODES.get(code, "other")  # type: ignore[assignment]
            revoked = _iso_date(cells[5])
            advisories.append(
                ShortTermAdvisory(
                    region=region,
                    first_nation=cells[0],
                    community=cells[1] or None,
                    water_system=cells[2] or None,
                    code=code,
                    kind=kind,
                    date_set=_iso_date(cells[4]),
                    date_revoked=revoked,
                    active=revoked is None,
                    population=cells[6] or None,
                    isc_supported=_yes_no(cells[7]),
                )
            )
    return as_of, count, advisories


def _stdwa_region(province: str, lang: str) -> str:
    folded = _fold(province)
    if not folded:
        return ""
    if folded in constants.STDWA_REGION_NAMES:
        return constants.STDWA_REGION_NAMES[folded]
    region = constants.STDWA_REGIONS.get(province_code(province, lang), "")
    if not region:
        raise_localized(
            InvalidInput,
            f"isc: the short-term list has no table for {province!r}; it covers the "
            "Atlantic provinces, Quebec, Ontario, Manitoba, Saskatchewan and Alberta "
            "(British Columbia's are published by the First Nations Health Authority).",
            f"isc : la liste à court terme n'a pas de tableau pour {province!r} ; elle "
            "couvre les provinces de l'Atlantique, le Québec, l'Ontario, le Manitoba, la "
            "Saskatchewan et l'Alberta (ceux de la Colombie-Britannique sont publiés par "
            "l'Autorité sanitaire des Premières Nations).",
            lang,
        )
    return region


async def list_short_term_advisories(
    *,
    province: str = "",
    community: str = "",
    active_only: bool = False,
    lang: str = "en",
) -> ShortTermAdvisoryList:
    region = _stdwa_region(province, lang)
    url = constants.STDWA_PAGE.format(lang=_page_lang(lang))

    async def fetch() -> tuple[date | None, int | None, list[ShortTermAdvisory]]:
        return parse_short_term(_decode(await _fetch(url, constants.MAX_PAGE_BYTES, lang)))

    (as_of, count, advisories), cached = await cached_fetch(
        f"isc:stdwa:{lang}", constants.ADVISORY_TTL_SECONDS, fetch
    )
    matches = [a for a in advisories if not region or a.region == region]
    if active_only:
        matches = [a for a in matches if a.active]
    wanted = _fold(community)
    if wanted:
        matches = [a for a in matches if wanted in _fold(f"{a.first_nation} {a.community or ''}")]
    return ShortTermAdvisoryList(
        as_of=as_of,
        in_effect_count=count,
        advisories=matches,
        returned_count=len(matches),
        total_matched=len(matches),
        notes=[_text(_STDWA_NOTE, _STDWA_NOTE_FR, lang)],
        provenance=make_provenance(
            source="isc",
            url=url,
            cached=cached,
            schema_name="isc.ShortTermAdvisoryList",
            as_of=_midnight(as_of),
            freshness=_text(
                "Updated by ISC as advisories are reported; postings can be delayed.",
                "Mis à jour par SAC à mesure que les avis sont signalés ; la publication "
                "peut être retardée.",
                lang,
            ),
            licence=CANADA_CA_TERMS,
            lang=lang,
        ),
    )
