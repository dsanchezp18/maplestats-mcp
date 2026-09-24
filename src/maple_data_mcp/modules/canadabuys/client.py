"""Client for CanadaBuys' open-data notice CSVs.

Confirmed live 2026-09-22 against the files themselves (not the data
dictionary prose):

- Every file is UTF-8 with a BOM, and every column name is bilingual,
  e.g. `title-titre-eng` / `title-titre-fra`, so the `lang` argument picks
  a column suffix rather than a different URL.
- Multi-valued fields (procurement category, region of delivery, UNSPSC,
  trade agreements) are packed into one cell as `*A\\n*B`; split to lists.
- Descriptions carry raw HTML and entities (`&nbsp;`, `&eacute;`, leading
  `\\r\\n\\t`); they are unescaped and tag-stripped here.
- `referenceNumber-numeroReference` was unique within each file checked
  (905 open tenders, 3,983 2026-2027 awards), so it is the lookup key.
- Some awards report `totalContractValue` as `0.00` alongside a non-zero
  `contractAmount` (e.g. a $2,000,000 Marine Atlantic award): zero there
  means "not reported", so it is returned as None rather than 0.
- The award files are 10MB+ and served as `application/octet-stream`;
  like CRA's large canada.ca page (see cra_digital_economy_registry),
  they are fetched over a dedicated http2=False client with its own
  retry, so a stream reset on a big body does not touch the shared
  client StatCan depends on.
"""

from __future__ import annotations

import csv
import html
import io
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from maple_data_mcp.modules.canadabuys import constants
from maple_data_mcp.modules.canadabuys.schemas import (
    AwardNotice,
    AwardSearchResult,
    BulkFile,
    BulkFileList,
    ContractRecord,
    ContractSearchResult,
    NoticeDetail,
    TenderNotice,
    TenderSearchResult,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import new_client
from maple_data_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_client = new_client(timeout=90.0, http2=False)

_CATEGORY_CODES = {
    "goods": "GD",
    "services": "SRV",
    "construction": "CNST",
    "services_related_to_goods": "SRVTGD",
}
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_FISCAL_YEAR_RE = re.compile(r"^(\d{4})-(\d{4})$")


@retry(
    retry=retry_if_exception_type(
        (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError)
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
async def _get(url: str) -> httpx.Response:
    response = await _client.get(url)
    response.raise_for_status()
    return response


async def _load_rows(
    url: str,
    *,
    columns: tuple[str, ...] | None = None,
    ttl: int = constants.CACHE_TTL_SECONDS,
) -> tuple[list[dict[str, str]], bool]:
    async def fetch() -> list[dict[str, str]]:
        await _LIMITER.acquire()
        try:
            response = await _get(url)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise NotFound(f"canadabuys: no file published at {url}.") from exc
            raise UpstreamError(
                f"canadabuys returned HTTP {exc.response.status_code} for {url}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"canadabuys did not respond in time for {url}.") from exc
        text = response.content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if not reader.fieldnames or "referenceNumber-numeroReference" not in reader.fieldnames:
            raise UpstreamError(
                "canadabuys: expected CSV columns not found "
                "(missing referenceNumber-numeroReference)."
            )
        if columns is None:
            return list(reader)
        # Contract-history files carry 91 columns and run up to 113MB;
        # keeping only the columns a tool reads keeps the cached copy small.
        return [{column: row.get(column) or "" for column in columns} for row in reader]

    return await cached_fetch(f"canadabuys:{url}", ttl, fetch)


def _value(row: dict[str, str], column: str) -> str | None:
    text = (row.get(column) or "").strip()
    return text or None


def _localized(row: dict[str, str], stem: str, lang: str) -> str | None:
    suffix = "eng" if lang == "en" else "fra"
    return _value(row, f"{stem}-{suffix}") or _value(row, f"{stem}-eng")


def _list(text: str | None) -> list[str]:
    if not text:
        return []
    return [part.strip().lstrip("*").strip() for part in text.split("\n") if part.strip("* \r\t")]


def _clean_description(text: str | None, max_chars: int | None) -> str | None:
    if not text:
        return None
    cleaned = _SPACE_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", text))).strip()
    if max_chars is not None and len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rstrip() + "..."
    return cleaned or None


def _amount(text: str | None) -> float | None:
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value or None


def _tender(row: dict[str, str], lang: str, max_chars: int | None) -> TenderNotice:
    return TenderNotice(
        reference_number=row["referenceNumber-numeroReference"],
        solicitation_number=_value(row, "solicitationNumber-numeroSollicitation"),
        amendment_number=_value(row, "amendmentNumber-numeroModification"),
        title=_localized(row, "title-titre", lang) or "",
        status=_localized(row, "tenderStatus-appelOffresStatut", lang),
        publication_date=_value(row, "publicationDate-datePublication"),
        closing_date=_value(row, "tenderClosingDate-appelOffresDateCloture"),
        procurement_categories=_list(_value(row, "procurementCategory-categorieApprovisionnement")),
        procurement_method=_localized(row, "procurementMethod-methodeApprovisionnement", lang),
        contracting_entity=_localized(row, "contractingEntityName-nomEntitContractante", lang),
        regions_of_delivery=_list(_localized(row, "regionsOfDelivery-regionsLivraison", lang)),
        unspsc=_list(_localized(row, "unspscDescription", lang)),
        notice_url=_localized(row, "noticeURL-URLavis", lang),
        description=_clean_description(
            _localized(row, "tenderDescription-descriptionAppelOffres", lang), max_chars
        ),
    )


def _award(row: dict[str, str], lang: str, max_chars: int | None) -> AwardNotice:
    return AwardNotice(
        reference_number=row["referenceNumber-numeroReference"],
        solicitation_number=_value(row, "solicitationNumber-numeroSollicitation"),
        contract_number=_value(row, "contractNumber-numeroContrat"),
        title=_localized(row, "title-titre", lang) or "",
        status=_localized(row, "awardStatus-attributionStatut", lang),
        publication_date=_value(row, "publicationDate-datePublication"),
        award_date=_value(row, "contractAwardDate-dateAttributionContrat"),
        contract_start_date=_value(row, "contractStartDate-contratDateDebut"),
        contract_end_date=_value(row, "contractEndDate-dateFinContrat"),
        contract_amount=_amount(_value(row, "contractAmount-montantContrat")),
        total_contract_value=_amount(_value(row, "totalContractValue-valeurTotaleContrat")),
        currency=_value(row, "contractCurrency-contratMonnaie"),
        supplier_name=_localized(row, "supplierLegalName-nomLegalFournisseur", lang),
        supplier_city=_localized(row, "supplierAddressCity-fournisseurAdresseVille", lang),
        supplier_province=_localized(
            row, "supplierAddressProvince-fournisseurAdresseProvince", lang
        ),
        supplier_country=_localized(row, "supplierAddressCountry-fournisseurAdressePays", lang),
        contracting_entity=_localized(row, "contractingEntityName-nomEntitContractante", lang),
        procurement_categories=_list(_value(row, "procurementCategory-categorieApprovisionnement")),
        procurement_method=_localized(row, "procurementMethod-methodeApprovisionnement", lang),
        regions_of_delivery=_list(_localized(row, "regionsOfDelivery-regionsLivraison", lang)),
        unspsc=_list(_localized(row, "unspscDescription", lang)),
        description=_clean_description(
            _localized(row, "awardDescription-descriptionAttribution", lang), max_chars
        ),
    )


def _check_lang(lang: str) -> None:
    if lang not in ("en", "fr"):
        raise InvalidInput(f"lang must be one of ('en', 'fr'), got {lang!r}.")


def _check_limit(limit: int) -> None:
    if not 1 <= limit <= constants.SEARCH_RESULTS_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.SEARCH_RESULTS_MAX}.")


def _category_code(category: str | None) -> str | None:
    if category is None:
        return None
    code = _CATEGORY_CODES.get(category)
    if code is None:
        raise InvalidInput(f"category must be one of {tuple(_CATEGORY_CODES)}, got {category!r}.")
    return code


def current_fiscal_year(today: datetime | None = None) -> str:
    now = today or datetime.now(ZoneInfo(constants.FISCAL_YEAR_TIMEZONE))
    start = now.year if now.month >= 4 else now.year - 1
    return f"{start}-{start + 1}"


def _check_fiscal_year(fiscal_year: str) -> str:
    match = _FISCAL_YEAR_RE.match(fiscal_year)
    current_start = int(current_fiscal_year()[:4])
    if (
        match is None
        or int(match.group(2)) != int(match.group(1)) + 1
        or not constants.FIRST_AWARD_FISCAL_YEAR <= int(match.group(1)) <= current_start
    ):
        raise InvalidInput(
            f"fiscal_year must look like '2025-2026' and fall between "
            f"{constants.FIRST_AWARD_FISCAL_YEAR}-{constants.FIRST_AWARD_FISCAL_YEAR + 1} "
            f"and {current_fiscal_year()}, got {fiscal_year!r}."
        )
    return fiscal_year


def _matches_terms(haystack: str, query: str) -> bool:
    # Every whitespace-separated term must appear, so "snow removal ottawa"
    # narrows rather than widens the result set.
    return all(term in haystack for term in query.lower().split())


def _haystack(row: dict[str, str], stems: tuple[str, ...], lang: str) -> str:
    parts = [row.get("referenceNumber-numeroReference", "")]
    parts.append(row.get("solicitationNumber-numeroSollicitation", ""))
    parts.extend(_localized(row, stem, lang) or "" for stem in stems)
    return " ".join(parts).lower()


def _contains(value: str | None, needle: str | None) -> bool:
    return not needle or (value is not None and needle.strip().lower() in value.lower())


async def search_tenders(
    query: str = "",
    *,
    notice_set: str = "open",
    category: str | None = None,
    region: str | None = None,
    buyer: str | None = None,
    limit: int = constants.SEARCH_RESULTS_DEFAULT,
    lang: str = "en",
) -> TenderSearchResult:
    _check_lang(lang)
    _check_limit(limit)
    code = _category_code(category)
    if notice_set not in ("open", "new"):
        raise InvalidInput(f"notice_set must be 'open' or 'new', got {notice_set!r}.")
    url = constants.OPEN_TENDERS_URL if notice_set == "open" else constants.NEW_TENDERS_URL
    rows, was_cached = await _load_rows(url)
    # Checked live 2026-09-24: the "open" file still lists 54 of its first
    # 100 soonest-closing notices whose closing date has passed (one from
    # 2023). Closing times are Ottawa local time, like FISCAL_YEAR_TIMEZONE.
    now = datetime.now(ZoneInfo(constants.FISCAL_YEAR_TIMEZONE)).strftime("%Y-%m-%dT%H:%M:%S")
    expired = 0
    if notice_set == "open":
        live = [
            r for r in rows if (r.get("tenderClosingDate-appelOffresDateCloture") or "9999") >= now
        ]
        expired = len(rows) - len(live)
        rows = live

    stems = ("title-titre", "tenderDescription-descriptionAppelOffres", "unspscDescription")
    matched = [
        row
        for row in rows
        if _matches_terms(_haystack(row, stems, lang), query)
        and (
            code is None or code in _list(row.get("procurementCategory-categorieApprovisionnement"))
        )
        and _contains(_localized(row, "regionsOfDelivery-regionsLivraison", lang), region)
        and _contains(_localized(row, "contractingEntityName-nomEntitContractante", lang), buyer)
    ]

    # Soonest-closing first: the most time-sensitive open opportunities lead.
    matched.sort(key=lambda row: row.get("tenderClosingDate-appelOffresDateCloture") or "9999")
    tenders = [_tender(row, lang, constants.SUMMARY_DESCRIPTION_CHARS) for row in matched[:limit]]
    coverage = None
    if len(matched) > len(tenders):
        coverage = f"first {len(tenders)} of {len(matched)} matches -- narrow the query"

    return TenderSearchResult(
        query=query,
        notice_set=notice_set,
        tenders=tenders,
        returned_count=len(tenders),
        total_matched=len(matched),
        total_notices=len(rows),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="canadabuys.TenderSearchResult",
            freshness="regenerated daily by CanadaBuys",
            coverage=coverage,
            limits=f"descriptions truncated to {constants.SUMMARY_DESCRIPTION_CHARS} characters; "
            "use canadabuys_get_notice for the full text"
            + (f"; {expired} notices past their closing date were left out" if expired else ""),
        ),
    )


async def search_awards(
    query: str = "",
    *,
    supplier: str | None = None,
    buyer: str | None = None,
    category: str | None = None,
    fiscal_year: str | None = None,
    limit: int = constants.SEARCH_RESULTS_DEFAULT,
    lang: str = "en",
) -> AwardSearchResult:
    _check_lang(lang)
    _check_limit(limit)
    code = _category_code(category)
    year = _check_fiscal_year(fiscal_year) if fiscal_year else current_fiscal_year()
    url = constants.AWARDS_URL_TEMPLATE.format(fiscal_year=year)
    rows, was_cached = await _load_rows(url)

    stems = (
        "title-titre",
        "awardDescription-descriptionAttribution",
        "unspscDescription",
        "supplierLegalName-nomLegalFournisseur",
        "contractingEntityName-nomEntitContractante",
    )
    matched = [
        row
        for row in rows
        if _matches_terms(_haystack(row, stems, lang), query)
        and (
            code is None or code in _list(row.get("procurementCategory-categorieApprovisionnement"))
        )
        and _contains(_localized(row, "supplierLegalName-nomLegalFournisseur", lang), supplier)
        and _contains(_localized(row, "contractingEntityName-nomEntitContractante", lang), buyer)
    ]

    matched.sort(key=lambda row: row.get("publicationDate-datePublication") or "", reverse=True)
    awards = [_award(row, lang, constants.SUMMARY_DESCRIPTION_CHARS) for row in matched[:limit]]
    coverage = f"award notices published in fiscal year {year}"
    if len(matched) > len(awards):
        coverage += f"; first {len(awards)} of {len(matched)} matches -- narrow the query"

    return AwardSearchResult(
        query=query,
        fiscal_year=year,
        awards=awards,
        returned_count=len(awards),
        total_matched=len(matched),
        total_notices=len(rows),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="canadabuys.AwardSearchResult",
            freshness="regenerated daily by CanadaBuys",
            coverage=coverage,
            limits="total_contract_value is None when CanadaBuys reports 0.00 (not reported)",
        ),
    )


async def get_notice(
    reference_number: str, *, fiscal_year: str | None = None, lang: str = "en"
) -> NoticeDetail:
    _check_lang(lang)
    reference = reference_number.strip()
    if not reference:
        raise InvalidInput("reference_number must not be empty.")

    rows, was_cached = await _load_rows(constants.OPEN_TENDERS_URL)
    for row in rows:
        if row["referenceNumber-numeroReference"] == reference:
            return NoticeDetail(
                reference_number=reference,
                notice_kind="tender",
                tender=_tender(row, lang, None),
                award=None,
                provenance=make_provenance(
                    source=constants.RATE_LIMIT_SOURCE,
                    url=constants.OPEN_TENDERS_URL,
                    cached=was_cached,
                    schema_name="canadabuys.NoticeDetail",
                ),
            )

    # Not an open tender: look in the requested award year, or else the
    # current and previous fiscal years (a notice published in March is
    # in last year's file).
    if fiscal_year:
        years = [_check_fiscal_year(fiscal_year)]
    else:
        current_start = int(current_fiscal_year()[:4])
        years = [f"{start}-{start + 1}" for start in (current_start, current_start - 1)]
    for year in years:
        url = constants.AWARDS_URL_TEMPLATE.format(fiscal_year=year)
        rows, was_cached = await _load_rows(url)
        for row in rows:
            if row["referenceNumber-numeroReference"] == reference:
                return NoticeDetail(
                    reference_number=reference,
                    notice_kind="award",
                    tender=None,
                    award=_award(row, lang, None),
                    provenance=make_provenance(
                        source=constants.RATE_LIMIT_SOURCE,
                        url=url,
                        cached=was_cached,
                        schema_name="canadabuys.NoticeDetail",
                        coverage=f"award notices published in fiscal year {year}",
                    ),
                )

    raise NotFound(
        f"canadabuys: reference number {reference!r} is not an open tender or an award "
        f"notice in {', '.join(years)}. Pass fiscal_year to search an older award year."
    )


_CONTRACT_STEMS = (
    "title-titre",
    "supplierLegalName-nomLegalFournisseur",
    "supplierStandardizedName-nomNormaliseFournisseur",
    "supplierAddressProvince-fournisseurAdresseProvince",
    "supplierAddressCountry-fournisseurAdressePays",
    "contractingEntityName-nomEntitContractante",
    "endUserEntitiesName-nomEntitesUtilisateurFinal",
    "contractStatus-statutContrat",
    "procurementMethod-methodeApprovisionnement",
    "limitedTenderingReason-raisonAppelOffresLimite",
    "unspscDescription",
    "gsinDescription-nibsDescription",
)
_CONTRACT_COLUMNS = (
    "referenceNumber-numeroReference",
    "solicitationNumber-numeroSollicitation",
    "contractNumber-numeroContrat",
    "amendmentNumber-numeroModification",
    "contractAwardDate-dateAttributionContrat",
    "amendmentDate-dateModification",
    "contractStartDate-contratDateDebut",
    "contractEndDate-dateFinContrat",
    "contractAmount-montantContrat",
    "totalContractValue-valeurTotaleContrat",
    "contractCurrency-contratMonnaie",
    "procurementCategory-categorieApprovisionnement",
    *(f"{stem}-{suffix}" for stem in _CONTRACT_STEMS for suffix in ("eng", "fra")),
)


def _check_contract_year(fiscal_year: str) -> str:
    if fiscal_year == constants.CONTRACTS_PARTIAL_2009_KEY:
        return fiscal_year
    match = _FISCAL_YEAR_RE.match(fiscal_year)
    current_start = int(current_fiscal_year()[:4])
    if (
        match is None
        or int(match.group(2)) != int(match.group(1)) + 1
        or not constants.FIRST_CONTRACT_FISCAL_YEAR <= int(match.group(1)) <= current_start
    ):
        raise InvalidInput(
            f"fiscal_year must look like '2015-2016' and fall between "
            f"{constants.FIRST_CONTRACT_FISCAL_YEAR}-{constants.FIRST_CONTRACT_FISCAL_YEAR + 1} "
            f"and {current_fiscal_year()} (or '{constants.CONTRACTS_PARTIAL_2009_KEY}' for "
            f"January-March 2009), got {fiscal_year!r}."
        )
    return fiscal_year


def _contract(rows: list[dict[str, str]], lang: str) -> ContractRecord:
    # One contract appears once per amendment (confirmed live: 97 rows for
    # one 2020-2021 contract). The original row (000) holds the awarded
    # amount; the highest-numbered row holds the latest status and total.
    ordered = sorted(rows, key=lambda row: row["amendmentNumber-numeroModification"])
    original, latest = ordered[0], ordered[-1]
    return ContractRecord(
        reference_number=latest["referenceNumber-numeroReference"],
        contract_number=_value(latest, "contractNumber-numeroContrat"),
        title=_localized(latest, "title-titre", lang) or "",
        status=_localized(latest, "contractStatus-statutContrat", lang),
        award_date=_value(original, "contractAwardDate-dateAttributionContrat"),
        contract_start_date=_value(original, "contractStartDate-contratDateDebut"),
        contract_end_date=_value(latest, "contractEndDate-dateFinContrat"),
        original_amount=_amount(_value(original, "contractAmount-montantContrat")),
        total_contract_value=_amount(_value(latest, "totalContractValue-valeurTotaleContrat")),
        currency=_value(latest, "contractCurrency-contratMonnaie"),
        amendment_count=len(ordered) - 1,
        latest_amendment_date=_value(latest, "amendmentDate-dateModification"),
        supplier_name=_localized(latest, "supplierLegalName-nomLegalFournisseur", lang),
        supplier_standardized_name=_localized(
            latest, "supplierStandardizedName-nomNormaliseFournisseur", lang
        ),
        supplier_province=_localized(
            latest, "supplierAddressProvince-fournisseurAdresseProvince", lang
        ),
        supplier_country=_localized(latest, "supplierAddressCountry-fournisseurAdressePays", lang),
        contracting_entity=_localized(latest, "contractingEntityName-nomEntitContractante", lang),
        end_user_entity=_localized(latest, "endUserEntitiesName-nomEntitesUtilisateurFinal", lang),
        procurement_categories=_list(
            _value(latest, "procurementCategory-categorieApprovisionnement")
        ),
        procurement_method=_localized(latest, "procurementMethod-methodeApprovisionnement", lang),
        limited_tendering_reason=_localized(
            latest, "limitedTenderingReason-raisonAppelOffresLimite", lang
        ),
        commodity=_list(
            _localized(latest, "unspscDescription", lang)
            or _localized(latest, "gsinDescription-nibsDescription", lang)
        ),
    )


async def search_contracts(
    query: str = "",
    *,
    supplier: str | None = None,
    buyer: str | None = None,
    category: str | None = None,
    min_value: float | None = None,
    fiscal_year: str | None = None,
    limit: int = constants.SEARCH_RESULTS_DEFAULT,
    lang: str = "en",
) -> ContractSearchResult:
    _check_lang(lang)
    _check_limit(limit)
    code = _category_code(category)
    year = _check_contract_year(fiscal_year) if fiscal_year else current_fiscal_year()
    url = constants.CONTRACTS_URL_TEMPLATE.format(fiscal_year=year)
    ttl = (
        constants.CACHE_TTL_SECONDS
        if year == current_fiscal_year()
        else constants.PAST_YEAR_CACHE_TTL_SECONDS
    )
    rows, was_cached = await _load_rows(url, columns=_CONTRACT_COLUMNS, ttl=ttl)

    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["referenceNumber-numeroReference"], []).append(row)

    supplier_needle = (supplier or "").strip().lower()
    matched: list[ContractRecord] = []
    for group in grouped.values():
        if not _matches_terms(_haystack(group[-1], _CONTRACT_STEMS, lang), query):
            continue
        contract = _contract(group, lang)
        names = (contract.supplier_name, contract.supplier_standardized_name)
        if (
            (code is None or code in contract.procurement_categories)
            and (not supplier_needle or any(supplier_needle in (n or "").lower() for n in names))
            and _contains(contract.contracting_entity, buyer)
            and (min_value is None or (contract.total_contract_value or 0) >= min_value)
        ):
            matched.append(contract)

    matched.sort(key=lambda contract: contract.total_contract_value or 0, reverse=True)
    returned = matched[:limit]
    coverage = f"contracts awarded or amended in fiscal year {year}"
    if len(matched) > len(returned):
        coverage += f"; first {len(returned)} of {len(matched)} matches -- narrow the query"

    return ContractSearchResult(
        query=query,
        fiscal_year=year,
        contracts=returned,
        returned_count=len(returned),
        total_matched=len(matched),
        total_contracts=len(grouped),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="canadabuys.ContractSearchResult",
            coverage=coverage,
            limits="one record per contract, amendments merged; amendments made in other "
            "fiscal years are in those years' files",
        ),
    )


async def list_bulk_files() -> BulkFileList:
    async def fetch() -> list[BulkFile]:
        files: list[BulkFile] = []
        for key, (title, name) in constants.BULK_FILES.items():
            url = f"{constants.BASE_URL}/{name}"
            await _LIMITER.acquire()
            try:
                response = await _client.head(url)
            except httpx.HTTPError as exc:
                raise UpstreamUnavailable(f"canadabuys did not respond for {url}.") from exc
            if response.status_code != 200:
                raise UpstreamError(f"canadabuys returned HTTP {response.status_code} for {url}.")
            length = response.headers.get("content-length")
            files.append(
                BulkFile(
                    key=key,
                    title=title,
                    url=url,
                    size_bytes=int(length) if length and length.isdigit() else None,
                    last_modified=response.headers.get("last-modified"),
                )
            )
        return files

    files, was_cached = await cached_fetch(
        "canadabuys:bulk-files", constants.PAST_YEAR_CACHE_TTL_SECONDS, fetch
    )
    return BulkFileList(
        files=files,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.BASE_URL,
            cached=was_cached,
            schema_name="canadabuys.BulkFileList",
            limits="links only: these files are too large to query through this server",
        ),
    )
