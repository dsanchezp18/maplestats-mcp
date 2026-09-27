"""Build the MapleStats MCP website: site/ templates -> build/site/.

    uv run python scripts/build_site.py
    uv run python -m http.server --directory build/site 8080

The tool atlas, the counts, the search index and the worked examples are
generated from the server's own tool registry (the same objects
search_tools indexes), so the site cannot list a tool the server lost or
miss one it gained. What the registry does not know (a module's display
name, level and provinces, and each portal's province) is in SOURCES,
FAMILIES and PORTAL_PLACES below; tests/test_site.py fails when a module
or portal is missing from them.

Templates (site/*.html) use three markers:

    {{> name}}           include site/_partials/name.html
    {en}...{fr}...{/}    the English or the French text, per output page
    {{name}}             a value or pre-rendered fragment from this script

Each template becomes <name>.html (English) and fr/<name>.html (French).
"""

from __future__ import annotations

import argparse
import asyncio
import html
import importlib
import importlib.util
import inspect
import json
import math
import re
import shutil
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

from fastmcp import Client
from fastmcp.server.transforms.search import BM25SearchTransform
from fastmcp.server.transforms.search.base import _extract_searchable_text
from fastmcp.tools import Tool

from maplestats_mcp import __version__
from maplestats_mcp.modules.arcgis_hub.constants import PORTALS as ARCGIS_PORTALS
from maplestats_mcp.modules.ckan.constants import PORTALS as CKAN_PORTALS
from maplestats_mcp.modules.planner import client as planner
from maplestats_mcp.modules.reproduce import client as reproduce
from maplestats_mcp.modules.socrata.constants import PORTALS as SOCRATA_PORTALS
from maplestats_mcp.server import MODULES_ROOT, ModuleProvider, mcp
from maplestats_mcp.shared.search import tokenize

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
DEFAULT_OUT = ROOT / "build" / "site"
REPO = "https://github.com/dsanchezp18/maplestats-mcp"
# Where GitHub Pages serves the site (.github/workflows/pages.yml). Canonical,
# hreflang and Open Graph URLs, the sitemap and the 404 page are absolute
# from here, because a crawler or a link preview has no page to resolve from.
SITE_URL = "https://dsanchezp18.github.io/maplestats-mcp/"

Lang = Literal["en", "fr"]
LANGS: tuple[Lang, ...] = ("en", "fr")


def page_url(name: str, lang: Lang) -> str:
    """A page's absolute URL; index.html is its folder."""
    path = "" if name == "index.html" else name
    return f"{SITE_URL}{'' if lang == 'en' else 'fr/'}{path}"


Level = Literal["national", "provincial", "municipal", "catalogue", "utility"]
Row = Literal["provincial_catalogue", "provincial_agency", "municipal_catalogue", "municipal_feed"]


@dataclass(frozen=True)
class Source:
    en: str
    fr: str
    level: Level
    short_en: str = ""
    short_fr: str = ""
    domain: str | None = None
    places: tuple[str, ...] = ()
    row: Row | None = None

    def title(self, lang: Lang) -> str:
        return self.en if lang == "en" else self.fr

    def short(self, lang: Lang) -> str:
        label = self.short_en if lang == "en" else self.short_fr
        return label or self.title(lang)


LEVELS: dict[Level, tuple[str, str]] = {
    "national": ("Federal and national", "Fédéral et national"),
    "provincial": ("Provincial", "Provincial"),
    "municipal": ("Municipal", "Municipal"),
    "catalogue": ("Open-data catalogues", "Catalogues de données ouvertes"),
    "utility": ("Planning and code", "Planification et code"),
}

DOMAINS: dict[str, tuple[str, str]] = {
    "statistics": ("Statistics and census", "Statistiques et recensement"),
    "money": ("Money, prices and public finance", "Monnaie, prix et finances publiques"),
    "housing": ("Housing", "Logement"),
    "health": ("Health", "Santé"),
    "environment": ("Environment and hazards", "Environnement et risques naturels"),
    "energy": ("Energy", "Énergie"),
    "business": ("Business, IP and competition", "Entreprises, PI et concurrence"),
    "immigration": ("Immigration", "Immigration"),
    "government": ("Parliament, law and elections", "Parlement, droit et élections"),
    "transport": ("Transport and safety", "Transport et sécurité"),
    "geography": ("Geography", "Géographie"),
    "agriculture": ("Agriculture and food", "Agriculture et alimentation"),
}

# One entry per modules/<key>/ directory. tests/test_site.py keeps this in
# sync with the directory listing.
SOURCES: dict[str, Source] = {
    "ab_economic": Source(
        "Alberta Economic Dashboard",
        "Tableau de bord économique de l'Alberta",
        "provincial",
        places=("AB",),
        row="provincial_agency",
    ),
    "aer": Source(
        "Alberta Energy Regulator",
        "Alberta Energy Regulator",
        "provincial",
        "AER",
        "AER",
        places=("AB",),
        row="provincial_agency",
    ),
    "arcgis_hub": Source("ArcGIS Hub portals", "Portails ArcGIS Hub", "catalogue", "ArcGIS Hub"),
    "bcgw": Source(
        "BC Geographic Warehouse",
        "Entrepôt géographique de la C.-B.",
        "provincial",
        "BCGW",
        "BCGW",
        places=("BC",),
        row="provincial_agency",
    ),
    "boc": Source("Bank of Canada", "Banque du Canada", "national", domain="money"),
    "borealis": Source(
        "Borealis: Beyond 20/20 tables",
        "Borealis : tableaux Beyond 20/20",
        "national",
        "Borealis",
        "Borealis",
        domain="statistics",
    ),
    "canadabuys": Source("CanadaBuys", "AchatsCanada", "national", domain="money"),
    "cdc": Source(
        "Canadian Dairy Commission",
        "Commission canadienne du lait",
        "national",
        "CDC",
        "CCL",
        domain="agriculture",
    ),
    "cer": Source(
        "Canada Energy Regulator",
        "Régie de l'énergie du Canada",
        "national",
        "CER",
        "Régie de l'énergie",
        domain="energy",
    ),
    "cfia": Source(
        "Canadian Food Inspection Agency",
        "Agence canadienne d'inspection des aliments",
        "national",
        "CFIA",
        "ACIA",
        domain="agriculture",
    ),
    "cgc": Source(
        "Canadian Grain Commission",
        "Commission canadienne des grains",
        "national",
        "CGC",
        "CCG",
        domain="agriculture",
    ),
    "cihi": Source(
        "Canadian Institute for Health Information",
        "Institut canadien d'information sur la santé",
        "national",
        "CIHI",
        "ICIS",
        domain="health",
    ),
    "ckan": Source("CKAN catalogues", "Catalogues CKAN", "catalogue", "CKAN", "CKAN"),
    "cmhc": Source(
        "Canada Mortgage and Housing Corporation",
        "Société canadienne d'hypothèques et de logement",
        "national",
        "CMHC",
        "SCHL",
        domain="housing",
    ),
    "competition_bureau": Source(
        "Competition Bureau: merger reviews",
        "Bureau de la concurrence : examens de fusions",
        "national",
        "Competition Bureau",
        "Bureau de la concurrence",
        domain="business",
    ),
    "cra_digital_economy_registry": Source(
        "CRA digital economy registry",
        "Registre de l'économie numérique de l'ARC",
        "national",
        "CRA",
        "ARC",
        domain="business",
    ),
    "dfo_iwls": Source(
        "Fisheries and Oceans Canada: tides and water levels",
        "Pêches et Océans Canada : marées et niveaux d'eau",
        "national",
        "DFO tides",
        "Marées du MPO",
        domain="environment",
    ),
    "earthquakes": Source("Earthquakes Canada", "Séismes Canada", "national", domain="environment"),
    "eccc": Source(
        "Environment and Climate Change Canada",
        "Environnement et Changement climatique Canada",
        "national",
        "ECCC",
        "ECCC",
        domain="environment",
    ),
    "elections_financial_returns": Source(
        "Elections Canada: candidate financial returns",
        "Élections Canada : rapports financiers des candidats",
        "national",
        "Elections Canada",
        "Élections Canada",
        domain="government",
    ),
    "epcor": Source(
        "EPCOR water quality, Edmonton",
        "Qualité de l'eau d'EPCOR, Edmonton",
        "municipal",
        "EPCOR",
        "EPCOR",
        places=("AB",),
        row="municipal_feed",
    ),
    "eps": Source(
        "Edmonton Police Service",
        "Service de police d'Edmonton",
        "municipal",
        "Edmonton police",
        "Police d'Edmonton",
        places=("AB",),
        row="municipal_feed",
    ),
    "ets": Source(
        "Edmonton Transit Service",
        "Edmonton Transit Service",
        "municipal",
        "Edmonton transit",
        "Transport d'Edmonton",
        places=("AB",),
        row="municipal_feed",
    ),
    "fcac": Source(
        "Financial Consumer Agency of Canada: comparison tools",
        "Agence de la consommation en matière financière du Canada : outils de comparaison",
        "national",
        "FCAC",
        "ACFC",
        domain="money",
    ),
    "gazette": Source("Canada Gazette", "Gazette du Canada", "national", domain="government"),
    "gc_infobase": Source("GC InfoBase", "InfoBase du GC", "national", domain="money"),
    "ircc": Source(
        "Immigration, Refugees and Citizenship Canada",
        "Immigration, Réfugiés et Citoyenneté Canada",
        "national",
        "IRCC",
        "IRCC",
        domain="immigration",
    ),
    "ised": Source(
        "Innovation, Science and Economic Development Canada",
        "Innovation, Sciences et Développement économique Canada",
        "national",
        "ISED",
        "ISDE",
        domain="business",
    ),
    "isq": Source(
        "Institut de la statistique du Québec",
        "Institut de la statistique du Québec",
        "provincial",
        "ISQ",
        "ISQ",
        places=("QC",),
        row="provincial_agency",
    ),
    "nl_opendata": Source(
        "Open Data Newfoundland and Labrador",
        "Données ouvertes de Terre-Neuve-et-Labrador",
        "catalogue",
        "Open Data NL",
        "Données ouvertes T.-N.-L.",
        places=("NL",),
        row="provincial_catalogue",
    ),
    "nrcan_energy_use": Source(
        "Natural Resources Canada: energy use",
        "Ressources naturelles Canada : consommation d'énergie",
        "national",
        "NRCan energy use",
        "RNCan énergie",
        domain="energy",
    ),
    "nrcan_geo": Source(
        "Natural Resources Canada: geolocation and place names",
        "Ressources naturelles Canada : géolocalisation et toponymes",
        "national",
        "NRCan places",
        "RNCan toponymes",
        domain="geography",
    ),
    "nrcan_nbac": Source(
        "Natural Resources Canada: burned areas",
        "Ressources naturelles Canada : zones brûlées",
        "national",
        "NRCan burned areas",
        "RNCan zones brûlées",
        domain="environment",
    ),
    "opendatasoft_vancouver": Source(
        "City of Vancouver Open Data",
        "Données ouvertes de la Ville de Vancouver",
        "catalogue",
        "Vancouver",
        "Vancouver",
        places=("BC",),
        row="municipal_catalogue",
    ),
    "openparliament": Source(
        "House of Commons, via OpenParliament.ca",
        "Chambre des communes, par OpenParliament.ca",
        "national",
        "OpenParliament",
        "OpenParliament",
        domain="government",
    ),
    "pbo": Source(
        "Parliamentary Budget Officer",
        "Directeur parlementaire du budget",
        "national",
        "PBO",
        "DPB",
        domain="money",
    ),
    "phac_infobase": Source(
        "Public Health Agency of Canada: Health Infobase",
        "Agence de la santé publique du Canada : Infobase de la santé",
        "national",
        "PHAC Health Infobase",
        "Infobase de la santé (ASPC)",
        domain="health",
    ),
    "planner": Source("Query planner", "Planificateur de requêtes", "utility"),
    "recalls": Source(
        "Recalls and safety alerts",
        "Rappels et avis de sécurité",
        "national",
        "Recalls",
        "Rappels",
        domain="health",
    ),
    "reproduce": Source("Reproduction code", "Code de reproduction", "utility"),
    "senate": Source(
        "Senate of Canada votes",
        "Votes du Sénat du Canada",
        "national",
        "Senate",
        "Sénat",
        domain="government",
    ),
    "socrata": Source("Socrata portals", "Portails Socrata", "catalogue", "Socrata", "Socrata"),
    "statcan": Source(
        "Statistics Canada",
        "Statistique Canada",
        "national",
        "StatCan",
        "StatCan",
        domain="statistics",
    ),
    "tc_recalls": Source(
        "Transport Canada: vehicle recalls",
        "Transports Canada : rappels de véhicules",
        "national",
        "Transport Canada",
        "Transports Canada",
        domain="transport",
    ),
}

# Sub-API folders (modules/<key>/<family>/tools.py), keyed "<key>/<family>".
# Tools in a module's own tools.py belong to the "<key>/" entry.
FAMILIES: dict[str, tuple[str, str]] = {
    "cmhc/": (
        "Housing Market Information Portal",
        "Portail de l'information sur le marché de l'habitation",
    ),
    "cmhc/data_tables": ("Data tables (Excel)", "Tableaux de données (Excel)"),
    "ircc/": ("Express Entry rounds", "Rondes d'invitations Entrée express"),
    "ircc/monthly": ("Monthly IRCC Updates", "Mises à jour mensuelles d'IRCC"),
    "ised/cipo": ("Trademarks (CIPO)", "Marques de commerce (OPIC)"),
    "ised/clean_growth": ("Clean technology investment", "Investissements en technologies propres"),
    "ised/corporations": ("Federal corporations", "Sociétés fédérales"),
    "ised/ip_horizons": ("Patents and IP bulk data", "Brevets et données de PI"),
    "ised/spectrum": ("Spectrum licences", "Licences de spectre"),
    "statcan/census_profile": ("2021 Census Profile", "Profil du recensement de 2021"),
    "statcan/census_profile_2016": ("2016 Census Profile", "Profil du recensement de 2016"),
    "statcan/census_profile_archive": (
        "Census Profile archive, 2001-2016",
        "Archives des profils du recensement, 2001-2016",
    ),
    "statcan/census_tables": (
        "Census data tables, 2006-2016",
        "Tableaux de données du recensement, 2006-2016",
    ),
    "statcan/daily": ("The Daily", "Le Quotidien"),
    "statcan/delta": (
        "Delta files: daily bulk updates",
        "Fichiers delta : mises à jour quotidiennes",
    ),
    "statcan/geo": ("Census geography", "Géographie du recensement"),
    "statcan/indicators": ("Indicators", "Indicateurs"),
    "statcan/pumf": (
        "Public use microdata files (PUMF)",
        "Fichiers de microdonnées à grande diffusion (FMGD)",
    ),
    "statcan/rdaas": ("Classifications and concordances", "Classifications et concordances"),
    "statcan/reference": ("Definitions, methods and analysis", "Définitions, méthodes et analyses"),
    "statcan/sdg": ("Sustainable Development Goals", "Objectifs de développement durable"),
    "statcan/sdmx": ("SDMX API: filtered series", "API SDMX : séries filtrées"),
    "statcan/surveys": ("Surveys and metadata", "Enquêtes et métadonnées"),
    "statcan/wds": (
        "Web Data Service: tables and vectors",
        "Service de données Web : tableaux et vecteurs",
    ),
}

# Provinces and territories in Standard Geographical Classification order.
PLACES: dict[str, tuple[str, str, str]] = {
    "NL": ("10", "Newfoundland and Labrador", "Terre-Neuve-et-Labrador"),
    "PE": ("11", "Prince Edward Island", "Île-du-Prince-Édouard"),
    "NS": ("12", "Nova Scotia", "Nouvelle-Écosse"),
    "NB": ("13", "New Brunswick", "Nouveau-Brunswick"),
    "QC": ("24", "Quebec", "Québec"),
    "ON": ("35", "Ontario", "Ontario"),
    "MB": ("46", "Manitoba", "Manitoba"),
    "SK": ("47", "Saskatchewan", "Saskatchewan"),
    "AB": ("48", "Alberta", "Alberta"),
    "BC": ("59", "British Columbia", "Colombie-Britannique"),
    "YT": ("60", "Yukon", "Yukon"),
    "NT": ("61", "Northwest Territories", "Territoires du Nord-Ouest"),
    "NU": ("62", "Nunavut", "Nunavut"),
}

PortalLevel = Literal["national", "provincial", "municipal"]
_P: PortalLevel = "provincial"
_M: PortalLevel = "municipal"

# Every portal key of the three catalogue families: (province, level).
PORTAL_PLACES: dict[str, dict[str, tuple[str, PortalLevel]]] = {
    "ckan": {
        "federal": ("", "national"),
        "on": ("ON", _P),
        "bc": ("BC", _P),
        "ab": ("AB", _P),
        "qc": ("QC", _P),
        "nt": ("NT", _P),
        "yt": ("YT", _P),
        "montreal": ("QC", _M),
        "toronto": ("ON", _M),
        "regina": ("SK", _M),
    },
    "arcgis_hub": {
        "mb": ("MB", _P),
        "sk": ("SK", _P),
        "pe": ("PE", _P),
        "alberta_geological_survey": ("AB", _P),
        "hamilton": ("ON", _M),
        "london": ("ON", _M),
        "kitchener": ("ON", _M),
        "windsor": ("ON", _M),
        "ottawa": ("ON", _M),
        "mississauga": ("ON", _M),
        "peel": ("ON", _M),
        "durham": ("ON", _M),
        "waterloo_region": ("ON", _M),
        "york": ("ON", _M),
        "markham": ("ON", _M),
        "newmarket": ("ON", _M),
        "aurora": ("ON", _M),
        "saskatoon": ("SK", _M),
        "victoria": ("BC", _M),
        "surrey": ("BC", _M),
        "metro_vancouver": ("BC", _M),
        "halifax": ("NS", _M),
        "medicine_hat": ("AB", _M),
        "grande_prairie": ("AB", _M),
        "grande_prairie_county": ("AB", _M),
        "st_albert": ("AB", _M),
        "lethbridge": ("AB", _M),
        "airdrie": ("AB", _M),
        "strathcona_county": ("AB", _M),
        "parkland_county": ("AB", _M),
        "sturgeon_county": ("AB", _M),
        "emrb": ("AB", _M),
        "red_deer": ("AB", _M),
    },
    "socrata": {
        "ns": ("NS", _P),
        "nb": ("NB", _P),
        "calgary": ("AB", _M),
        "edmonton": ("AB", _M),
        "winnipeg": ("MB", _M),
    },
}

ROWS: dict[Row, tuple[str, str]] = {
    "provincial_catalogue": (
        "Provincial and territorial catalogues",
        "Catalogues provinciaux et territoriaux",
    ),
    "provincial_agency": ("Provincial agencies", "Organismes provinciaux"),
    "municipal_catalogue": ("City and regional catalogues", "Catalogues municipaux et régionaux"),
    "municipal_feed": ("City data feeds", "Flux de données municipaux"),
}

# Worked examples, generated by the server at build time (the planner, the
# search and reproduce_code need no network). The data call itself is a
# capture, in site/_data/, because a build must not depend on an upstream.
PLAN_QUESTION: dict[Lang, str] = {
    "en": "How have rents and interest rates moved in Calgary since 2020?",
    "fr": "Comment les loyers et les taux d'intérêt ont-ils évolué à Calgary depuis 2020?",
}
SEARCH_EXAMPLE: dict[Lang, str] = {
    "en": "Bank of Canada policy rate",
    "fr": "taux directeur de la Banque du Canada",
}
# Checked against search_tools on 2026-09-26: each one's top results are on topic.
SEARCH_SUGGESTIONS: dict[Lang, tuple[str, ...]] = {
    "en": (
        "federal contract awards",
        "PUMF bootstrap weights",
        "tide times Halifax",
        "census profile income",
        "taux de chômage",
    ),
    "fr": (
        "taux de chômage",
        "poids bootstrap microdonnées",
        "ronde d'invitations entrée express",
        "superficie brûlée feux de forêt",
        "federal contract awards",
    ),
}


# Each page offers one query in the other language, to show both work.
SUGGESTION_LANG: dict[str, Lang] = {"taux de chômage": "fr", "federal contract awards": "en"}


def suggestion_buttons(lang: Lang) -> str:
    buttons = []
    for query in SEARCH_SUGGESTIONS[lang]:
        own = SUGGESTION_LANG.get(query, lang)
        mark = f' lang="{own}"' if own != lang else ""
        buttons.append(f'<button type="button" data-q="{esc(query)}"{mark}>{esc(query)}</button>')
    return " ".join(buttons)


CAPTURE = SITE / "_data" / "boc-policy-rate.json"

# --------------------------------------------------------------------------
# Collect: modules, tools and their documentation, straight from the server.
# --------------------------------------------------------------------------


@dataclass
class Param:
    name: str
    type: str
    required: bool
    default: str | None


@dataclass
class ToolDoc:
    name: str
    module: str
    family: str
    summary: str
    use_for: str
    keywords: list[str]
    mots_cles: list[str]
    params: list[Param]
    searchable: str


@dataclass
class ModuleDoc:
    key: str
    source: Source
    description: dict[Lang, str]
    tools: list[ToolDoc] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)


# A docstring field runs until a blank line, the next label, or the end.
_STOP = r"(?=\n[ \t]*\n|Use for:|Keywords:|Mots-clés\s*:|\Z)"


def _field(doc: str, label: str) -> str:
    match = re.search(label + r"\s*(.*?)" + _STOP, doc, re.DOTALL)
    return " ".join(match.group(1).split()) if match else ""


def _terms(doc: str, label: str) -> list[str]:
    text = _field(doc, label).rstrip(".")
    return [term.strip() for term in text.split(",") if term.strip()]


def _schema_type(schema: Any, defs: dict[str, Any]) -> str:
    if not isinstance(schema, dict):
        return "any"
    if "$ref" in schema:
        name = str(schema["$ref"]).rsplit("/", 1)[-1]
        return _schema_type(defs[name], defs) if name in defs else name
    if "anyOf" in schema:
        parts = [_schema_type(branch, defs) for branch in schema["anyOf"]]
        return " | ".join(dict.fromkeys(parts))
    if "enum" in schema:
        return " | ".join(json.dumps(value, ensure_ascii=False) for value in schema["enum"])
    kind = schema.get("type")
    if kind == "array":
        return f"list[{_schema_type(schema.get('items', {}), defs)}]"
    if kind == "object":
        extra = schema.get("additionalProperties")
        return f"dict[str, {_schema_type(extra, defs)}]" if isinstance(extra, dict) else "dict"
    names = {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
        "null": "null",
    }
    return names.get(kind, "any") if isinstance(kind, str) else "any"


def _params(schema: dict[str, Any]) -> list[Param]:
    defs = schema.get("$defs", {})
    required = set(schema.get("required", []))
    params = []
    for name, spec in schema.get("properties", {}).items():
        default = None
        if isinstance(spec, dict) and "default" in spec:
            default = json.dumps(spec["default"], ensure_ascii=False)
        params.append(Param(name, _schema_type(spec, defs), name in required, default))
    return params


def _family(tool: Tool, module_dir: Path) -> str:
    fn = getattr(tool, "fn", None)
    source_file = inspect.getsourcefile(fn) if fn is not None else None
    if source_file is None:
        return ""
    relative = Path(source_file).resolve().relative_to(module_dir.resolve())
    return relative.parent.as_posix() if relative.parent != Path(".") else ""


def _tool_doc(tool: Tool, key: str, module_dir: Path) -> ToolDoc:
    doc = inspect.cleandoc(tool.description or "")
    return ToolDoc(
        name=tool.name,
        module=key,
        family=_family(tool, module_dir),
        summary=" ".join(doc.split("\n\n", 1)[0].split()),
        use_for=_field(doc, "Use for:"),
        keywords=_terms(doc, "Keywords:"),
        mots_cles=_terms(doc, r"Mots-clés\s*:"),
        params=_params(tool.parameters or {}),
        searchable=_extract_searchable_text(tool),
    )


async def collect_modules() -> list[ModuleDoc]:
    """Every module the server registers, in the server's own order."""
    modules = []
    for module_dir in sorted(MODULES_ROOT.iterdir()):
        # The same filter as server.build_server, so the order matches too.
        if not module_dir.is_dir() or module_dir.name.startswith("_"):
            continue
        key = module_dir.name
        if key not in SOURCES:
            raise SystemExit(f"modules/{key}/ has no SOURCES entry in scripts/build_site.py")
        package = importlib.import_module(f"maplestats_mcp.modules.{key}")
        provider = ModuleProvider(root=module_dir)
        module = ModuleDoc(
            key=key,
            source=SOURCES[key],
            description={
                "en": getattr(package, "MODULE_DESCRIPTION", ""),
                "fr": getattr(package, "MODULE_DESCRIPTION_FR", ""),
            },
            tools=[_tool_doc(t, key, module_dir) for t in await provider.list_tools()],
            resources=[str(r.uri) for r in await provider.list_resources()],
            prompts=[p.name for p in await provider.list_prompts()],
        )
        families = list(dict.fromkeys(t.family for t in module.tools))
        if families != [""]:
            for family in families:
                if f"{key}/{family}" not in FAMILIES:
                    raise SystemExit(f"modules/{key}/{family}: add {key}/{family!r} to FAMILIES")
        modules.append(module)
    return modules


# --------------------------------------------------------------------------
# Search: the same BM25 index search_tools builds, shipped to the browser.
# --------------------------------------------------------------------------


def _search_transform() -> BM25SearchTransform:
    for transform in mcp.transforms:
        if isinstance(transform, BM25SearchTransform):
            return transform
    raise SystemExit("the server has no BM25SearchTransform; the site search cannot match it")


def always_visible() -> set[str]:
    return set(_search_transform()._always_visible)


def build_index(modules: list[ModuleDoc]) -> dict[str, Any]:
    """The server's BM25 index over every searchable tool, in its order.

    search_tools indexes each tool's name, description and parameters
    (fastmcp's _extract_searchable_text) with shared/search.py's accent-
    and plural-folding tokenizer; this ships those exact tokens, so the
    browser only tokenizes the query. k1, b and the result count are read
    from the live transform rather than copied.
    """
    transform = _search_transform()
    pinned = always_visible()
    docs = [t for m in modules for t in m.tools if t.name not in pinned]
    postings: dict[str, list[int]] = {}
    lengths = []
    for i, tool in enumerate(docs):
        tokens = tokenize(tool.searchable)
        lengths.append(len(tokens))
        counts: dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        for token, count in counts.items():
            postings.setdefault(token, []).extend((i, count))
    return {
        "k1": transform._index.k1,
        "b": transform._index.b,
        "top": transform._max_results,
        "avg": sum(lengths) / len(lengths),
        "len": lengths,
        "tools": [[t.name, t.module, t.summary] for t in docs],
        "post": postings,
    }


def rank(index: dict[str, Any], query: str) -> list[int]:
    """Python twin of site.js's ranking; tests/test_site.py compares it to search_tools."""
    k1, b, avg = index["k1"], index["b"], index["avg"]
    lengths: list[int] = index["len"]
    n = len(lengths)
    scores = [0.0] * n
    for token in tokenize(query):
        posting = index["post"].get(token)
        if not posting:
            continue
        df = len(posting) // 2
        idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
        for j in range(0, len(posting), 2):
            i, tf = posting[j], posting[j + 1]
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * lengths[i] / avg)
            scores[i] += idf * numerator / denominator
    ranked = sorted(range(n), key=lambda i: scores[i], reverse=True)
    return [i for i in ranked if scores[i] > 0]


async def server_search(query: str) -> list[str]:
    """Tool names the real search_tools returns for a query."""
    async with Client(mcp) as client:
        result = await client.call_tool("search_tools", {"query": query})
    structured = result.structured_content or {}
    items = structured.get("result")
    if not isinstance(items, list):
        items = json.loads("".join(getattr(block, "text", "") for block in result.content))
    return [item["name"] for item in items]


# --------------------------------------------------------------------------
# Rendering helpers.
# --------------------------------------------------------------------------


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def en_only(lang: Lang) -> str:
    """The attribute lang="en" on a French page, for text only in English on the server.

    Tool docstrings, the planner's plan and reproduce_code's notes are written
    in English; marking them keeps screen readers and hyphenation right and
    tells the reader (and tests/test_site.py) that the English is known.
    """
    return ' lang="en"' if lang == "fr" else ""


def en_span(fragment: str, lang: Lang) -> str:
    """An HTML fragment in a lang="en" span on a French page, as is on an English one."""
    return f'<span lang="en">{fragment}</span>' if lang == "fr" else fragment


def lead(text: str, limit: int = 280) -> str:
    """The first sentence of a module description, clipped at a clause break.

    Module descriptions are written for agents and some run to thousands of
    characters; the page shows this lead and keeps the full text behind a
    disclosure.
    """
    # French sentences can open on an accented capital (« État », « À »).
    sentence_end = r"(?<!e\.g\.)(?<!i\.e\.)(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Ý«“(])| -- "
    first = re.split(sentence_end, text.strip(), maxsplit=1)[0]
    if len(first) <= limit:
        return first
    cut = first[:limit]
    for mark in ("; ", ", ", " "):
        at = cut.rfind(mark)
        if at > limit // 2:
            return cut[:at].rstrip(" ,;:") + "…"
    return cut.rstrip() + "…"


def inline_code(text: str) -> str:
    """Escape prose and turn `backticked` spans into <code>."""
    parts = re.split(r"`([^`]+)`", text)
    return "".join(f"<code>{esc(p)}</code>" if i % 2 else esc(p) for i, p in enumerate(parts))


_JSON_TOKEN = re.compile(
    r'(?P<key>"(?:[^"\\]|\\.)*")(?=\s*:)|(?P<str>"(?:[^"\\]|\\.)*")'
    r"|(?P<num>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|(?P<lit>\btrue\b|\bfalse\b|\bnull\b)"
)


def highlight_json(text: str) -> str:
    out, last = [], 0
    for match in _JSON_TOKEN.finditer(text):
        out.append(esc(text[last : match.start()]))
        kind = match.lastgroup or "str"
        out.append(f'<span class="s-{kind}">{esc(match.group())}</span>')
        last = match.end()
    out.append(esc(text[last:]))
    return "".join(out)


_COMMENT = {"r": r"#.*$", "python": r"#.*$", "julia": r"#.*$", "stata": r"(?:^\s*\*|//).*$"}


def highlight_script(code: str, language: str) -> str:
    pattern = re.compile(
        rf'(?P<com>{_COMMENT[language]})|(?P<str>"(?:[^"\\\n]|\\.)*")', re.MULTILINE
    )
    out, last = [], 0
    for match in pattern.finditer(code):
        out.append(esc(code[last : match.start()]))
        out.append(f'<span class="s-{match.lastgroup}">{esc(match.group())}</span>')
        last = match.end()
    out.append(esc(code[last:]))
    return "".join(out)


def tool_href(name: str, root: str) -> str:
    return f"{root}tools.html#t-{name}"


_VERBS = {"get", "list", "search", "query", "find", "describe", "resolve", "fetch"}


def _family_prefix(names: list[str], key: str, family: str) -> str:
    if len(names) == 1:
        if not family:
            return names[0]
        candidates = (f"{key}_{family}_", f"{key}_")
        return next((c for c in candidates if names[0].startswith(c)), names[0])
    # Whole underscore-separated words shared by every name, minus trailing
    # verbs: sdmx_get_data and sdmx_get_structure share "sdmx_", not "sdmx_get_".
    words = [name.split("_") for name in names]
    shared: list[str] = []
    for column in zip(*words, strict=False):
        if len(set(column)) != 1:
            break
        shared.append(column[0])
    while len(shared) > 1 and shared[-1] in _VERBS:
        shared.pop()
    return "_".join(shared) + "_" if shared else names[0]


def prefixes(module: ModuleDoc) -> list[str]:
    """The tool-name prefixes a module's families use, e.g. wds_, sdmx_."""
    found: list[str] = []
    for family in dict.fromkeys(t.family for t in module.tools):
        names = [t.name for t in module.tools if t.family == family]
        prefix = _family_prefix(names, module.key, family)
        if prefix not in found:
            found.append(prefix)
    return found


def breakable(name: str) -> str:
    """A tool name that may wrap after its underscores only."""
    return esc(name).replace("_", "_<wbr>")


# --------------------------------------------------------------------------
# Fragments.
# --------------------------------------------------------------------------

LEVEL_ORDER: tuple[Level, ...] = ("national", "provincial", "municipal", "catalogue", "utility")


def ordered(modules: list[ModuleDoc], lang: Lang) -> list[ModuleDoc]:
    return sorted(
        modules,
        key=lambda m: (LEVEL_ORDER.index(m.source.level), -len(m.tools), m.source.title(lang)),
    )


def result_items(names: list[str], by_name: dict[str, ToolDoc], lang: Lang, root: str) -> str:
    items = []
    for rank_no, name in enumerate(names, 1):
        tool = by_name[name]
        source = SOURCES[tool.module]
        items.append(
            f'<li><a href="{tool_href(name, root)}">'
            f'<span class="r-rank">{rank_no}</span>'
            f'<span class="r-name">{breakable(name)}</span>'
            f'<span class="r-src">{esc(source.short(lang))}</span>'
            f'<span class="r-sum"{en_only(lang)}>{esc(tool.summary)}</span></a></li>'
        )
    return "\n".join(items)


def params_table(tool: ToolDoc, lang: Lang) -> str:
    if not tool.params:
        return ""
    head = ("Parameter", "Type", "Default") if lang == "en" else ("Paramètre", "Type", "Défaut")
    required = "required" if lang == "en" else "obligatoire"
    rows = []
    for p in tool.params:
        default = f"<code>{esc(p.default)}</code>" if p.default is not None else ""
        if p.required:
            default = f'<span class="req">{required}</span>'
        rows.append(
            f"<tr><td><code>{esc(p.name)}</code></td>"
            f'<td><code class="type">{esc(p.type)}</code></td><td>{default}</td></tr>'
        )
    caption = "Parameters of" if lang == "en" else "Paramètres de"
    return (
        '<div class="table-wrap"><table class="params">'
        f'<caption class="sr">{caption} <code>{esc(tool.name)}</code></caption><thead><tr>'
        + "".join(f"<th>{h}</th>" for h in head)
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def example_call(tool: ToolDoc) -> str:
    args: dict[str, str] = {}
    for p in tool.params:
        if p.required:
            args[p.name] = "…"
    body = json.dumps({"name": tool.name, "arguments": args}, ensure_ascii=False)
    return f'<pre class="call"><code>call_tool {highlight_json(body)}</code></pre>'


def tool_details(tool: ToolDoc, lang: Lang) -> str:
    # The docstring is English; on a French page it is marked so, and the
    # labels around it say which keywords are which.
    en = en_only(lang)
    use_label = "Use for" if lang == "en" else "Usage"
    kw_label, mc_label = (
        ("Keywords", "Mots-clés")
        if lang == "en"
        else ("Mots-clés en anglais", "Mots-clés en français")
    )
    kw = ", ".join(tool.keywords)
    mc = ", ".join(tool.mots_cles)
    return (
        f'<details class="tool" id="t-{esc(tool.name)}" data-tool="{esc(tool.name)}">'
        f'<summary><code class="t-name">{breakable(tool.name)}</code>'
        f'<span class="t-sum"{en}>{esc(tool.summary)}</span></summary>'
        # Two stacks, side by side where the row is wide enough: what the
        # tool is for and how to find it, then how to call it.
        '<div class="t-body"><div class="t-main">'
        + (
            f'<p class="t-use"><b>{use_label}</b> {en_span(inline_code(tool.use_for), lang)}</p>'
            if tool.use_for
            else ""
        )
        + '<dl class="t-kw">'
        + f"<div><dt>{kw_label}</dt><dd{en}>{esc(kw)}</dd></div>"
        + f'<div lang="fr"><dt>{mc_label}</dt><dd>{esc(mc)}</dd></div>'
        + '</dl></div><div class="t-side">'
        + params_table(tool, lang)
        + example_call(tool)
        + "</div></div></details>"
    )


def module_description(text: str, lang: Lang) -> str:
    """The lead as a paragraph; the full text in a <details> when it says more."""
    short = lead(text)
    html = f'<p class="mod-desc">{inline_code(short)}</p>'
    if len(text.strip()) > len(short) + 40:
        label = "Full description" if lang == "en" else "Description complète"
        html += (
            f'<details class="mod-more"><summary>{label}</summary>'
            f'<p class="mod-desc">{inline_code(text.strip())}</p></details>'
        )
    return html


def atlas(modules: list[ModuleDoc], lang: Lang) -> str:
    pinned = always_visible()
    sections = []
    for module in ordered(modules, lang):
        source = module.source
        count = len(module.tools)
        tools_word = (
            ("tool" if count == 1 else "tools")
            if lang == "en"
            else ("outil" if count == 1 else "outils")
        )
        meta = [f"{count} {tools_word}"]
        if module.resources:
            label = "Resources" if lang == "en" else "Ressources"
            meta.append(
                f"{label}: " + ", ".join(f"<code>{esc(r)}</code>" for r in module.resources)
            )
        if module.prompts:
            label = "Prompts" if lang == "en" else "Invites"
            meta.append(f"{label}: " + ", ".join(f"<code>{esc(p)}</code>" for p in module.prompts))
        places = " · ".join(esc(PLACES[p][1 if lang == "en" else 2]) for p in source.places)
        kicker = esc(LEVELS[source.level][0 if lang == "en" else 1]) + (
            f" · {places}" if places else ""
        )
        families = list(dict.fromkeys(t.family for t in module.tools))
        body = []
        for family in families:
            tools = [t for t in module.tools if t.family == family]
            if families != [""]:
                title = FAMILIES[f"{module.key}/{family}"][0 if lang == "en" else 1]
                body.append(
                    f'<h3 class="fam">{esc(title)} <span class="count">{len(tools)}</span></h3>'
                )
            body.extend(tool_details(t, lang) for t in tools)
        pinned_note = ""
        if any(t.name in pinned for t in module.tools):
            pinned_note = (
                '<p class="pinned">'
                + (
                    "Always visible to the agent, so search_tools does not return it."
                    if lang == "en"
                    else "Toujours visible pour l'agent; search_tools ne le renvoie donc pas."
                )
                + "</p>"
            )
        sections.append(
            f'<section class="mod" id="m-{module.key}" data-level="{source.level}">'
            '<header class="mod-head">'
            f'<p class="label">{kicker}</p>'
            f"<h2>{esc(source.title(lang))}</h2>"
            f'<p class="mod-prefix">{" ".join(f"<code>{esc(p)}</code>" for p in prefixes(module))}</p>'
            f"{module_description(module.description[lang], lang)}"
            f'<p class="mod-meta">{" · ".join(meta)}</p>'
            f"{pinned_note}</header>" + "".join(body) + "</section>"
        )
    return "\n".join(sections)


def atlas_index(modules: list[ModuleDoc], lang: Lang) -> str:
    groups = []
    for level in LEVEL_ORDER:
        members = [m for m in ordered(modules, lang) if m.source.level == level]
        links = "".join(
            f'<li data-level="{level}"><a href="#m-{m.key}">{esc(m.source.short(lang))}'
            f'<span class="count">{len(m.tools)}</span></a></li>'
            for m in members
        )
        groups.append(
            f'<div class="idx-group"><p class="label">{esc(LEVELS[level][0 if lang == "en" else 1])}</p>'
            f"<ul>{links}</ul></div>"
        )
    return "".join(groups)


def level_filters(modules: list[ModuleDoc], lang: Lang) -> str:
    counts = {
        level: sum(len(m.tools) for m in modules if m.source.level == level)
        for level in LEVEL_ORDER
    }
    total = sum(counts.values())
    buttons = [
        (
            f'<button type="button" class="chip" data-level="all" aria-pressed="true">'
            f'{"All" if lang == "en" else "Tous"} <span class="count">{total}</span></button>'
        )
    ]
    for level in LEVEL_ORDER:
        buttons.append(
            f'<button type="button" class="chip" data-level="{level}" aria-pressed="false">'
            f'{esc(LEVELS[level][0 if lang == "en" else 1])} <span class="count">{counts[level]}</span></button>'
        )
    return "".join(buttons)


def portal_entries() -> list[tuple[Row, str, str, str]]:
    """(matrix row, province, English name, French name) for every local source."""
    entries: list[tuple[Row, str, str, str]] = []
    families = {"ckan": CKAN_PORTALS, "arcgis_hub": ARCGIS_PORTALS, "socrata": SOCRATA_PORTALS}
    for family, portals in families.items():
        for key, portal in portals.items():
            place, level = PORTAL_PLACES[family][key]
            if level == "national":
                continue
            row: Row = "provincial_catalogue" if level == "provincial" else "municipal_catalogue"
            entries.append((row, place, portal.name_en, portal.name_fr or portal.name_en))
    for source in SOURCES.values():
        if source.row is not None:
            for place in source.places:
                entries.append((source.row, place, source.en, source.fr))
    return entries


def coverage_counts() -> dict[str, int]:
    entries = portal_entries()
    catalogues = sum(len(p) for p in (CKAN_PORTALS, ARCGIS_PORTALS, SOCRATA_PORTALS))
    catalogues += sum(1 for s in SOURCES.values() if s.level == "catalogue" and s.places)
    return {
        "places_covered": len({place for _, place, _, _ in entries}),
        "catalogue_count": catalogues,
        "local_catalogue_count": sum(1 for row, *_ in entries if row.endswith("catalogue")),
        "local_source_count": len(entries),
    }


def _shade(count: int) -> int:
    """Four shades: 1, 2, 3 to 5, 6 or more sources."""
    return 0 if count == 0 else 1 if count == 1 else 2 if count == 2 else 3 if count <= 5 else 4


def coverage_matrix(lang: Lang) -> str:
    entries = portal_entries()
    i = 1 if lang == "en" else 2
    head = "".join(
        f'<th scope="col" title="{esc(PLACES[code][i])}"><span class="sgc">{PLACES[code][0]}</span>{code}</th>'
        for code in PLACES
    )
    body = []
    for row, labels in ROWS.items():
        cells = []
        for code in PLACES:
            names = [
                e[2] if lang == "en" else e[3] for e in entries if e[0] == row and e[1] == code
            ]
            count = len(names)
            title = f' title="{esc("; ".join(names))}"' if names else ""
            cells.append(f'<td class="c{_shade(count)}"{title}>{count or ""}</td>')
        body.append(
            f'<tr><th scope="row">{esc(labels[0 if lang == "en" else 1])}</th>{"".join(cells)}</tr>'
        )
    totals = "".join(
        f"<td>{sum(1 for e in entries if e[1] == code) or '–'}</td>" for code in PLACES
    )
    total_label = "All local sources" if lang == "en" else "Toutes les sources locales"
    caption = (
        "Local sources by province and territory, in Standard Geographical Classification order"
        if lang == "en"
        else "Sources locales par province et territoire, dans l'ordre de la Classification géographique type"
    )
    return (
        f'<div class="table-wrap"><table class="matrix"><caption class="sr">{caption}</caption>'
        f"<thead><tr><td></td>{head}</tr></thead><tbody>{''.join(body)}</tbody>"
        f'<tfoot><tr><th scope="row">{total_label}</th>{totals}</tr></tfoot></table></div>'
    )


def coverage_lists(lang: Lang) -> str:
    """Every local source by province, for readers who want names, not shades."""
    entries = portal_entries()
    i = 1 if lang == "en" else 2
    blocks = []
    for code, place in PLACES.items():
        names = sorted({e[2] if lang == "en" else e[3] for e in entries if e[1] == code})
        if not names:
            continue
        items = "".join(f"<li>{esc(n)}</li>" for n in names)
        blocks.append(
            f'<div><p class="label">{place[0]} {code} · {esc(place[i])}</p><ul>{items}</ul></div>'
        )
    return "".join(blocks)


def national_sources(modules: list[ModuleDoc], lang: Lang, root: str) -> str:
    by_domain: dict[str, list[ModuleDoc]] = {}
    for module in modules:
        if module.source.level == "national" and module.source.domain:
            by_domain.setdefault(module.source.domain, []).append(module)
    blocks = []
    for domain, labels in DOMAINS.items():
        members = sorted(by_domain.get(domain, []), key=lambda m: -len(m.tools))
        if not members:
            continue
        items = "".join(
            f'<li><a href="{root}tools.html#m-{m.key}">{esc(m.source.title(lang))}</a>'
            f'<span class="count">{len(m.tools)}</span></li>'
            for m in members
        )
        blocks.append(
            f'<div class="dom"><h3>{esc(labels[0 if lang == "en" else 1])}</h3><ul>{items}</ul></div>'
        )
    return "".join(blocks)


def plan_panel(lang: Lang, root: str) -> str:
    """The planner's answer as short lists: one per topic or place, tool over purpose."""
    # plan_query writes its plan in English only (its lang argument is accepted
    # for consistency), so on a French page the plan's own words are marked
    # lang="en" and only the labels around them are French.
    plan = planner.plan(PLAN_QUESTION[lang]).model_dump(mode="json")
    caveat = "Caveat" if lang == "en" else "Précaution"
    en = en_only(lang)

    def group(title: str, steps: list[dict[str, Any]], caveats: list[str], title_en: bool) -> str:
        items = "".join(
            f'<li><a href="{tool_href(s["tool"], root)}"><code>{breakable(s["tool"])}</code></a>'
            f"<span{en}>{esc(s['purpose'])}</span></li>"
            for s in steps
        )
        notes = "".join(
            f'<p class="plan-note"><b>{caveat}</b> {en_span(esc(c), lang)}</p>' for c in caveats
        )
        head = f"<h4{en if title_en else ''}>{esc(title)}</h4>"
        return f'<div class="plan-group">{head}<ol>{items}</ol>{notes}</div>'

    parts = [group(t["label"], t["steps"], t["caveats"], True) for t in plan["topics"]]
    kinds = {"city": "ville"} if lang == "fr" else {}
    # A place heading is the place's name and its kind, both shown in French.
    parts += [
        group(
            f"{place_name(p['place'], lang)} ({kinds.get(p['kind'], p['kind'])})",
            p["steps"],
            [],
            False,
        )
        for p in plan["places"]
    ]
    return "".join(parts)


# English place names (the planner's and the portals') that French writes
# differently; provinces and territories come from PLACES.
PLACE_FR: dict[str, str] = {
    "Montreal": "Montréal",
    "Quebec City": "Québec",
    "Trois-Rivieres": "Trois-Rivières",
    "Region of Waterloo": "Région de Waterloo",
}


def place_name(name: str, lang: Lang) -> str:
    if lang == "en":
        return name
    provinces = {en: fr for _, en, fr in PLACES.values()}
    return provinces.get(name) or PLACE_FR.get(name, name)


async def reproduce_scripts() -> list[tuple[str, str]]:
    capture = json.loads(CAPTURE.read_text(encoding="utf-8"))
    request = capture["request"]
    result = await reproduce.reproduce(request["name"], request["arguments"], "all")
    return [(script.language, script.code) for script in result.scripts]


# The homepage shows the first lines of each script; site.js adds the button
# that shows the rest (without scripts the whole script shows).
SHOW_MORE: dict[Lang, tuple[str, str]] = {
    "en": ("Show all {n} lines", "Show fewer lines"),
    "fr": ("Afficher les {n} lignes", "Afficher moins de lignes"),
}


def script_tabs(
    scripts: list[tuple[str, str]], prefix: str, more: tuple[str, str] | None = None
) -> str:
    """R / Python / Stata / Julia tabs; `prefix` keeps ids unique on a page.

    With `more` (the expand and collapse labels), each script is shown cut
    to its first lines with a button for the rest; without it, it scrolls.
    """
    labels = {"r": "R", "python": "Python", "stata": "Stata", "julia": "Julia"}
    tabs, panels = [], []
    for n, (language, code) in enumerate(scripts):
        selected = "true" if n == 0 else "false"
        hidden = "" if n == 0 else " hidden"
        tabs.append(
            f'<button type="button" role="tab" id="{prefix}-tab-{language}" aria-selected="{selected}"'
            f' aria-controls="{prefix}-{language}" tabindex="{0 if n == 0 else -1}">'
            f"{labels.get(language, language)}</button>"
        )
        body = highlight_script(code.rstrip(), language)
        lines = code.rstrip().count("\n") + 1
        if more and lines <= 18:
            block = f'<pre class="ex-code"><code>{body}</code></pre>'
        elif more:
            block = (
                f'<div class="ex-more" data-more><pre class="ex-code" id="{prefix}-{language}-code">'
                f"<code>{body}</code></pre>"
                f'<button type="button" class="ex-toggle" aria-controls="{prefix}-{language}-code"'
                f' aria-expanded="true" data-more-label="{esc(more[0].format(n=lines))}"'
                f' data-less-label="{esc(more[1])}" hidden>{esc(more[1])}</button></div>'
            )
        else:
            block = f'<pre class="code scroll"><code>{body}</code></pre>'
        panels.append(
            f'<div role="tabpanel" id="{prefix}-{language}" aria-labelledby="{prefix}-tab-{language}"{hidden}>'
            f"{block}</div>"
        )
    return (
        f'<div class="tabs" data-tabs><div role="tablist" class="tablist">{"".join(tabs)}</div>'
        + "".join(panels)
        + "</div>"
    )


def compact_json(value: dict[str, Any], expand: tuple[str, ...]) -> list[str]:
    """One top-level key per line; the keys in `expand` get one line per member."""
    lines = ["{"]
    items = list(value.items())
    for n, (key, item) in enumerate(items):
        comma = "," if n < len(items) - 1 else ""
        if key in expand and isinstance(item, (dict, list)) and item:
            members = list(item.items()) if isinstance(item, dict) else [(None, v) for v in item]
            brackets = "{}" if isinstance(item, dict) else "[]"
            lines.append(f"  {json.dumps(key)}: {brackets[0]}")
            for m, (member_key, member) in enumerate(members):
                label = f"{json.dumps(member_key)}: " if member_key is not None else ""
                tail = "," if m < len(members) - 1 else ""
                lines.append(f"    {label}{json.dumps(member, ensure_ascii=False)}{tail}")
            lines.append(f"  {brackets[1]}{comma}")
        else:
            lines.append(f"  {json.dumps(key)}: {json.dumps(item, ensure_ascii=False)}{comma}")
    lines.append("}")
    return lines


def response_html(response: dict[str, Any]) -> str:
    lines = compact_json(response, expand=("series", "observations", "provenance"))
    start = next(i for i, line in enumerate(lines) if line.startswith('  "provenance"'))
    end = next(i for i in range(start, len(lines)) if lines[i].startswith("  }"))
    before = highlight_json("\n".join(lines[:start]) + "\n")
    marked = highlight_json("\n".join(lines[start : end + 1]))
    # .prov is display: block, so it ends its own line.
    after = highlight_json("\n".join(lines[end + 1 :]))
    return f'{before}<span class="prov">{marked}</span>{after}'


MONTHS_FR = (
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
)


def long_date(iso: str, lang: Lang) -> str:
    """26 September 2026 / 26 septembre 2026; 1 January / 1er janvier."""
    day = date.fromisoformat(iso[:10])
    if lang == "en":
        return f"{day.day} {day:%B} {day.year}"
    ordinal = "1er" if day.day == 1 else str(day.day)
    return f"{ordinal} {MONTHS_FR[day.month - 1]} {day.year}"


# The one prompt that sets MapleStats up. The home page, the Connect page and
# the README all show it word for word (tests/test_site.py checks), so a
# reader meets the same sentence wherever they start.
AGENT_PROMPT: dict[Lang, str] = {
    "en": f"Install the MapleStats MCP server and connect it to this agent. Follow the setup steps in {REPO}",
    "fr": f"Installe le serveur MCP MapleStats et connecte-le à cet agent. Suis les étapes d'installation de {REPO}",
}


def captured_call(lang: Lang) -> dict[str, str]:
    capture = json.loads(CAPTURE.read_text(encoding="utf-8"))
    request = json.dumps(capture["request"], ensure_ascii=False)
    reproduce_request = json.dumps(
        {"tool_name": capture["request"]["name"], "arguments": capture["request"]["arguments"]},
        ensure_ascii=False,
    )
    when = long_date(capture["captured"], lang)
    return {
        "call_request": highlight_json(request),
        "reproduce_request": highlight_json(reproduce_request),
        "call_response": response_html(capture["response"]),
        "call_result": call_result(capture["response"], lang),
        "captured_on": when,
    }


def call_result(response: dict[str, Any], lang: Lang) -> str:
    """The recorded observations as a small table, and the provenance in plain words.

    The full JSON stays one click away on the page; this is what a reader
    needs at a glance: the series, its values, and where they came from.
    """
    en = lang == "en"
    tables = []
    for code, series in response["series"].items():
        rows = "".join(
            f"<tr><td>{esc(long_date(obs['ref_date'], lang))}</td>"
            f"<td>{esc(number(obs['values'][code], lang, 2))}</td></tr>"
            for obs in response["observations"]
            if obs["values"].get(code) is not None
        )
        tables.append(
            # The Valet label comes back in English; the tool has no French.
            f'<table class="ex-table"><caption>{en_span(esc(series["label"]), lang)}'
            f" <code>{esc(code)}</code></caption>"
            f'<thead><tr><th scope="col">Date</th><th scope="col">{"Value" if en else "Valeur"}</th></tr></thead>'
            f"<tbody>{rows}</tbody></table>"
        )
    prov = response["provenance"]
    stamp = prov["queried_at"]
    clock = stamp[11:16] if en else stamp[11:16].replace(":", " h ")
    facts = (
        (
            "Source URL" if en else "URL de la source",
            f'<a href="{esc(prov["url"])}">{esc(prov["url"])}</a>',
        ),
        ("Queried" if en else "Consultée le", f"{esc(long_date(stamp, lang))}, {clock} UTC"),
        ("Result type" if en else "Type de résultat", f"<code>{esc(prov['schema_name'])}</code>"),
    )
    rows = "".join(f"<div><dt>{label}</dt><dd>{value}</dd></div>" for label, value in facts)
    return (
        f'<div class="ex-part"><p class="ex-label">{"Result" if en else "Résultat"}</p>{"".join(tables)}</div>'
        f'<div class="ex-part ex-prov"><p class="ex-label">Provenance</p><dl>{rows}</dl></div>'
    )


# --------------------------------------------------------------------------
# Templates.
# --------------------------------------------------------------------------

_INCLUDE = re.compile(r"\{\{>\s*([a-z0-9_-]+)\s*\}\}")
_LANG_BLOCK = re.compile(r"\{en\}(.*?)\{fr\}(.*?)\{/\}", re.DOTALL)
_VAR = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}")


# --------------------------------------------------------------------------
# Case studies: recorded calls (scripts/capture_cases.py) drawn as charts.
# --------------------------------------------------------------------------

CASES_DIR = SITE / "_data" / "cases"
CASE_KEYS = ("pumf", "ircc", "housing", "micro", "cards", "curve", "patents", "boc")


def _load_charts() -> Any:
    """scripts/site_charts.py, loaded by path so tests can import this file too."""
    spec = importlib.util.spec_from_file_location(
        "site_charts", Path(__file__).resolve().parent / "site_charts.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


charts = _load_charts()

PR_NAMES: dict[str, tuple[str, str]] = {
    "10": ("Newfoundland and Labrador", "Terre-Neuve-et-Labrador"),
    "11": ("Prince Edward Island", "Île-du-Prince-Édouard"),
    "12": ("Nova Scotia", "Nouvelle-Écosse"),
    "13": ("New Brunswick", "Nouveau-Brunswick"),
    "24": ("Quebec", "Québec"),
    "35": ("Ontario", "Ontario"),
    "46": ("Manitoba", "Manitoba"),
    "47": ("Saskatchewan", "Saskatchewan"),
    "48": ("Alberta", "Alberta"),
    "59": ("British Columbia", "Colombie-Britannique"),
    "70": ("Northern Canada", "Nord canadien"),
}
# French names a province with its article in running text ("pour le Québec",
# "pour l'Ontario"); a chart label keeps the bare name from PR_NAMES.
PR_WITH_ARTICLE_FR: dict[str, str] = {
    "10": "Terre-Neuve-et-Labrador",
    "11": "l'Île-du-Prince-Édouard",
    "12": "la Nouvelle-Écosse",
    "13": "le Nouveau-Brunswick",
    "24": "le Québec",
    "35": "l'Ontario",
    "46": "le Manitoba",
    "47": "la Saskatchewan",
    "48": "l'Alberta",
    "59": "la Colombie-Britannique",
    "70": "le Nord canadien",
}
MONTHS_EN = tuple(f"{date(2000, m, 1):%B}" for m in range(1, 13))


def load_case(key: str) -> dict[str, Any]:
    return json.loads((CASES_DIR / f"{key}.json").read_text(encoding="utf-8"))


def number(value: float, lang: Lang, decimals: int = 0) -> str:
    """16,745 / 16 745 (narrow no-break space); 6.5 / 6,5."""
    text = f"{value:,.{decimals}f}"
    return text if lang == "en" else text.replace(",", " ").replace(".", ",")


def percent(value: float, lang: Lang, decimals: int = 1) -> str:
    """6.5% / 6,5 % (narrow no-break space, so the sign never wraps alone)."""
    return number(value, lang, decimals) + ("%" if lang == "en" else NNBSP + "%")


def join_names(names: list[str], lang: Lang) -> str:
    return f" {'and' if lang == 'en' else 'et'} ".join(names)


def call_source(response: Any, lang: Lang) -> str:
    """Source: <url>, queried <date>."""
    prov = (response[0] if isinstance(response, list) else response)["provenance"]
    when = long_date(prov["queried_at"], lang)
    queried = f"queried {when}" if lang == "en" else f"interrogée le {when}"
    label = "Source:" if lang == "en" else f"Source{NBSP}:"
    return (
        f'<span class="case-source">{label} <a href="{esc(prov["url"])}">{esc(prov["url"])}</a>, '
        f"{queried}</span>"
    )


def how_block(case: dict[str, Any], key: str, lang: Lang) -> str:
    """The calls behind a chart and the script that repeats the first one.

    A run of calls to the same tool (one per candidate, one per year) shows
    its first request and says how many more there were. A call with no
    script (a web page the tool parses) shows reproduce_code's note instead.
    """
    summary = "How the agent got this" if lang == "en" else "Comment l'agent l'a obtenu"
    request_label = "Request" if lang == "en" else "Requête"
    runs: list[list[dict[str, Any]]] = []
    for call in case["calls"]:
        if runs and runs[-1][0]["name"] == call["name"] and len(case["calls"]) > 2:
            runs[-1].append(call)
        else:
            runs.append([call])
    panels = []
    for run in runs:
        first = run[0]
        request = json.dumps(
            {"name": first["name"], "arguments": first["arguments"]}, ensure_ascii=False
        )
        more = ""
        if len(run) > 1:
            n = len(run) - 1
            more = (
                f'<p class="how-more">{n} more {"call" if n == 1 else "calls"} like this one, with other arguments.</p>'
                if lang == "en"
                else f'<p class="how-more">{n} autre{"s" if n > 1 else ""} appel{"s" if n > 1 else ""} semblable{"s" if n > 1 else ""}, avec d\'autres arguments.</p>'
            )
        panels.append(
            f'<figure class="panel"><figcaption class="panel-bar"><span>{request_label}</span>'
            f"<code>call_tool</code></figcaption><pre><code>{highlight_json(request)}</code></pre>"
            f"{more}</figure>"
        )
    first = case["calls"][0]
    if first.get("scripts"):
        tail = f'<figure class="panel">{script_tabs(list(first["scripts"].items()), f"{key}-rp")}</figure>'
    else:
        heading = "No script for this one" if lang == "en" else "Pas de script pour cet appel"
        # reproduce_code explains itself in English only.
        notes = en_span(" ".join(esc(n) for n in first.get("script_notes", [])), lang)
        tail = f'<div class="how-note"><strong>{heading}.</strong> <code>reproduce_code</code>: {notes}</div>'
    return (
        f'<details class="how"><summary>{summary}</summary><div class="how-body">'
        + "".join(panels)
        + tail
        + "</div></details>"
    )


# Every chart is followed by its data (site_charts.with_table), in a closed
# <details>: the chart itself is one labelled image to a screen reader.
SHOW_DATA: dict[Lang, str] = {"en": "Show the data", "fr": "Voir les données"}
CI_HEAD: dict[Lang, tuple[str, str, str]] = {
    "en": ("Estimate", "95% CI low", "95% CI high"),
    "fr": ("Estimation", "IC à 95 %, borne inf.", "IC à 95 %, borne sup."),
}


def chart_table(
    svg: str, key: str, lang: Lang, caption: str, head: tuple[str, ...], rows: list[list[str]]
) -> str:
    return charts.with_table(
        svg, ident=f"data-{key}", summary=SHOW_DATA[lang], caption=caption, head=head, rows=rows
    )


def pumf_context(case: dict[str, Any], lang: Lang) -> dict[str, str]:
    response = case["calls"][0]["response"]
    rows = []
    in_text: dict[str, str] = {}
    for cell in response["cells"]:
        groups = {g["variable"]: g["code"] for g in cell["groups"]}
        if groups.get("HDGREE") != "9":
            continue
        name = PR_NAMES[groups["PR"]][0 if lang == "en" else 1]
        half = 1.96 * cell["standard_error"]
        rows.append((name, cell["estimate"], cell["estimate"] - half, cell["estimate"] + half))
        in_text[name] = name if lang == "en" else PR_WITH_ARTICLE_FR[groups["PR"]]
    by_width = sorted(rows, key=lambda r: r[3] - r[2])
    label = (
        "Share of adults 25 to 64 whose highest credential is a bachelor's degree, with 95% confidence intervals"
        if lang == "en"
        else "Part des adultes de 25 à 64 ans dont le plus haut diplôme est un baccalauréat, avec intervalles de confiance à 95 %"
    )

    def fmt(v: float) -> str:
        return percent(v, lang)

    return {
        "chart_pumf": chart_table(
            charts.ci_chart(rows, label=label, value_format=fmt, range_word=RANGE_WORD[lang]),
            "pumf",
            lang,
            label,
            ("Province", *CI_HEAD[lang]),
            charts.ci_rows(rows, fmt),
        ),
        "pumf_narrow": esc(join_names([in_text[r[0]] for r in by_width[:2]], lang)),
        "pumf_wide": esc(join_names([in_text[r[0]] for r in by_width[-2:]], lang)),
        "source_pumf": call_source(response, lang),
    }


def ircc_context(case: dict[str, Any], lang: Lang) -> dict[str, str]:
    edmonton, calgary = (call["response"]["rows"] for call in case["calls"])
    years = [row["period"] for row in edmonton]
    last = edmonton[-1]
    partial = ""
    categories = list(years)
    if last["cells"] < 12:
        months = MONTHS_EN if lang == "en" else MONTHS_FR
        categories[-1] = f"{last['period']}*"
        partial = (
            f"*{last['period']} covers January to {months[last['cells'] - 1]} only."
            if lang == "en"
            else f"*{last['period']} ne couvre que les mois de janvier à {months[last['cells'] - 1]}."
        )
    series = [
        ("Edmonton", [float(r["value"]) for r in edmonton]),
        ("Calgary", [float(r["value"]) for r in calgary]),
    ]
    label = (
        "New permanent residents by intended destination, Edmonton and Calgary, by year"
        if lang == "en"
        else "Nouveaux résidents permanents selon la destination prévue, Edmonton et Calgary, par année"
    )

    def fmt(v: float) -> str:
        return number(v, lang)

    return {
        "chart_ircc": chart_table(
            charts.grouped_bars(categories, series, label=label, value_format=fmt),
            "ircc",
            lang,
            label,
            ("Year" if lang == "en" else "Année", *(name for name, _ in series)),
            charts.bar_rows(categories, series, fmt),
        ),
        "ircc_partial": esc(partial),
        "source_ircc": call_source(case["calls"][0]["response"], lang),
    }


def year_ticks(iso: str) -> str | None:
    return iso[:4] if iso[5:7] == "01" else None


# "12.5% to 14.1%" / "12,5 % à 14,1 %" in a confidence interval's tooltip.
RANGE_WORD: dict[Lang, str] = {"en": "to", "fr": "à"}


def tip_date(lang: Lang, monthly: bool) -> Callable[[str], str] | None:
    """A chart tooltip's date: ISO in English, as before; written out in French."""
    if lang == "en":
        return None
    if monthly:
        return lambda iso: month_name(iso, lang)
    return lambda iso: long_date(iso, lang)


def housing_context(case: dict[str, Any], lang: Lang) -> dict[str, str]:
    response = case["calls"][0]["response"]
    # CMHC publishes this table by month; a year counts only once all twelve
    # months are in, so the chart ends at the last complete year.
    years: dict[str, dict[str, float]] = {}
    months: dict[str, int] = {}
    for row in response["rows"]:
        year = row["period"][:4]
        months[year] = months.get(year, 0) + 1
        totals = years.setdefault(year, {})
        for column, cell in row["values"].items():
            totals[column] = totals.get(column, 0.0) + (cell["value"] or 0.0)
    complete = [y for y in years if months[y] == 12 and y >= "2005"]
    first, last = complete[0], complete[-1]
    share = {y: years[y]["Apartment"] / years[y]["Total"] * 100 for y in complete}
    crossed = next(
        y
        for y in complete
        if all(years[z]["Apartment"] > years[z]["Single"] for z in complete if z >= y)
    )
    single_label = "Single-detached" if lang == "en" else "Individuelles"
    apartment_label = "Apartments" if lang == "en" else "Appartements"
    label = (
        "Housing starts in Canada by year, single-detached homes and apartments, centres of 10,000 people or more"
        if lang == "en"
        else "Mises en chantier au Canada par année, maisons individuelles et appartements, centres de 10 000 habitants ou plus"
    )
    series: list[tuple[str, list[float | None]]] = [
        (single_label, [years[y]["Single"] for y in complete]),
        (apartment_label, [years[y]["Apartment"] for y in complete]),
    ]

    def fmt(v: float) -> str:
        return number(v, lang)

    return {
        "chart_housing": chart_table(
            charts.grouped_bars(complete, series, label=label, value_format=fmt),
            "housing",
            lang,
            label,
            ("Year" if lang == "en" else "Année", single_label, apartment_label),
            charts.bar_rows(complete, series, fmt),
        ),
        "count_housing": number(case["calls"][1]["response"]["total_count"], lang),
        "housing_first": first,
        "housing_last": last,
        "housing_single_first": number(years[first]["Single"], lang),
        "housing_single_last": number(years[last]["Single"], lang),
        "housing_apt_first": number(years[first]["Apartment"], lang),
        "housing_apt_last": number(years[last]["Apartment"], lang),
        "housing_share_first": esc(percent(share[first], lang, 0)),
        "housing_share_last": esc(percent(share[last], lang, 0)),
        "housing_crossed": crossed,
        "source_housing": call_source(response, lang),
    }


GENSTAT_NAMES: dict[str, tuple[str, str]] = {
    "1": ("First generation (born abroad)", "Première génération (née à l'étranger)"),
    "2": (
        "Second generation, both parents born abroad",
        "Deuxième génération, deux parents nés à l'étranger",
    ),
    "3": (
        "Second generation, one parent born abroad",
        "Deuxième génération, un parent né à l'étranger",
    ),
    "4": ("Third generation or more", "Troisième génération ou plus"),
}


def micro_context(case: dict[str, Any], lang: Lang) -> dict[str, str]:
    response = case["calls"][0]["response"]
    rows = []
    for cell in response["cells"]:
        groups = {g["variable"]: g["code"] for g in cell["groups"]}
        if groups["LOLIMA"] != "2":
            continue
        half = 1.96 * cell["standard_error"]
        name = GENSTAT_NAMES[groups["GENSTAT"]][0 if lang == "en" else 1]
        rows.append((name, cell["estimate"], cell["estimate"] - half, cell["estimate"] + half))
    first, second_both, second_one, third = (r[1] for r in rows)
    label = (
        "Share of people in low income (LIM-AT) by immigrant generation, 2021 Census, with 95% confidence intervals"
        if lang == "en"
        else "Part des personnes à faible revenu (MFR-ApI) selon la génération, recensement de 2021, avec intervalles de confiance à 95 %"
    )

    def fmt(v: float) -> str:
        return percent(v, lang)

    return {
        "chart_micro": chart_table(
            charts.ci_chart(
                rows, label=label, value_format=fmt, row_height=64.0, range_word=RANGE_WORD[lang]
            ),
            "micro",
            lang,
            label,
            ("Generation" if lang == "en" else "Génération", *CI_HEAD[lang]),
            charts.ci_rows(rows, fmt),
        ),
        "micro_first": esc(percent(first, lang)),
        "micro_second": esc(
            f"{percent(second_both, lang)} {'and' if lang == 'en' else 'et'} {percent(second_one, lang)}"
        ),
        "micro_third": esc(percent(third, lang)),
        "count_records": number(response["unweighted_n"], lang),
        "source_micro": call_source(response, lang),
    }


def dollars(value: float, lang: Lang, cents: bool = True) -> str:
    """$99 / $22.50: cents only when there are any, and only if asked for."""
    shown = number(value, lang, 2 if cents and value != round(value) else 0)
    return f"${shown}" if lang == "en" else f"{shown}{NBSP}$"


def cards_context(case: dict[str, Any], lang: Lang) -> dict[str, str]:
    response = case["calls"][0]["response"]
    # A purchase rate under 1% is a prepaid card (no credit, so no real rate).
    priced = [
        c for c in response["cards"] if c["purchase_rate"] is not None and c["purchase_rate"] >= 1
    ]
    groups: dict[tuple[float, float, int], list[str]] = {}
    for card in priced:
        key = (card["annual_fee"], card["purchase_rate"], 0 if card["rewards"] else 1)
        groups.setdefault(key, []).append(card["name"])
    points = []
    for (fee, rate, series), names in groups.items():
        head = f"{dollars(fee, lang)}, {percent(rate, lang, 2)}"
        shown = ", ".join(names[:3]) + (f" (+{len(names) - 3})" if len(names) > 3 else "")
        points.append((fee, rate, series, len(names), f"{head}: {shown}"))
    rewards = [c for c in priced if c["rewards"]]
    plain = [c for c in priced if not c["rewards"]]

    def median(values: list[float]) -> float:
        ordered_values = sorted(values)
        mid = len(ordered_values) // 2
        if len(ordered_values) % 2:
            return ordered_values[mid]
        return (ordered_values[mid - 1] + ordered_values[mid]) / 2

    series = (
        ["With rewards", "No rewards"] if lang == "en" else ["Avec récompenses", "Sans récompenses"]
    )
    label = (
        "Credit cards offered in Alberta: annual fee against purchase interest rate"
        if lang == "en"
        else "Cartes de crédit offertes en Alberta : frais annuels et taux d'intérêt sur les achats"
    )
    x_title = "Annual fee" if lang == "en" else "Frais annuels"
    y_title = "Purchase rate" if lang == "en" else "Taux sur les achats"
    return {
        "chart_cards": chart_table(
            charts.scatter_chart(
                points,
                series=series,
                label=label,
                x_format=lambda v: dollars(v, lang),
                y_format=lambda v: percent(v, lang, 0),
                x_title=x_title,
                y_title=y_title,
            ),
            "cards",
            lang,
            label,
            ("Type", x_title, y_title, "Cards" if lang == "en" else "Cartes"),
            # The table gives the rate to the cent the tooltips show.
            charts.scatter_rows(
                points, series, lambda v: dollars(v, lang), lambda v: percent(v, lang, 2)
            ),
        ),
        "count_cards": number(response["total_matched"], lang),
        "cards_priced": str(len(priced)),
        "cards_rewards": str(len(rewards)),
        "cards_plain": str(len(plain)),
        "cards_fee_rewards": esc(dollars(median([c["annual_fee"] for c in rewards]), lang)),
        "cards_fee_plain": esc(dollars(median([c["annual_fee"] for c in plain]), lang)),
        "cards_rate_rewards": esc(percent(median([c["purchase_rate"] for c in rewards]), lang, 2)),
        "cards_rate_plain": esc(percent(median([c["purchase_rate"] for c in plain]), lang, 2)),
        "source_cards": call_source(response, lang),
    }


def month_name(iso: str, lang: Lang) -> str:
    months = MONTHS_EN if lang == "en" else MONTHS_FR
    return f"{months[int(iso[5:7]) - 1]} {iso[:4]}"


def curve_context(case: dict[str, Any], lang: Lang) -> dict[str, str]:
    response = case["calls"][0]["response"]
    two, ten = "BD.CDN.2YR.DQ.YLD", "BD.CDN.10YR.DQ.YLD"
    days = [
        (o["ref_date"], o["values"][ten] - o["values"][two])
        for o in response["observations"]
        if o["values"].get(two) is not None and o["values"].get(ten) is not None
    ]
    # A monthly average of the daily gap keeps the line readable over 25
    # years; the text quotes the last day as it was published.
    months: dict[str, list[float]] = {}
    for iso, gap in days:
        months.setdefault(iso[:7], []).append(gap)
    points = [(f"{m}-01", sum(v) / len(v)) for m, v in sorted(months.items())]
    # Spells of inverted months: runs below zero, joined when fewer than six
    # months apart, named by year ("2006 to 2007").
    runs: list[list[int]] = []
    for n, (_, gap) in enumerate(points):
        if gap < 0:
            if runs and n - runs[-1][1] < 6:
                runs[-1][1] = n
            else:
                runs.append([n, n])
    spells = [(points[a][0][:4], points[b][0][:4]) for a, b in runs]
    to = "to" if lang == "en" else "à"
    names = [a if a == b else f"{a} {to} {b}" for a, b in spells]
    deepest_iso, deepest = min(points, key=lambda p: p[1])
    label = (
        "The yield curve: 10-year minus 2-year Government of Canada benchmark bond yields, monthly average of daily values, with inverted months shaded"
        if lang == "en"
        else "La courbe des taux : rendement des obligations de référence du gouvernement du Canada à 10 ans moins celui à 2 ans, moyenne mensuelle des valeurs quotidiennes, mois inversés ombrés"
    )
    low = min(p[1] for p in points)
    band = (low, 0.0, "Inverted" if lang == "en" else "Inversée")
    bp = "bp" if lang == "en" else "pb"
    points = [(iso, v * 100) for iso, v in points]
    band = (band[0] * 100, 0.0, band[2])

    def fmt(v: float) -> str:
        return f"{number(v, lang)} {bp}"

    # Some 300 monthly points would make a long table; a row per year keeps
    # it readable, and the caption says what the rows are.
    caption = (
        "The 10-year minus 2-year yield gap by year: the average, lowest and highest of that year's monthly averages"
        if lang == "en"
        else "L'écart de rendement entre 10 ans et 2 ans par année : moyenne, minimum et maximum des moyennes mensuelles de l'année"
    )
    head = ("Year", "Average", "Lowest month", "Highest month")
    if lang == "fr":
        head = ("Année", "Moyenne", "Mois le plus bas", "Mois le plus haut")
    return {
        "chart_curve": chart_table(
            charts.line_chart(
                points,
                label=label,
                value_format=fmt,
                x_tick_format=lambda iso: (
                    iso[:4] if iso[5:7] == "01" and int(iso[:4]) % 5 == 0 else None
                ),
                band=band,
                date_format=tip_date(lang, monthly=True),
            ),
            "curve",
            lang,
            caption,
            head,
            charts.yearly_rows(points, fmt),
        ),
        "count_curve": number(len(days), lang),
        "curve_first_year": days[0][0][:4],
        "curve_spells": esc(
            join_names(names, lang)
            if len(names) <= 2
            else ", ".join(names[:-1]) + (" and " if lang == "en" else " et ") + names[-1]
        ),
        "curve_deepest": esc(f"{number(deepest * 100, lang)} {bp}"),
        "curve_deepest_month": esc(month_name(deepest_iso, lang)),
        "curve_last": esc(f"{number(points[-1][1], lang)} {bp}"),
        "curve_last_month": esc(month_name(points[-1][0], lang)),
        "source_curve": call_source(response, lang),
    }


def patents_context(case: dict[str, Any], lang: Lang) -> dict[str, str]:
    calls = case["calls"]
    by_year = [
        (c["arguments"]["filed_from"][:4], c["response"]["total_matched"]) for c in calls[1:]
    ]
    # Applications are published about 18 months after filing, so the last
    # year is still filling in; the chart stops the year before it.
    shown, (partial_year, partial_count) = by_year[:-1], by_year[-1]
    peak_year, peak = max(shown, key=lambda p: p[1])
    label = (
        "Canadian patent applications in IPC class G06N (machine learning and other biological-model computing), by filing year"
        if lang == "en"
        else "Demandes de brevet canadiennes dans la classe CIB G06N (apprentissage automatique et autres calculs fondés sur des modèles biologiques), par année de dépôt"
    )
    years = [year for year, _ in shown]
    series: list[tuple[str, list[float | None]]] = [("G06N", [float(n) for _, n in shown])]

    def fmt(v: float) -> str:
        return number(v, lang)

    return {
        "chart_patents": chart_table(
            charts.grouped_bars(years, series, label=label, value_format=fmt),
            "patents",
            lang,
            label,
            ("Filing year" if lang == "en" else "Année de dépôt", "G06N"),
            charts.bar_rows(years, series, fmt),
        ),
        "count_patents": number(calls[0]["response"]["total_matched"], lang),
        "patents_first_year": shown[0][0],
        "patents_first": number(shown[0][1], lang),
        "patents_peak_year": peak_year,
        "patents_peak": number(peak, lang),
        "patents_partial_year": partial_year,
        "patents_partial": number(partial_count, lang),
        "source_patents": call_source(calls[1]["response"], lang),
    }


def boc_context(case: dict[str, Any], lang: Lang) -> dict[str, str]:
    response = case["calls"][0]["response"]
    points = sorted(
        (o["ref_date"], float(o["values"]["V39079"]))
        for o in response["observations"]
        if o["values"].get("V39079") is not None
    )
    values = [v for _, v in points]
    changes = sum(1 for a, b in pairwise(values) if a != b)
    label = (
        "Bank of Canada target for the overnight rate, daily since 2015"
        if lang == "en"
        else "Taux cible du financement à un jour de la Banque du Canada, quotidien depuis 2015"
    )

    def fmt(v: float) -> str:
        return percent(v, lang, 2)

    # Every day since 2015 would be thousands of rows; the rate only moves on
    # announcement days, so the table lists those (and the first and last day).
    caption = (
        "Bank of Canada target for the overnight rate: the first day, each day it changed, and the last day"
        if lang == "en"
        else "Taux cible du financement à un jour de la Banque du Canada : le premier jour, chaque jour où il a changé et le dernier jour"
    )
    return {
        "chart_boc": chart_table(
            charts.step_chart(
                points,
                label=label,
                value_format=fmt,
                x_tick_format=year_ticks,
                date_format=tip_date(lang, monthly=False),
            ),
            "boc",
            lang,
            caption,
            ("Date", "Rate" if lang == "en" else "Taux"),
            charts.time_rows(points, fmt, lambda iso: long_date(iso, lang), steps=True),
        ),
        "boc_changes": str(changes),
        "boc_min": esc(percent(min(values), lang, 2)),
        "boc_max": esc(percent(max(values), lang, 2)),
        "boc_last": esc(percent(values[-1], lang, 2)),
        "boc_last_date": esc(long_date(points[-1][0], lang)),
        "source_boc": call_source(response, lang),
    }


# The ring's arcs: sixteen subjects, grouped so every arc is wide enough
# to carry its own name and count. (short EN, short FR, subject keys); the
# tooltip lists the subjects each arc holds.
RING_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Statistics", "Statistique", ("statistics",)),
    ("Provinces and cities", "Provinces et villes", ("catalogue", "provincial", "municipal")),
    ("Money and business", "Argent et affaires", ("money", "business")),
    (
        "Land and energy",
        "Terre et énergie",
        ("agriculture", "environment", "energy", "geography", "transport"),
    ),
    ("People", "Population", ("health", "housing", "immigration")),
    ("Parliament", "Parlement", ("government",)),
)


# West to east, then north: the order the inner inscription travels.
RING_ORDER = ("BC", "AB", "SK", "MB", "ON", "QC", "NB", "NS", "PE", "NL", "YT", "NT", "NU")


def _city(name: str) -> str:
    """'City of Red Deer ArcGIS Hub' -> 'Red Deer': the place a portal serves."""
    name = re.sub(r"\s*\(.*?\)", "", name)
    name = re.sub(r"^(City|Town|County|Region) of |^Open ", "", name)
    for _ in range(2):
        name = re.sub(
            r"\s+(Open Data.*|Data Catalogue|Data Catalog|Data Hub|GeoHub|ArcGIS Hub|"
            r"Atlas|Regional Municipality|Portal|Region|County)$",
            "",
            name,
        )
    return name.strip()


def alphabetical(name: str) -> str:
    """A sort key that files « Élections » under E, as a French reader expects."""
    return unicodedata.normalize("NFKD", name.casefold()).encode("ascii", "ignore").decode()


def ring_places(lang: Lang) -> list[str]:
    """Every province and city with a local source, grouped west to east."""
    provinces: set[str] = set()
    cities: dict[str, set[str]] = {}
    families = {"ckan": CKAN_PORTALS, "arcgis_hub": ARCGIS_PORTALS, "socrata": SOCRATA_PORTALS}
    for family, portals in families.items():
        for key, portal in portals.items():
            place, level = PORTAL_PLACES[family][key]
            if level == "provincial":
                provinces.add(place)
            elif level == "municipal":
                cities.setdefault(place, set()).add(_city(portal.name_en))
    for source in SOURCES.values():
        for place in source.places:
            if source.level == "municipal" or source.en.startswith("City of"):
                cities.setdefault(place, set()).add(_city(source.en))
            elif source.level in ("provincial", "catalogue"):
                provinces.add(place)
    # A longer name that contains a city already listed is that city's: EPCOR,
    # the police, transit and the metropolitan board are all Edmonton's.
    for place, group in cities.items():
        short = {c for c in group if len(c.split()) <= 2}
        cities[place] = {next((k for k in short if k in c and k != c), c) for c in group}
    names: list[str] = []
    for code in RING_ORDER:
        if code in provinces:
            names.append(PLACES[code][1 if lang == "en" else 2])
        names.extend(sorted((place_name(c, lang) for c in cities.get(code, ())), key=alphabetical))
    return names


def counter_list(items: list[tuple[int, str]], lang: Lang) -> str:
    """Big numbers that count up once scrolled into view (assets/charts.js)."""
    cells = "".join(
        f'<li><span class="counter-n" data-count="">{number(n, lang)}</span>'
        f'<span class="counter-l">{esc(text)}</span></li>'
        for n, text in sorted(items, key=lambda item: -item[0])
    )
    return f'<ul class="counters" data-counters="">{cells}</ul>'


def finale_context(counts: dict[str, Any], modules: list[ModuleDoc], lang: Lang) -> dict[str, str]:
    """The One Ring: every publisher inscribed, the tools as arcs by subject."""
    en = lang == "en"
    tools = sum(len(m.tools) for m in modules)
    outer = sorted(
        {m.source.short(lang) for m in modules if m.source.level == "national"}, key=alphabetical
    )
    by_subject: dict[str, int] = {}
    for module in modules:
        source = module.source
        key = source.domain if source.level == "national" else source.level
        if key:
            by_subject[key] = by_subject.get(key, 0) + len(module.tools)
    arcs = []
    for short_en, short_fr, keys in RING_GROUPS:
        members = [(DOMAINS.get(k) or LEVELS[k])[0 if en else 1] for k in keys]  # type: ignore[index]
        count = sum(by_subject.get(k, 0) for k in keys)
        short = short_en if en else short_fr
        listed = ", ".join(m[0].lower() + m[1:] for m in members)
        arcs.append((short, f"{short}: {listed}", count))
    arcs.sort(key=lambda arc: -arc[2])
    # Every tool is either in an arc or is one of MapleStats' own (the
    # planner and the script writer), counted only in the centre figure.
    grouped = {k for _, _, keys in RING_GROUPS for k in keys}
    assert set(by_subject) - grouped <= {"utility"}, set(by_subject) - grouped
    label = (
        f"The ring: {len(outer)} federal publishers around the outside, the provinces and "
        f"cities with local sources inside, and {tools} tools as arcs by subject"
        if en
        else f"L'anneau : {len(outer)} éditeurs fédéraux à l'extérieur, les provinces et les "
        f"villes dotées de sources locales à l'intérieur, et {tools} outils en arcs par sujet"
    )
    micro = load_case("micro")["calls"][0]["response"]
    items = [
        (
            load_case("patents")["calls"][0]["response"]["total_matched"],
            "patents" if en else "brevets",
        ),
        (micro["unweighted_n"], "census records" if en else "fiches du recensement"),
        (
            counts["boc_list_series"]["total_count"],
            "Bank of Canada series" if en else "séries de la Banque du Canada",
        ),
        (
            counts["wds_list_all_cubes"]["total_count"],
            "Statistics Canada tables" if en else "tableaux de Statistique Canada",
        ),
        (
            counts["statcan_reference_search_data"]["product_count"],
            "microdata files" if en else "fichiers de microdonnées",
        ),
        (
            load_case("cards")["calls"][0]["response"]["total_matched"],
            "credit cards" if en else "cartes de crédit",
        ),
        (
            counts["ircc_monthly_list_tables"]["returned_count"],
            "immigration tables" if en else "tableaux d'immigration",
        ),
        (
            load_case("housing")["calls"][1]["response"]["total_count"],
            "housing tables" if en else "tableaux sur le logement",
        ),
    ]
    return {
        "chart_ring": chart_table(
            charts.ring_chart(
                outer,
                ring_places(lang),
                arcs,
                centre=str(tools),
                centre_lines=(
                    "tools," if en else "outils,",
                    "one connection" if en else "une connexion",
                ),
                label=label,
            ),
            "ring",
            lang,
            (
                f"The {tools} tools by subject (the arcs); MapleStats' own tools are counted only in the total"
                if en
                else f"Les {tools} outils par sujet (les arcs); les outils propres à MapleStats ne comptent que dans le total"
            ),
            ("Subject", "Tools") if en else ("Sujet", "Outils"),
            charts.ring_rows(arcs, lambda v: number(v, lang)),
        ),
        "ring_federal": str(len(outer)),
        "counters": counter_list(items, lang),
    }


def case_context(lang: Lang, modules: list[ModuleDoc]) -> dict[str, str]:
    context: dict[str, str] = {}
    builders = {
        "pumf": pumf_context,
        "ircc": ircc_context,
        "housing": housing_context,
        "micro": micro_context,
        "cards": cards_context,
        "curve": curve_context,
        "patents": patents_context,
        "boc": boc_context,
    }
    for key in CASE_KEYS:
        # A French capture of the same call (the tool's lang="fr"), where the
        # server has French to give, replaces the English one on French pages.
        french = lang == "fr" and (CASES_DIR / f"{key}_fr.json").exists()
        case = load_case(f"{key}_fr" if french else key)
        context.update(builders[key](case, lang))
        context[f"how_{key}"] = how_block(case, key, lang)
    counts = {call["name"]: call["response"] for call in load_case("counts")["calls"]}
    context["count_pumf"] = number(counts["statcan_reference_search_data"]["product_count"], lang)
    context["count_ircc"] = number(counts["ircc_monthly_list_tables"]["returned_count"], lang)
    context["count_tables"] = number(counts["wds_list_all_cubes"]["total_count"], lang)
    context["count_series"] = number(counts["boc_list_series"]["total_count"], lang)
    context["cases_captured"] = long_date(load_case("counts")["captured"], lang)
    context.update(finale_context(counts, modules, lang))
    return context


# --------------------------------------------------------------------------
# The Statistics Canada page (site/statcan.html): a post that walks through
# recorded calls (site/_data/cases/statcan.json, macro.json and pumf.json),
# with counts from the registry and variance methods from the PUMF module.
# Every code box on it is cut from a recording here, never typed by hand.
# --------------------------------------------------------------------------

# Every statcan/<family>/ folder in one group, for the family list at the
# end of the post; statcan_context() fails the build when one is missing.
STATCAN_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Tables and time series", "Tableaux et séries chronologiques", ("wds", "sdmx", "delta")),
    (
        "Census",
        "Recensement",
        ("census_profile", "census_profile_2016", "census_profile_archive", "census_tables", "geo"),
    ),
    ("Microdata", "Microdonnées", ("pumf",)),
    ("Classifications", "Classifications", ("rdaas",)),
    ("Indicators", "Indicateurs", ("indicators", "sdg")),
    (
        "Releases, catalogues and methods",
        "Diffusions, catalogues et méthodes",
        ("daily", "reference", "surveys"),
    ),
)

# The file each verified variance method in statcan/pumf/tabulate.py covers,
# keyed by its url_marker; the build fails when a method has no entry.
VARIANCE_FILES: dict[str, tuple[str, str]] = {
    "cen21_ind_": (
        "2021 Census, individuals file (98M0001X)",
        "Recensement de 2021, fichier des particuliers (98M0001X)",
    ),
    "/89m0025x/2022001/2024.zip": (
        "Employment Insurance Coverage Survey, 2024 (89M0025X)",
        "Enquête sur la couverture de l'assurance-emploi, 2024 (89M0025X)",
    ),
    "/14-25-0001/2026001/2024-2025.zip": (
        "CSWC, 2024-2025 (14-25-0001)",
        "CSWC, 2024-2025 (14-25-0001)",
    ),
}

# The search_tools query the post shows, and the tool its text says the
# ranking offers; the build fails if that tool drops out of the results.
STATCAN_SEARCH: dict[Lang, str] = {
    "en": "search StatCan tables",
    "fr": "chercher un tableau Statistique Canada",
}
STATCAN_SEARCH_PICK = "wds_search_cubes"

# Names in <code> that look like StatCan tools. The first mention of each
# real tool becomes a link to it; one the server does not have fails the build.
_STATCAN_PREFIXES = ("wds_", "sdmx_", "rdaas_", "statcan_")
_CODE_NAME = re.compile(r"<code>([a-z][a-z0-9_]*[a-z0-9])</code>")


def link_tools(text: str, tools: set[str], root: str) -> str:
    seen: set[str] = set()

    def one(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in tools:
            if name.startswith(_STATCAN_PREFIXES):
                raise SystemExit(f"statcan.html names a tool the server does not have: {name}")
            return match.group(0)
        if name in seen:
            return match.group(0)
        seen.add(name)
        return f'<a href="{tool_href(name, root)}"><code>{esc(name)}</code></a>'

    return _CODE_NAME.sub(one, text)


# A trimmed code box marks what it leaves out with a comment line: a string
# item in a list, or a value under this key in an object.
_MORE = "\x00more"


def _json_parts(value: Any, depth: int, flat: int) -> str:
    """Indented JSON; containers `flat` levels down and deeper stay on one line."""
    if not isinstance(value, (dict, list)) or not value or depth >= flat:
        return json.dumps(value, ensure_ascii=False)
    pad = "  " * (depth + 1)
    pairs = list(value.items()) if isinstance(value, dict) else [(None, v) for v in value]
    items: list[tuple[str, bool]] = []
    for key, item in pairs:
        if key == _MORE:
            items.append((f"{pad}// {item}", True))
        elif isinstance(item, str) and item.startswith(_MORE):
            items.append((f"{pad}// {item[len(_MORE) :]}", True))
        else:
            label = f"{json.dumps(key, ensure_ascii=False)}: " if key is not None else ""
            items.append((pad + label + _json_parts(item, depth + 1, flat), False))
    lines = []
    for n, (text, comment) in enumerate(items):
        later = any(not c for _, c in items[n + 1 :])
        lines.append(text + ("," if not comment and later else ""))
    brackets = "{}" if isinstance(value, dict) else "[]"
    return brackets[0] + "\n" + "\n".join(lines) + "\n" + "  " * depth + brackets[1]


def post_json(value: Any, flat: int = 1) -> str:
    """`value` as indented, highlighted JSON, with its // comment lines."""
    out = []
    for line in _json_parts(value, 0, flat).split("\n"):
        if line.lstrip().startswith("// "):
            indent = len(line) - len(line.lstrip())
            out.append(f'{line[:indent]}<span class="s-com">{esc(line.lstrip())}</span>')
        else:
            out.append(highlight_json(line))
    return "\n".join(out)


def _call_box(
    call: dict[str, Any],
    response: Any,
    lang: Lang,
    *,
    request_flat: int = 1,
    response_flat: int = 2,
) -> str:
    """One recorded call: its call_tool request, then `response`, the part
    of the recorded response the box shows, named by the result's schema."""
    en = lang == "en"
    request = {"name": call["name"], "arguments": call["arguments"]}
    recorded = call["response"]
    schema = (recorded[0] if isinstance(recorded, list) else recorded)["provenance"]["schema_name"]
    shown = _strip_provenance(response, lang)
    return (
        '<figure class="panel post-call post-wide">'
        f'<figcaption class="panel-bar"><span>{"Request" if en else "Requête"}</span>'
        f'<code class="tag">call_tool</code></figcaption>'
        f"<pre><code>{post_json(request, request_flat)}</code></pre>"
        f'<div class="panel-bar"><span>{"Response, trimmed" if en else "Réponse, abrégée"}</span>'
        f'<code class="tag">{esc(schema)}</code></div>'
        f"<pre><code>{post_json(shown, response_flat)}</code></pre>"
        "</figure>"
    )


def _strip_provenance(value: Any, lang: Lang) -> Any:
    """Every box keeps the response's shape; the provenance keeps only its URL
    (or what a box chose to keep, when it already marks the rest)."""
    if isinstance(value, list):
        return [_strip_provenance(v, lang) for v in value]
    if isinstance(value, dict) and "provenance" in value and _MORE not in value["provenance"]:
        prov = value["provenance"]
        return {
            **{k: v for k, v in value.items() if k != "provenance"},
            "provenance": {"url": prov["url"], _MORE: _more_fields(len(prov) - 1, lang)},
        }
    return value


def _more_fields(count: int, lang: Lang) -> str:
    if lang == "en":
        return f"+ {count} more {'field' if count == 1 else 'fields'}"
    return f"+ {count} autre{'s' if count > 1 else ''} champ{'s' if count > 1 else ''}"


def _excerpt(code: str, start: str, end: str) -> str:
    """The lines of a recorded script from the one starting with `start`
    through the next one starting with `end`; the build fails if either is gone."""
    lines = code.split("\n")
    first = next((n for n, line in enumerate(lines) if line.startswith(start)), None)
    if first is None:
        raise SystemExit(f"the recorded script no longer has a line starting {start!r}")
    last = next((n for n in range(first, len(lines)) if lines[n].startswith(end)), None)
    if last is None:
        raise SystemExit(f"the recorded script has no {end!r} after {start!r}")
    return "\n".join(lines[first : last + 1])


def _calls(key: str) -> dict[str, dict[str, Any]]:
    return {call["name"]: call for call in load_case(key)["calls"]}


def _search_box(names: list[str], query: str, lang: Lang) -> str:
    en = lang == "en"
    return (
        '<figure class="panel post-call">'
        f'<figcaption class="panel-bar"><span>{"Request" if en else "Requête"}</span>'
        '<code class="tag">search_tools</code></figcaption>'
        f"<pre><code>{post_json({'query': query})}</code></pre>"
        f'<div class="panel-bar"><span>{"Response: names only" if en else "Réponse : noms seulement"}</span>'
        f"<span>{'ranked when this page was built' if en else 'classement au moment de la génération'}</span></div>"
        f"<pre><code>{post_json(names)}</code></pre>"
        "</figure>"
    )


def statcan_snippets(lang: Lang) -> dict[str, str]:
    """The code boxes, cut from the recorded calls, and the numbers the text
    quotes from them."""
    en = lang == "en"
    suffix = "en" if en else "fr"
    calls = _calls("statcan")
    macro = _calls("macro")["wds_get_data_from_vectors"]
    pumf = _calls("pumf")["statcan_pumf_tabulate"]

    # Finding the table: the CPI table and the match after it.
    search = calls["wds_search_cubes"]
    cubes = search["response"]["cubes"]
    at = next((n for n, c in enumerate(cubes) if c["product_id"] == 18100004), None)
    if at is None:
        raise SystemExit("the recorded search no longer finds table 18100004")
    fields = ("product_id", "cansim_id", f"cube_title_{suffix}", "release_time")
    before, after = at, len(cubes) - at - 2

    def skipped(count: int) -> list[str]:
        if not count:
            return []
        return [f"{_MORE}{count} more" if en else f"{_MORE}{count} de plus"]

    search_shown = {
        "cubes": skipped(before)
        + [{k: c[k] for k in fields} for c in cubes[at : at + 2]]
        + skipped(after),
        "total_count": search["response"]["total_count"],
        "provenance": {
            "url": search["response"]["provenance"]["url"],
            "coverage": search["response"]["provenance"]["coverage"],
            _MORE: _more_fields(len(search["response"]["provenance"]) - 2, lang),
        },
    }

    # The table's dimensions: two members each, in the page's language.
    meta = calls["wds_get_cube_metadata"]
    dims = meta["response"]["dimensions"]
    meta_shown = {
        "product_id": meta["response"]["product_id"],
        f"cube_title_{suffix}": meta["response"][f"cube_title_{suffix}"],
        "n_series": meta["response"]["n_series"],
        "dimensions": [
            {
                "dimension_position_id": d["dimension_position_id"],
                f"dimension_name_{suffix}": d[f"dimension_name_{suffix}"],
                "members": [
                    {
                        "member_id": m["member_id"],
                        "parent_member_id": m["parent_member_id"],
                        f"member_name_{suffix}": m[f"member_name_{suffix}"],
                    }
                    for m in d["members"][:2]
                ]
                + [
                    f"{_MORE}{d['member_count'] - 2} more members"
                    if en
                    else f"{_MORE}{d['member_count'] - 2} autres membres"
                ],
            }
            for d in dims
        ],
    }
    # The capture replaced the footnotes with their count (capture_cases.py).
    fields_meta = (set(meta["response"]) - {"footnote_count"}) | {"footnotes"}
    meta_shown[_MORE] = _more_fields(len(fields_meta - set(meta_shown)), lang)
    roots = [d["members"][0] for d in dims]
    if [m["member_id"] for m in roots] != [2, 2] or any(m["parent_member_id"] for m in roots):
        raise SystemExit("the text says member 2 is the root of both CPI dimensions; check it")
    combos = math.prod(d["member_count"] for d in dims)

    coord = calls["wds_get_series_info_from_cube_pid_coord"]
    if coord["response"]["vector_id"] != macro["arguments"]["vector_ids"][0]:
        raise SystemExit("the coordinate call and the CPI call no longer name the same vector")

    # The CPI call from the case studies: its latest month in full.
    series = macro["response"][0]
    obs = series["observations"]
    earlier = len(obs) - 1
    data_shown = [
        {
            "product_id": series["product_id"],
            "coordinate": series["coordinate"],
            "vector_id": series["vector_id"],
            "observations": [
                f"{_MORE}{earlier} earlier months" if en else f"{_MORE}{earlier} mois précédents",
                obs[-1],
            ],
            "provenance": series["provenance"],
        }
    ]
    last = obs[-1]
    if obs[0]["release_time"][:4] <= obs[0]["ref_period"][:4]:
        raise SystemExit("the text says the oldest recorded CPI month was re-released years later")

    sdmx = calls["sdmx_get_vector_data"]

    # The PUMF call: one bachelor's degree cell in full, then the bachelor's
    # rows of the first provinces as a table.
    cells = pumf["response"]["cells"]
    bachelor = [
        c for c in cells if any(g["variable"] == "HDGREE" and g["code"] == "9" for g in c["groups"])
    ]
    pumf_keys = ("data_file", "statistic", "weight", "unweighted_n", "weighted_total")
    pumf_shown = {
        **{k: pumf["response"][k] for k in pumf_keys},
        "cells": [
            bachelor[0],
            f"{_MORE}{len(cells) - 1} more cells"
            if en
            else f"{_MORE}{len(cells) - 1} autres cellules",
        ],
    }
    pumf_shown[_MORE] = "+ " + ", ".join(k for k in pumf["response"] if k not in pumf_shown)
    pumf_rows = bachelor[:5]
    heads = ("estimate", "standard_error", "cv", "unweighted_n", "low_count")
    body = "".join(
        "<tr>"
        f"<td>{esc(PR_NAMES[next(g['code'] for g in c['groups'] if g['variable'] == 'PR')][0 if en else 1])}</td>"
        f'<td data-label="estimate">{number(c["estimate"], lang, 2)}</td>'
        f'<td data-label="standard_error">{number(c["standard_error"], lang, 2)}</td>'
        f'<td data-label="cv">{number(c["cv"], lang, 3)}</td>'
        f'<td data-label="unweighted_n">{number(c["unweighted_n"], lang)}</td>'
        f'<td data-label="low_count"><code>{str(c["low_count"]).lower()}</code></td>'
        "</tr>"
        for c in pumf_rows
    )
    caption = (
        f"The bachelor's degree cells for the first {len(pumf_rows)} provinces in the response, rounded."
        if en
        else f"Les cellules du baccalauréat pour les {len(pumf_rows)} premières provinces de la réponse, arrondies."
    )
    pumf_table = (
        '<div class="table-wrap post-wide"><table class="params post-table post-cells">'
        f"<caption>{esc(caption)}</caption><thead><tr><th>Province</th>"
        + "".join(f"<th><code>{h}</code></th>" for h in heads)
        + f"</tr></thead><tbody>{body}</tbody></table></div>"
    )

    # From a call to a script: the lines of the recorded CPI scripts that
    # the text talks about.
    scripts = macro["scripts"]
    python = (
        _excerpt(scripts["python"], "with httpx.Client(", "raw_path.write_bytes(")
        + "\n\n# …\n\n"
        + _excerpt(scripts["python"], "# scalarFactorCode is", ")")
    )
    r_code = (
        _excerpt(scripts["r"], "data <- get_cansim_vector(", "data <- get_cansim_vector(")
        + "\n\n# …\n\n"
        + _excerpt(scripts["r"], "# cansim adds val_norm", "  filter(")
    )
    if "http2=True" not in python or "10 ** pl.col" not in python:
        raise SystemExit(
            "the text says the Python script sets http2=True and scales in a new column"
        )
    script_box = (
        '<figure class="panel post-wide post-script">'
        + script_tabs([("python", python), ("r", r_code)], "sc-rp")
        + "</figure>"
    )

    captured = max(load_case(key)["captured"] for key in ("statcan", "macro", "pumf"))
    return {
        "sc_date": esc(long_date(captured, lang)),
        "sc_date_iso": captured,
        "sc_search_box": _call_box(search, search_shown, lang, response_flat=3),
        "sc_meta_box": _call_box(meta, meta_shown, lang, response_flat=4),
        "sc_coord_box": _call_box(coord, coord["response"], lang),
        "sc_data_box": _call_box(macro, data_shown, lang, response_flat=4),
        "sc_sdmx_box": _call_box(sdmx, sdmx["response"], lang, response_flat=4),
        "sc_pumf_box": _call_box(pumf, pumf_shown, lang, request_flat=3, response_flat=4),
        "sc_pumf_table": pumf_table,
        "sc_script_box": script_box,
        "sc_pumf_zip": esc(pumf["arguments"]["url"].rsplit("/", 1)[-1]),
        "sc_members_geo": number(dims[0]["member_count"], lang),
        "sc_members_prod": number(dims[1]["member_count"], lang),
        "sc_combos": number(combos, lang),
        "sc_n_series": number(meta["response"]["n_series"], lang),
        "sc_coord_in": esc(coord["arguments"]["coordinate"]),
        "sc_coord_out": esc(coord["response"]["coordinate"]),
        "sc_vector": str(coord["response"]["vector_id"]),
        "sc_latest_n": str(macro["arguments"]["latest_n"]),
        "sc_last_month": esc(month_name(last["ref_period"], lang)),
        "sc_last_release": esc(long_date(last["release_time"], lang)),
        # The oldest month in the recording, whose release_time is a later re-release.
        "sc_first_month": esc(month_name(obs[0]["ref_period"], lang)),
        "sc_first_release": esc(long_date(obs[0]["release_time"], lang)),
        "sc_sdmx_key": esc(sdmx["response"]["key"]),
        "sc_sdmx_url": esc(sdmx["response"]["provenance"]["url"]),
        "sc_search_coverage": esc(search["response"]["provenance"]["coverage"]),
        "sc_pumf_n": number(pumf["response"]["unweighted_n"], lang),
        "sc_pumf_weighted": number(pumf["response"]["weighted_total"], lang),
        "sc_pumf_cells": number(len(cells), lang),
    }


def _variance_table(lang: Lang) -> str:
    from maplestats_mcp.modules.statcan.pumf.tabulate import VARIANCE_METHODS

    en = lang == "en"
    head = (
        ("File", "Weight", "Replicates", "Standard error")
        if en
        else ("Fichier", "Poids", "Répliques", "Erreur-type")
    )
    rows = []
    for method in VARIANCE_METHODS:
        if method.url_marker not in VARIANCE_FILES:
            raise SystemExit(f"add {method.url_marker!r} to VARIANCE_FILES in build_site.py")
        name = VARIANCE_FILES[method.url_marker][0 if en else 1]
        divisor = number(method.divisor, lang)
        if method.centre == "mean":
            how = (
                f"Random groups: squared deviations from the replicates' mean, divided by {divisor}"
                if en
                else f"Groupes aléatoires : écarts au carré à la moyenne des répliques, divisés par {divisor}"
            )
        else:
            how = (
                f"Bootstrap: squared deviations from the full-sample estimate, divided by {divisor}"
                if en
                else f"Bootstrap : écarts au carré à l'estimation sur l'échantillon complet, divisés par {divisor}"
            )
        replicates = method.replicates
        rows.append(
            # data-label names each cell where the phone layout hides the header row.
            f"<tr><td>{esc(name)}</td>"
            f'<td data-label="{head[1]}"><code>{esc(method.main_weight)}</code></td>'
            f'<td data-label="{head[2]}"><code>{esc(replicates[0])}</code>–'
            f"<code>{esc(replicates[-1])}</code> "
            f'<span class="count">{number(len(replicates), lang)}</span></td>'
            f'<td data-label="{head[3]}">{esc(how)}</td></tr>'
        )
    caption = (
        "PUMF files with a standard-error method"
        if en
        else "Fichiers de microdonnées avec une méthode d'erreur-type"
    )
    return (
        '<div class="table-wrap post-wide"><table class="params post-table post-variance">'
        f'<caption class="sr">{caption}</caption><thead><tr>'
        + "".join(f"<th>{h}</th>" for h in head)
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _family_list(by_family: dict[str, list[ToolDoc]], lang: Lang, root: str) -> str:
    en = lang == "en"
    groups = []
    for title_en, title_fr, families in STATCAN_GROUPS:
        items = []
        for family in families:
            names = [t.name for t in by_family[family]]
            title = FAMILIES[f"statcan/{family}"][0 if en else 1]
            items.append(
                f'<li><a href="{tool_href(names[0], root)}">{esc(title)}</a>'
                f'<code class="tag">{esc(_family_prefix(names, "statcan", family))}</code>'
                f'<span class="count">{len(names)}</span></li>'
            )
        groups.append(
            f'<div class="post-family"><h3>{esc(title_en if en else title_fr)}</h3>'
            f"<ul>{''.join(items)}</ul></div>"
        )
    return f'<div class="post-families post-wide">{"".join(groups)}</div>'


def statcan_context(
    modules: list[ModuleDoc], lang: Lang, root: str, searched: list[str]
) -> dict[str, str]:
    from maplestats_mcp.modules.statcan.pumf.tabulate import VARIANCE_METHODS
    from maplestats_mcp.modules.statcan.wds import constants as wds_constants

    module = next(m for m in modules if m.key == "statcan")
    by_family: dict[str, list[ToolDoc]] = {}
    for tool in module.tools:
        by_family.setdefault(tool.family, []).append(tool)
    grouped = [family for _, _, families in STATCAN_GROUPS for family in families]
    missing = sorted(set(by_family) - set(grouped))
    stale = sorted(set(grouped) - set(by_family))
    if missing or stale:
        raise SystemExit(f"STATCAN_GROUPS in build_site.py: add {missing}, remove {stale}")
    if STATCAN_SEARCH_PICK not in searched:
        raise SystemExit(
            f"search_tools no longer returns {STATCAN_SEARCH_PICK} for {STATCAN_SEARCH[lang]!r}; "
            "change STATCAN_SEARCH and the text around it"
        )
    census = next(m for m in VARIANCE_METHODS if m.url_marker == "cen21_ind_")
    return {
        "statcan_tool_count": str(len(module.tools)),
        "statcan_family_count": str(len(by_family)),
        "statcan_resources": _code_list(module.resources, lang),
        "statcan_variance_count": str(len(VARIANCE_METHODS)),
        "statcan_variance_table": _variance_table(lang),
        "statcan_families": _family_list(by_family, lang, root),
        "sc_search_tools_box": _search_box(searched, STATCAN_SEARCH[lang], lang),
        "sc_replicates": str(len(census.replicates)),
        "sc_replicate_first": esc(census.replicates[0]),
        "sc_replicate_last": esc(census.replicates[-1]),
        "sc_census_weight": esc(census.main_weight),
        "sc_census_divisor": number(census.divisor, lang),
        "sc_rate": number(wds_constants.RATE_LIMIT_PER_SECOND, lang),
        **statcan_snippets(lang),
    }


def _code_list(names: list[str], lang: Lang) -> str:
    """<code>a</code>, <code>b</code> and <code>c</code>."""
    codes = [f"<code>{esc(name)}</code>" for name in names]
    if len(codes) < 2:
        return "".join(codes)
    return f"{', '.join(codes[:-1])} {'and' if lang == 'en' else 'et'} {codes[-1]}"


# On a French page, {{root}} is "../" so the shared assets resolve, but a link
# to another page must stay in French: "../tools.html#t-x" becomes
# "tools.html#t-x". The language switch (it carries hreflang) keeps pointing
# at the English page, and data-pages tells site.js where pages live.
_PAGE_LINK = re.compile(r'(<a\b(?![^>]*\bhreflang=)[^>]*?\bhref=")\.\./([\w-]+\.html)')


def french_links(html_text: str) -> str:
    html_text = _PAGE_LINK.sub(r"\1\2", html_text)
    return html_text.replace('data-root="../"', 'data-root="../" data-pages=""', 1)


# A box that scrolls sideways must take keyboard focus, or a keyboard user
# cannot read what is cut off (axe: scrollable-region-focusable). The code
# blocks, the setup prompt and the tables that scroll are all marked here,
# after rendering, so a new template or fragment gets it without asking. A
# table box is a region named by its table's caption, so every table in one
# needs a <caption> (class="sr" when it would only repeat the heading).
_PRE_TAG = re.compile(r"<pre\b(?![^>]*\btabindex=)")
_CMD_CODE = re.compile(r'(<div class="cmd\b[^"]*">\s*<code)\b(?![^>]*\btabindex=)')
_TABLE_WRAP = re.compile(r'<div class="table-wrap\b[^"]*"(?![^>]*\btabindex=)')
_TABLE_CAPTION = re.compile(r"\s*<table\b[^>]*>\s*<caption\b(?![^>]*\bid=)")


def focusable_scrollers(html_text: str) -> str:
    html_text = _PRE_TAG.sub('<pre tabindex="0"', html_text)
    html_text = _CMD_CODE.sub(r'\1 tabindex="0"', html_text)
    out: list[str] = []
    pos = 0
    for n, match in enumerate(_TABLE_WRAP.finditer(html_text), start=1):
        close = html_text.index(">", match.end()) + 1
        caption = _TABLE_CAPTION.match(html_text, close)
        if not caption:
            snippet = html_text[match.start() : match.start() + 160]
            raise SystemExit(f"a .table-wrap table needs a <caption> to name it: {snippet}")
        label = f"tbl-{n}"
        out.append(html_text[pos : match.end()])
        out.append(f' role="region" aria-labelledby="{label}" tabindex="0"')
        out.append(html_text[match.end() : caption.end()])
        out.append(f' id="{label}"')
        pos = caption.end()
    out.append(html_text[pos:])
    return "".join(out)


# Tabs without JavaScript: the templates mark every panel but the first
# hidden, which is how site.js starts them, but without scripts the tab
# buttons do nothing and those panels could never be read. So every panel
# ships visible, headed by its tab's name (.tab-name, shown only without
# scripts, when the tab list is hidden by site.css), and site.js hides the
# unselected ones as it starts the tabs.
_TABPANEL = re.compile(r'<div role="tabpanel"([^>]*?)\saria-labelledby="([^"]+)"([^>]*)>')
_TAB_BUTTON = re.compile(
    r'<button\b[^>]*\brole="tab"[^>]*\bid="([^"]+)"[^>]*>(.*?)</button>', re.DOTALL
)


def tabs_without_scripts(html_text: str) -> str:
    names = {m.group(1): m.group(2) for m in _TAB_BUTTON.finditer(html_text)}

    def panel(match: re.Match[str]) -> str:
        before, label, after = match.groups()
        attrs = re.sub(r"\shidden\b", "", f'{before} aria-labelledby="{label}"{after}')
        name = names.get(label)
        if name is None:
            raise SystemExit(f"tab panel labelled by a missing tab: {label}")
        return f'<div role="tabpanel"{attrs}><p class="tab-name">{name}</p>'

    return _TABPANEL.sub(panel, html_text)


# Link previews (Open Graph, X/Twitter) repeat each page's own <title> and
# description; head.html holds these marks where they go.
OG_TITLE, OG_DESCRIPTION = "\x00og-title", "\x00og-description"
_TITLE = re.compile(r"<title>(.*?)</title>", re.DOTALL)
_META_DESCRIPTION = re.compile(r'<meta name="description" content="([^"]*)">')


def social_meta(html_text: str) -> str:
    title = _TITLE.search(html_text)
    description = _META_DESCRIPTION.search(html_text)
    if not title or not description:
        raise SystemExit("every page needs a <title> and a meta description")
    plain_title = html.escape(html.unescape(title.group(1).strip()), quote=True)
    return html_text.replace(OG_TITLE, plain_title).replace(OG_DESCRIPTION, description.group(1))


# French typography, as Canadian French usage sets it: a narrow no-break
# space before ; ? ! and %, a no-break space before : and inside « ». It is
# applied to the text a reader sees wherever the language is French (a French
# page, or a lang="fr" passage on an English page), so templates, generated
# fragments and the server's French text all get it. Code, scripts and
# anything marked lang="en" are left as they are.
NNBSP, NBSP = "\u202f", "\u00a0"
_MARKUP = re.compile(
    r"<!--.*?-->|<(/?)([a-zA-Z][\w:-]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>", re.DOTALL
)
_LANG_ATTR = re.compile(r'\slang="([a-zA-Z-]*)"')
_TEXT_ATTR = re.compile(
    r'(\s(?:title|aria-label|placeholder|alt|data-more-label|data-less-label|data-label)=")'
    r'([^"]*)(")'
)
_DESCRIPTION = re.compile(r'(\scontent=")([^"]*)(")')
_LITERAL = {"script", "style", "pre", "code", "kbd", "samp", "textarea"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta"}
_VOID |= {"source", "wbr"}
# Inline elements continue the text around them; any other tag starts afresh.
_INLINE = {"a", "abbr", "b", "cite", "code", "em", "i", "kbd", "mark", "q", "samp", "small"}
_INLINE |= {"span", "strong", "sub", "sup", "time", "wbr"}
# (what comes before, the mark): the mark takes a space unless it follows one.
_SPACED = (
    (re.compile(r"(^|\S)\s?([;?!]+)(?=[\s)»]|$)"), NNBSP),
    (re.compile(r"(^|\S)\s?(:)(?=\s|$)"), NBSP),
    (re.compile(r"(^|\S)\s?(»)"), NBSP),
)
_OPEN_QUOTE = re.compile(r"«\s?(?=\S)")
_PERCENT = re.compile(r"(\d)\s?%")


def french_punctuation(text: str, before: str = "") -> str:
    """Space French punctuation; `before` is the character just before `text`."""

    def spacer(space: str) -> Any:
        def repl(match: re.Match[str]) -> str:
            lead, mark = match.group(1), match.group(2)
            # At the start of the text the mark may follow a tag, as in
            # "<code>x</code>: y"; `before` says whether it touches a word.
            if lead or (before and not before.isspace()):
                return f"{lead}{space}{mark}"
            return match.group(0)

        return repl

    for pattern, space in _SPACED:
        text = pattern.sub(spacer(space), text)
    text = _OPEN_QUOTE.sub("«" + NBSP, text)
    return _PERCENT.sub(r"\1" + NNBSP + "%", text)


def french_typography(html_text: str) -> str:
    """french_punctuation() on every French text and text attribute of a page."""
    out: list[str] = []
    # One (tag, lang, literal) per open element.
    stack: list[tuple[str, str, bool]] = [("", "", False)]
    before = ""
    pos = 0

    def french() -> bool:
        lang = next((lang for _, lang, _ in reversed(stack) if lang), "")
        return lang.startswith("fr") and not stack[-1][2]

    def fix(raw: str, quote: bool, prev: str = "") -> str:
        plain = html.unescape(raw)
        fixed = french_punctuation(plain, prev)
        return raw if fixed == plain else html.escape(fixed, quote=quote)

    for match in _MARKUP.finditer(html_text):
        if match.start() < pos:  # inside a script or style skipped below
            continue
        text = html_text[pos : match.start()]
        if text:
            out.append(fix(text, False, before) if french() else text)
            before = html.unescape(text)[-1:] or before
        pos = match.end()
        closing, name, attrs = match.group(1), (match.group(2) or "").lower(), match.group(3)
        if not name:  # a comment
            out.append(match.group(0))
            continue
        if name not in _INLINE:
            before = ""
        if closing:
            if any(tag == name for tag, _, _ in stack[1:]):
                while stack.pop()[0] != name:
                    pass
            out.append(match.group(0))
            continue
        lang = _LANG_ATTR.search(attrs or "")
        literal = stack[-1][2] or name in _LITERAL
        frame = (name, lang.group(1) if lang else "", literal)
        self_closing = name in _VOID or (attrs or "").rstrip().endswith("/")
        stack.append(frame)
        tag = match.group(0)
        if french():
            tag = _TEXT_ATTR.sub(lambda m: m.group(1) + fix(m.group(2), True) + m.group(3), tag)
            if name == "meta" and 'name="description"' in tag:
                tag = _DESCRIPTION.sub(
                    lambda m: m.group(1) + fix(m.group(2), True) + m.group(3), tag
                )
        out.append(tag)
        if self_closing:
            stack.pop()
        elif name in ("script", "style"):
            # Raw text: jump to the closing tag without reading the content.
            end = html_text.find(f"</{name}", pos)
            end = len(html_text) if end < 0 else end
            out.append(html_text[pos:end])
            pos = end
    out.append(html_text[pos:])
    return "".join(out)


def render(template: str, lang: Lang, context: dict[str, str]) -> str:
    def include(match: re.Match[str]) -> str:
        return render_partial(match.group(1))

    def render_partial(name: str) -> str:
        path = SITE / "_partials" / f"{name}.html"
        return _INCLUDE.sub(include, path.read_text(encoding="utf-8"))

    text = _INCLUDE.sub(include, template)
    text = _LANG_BLOCK.sub(lambda m: m.group(1) if lang == "en" else m.group(2), text)
    missing = sorted(set(_VAR.findall(text)) - set(context))
    if missing:
        raise SystemExit(f"template values not defined: {', '.join(missing)}")
    if "{en}" in text or "{fr}" in text or "{/}" in text:
        raise SystemExit("unbalanced {en}/{fr}/{/} marker in a template")
    return _VAR.sub(lambda m: context[m.group(1)], text)


async def build(out: Path) -> dict[str, int]:
    modules = await collect_modules()
    by_name = {t.name: t for m in modules for t in m.tools}
    index = build_index(modules)
    counts = coverage_counts()
    national = [m for m in modules if m.source.level == "national"]
    shared: dict[str, str] = {
        "version": __version__,
        "repo": REPO,
        "tool_count": str(len(by_name)),
        "module_count": str(len(modules)),
        "searchable_count": str(len(index["tools"])),
        "national_count": str(len(national)),
        "other_national_count": str(len(national) - 3),
        "places_covered": str(counts["places_covered"]),
        "catalogue_count": str(counts["catalogue_count"]),
        "local_catalogue_count": str(counts["local_catalogue_count"]),
        "local_plus_federal": str(len(national) - 3 + counts["local_catalogue_count"]),
        # "more than N": the source count rounded down to the multiple of 5 below it
        "sources_over": str((len(national) + counts["local_catalogue_count"] - 1) // 5 * 5),
        "local_source_count": str(counts["local_source_count"]),
        "search_top": str(index["top"]),
    }
    scripts = await reproduce_scripts()
    search_results = {lang: await server_search(SEARCH_EXAMPLE[lang]) for lang in LANGS}
    statcan_searched = {lang: await server_search(STATCAN_SEARCH[lang]) for lang in LANGS}

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SITE / "assets", out / "assets")
    (out / "assets" / "search-index.json").write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    module_names = {m.key: [m.source.short("en"), m.source.short("fr")] for m in modules}
    (out / "assets" / "modules.json").write_text(
        json.dumps(module_names, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    (out / "llms.txt").write_text(llms_txt(modules, counts), encoding="utf-8")

    pages = sorted(p for p in SITE.glob("*.html"))
    cases = {lang: case_context(lang, modules) for lang in LANGS}
    for lang in LANGS:
        root = "" if lang == "en" else "../"
        target_dir = out if lang == "en" else out / "fr"
        target_dir.mkdir(parents=True, exist_ok=True)
        statcan = statcan_context(modules, lang, root, statcan_searched[lang])
        for page in pages:
            context = {
                **shared,
                **captured_call(lang),
                **cases[lang],
                **statcan,
                "lang": lang,
                "root": root,
                "page": page.name,
                "alt_href": (f"fr/{page.name}" if lang == "en" else f"../{page.name}"),
                "site_url": SITE_URL,
                "canonical": page_url(page.name, lang),
                "url_en": page_url(page.name, "en"),
                "url_fr": page_url(page.name, "fr"),
                "og_title": OG_TITLE,
                "og_description": OG_DESCRIPTION,
                "search_query": esc(SEARCH_EXAMPLE[lang]),
                "agent_prompt": esc(AGENT_PROMPT[lang]),
                "search_suggestions": suggestion_buttons(lang),
                "plan_question": esc(PLAN_QUESTION[lang]),
                "plan_panel": plan_panel(lang, root),
                "reproduce_tabs": script_tabs(scripts, "rp", SHOW_MORE[lang]),
                "cur_tools": ' aria-current="page"' if page.name == "tools.html" else "",
                "cur_sources": ' aria-current="page"' if page.name == "sources.html" else "",
                "cur_connect": ' aria-current="page"' if page.name == "connect.html" else "",
                "cur_about": ' aria-current="page"' if page.name == "about.html" else "",
                "cur_cases": ' aria-current="page"' if page.name == "cases.html" else "",
                "cur_statcan": ' aria-current="page"' if page.name == "statcan.html" else "",
                "cur_contributing": (
                    ' aria-current="page"' if page.name == "contributing.html" else ""
                ),
                "search_results": result_items(search_results[lang], by_name, lang, root),
                "coverage_matrix": coverage_matrix(lang),
                "coverage_lists": coverage_lists(lang),
                "national_sources": national_sources(modules, lang, root),
                "atlas": atlas(modules, lang),
                "atlas_index": atlas_index(modules, lang),
                "level_filters": level_filters(modules, lang),
            }
            rendered = render(page.read_text(encoding="utf-8"), lang, context)
            if page.name == "statcan.html":
                rendered = link_tools(rendered, set(by_name), root)
            if lang == "fr":
                rendered = french_links(rendered)
            rendered = tabs_without_scripts(focusable_scrollers(rendered))
            # Both languages: English pages have French passages too.
            rendered = french_typography(rendered)
            # After the typography, so a French preview is spaced as the page is.
            rendered = social_meta(rendered)
            (target_dir / page.name).write_text(rendered, encoding="utf-8")
    (out / "sitemap.xml").write_text(sitemap([p.name for p in pages]), encoding="utf-8")
    (out / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}sitemap.xml\n", encoding="utf-8"
    )
    (out / "404.html").write_text(not_found_page(), encoding="utf-8")
    return {"tools": len(by_name), "modules": len(modules), "pages": len(pages) * len(LANGS)}


def sitemap(names: list[str]) -> str:
    """Every page in both languages, each naming its other-language twin."""
    entries = []
    # The home page first; the rest in file order.
    for name in sorted(names, key=lambda n: (n != "index.html", n)):
        alternates: tuple[tuple[str, Lang], ...] = (("en", "en"), ("fr", "fr"), ("x-default", "en"))
        links = "".join(
            f'<xhtml:link rel="alternate" hreflang="{code}" href="{page_url(name, lang)}"/>'
            for code, lang in alternates
        )
        entries += [f"<url><loc>{page_url(name, lang)}</loc>{links}</url>" for lang in LANGS]
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + "\n".join(entries) + "\n</urlset>\n"
    )


def not_found_page() -> str:
    """404.html, in both languages on one page.

    GitHub Pages serves it for any missing path under the site, at whatever
    depth, so every link and asset is absolute from the site's own path.
    """
    base = "/" + SITE_URL.split("://", 1)[1].split("/", 1)[1]
    return french_typography(
        f"""<!doctype html>
<html lang="en" data-root="{base}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Page not found · Page introuvable · MapleStats MCP</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400..900&amp;family=Source+Sans+3:wght@400..900&amp;display=swap">
<link rel="stylesheet" href="{base}assets/site.css">
<link rel="icon" href="{base}assets/mark.svg" type="image/svg+xml">
<script>try{{var t=localStorage.getItem("maplestats:theme");if(t==="dark"||t==="light")document.documentElement.dataset.theme=t}}catch(e){{}}</script>
</head>
<body>
<main id="main" class="wrap not-found">
  <p><a href="{base}"><img src="{base}assets/logo.svg" width="96" height="96" alt="MapleStats MCP"></a></p>
  <section>
    <h1>Page not found</h1>
    <p>There is no page at this address. It may have moved.</p>
    <p><a href="{base}">MapleStats MCP home</a> · <a href="{base}tools.html">All tools</a></p>
  </section>
  <section lang="fr">
    <h2>Page introuvable</h2>
    <p>Il n'y a pas de page à cette adresse. Elle a peut-être été déplacée.</p>
    <p><a href="{base}fr/">Accueil de MapleStats MCP</a> · <a href="{base}fr/tools.html">Tous les outils</a></p>
  </section>
</main>
</body>
</html>
"""
    )


def llms_txt(modules: list[ModuleDoc], counts: dict[str, int]) -> str:
    """The catalogue as Markdown for agents (llmstxt.org), English only."""
    lines = [
        "# MapleStats MCP",
        "",
        (
            "> One MCP server for Canadian open data: Statistics Canada, the Bank of Canada, "
            f"CMHC, federal agencies and {counts['catalogue_count']} open-data catalogues, in "
            "English and French. Clients see plan_query, search_tools and call_tool; every "
            "other tool is found with search_tools and run with call_tool."
        ),
        "",
        (
            f"Install (stdio, no API key): `uvx --from git+{REPO} maplestats-mcp`, or "
            "`uvx maplestats-mcp` once it is on PyPI. Setup steps for an agent, per client: "
            f"{REPO}#let-your-agent-set-it-up"
        ),
        "",
    ]
    for module in ordered(modules, "en"):
        lines.append(f"## {module.source.en} ({module.key})")
        lines.append("")
        lines.extend(f"- {t.name}: {t.summary}" for t in module.tools)
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory")
    args = parser.parse_args()
    stats = asyncio.run(build(args.out))
    print(
        f"Built {stats['pages']} pages for {stats['tools']} tools in {stats['modules']} modules -> {args.out}"
    )


if __name__ == "__main__":
    main()
