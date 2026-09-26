"""Constants for every Canadian CKAN open-data portal this server covers.

Every portal below runs the stock CKAN Action API 3, so one client
serves all of them. What genuinely differs per portal was confirmed
live against each deployment when it was first added (2026-09) and is
recorded here as data rather than as ten copies of the client:

- federal: bilingual `_translated` dicts and `_fra` license fields; no
  tags or groups at all (tag_list/group_list return `[]`); subject
  terms live in the bilingual `keywords` field instead.
- on: bilingual `_translated` dicts; Ontario-specific metadata
  (access level, current-as-of date, geographic coverage).
- bc: English-only; `organization_list(all_fields=True)` silently caps
  at 25 and `group_list(all_fields=True)` returns 403 anonymously, so
  both rosters come from package_search facets; some string fields are
  the literal "null".
- qc, montreal: French-only content; montreal ignores an unknown sort
  field and returns 409 for a malformed fq.
- toronto: English-only; curated `excerpt`, no groups; package id and
  name differ; 404 bodies are HTML, not a CKAN envelope.
- yt: English-only content under bilingual site chrome; no DataStore
  extension (`datastore_search` answers "Action name not known").
- ab: English-only; its DataStore answers HTTP 500 for every resource,
  so row queries are disabled.
- nt, regina: English-only, standard CKAN.

Each portal keeps its own rate-limit bucket (`ckan-<key>`) so a burst
against one catalogue never throttles another.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

OrganizationSource = Literal["all_fields", "facet"]
GroupSource = Literal["all_fields", "facet", "none"]


@dataclass(frozen=True)
class Portal:
    base_url: str
    name_en: str
    name_fr: str
    # Landing-page templates take {lang} and {id}; {id} is the package
    # `name` when `landing_uses_name`, else its UUID.
    dataset_url: str
    organization_url: str
    group_url: str | None = None
    content_language: Literal["bilingual", "en", "fr"] = "en"
    landing_uses_name: bool = False
    rate_per_second: float = 2.0
    rate_capacity: float = 5.0
    # Seconds per request attempt; raise it only for a portal measured slow.
    timeout_seconds: float = 30.0
    organizations: OrganizationSource = "all_fields"
    groups: GroupSource = "all_fields"
    has_tags: bool = True
    has_datastore: bool = True
    # Portal-specific package/resource fields surfaced under `extras`,
    # each read through `<field>_translated` when the portal has one.
    extra_fields: tuple[str, ...] = ()
    resource_extra_fields: tuple[str, ...] = ()
    note: str | None = None
    note_fr: str | None = None


PORTALS: dict[str, Portal] = {
    "federal": Portal(
        base_url="https://open.canada.ca/data/api/3/action/",
        name_en="Government of Canada Open Data (open.canada.ca)",
        name_fr="Données ouvertes du gouvernement du Canada (ouvert.canada.ca)",
        dataset_url="https://open.canada.ca/data/{lang}/dataset/{id}",
        organization_url="https://open.canada.ca/data/{lang}/organization/{id}",
        content_language="bilingual",
        groups="none",
        has_tags=False,
        note=(
            "~48,000 federal datasets, including CRA, OSFI, Health Canada, ESDC, "
            "CRTC and Elections Canada data. No tags or groups; subject terms are "
            "in each dataset's bilingual `keywords`. Full-text DataStore `query` "
            "is rejected on resources over 100,000 rows; use `filters` instead."
        ),
        note_fr=(
            "Environ 48 000 jeux de données fédéraux, dont ceux de l'ARC, du BSIF, "
            "de Santé Canada, d'EDSC, du CRTC et d'Élections Canada. Aucun mot-clé "
            "ni groupe CKAN : les thèmes figurent dans le champ bilingue `keywords`. "
            "La recherche plein texte DataStore (`query`) est refusée au-delà de "
            "100 000 lignes; utilisez plutôt `filters`."
        ),
    ),
    "on": Portal(
        base_url="https://data.ontario.ca/api/3/action/",
        name_en="Ontario Data Catalogue (data.ontario.ca)",
        name_fr="Catalogue de données de l'Ontario (data.ontario.ca)",
        dataset_url="https://data.ontario.ca/{lang}/dataset/{id}",
        organization_url="https://data.ontario.ca/{lang}/organization/{id}",
        group_url="https://data.ontario.ca/{lang}/group/{id}",
        content_language="bilingual",
        extra_fields=(
            "access_level",
            "current_as_of",
            "geographic_coverage",
            "geographic_granularity",
            "update_frequency",
            "author",
            "maintainer",
            "maintainer_email",
        ),
        resource_extra_fields=("data_last_updated", "data_range_start", "data_range_end"),
    ),
    "bc": Portal(
        base_url="https://catalogue.data.gov.bc.ca/api/3/action/",
        name_en="BC Data Catalogue (catalogue.data.gov.bc.ca)",
        name_fr="Catalogue de données de la Colombie-Britannique",
        dataset_url="https://catalogue.data.gov.bc.ca/dataset/{id}",
        organization_url="https://catalogue.data.gov.bc.ca/organization/{id}",
        group_url="https://catalogue.data.gov.bc.ca/group/{id}",
        organizations="facet",
        groups="facet",
        resource_extra_fields=("resource_storage_location", "object_name"),
        note=(
            "Organization and group rosters list only publishers/groups with at "
            "least one dataset (built from search facets)."
        ),
        note_fr=(
            "Les listes d'organisations et de groupes ne comprennent que ceux qui "
            "ont au moins un jeu de données (construites à partir des facettes)."
        ),
    ),
    "ab": Portal(
        base_url="https://open.alberta.ca/api/3/action/",
        name_en="Open Alberta (open.alberta.ca)",
        name_fr="Données ouvertes de l'Alberta (open.alberta.ca)",
        dataset_url="https://open.alberta.ca/dataset/{id}",
        organization_url="https://open.alberta.ca/organization/{id}",
        groups="none",
        has_datastore=False,
        extra_fields=(
            "creator",
            "contact",
            "contact_email",
            "createdate",
            "issuedate",
            "updatefrequency",
            "language",
            "subject",
            "subject1",
            "subject2",
            "subject3",
            "subject4",
            "subject5",
            "subject6",
        ),
        note=(
            "DataStore is broken portal-side: datastore_search and datastore_info "
            "return HTTP 500 for every resource sampled (15 of 15, rechecked "
            "2026-09-23), so row queries are disabled; download resource URLs instead."
        ),
        note_fr=(
            "Le DataStore est défaillant du côté du portail : datastore_search et "
            "datastore_info renvoient une erreur HTTP 500 pour chaque ressource "
            "vérifiée (15 sur 15, en septembre 2026); les requêtes de lignes sont "
            "donc désactivées. Téléchargez plutôt les ressources."
        ),
    ),
    "qc": Portal(
        base_url="https://www.donneesquebec.ca/recherche/api/3/action/",
        name_en="Données Québec (donneesquebec.ca)",
        name_fr="Données Québec (donneesquebec.ca)",
        dataset_url="https://www.donneesquebec.ca/recherche/dataset/{id}",
        organization_url="https://www.donneesquebec.ca/recherche/organization/{id}",
        group_url="https://www.donneesquebec.ca/recherche/group/{id}",
        content_language="fr",
        landing_uses_name=True,
        rate_per_second=1.0,
        rate_capacity=3.0,
        # organization_list takes 15-21 s for a 3 KB answer (measured
        # 2026-09-26, every attempt); at 30 s all three attempts timed out
        # in a live smoke run, so this portal gets twice the default.
        timeout_seconds=60.0,
        extra_fields=("language", "update_frequency", "spatial_data", "methodologie", "temporal"),
        note="Provincial and municipal Quebec datasets; content is in French.",
        note_fr="Jeux de données provinciaux et municipaux du Québec, en français.",
    ),
    "nt": Portal(
        base_url="https://opendata.gov.nt.ca/api/3/action/",
        name_en="Northwest Territories Open Data (opendata.gov.nt.ca)",
        name_fr="Données ouvertes des Territoires du Nord-Ouest (opendata.gov.nt.ca)",
        dataset_url="https://opendata.gov.nt.ca/dataset/{id}",
        organization_url="https://opendata.gov.nt.ca/organization/{id}",
        group_url="https://opendata.gov.nt.ca/group/{id}",
        rate_per_second=1.0,
        rate_capacity=3.0,
        extra_fields=("geographic_range", "source", "topic", "update_frequency"),
    ),
    "yt": Portal(
        base_url="https://open.yukon.ca/api/3/action/",
        name_en="Yukon Open Data (open.yukon.ca)",
        name_fr="Données ouvertes du Yukon (open.yukon.ca)",
        dataset_url="https://open.yukon.ca/{lang}/dataset/{id}",
        organization_url="https://open.yukon.ca/{lang}/organization/{id}",
        group_url="https://open.yukon.ca/{lang}/group/{id}",
        rate_per_second=1.0,
        rate_capacity=3.0,
        has_datastore=False,
        extra_fields=("custodian", "update_frequency", "homepage_url"),
        note="No DataStore extension: row-level queries are unavailable.",
        note_fr="Aucune extension DataStore : pas de requêtes au niveau des lignes.",
    ),
    "montreal": Portal(
        base_url="https://donnees.montreal.ca/api/3/action/",
        name_en="City of Montreal Open Data (donnees.montreal.ca)",
        name_fr="Données ouvertes de la Ville de Montréal (donnees.montreal.ca)",
        dataset_url="https://donnees.montreal.ca/{lang}/dataset/{id}",
        organization_url="https://donnees.montreal.ca/{lang}/organization/{id}",
        group_url="https://donnees.montreal.ca/{lang}/group/{id}",
        content_language="fr",
        landing_uses_name=True,
        extra_fields=("update_frequency",),
        note="Content is in French; an unknown `sort` field is silently ignored.",
        note_fr="Contenu en français; un champ `sort` inconnu est ignoré sans erreur.",
    ),
    "toronto": Portal(
        base_url="https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/",
        name_en="City of Toronto Open Data (open.toronto.ca)",
        name_fr="Données ouvertes de la Ville de Toronto (open.toronto.ca)",
        dataset_url="https://open.toronto.ca/dataset/{id}/",
        organization_url="https://open.toronto.ca/catalogue/?organization={id}",
        landing_uses_name=True,
        groups="none",
        extra_fields=(
            "dataset_category",
            "is_retired",
            "information_url",
            "limitations",
            "civic_issues",
            "topics",
            "refresh_rate",
        ),
        resource_extra_fields=("record_count",),
    ),
    "regina": Portal(
        base_url="https://openregina.ca/api/3/action/",
        name_en="City of Regina Open Data (openregina.ca)",
        name_fr="Données ouvertes de la Ville de Regina (openregina.ca)",
        dataset_url="https://openregina.ca/dataset/{id}",
        organization_url="https://openregina.ca/organization/{id}",
        group_url="https://openregina.ca/group/{id}",
    ),
}

CACHE_TTL_SEARCH_SECONDS = 10 * 60
CACHE_TTL_PACKAGE_SECONDS = 60 * 60
CACHE_TTL_ORGANIZATION_SECONDS = 24 * 60 * 60
CACHE_TTL_RESOURCE_SECONDS = 60 * 60
CACHE_TTL_LICENSE_SECONDS = 7 * 24 * 60 * 60
CACHE_TTL_TAG_SECONDS = 60 * 60
CACHE_TTL_GROUP_SECONDS = 24 * 60 * 60
CACHE_TTL_DATASTORE_SECONDS = 15 * 60

# package_search silently truncates `rows` above 1000 on most of these
# deployments; 100 keeps responses compact for an agent choosing what
# to open next.
SEARCH_ROWS_DEFAULT = 10
SEARCH_ROWS_MAX = 100
NOTES_EXCERPT_LENGTH = 300

# tag_list has no server-side limit (BC returns ~7,000 tags at once), so
# an unfiltered listing is capped client-side.
TAG_LIST_MAX = 200
FACET_LIMIT = 500

# datastore_search's own cap is far higher (32,000 rows on federal).
DATASTORE_ROWS_DEFAULT = 20
DATASTORE_ROWS_MAX = 1000
