"""Constants for the federal proactive disclosure DataStore tables on open.canada.ca.

Every id and field name below was read live on 2026-11-03 with
package_show and datastore_search, and the field meanings from the
"recombinant" schemas each package links as its Data Schema
(open.canada.ca/data/recombinant-published-schema/{contracts,grants,
travelq,hospitalityq}.json). What that check found and this module relies on:

- Every column, dates and dollar amounts included, is stored as `text`;
  dates are ISO (YYYY-MM-DD), so they sort correctly as text, but amounts
  do not (a `contract_value::numeric` sort is a 409 Validation Error).
- `datastore_search_sql` is not enabled ("Action name not known"), so
  totals cannot be computed by the portal; `datastore_search` returns at
  most 1,000 rows per call whatever `limit` asks (it used to be 32,000).
- `filters` are exact matches and take a list for "any of" (SQL IN);
  `q` as a {column: words} object is a per-column full-text match (case
  and word-form insensitive) that works on these 1.3-million-row tables,
  while a plain-string `q` fails on tables over 100,000 rows.
- A POST with a JSON body works like a GET and takes filter lists far
  longer than a URL holds; that is how a date range becomes an exact
  server-side filter (the list of every day in it).
- `distinct=true` returns an incomplete set of values on these tables
  (2 of 3 disclosure groups), so it is not used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

DatasetKey = Literal["contracts", "grants", "travel", "hospitality"]

BASE_URL = "https://open.canada.ca/data/api/3/action/"
DATASET_PAGE = "https://open.canada.ca/data/{lang}/dataset/{id}"

RATE_LIMIT_SOURCE = "proactive-disclosure"
RATE_LIMIT_PER_SECOND = 8.0
RATE_LIMIT_CAPACITY = 8.0
# Pages fetched at once while scanning a filtered set. Measured 2026-11-03:
# one 1,000-row page takes 0.7-1.7 s. Summing one fiscal year of contracts
# (88-95 pages) took 83 s 4 at a time, 40-70 s 8 at a time, 40 s 5 at a time
# (the portal's speed varies run to run); 12 at a time drew enough timeouts
# to open the shared circuit breaker for open.canada.ca. So 8, no more.
SCAN_CONCURRENCY = 8
REQUEST_TIMEOUT_SECONDS = 45.0

PAGE_SIZE = 1000
SEARCH_LIMIT_DEFAULT = 25
SEARCH_LIMIT_MAX = 100
# A value range, a value sort or a summary reads every matching row (only
# the few columns it needs). Past this many rows the request must be
# narrowed; 100,000 is a little more than one fiscal year of contracts for
# all departments (87,236 rows in 2024-2025).
SCAN_MAX_ROWS = 100_000
# A date range is sent as the list of its days; ten years is ~3,650 values,
# which open.canada.ca answered in 5 s on the contracts table.
DATE_SPAN_MAX_DAYS = 3_660
SUMMARY_TOP_DEFAULT = 25
SUMMARY_TOP_MAX = 200

CACHE_TTL_PAGE_SECONDS = 3 * 60 * 60
CACHE_TTL_PACKAGE_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class DatasetSpec:
    key: DatasetKey
    title_en: str
    title_fr: str
    dataset_id: str
    resource_id: str
    search_url_en: str
    search_url_fr: str
    value_field: str
    date_field: str
    # Freshness, in each language: the publication schedule the schema states.
    freshness_en: str
    freshness_fr: str
    # Columns that identify one agreement across its amendment rows, and the
    # column whose highest value marks the latest of them (None: no amendments).
    agreement_key: tuple[str, ...] = ()
    latest_by: str | None = None
    group_by: tuple[str, ...] = field(default_factory=tuple)


CONTRACTS = DatasetSpec(
    key="contracts",
    title_en="Proactive Publication - Contracts over $10,000",
    title_fr="Publication proactive - Contrats de plus de 10 000 $",
    dataset_id="d8f85d91-7dec-4fd1-8055-483b77225d8b",
    resource_id="fac950c0-00d5-4ec1-a4d3-9cbebf98a305",
    search_url_en="https://search.open.canada.ca/contracts",
    search_url_fr="https://rechercher.ouvert.canada.ca/contrats",
    value_field="contract_value",
    date_field="contract_date",
    freshness_en=(
        "published by fiscal quarter, within one month after the quarter ends; "
        "late entries are added to past quarters"
    ),
    freshness_fr=(
        "publié par trimestre financier, dans le mois suivant la fin du trimestre; "
        "les entrées tardives s'ajoutent aux trimestres passés"
    ),
    agreement_key=("owner_org", "procurement_id"),
    latest_by="reporting_period",
    group_by=(
        "department",
        "vendor",
        "fiscal_year",
        "quarter",
        "commodity_type",
        "solicitation_procedure",
        "instrument_type",
        "country_of_vendor",
        "economic_object_code",
    ),
)

GRANTS = DatasetSpec(
    key="grants",
    title_en="Proactive Disclosure - Grants and Contributions",
    title_fr="Divulgation proactive - Subventions et contributions",
    dataset_id="432527ab-7aac-45b5-81d6-7597107a7013",
    resource_id="1d15a62f-5656-49ad-8c88-f40ce689d831",
    search_url_en="https://search.open.canada.ca/grants",
    search_url_fr="https://rechercher.ouvert.canada.ca/subventions",
    value_field="agreement_value",
    date_field="agreement_start_date",
    freshness_en="published by fiscal quarter; amendments are added as new rows",
    freshness_fr="publié par trimestre financier; les modifications s'ajoutent en nouvelles lignes",
    agreement_key=("owner_org", "ref_number"),
    latest_by="amendment_number",
    group_by=(
        "department",
        "recipient",
        "program",
        "province",
        "riding",
        "fiscal_year",
        "recipient_type",
        "agreement_type",
    ),
)

TRAVEL = DatasetSpec(
    key="travel",
    title_en="Proactive Disclosure - Travel Expenses",
    title_fr="Divulgation proactive - Dépenses de voyage",
    dataset_id="009f9a49-c2d9-4d29-a6d4-1a228da335ce",
    resource_id="8282db2a-878f-475c-af10-ad56aa8fa72c",
    search_url_en="https://search.open.canada.ca/travelq",
    search_url_fr="https://rechercher.ouvert.canada.ca/voyage",
    value_field="total",
    date_field="start_date",
    freshness_en="published monthly by each organization",
    freshness_fr="publié chaque mois par chaque organisation",
    group_by=("department", "name", "title", "fiscal_year", "disclosure_group"),
)

HOSPITALITY = DatasetSpec(
    key="hospitality",
    title_en="Proactive Disclosure - Hospitality Expenses",
    title_fr="Divulgation proactive - Dépenses d'accueil",
    dataset_id="b9f51ef4-4605-4ef2-8231-62a2edda1b54",
    resource_id="7b301f1a-2a7a-48bd-9ea9-e0ac4a5313ed",
    search_url_en="https://search.open.canada.ca/hospitality",
    search_url_fr="https://rechercher.ouvert.canada.ca/accueil",
    value_field="total",
    date_field="start_date",
    freshness_en="published quarterly by each organization",
    freshness_fr="publié chaque trimestre par chaque organisation",
    group_by=("department", "name", "title", "fiscal_year", "disclosure_group", "vendor"),
)

DATASETS: dict[str, DatasetSpec] = {
    spec.key: spec for spec in (CONTRACTS, GRANTS, TRAVEL, HOSPITALITY)
}

# Code lists from the recombinant schemas (choices), English and French.
INSTRUMENT_TYPES = {
    "A": ("Amendment", "Modification"),
    "C": ("Contract", "Marché"),
    "SOSA": (
        "Standing Offer or Supply Arrangement Agreement",
        "Offre à commandes ou arrangement en matière d'approvisionnement",
    ),
}
SOLICITATION_PROCEDURES = {
    "AC": ("Advance Contract Award Notice", "Préavis d'adjudication de contrat"),
    "OB": (
        "Competitive - Open Bidding (GETS)",
        "Concurrentielle - Invitation ouverte à soumissionner (SEAOG)",
    ),
    "ST": ("Competitive - Selective Tendering", "Concurrentielle - Appel d'offres sélectif"),
    "TC": ("Competitive - Traditional", "Concurrentielle - Traditionnelle"),
    "TN": ("Non-Competitive", "Non concurrentielle"),
}
COMMODITY_TYPES = {
    "C": ("Construction", "Construction"),
    "G": ("Good", "Biens"),
    "S": ("Service", "Services"),
}
AGREEMENT_TYPES = {
    "C": ("Contribution", "Contribution"),
    "G": ("Grant", "Subvention"),
    "O": ("Other transfer payment", "Autre paiement de transfert"),
}
RECIPIENT_TYPES = {
    "A": ("Indigenous recipients", "Bénéficiaire autochtone"),
    "F": ("For-profit organizations", "Organisme à but lucratif"),
    "G": ("Government", "Gouvernement"),
    "I": ("International (non-government)", "Organisation internationale (non gouvernementale)"),
    "N": (
        "Not-for-profit organizations and charities",
        "Organisme à but non lucratif et organisme de bienfaisance",
    ),
    "O": ("Other", "Autre"),
    "P": ("Individual or sole proprietorships", "Particulier ou entreprise à propriétaire unique"),
    "S": ("Academia", "Établissement universitaire et institution publique"),
}
DISCLOSURE_GROUPS = {
    "MPSES": (
        "Minister, ministerial adviser or staff, parliamentary secretary, or exempt staff",
        (
            "Ministre, conseiller ou personnel ministériel, secrétaire parlementaire ou "
            "personnel exonéré"
        ),
    ),
    "SLE": ("Senior officer or employee", "Cadre supérieur ou employé"),
}
# Friendly argument values for the disclosure_group code.
DISCLOSURE_GROUP_ARGS = {"ministers": "MPSES", "senior_officials": "SLE"}
INSTRUMENT_TYPE_ARGS = {"contract": "C", "amendment": "A", "standing_offer": "SOSA"}
AGREEMENT_TYPE_ARGS = {"grant": "G", "contribution": "C", "other": "O"}
PROVINCES = ("AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT")
