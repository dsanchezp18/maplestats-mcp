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
import inspect
import json
import math
import re
import shutil
from dataclasses import dataclass, field
from datetime import date
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

Lang = Literal["en", "fr"]
LANGS: tuple[Lang, ...] = ("en", "fr")
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
        "Portail d'information sur le marché du logement",
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


def lead(text: str, limit: int = 280) -> str:
    """The first sentence of a module description, clipped at a clause break.

    Module descriptions are written for agents and some run to thousands of
    characters; the page shows this lead and keeps the full text behind a
    disclosure.
    """
    sentence_end = r"(?<!e\.g\.)(?<!i\.e\.)(?<=[.!?])\s+(?=[A-Z«“(])| -- "
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
            f'<span class="r-sum">{esc(tool.summary)}</span></a></li>'
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
    return (
        '<div class="table-wrap"><table class="params"><thead><tr>'
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
    use_label = "Use for" if lang == "en" else "Usage"
    kw = ", ".join(tool.keywords)
    mc = ", ".join(tool.mots_cles)
    return (
        f'<details class="tool" id="t-{esc(tool.name)}" data-tool="{esc(tool.name)}">'
        f'<summary><code class="t-name">{breakable(tool.name)}</code>'
        f'<span class="t-sum">{esc(tool.summary)}</span></summary>'
        '<div class="t-body">'
        + (
            f'<p class="t-use"><b>{use_label}</b> {inline_code(tool.use_for)}</p>'
            if tool.use_for
            else ""
        )
        + params_table(tool, lang)
        + '<dl class="t-kw">'
        + f"<div><dt>Keywords</dt><dd>{esc(kw)}</dd></div>"
        + f'<div lang="fr"><dt>Mots-clés</dt><dd>{esc(mc)}</dd></div>'
        + "</dl>"
        + example_call(tool)
        + "</div></details>"
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
    plan = planner.plan(PLAN_QUESTION[lang]).model_dump(mode="json")
    matched = "matched" if lang == "en" else "termes reconnus"
    parts = []
    for topic in plan["topics"]:
        steps = "".join(
            f'<li><a href="{tool_href(s["tool"], root)}"><code>{esc(s["tool"])}</code></a>'
            f"<span>{esc(s['purpose'])}</span></li>"
            for s in topic["steps"]
        )
        caveats = "".join(f'<p class="caveat">{esc(c)}</p>' for c in topic["caveats"])
        terms = ", ".join(f"“{esc(t)}”" for t in topic["matched_terms"])
        parts.append(
            f'<div class="p-topic"><p class="p-head"><b>{esc(topic["label"])}</b>'
            f"<span>{matched} {terms}</span></p><ol>{steps}</ol>{caveats}</div>"
        )
    for place in plan["places"]:
        steps = "".join(
            f'<li><a href="{tool_href(s["tool"], root)}"><code>{esc(s["tool"])}</code></a>'
            f"<span>{esc(s['purpose'])}</span></li>"
            for s in place["steps"]
        )
        parts.append(
            f'<div class="p-topic"><p class="p-head"><b>{esc(place["place"])}</b>'
            f"<span>{esc(place['kind'])}</span></p><ol>{steps}</ol></div>"
        )
    return "".join(parts)


async def reproduce_tabs() -> str:
    capture = json.loads(CAPTURE.read_text(encoding="utf-8"))
    request = capture["request"]
    result = await reproduce.reproduce(request["name"], request["arguments"], "all")
    labels = {"r": "R", "python": "Python", "stata": "Stata", "julia": "Julia"}
    tabs, panels = [], []
    for n, script in enumerate(result.scripts):
        selected = "true" if n == 0 else "false"
        hidden = "" if n == 0 else " hidden"
        tabs.append(
            f'<button type="button" role="tab" id="rp-tab-{script.language}" aria-selected="{selected}"'
            f' aria-controls="rp-{script.language}" tabindex="{0 if n == 0 else -1}">'
            f"{labels.get(script.language, script.language)}</button>"
        )
        panels.append(
            f'<div role="tabpanel" id="rp-{script.language}" aria-labelledby="rp-tab-{script.language}"{hidden}>'
            f'<pre class="code scroll"><code>{highlight_script(script.code.rstrip(), script.language)}</code></pre></div>'
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


def captured_call(lang: Lang) -> dict[str, str]:
    capture = json.loads(CAPTURE.read_text(encoding="utf-8"))
    request = json.dumps(capture["request"], ensure_ascii=False)
    reproduce_request = json.dumps(
        {"tool_name": capture["request"]["name"], "arguments": capture["request"]["arguments"]},
        ensure_ascii=False,
    )
    captured = date.fromisoformat(capture["captured"])
    months_fr = [
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
    ]
    when = (
        f"{captured.day} {captured:%B} {captured.year}"
        if lang == "en"
        else f"{captured.day} {months_fr[captured.month - 1]} {captured.year}"
    )
    return {
        "call_request": highlight_json(request),
        "reproduce_request": highlight_json(reproduce_request),
        "call_response": response_html(capture["response"]),
        "captured_on": when,
    }


# --------------------------------------------------------------------------
# Templates.
# --------------------------------------------------------------------------

_INCLUDE = re.compile(r"\{\{>\s*([a-z0-9_-]+)\s*\}\}")
_LANG_BLOCK = re.compile(r"\{en\}(.*?)\{fr\}(.*?)\{/\}", re.DOTALL)
_VAR = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}")


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
        "local_source_count": str(counts["local_source_count"]),
        "search_top": str(index["top"]),
        "reproduce_tabs": await reproduce_tabs(),
    }
    search_results = {lang: await server_search(SEARCH_EXAMPLE[lang]) for lang in LANGS}

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
    for lang in LANGS:
        root = "" if lang == "en" else "../"
        target_dir = out if lang == "en" else out / "fr"
        target_dir.mkdir(parents=True, exist_ok=True)
        for page in pages:
            context = {
                **shared,
                **captured_call(lang),
                "lang": lang,
                "root": root,
                "page": page.name,
                "alt_href": (f"fr/{page.name}" if lang == "en" else f"../{page.name}"),
                "search_query": esc(SEARCH_EXAMPLE[lang]),
                "search_suggestions": " ".join(
                    f'<button type="button" data-q="{esc(q)}">{esc(q)}</button>'
                    for q in SEARCH_SUGGESTIONS[lang]
                ),
                "plan_request": highlight_json(
                    json.dumps({"question": PLAN_QUESTION[lang]}, ensure_ascii=False)
                ),
                "plan_panel": plan_panel(lang, root),
                "cur_tools": ' aria-current="page"' if page.name == "tools.html" else "",
                "cur_connect": ' aria-current="page"' if page.name == "connect.html" else "",
                "cur_about": ' aria-current="page"' if page.name == "about.html" else "",
                "search_results": result_items(search_results[lang], by_name, lang, root),
                "coverage_matrix": coverage_matrix(lang),
                "coverage_lists": coverage_lists(lang),
                "national_sources": national_sources(modules, lang, root),
                "atlas": atlas(modules, lang),
                "atlas_index": atlas_index(modules, lang),
                "level_filters": level_filters(modules, lang),
            }
            rendered = render(page.read_text(encoding="utf-8"), lang, context)
            (target_dir / page.name).write_text(rendered, encoding="utf-8")
    return {"tools": len(by_name), "modules": len(modules), "pages": len(pages) * len(LANGS)}


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
