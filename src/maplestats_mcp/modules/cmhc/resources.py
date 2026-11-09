"""Zero-parameter MCP resources for the cmhc module.

Zero-parameter is a hard requirement: any parameter makes FastMCP treat
a decorated function as a ResourceTemplate instead of a FunctionResource.

Every category name and code below was looked up live against
https://www03.cmhc-schl.gc.ca/hmip-pimh/ this session - CMHC's category
taxonomy is not exhaustively documented here (use
cmhc_list_categories/cmhc_get_table_options for the rest), just a
starting point for the categories that matter most.
"""

from __future__ import annotations

from fastmcp.resources import resource

from maplestats_mcp.modules.cmhc.methodology import RMS_METHODOLOGY_DOC, RMS_METHODOLOGY_DOC_FR

_WELL_KNOWN_CATEGORIES_DOC = """\
# Well-known CMHC HMIP categories

Verified live against https://www03.cmhc-schl.gc.ca/hmip-pimh/ this
session, at the national (Canada) level. Pass `category_level_1`/
`category_level_2` exactly as spelled here to cmhc_get_table_options or
cmhc_get_table_data.

## Primary Rental Market (CMHC Rental Market Survey)

- category_level_1 = "Primary Rental Market"
- category_level_2 options include: "Vacancy Rate (%)", "Availability
  Rate (%)", "Average Rent ($)", "% Change of Average Rent", "Median
  Rent ($)", "Rental Universe", "Summary Statistics".
- Common column_field/row_field pairs (from cmhc_get_table_options):
  Bedroom Type=2 with Historical Time Periods=TIMESERIES (national time
  series), or Bedroom Type=2 with Provinces=21 (current cross-tab by
  province).

## New Housing Construction

- category_level_1 = "New Housing Construction"
- category_level_2 options include: "Starts (Actual)", "Starts
  (SAAR)", "Completions", "Under Construction Inventory", "Absorbed
  Units (Homeowner + Condo)", "Unabsorbed Unit Prices ($)".

## Secondary Rental Market

- category_level_1 = "Secondary Rental Market"
- Covers "Rental Condominium Apartments" and "Other Secondary Rental
  Dwellings" sub-categories.

## Seniors' Rental Housing

- category_level_1 = "Seniors' Rental Housing"
- category_level_2 options include: "Rental Housing Vacancy Rates
  (%)", "Universe, Number of Residents Living in Standard Spaces",
  "Vacancy Rate (%) and Average Rent".

## Population, Households and Housing Stock / Core Housing Need

- category_level_1 = "Population, Households and Housing Stock" or
  "Core Housing Need"
- Many category_level_2 sub-topics: household type/size, income,
  mortgages, shelter costs, structure type, period of construction, and
  more - call cmhc_list_categories for the full current list.

## Geography

- Default (no geography_type/geography_id passed) is Canada-wide
  (geography_type="Country", geography_id="1").
- Call cmhc_list_provinces for province-level ids, then pass
  geography_type="Province" with that id.
- For a city or CMA, call cmhc_list_metropolitan_areas (name="Toronto")
  and pass geography_type="MetropolitanMajorArea" ("CMA" also works)
  with that id: Toronto is "2270". The name itself is accepted as
  geography_id when exactly one area carries it.
"""

_GOTCHAS_DOC = """\
# Known CMHC quirks

- **This module covers two unrelated CMHC platforms.** `cmhc_*` tools
  query HMIP (www03.cmhc-schl.gc.ca) for live time-series/cross-tab
  data; `cmhc_dt_*` tools query the separate "Data Tables" document
  catalogue (www.cmhc-schl.gc.ca) for official per-edition Excel
  publications. They have different geography/edition id schemes
  (HMIP: small integers; Data Tables: Sitecore GUIDs like
  `{9EE6E91C-...}`) and an id from one is never valid on the other.
- **A category/geography/field combination that does not exist returns
  HTTP 500 with an ASP.NET error page**, not a clean 404 - confirmed
  live. cmhc_get_table_options and cmhc_get_table_data raise a typed
  NotFound for this rather than a generic upstream error, but there is
  no way to check validity without calling the discovery tools first
  (cmhc_list_categories, cmhc_get_table_options).
- **Data cells can hold a suppressed/not-applicable marker instead of a
  number.** `"**"` means the value was suppressed for confidentiality
  or is not statistically reliable; `"++"` means a percent-change value
  was not statistically significant (only appears on "% Change of
  Average Rent" tables); `"n/a"` is a third, plainer not-applicable
  marker. All three surface as `value: null` with the raw marker
  preserved in `flag` - check for `null` before doing arithmetic on a
  cell's value. **Separately, a bare `"-"` means no units exist in the
  universe for that category (CMHC's definition), not a suppressed
  value** - it surfaces as `value: 0`, not `null`.
- **The reliability flag legend**: `a` = Excellent, `b` = Very good,
  `c` = Good, `d` = Poor (use with caution); each table result's
  `flag_legend` explains the codes it carries, and
  docs://cmhc/rms-methodology has CMHC's thresholds and release rules. This flag is only present
  on statistically-sampled survey tables (e.g. Rental Market Survey
  vacancy rates/rents) - a census-style administrative table (e.g.
  Starts and Completions Survey, which counts every issued permit
  rather than sampling) has no flag column at all, and every cell's
  `flag` is `null`.
- **A table can support extra filter dimensions beyond `column_field`/
  `row_field`** (e.g. `season`: April/October, `dwelling_type_desc_en`:
  Row/Apartment for a Rental Market Survey table) - confirmed live
  these genuinely change the returned values, not just relabel them.
  Check `cmhc_get_table_data`'s own `available_filters` field (only
  populated once you have resolved a specific table) and pass a subset
  as `filters` on a follow-up call; an unrecognized filter key or value
  raises a clear error instead of being silently ignored.
- **`lang` genuinely changes category names, not just prose** - unlike
  most modules in this project (where `lang` only changes surrounding
  labels while codes/ids stay fixed), CMHC's `category_level_1`/
  `category_level_2` values are themselves different strings per
  language (confirmed live: "Primary Rental Market" in English is
  "Marché locatif primaire" in French, both resolving to the same
  underlying table). A value returned with `lang="en"` will not resolve
  anything when passed to a tool called with `lang="fr"`.
- **HMIP's name for a CMA is "MetropolitanMajorArea".** It answers
  geography_type="CMA" with an error, so this module translates "CMA",
  "metro", "centre" and similar names. Its metropolitan areas also
  include census agglomerations and smaller centres (225 in all,
  2026-11-03); cmhc_list_metropolitan_areas lists them. Some ids start
  with zero ("0120" is Barrie): pass them as text.
- **`cmhc_get_table_options` never passes column_field/row_field back
  to HMIP** - doing so narrows HMIP's own response to a partial slice
  around whatever was passed in, rather than the full set of valid
  options, so this module deliberately queries the bare category to get
  everything at once.
- **`cmhc_dt_*` (Data Tables): the most recent edition is always the
  first `<option>`, not one marked "selected"** - confirmed live, so
  omitting `edition_id`/`geography_id` in cmhc_dt_get_download_url
  picks the first entry from cmhc_dt_get_table's `editions`/
  `geographies` lists. Older editions' filenames are not always
  reliably guessable from the current pattern (a 2021 file omitted the
  language suffix a 2022/2023 file had) - always resolve through
  cmhc_dt_get_download_url rather than constructing a URL by hand.
  `category="canadian-housing-survey-data-tables"` currently returns no
  tables from cmhc_dt_list_tables - its tables live elsewhere on the
  site and are not yet mapped.
"""


@resource("docs://cmhc/well-known-categories")
def cmhc_well_known_categories_doc() -> str:
    """List well-known CMHC HMIP categories for rental market, housing
    starts, seniors housing, and population/household indicators. French version: docs://cmhc/fr/categories-courantes."""
    return _WELL_KNOWN_CATEGORIES_DOC


@resource("docs://cmhc/gotchas")
def cmhc_gotchas_doc() -> str:
    """List known CMHC HMIP quirks that are easy to get wrong. French version: docs://cmhc/fr/pieges."""
    return _GOTCHAS_DOC


_WELL_KNOWN_CATEGORIES_DOC_FR = """\
# Catégories courantes du HMIP de la SCHL

Vérifié en direct sur https://www03.cmhc-schl.gc.ca/hmip-pimh/ pour
cette session, à l'échelle nationale (Canada). Les noms de catégories
changent selon la langue : utilisez `lang="fr"` dans tous les appels
quand vous passez un libellé français (un libellé anglais ne donne rien
avec `lang="fr"`, et inversement). Passez `category_level_1` et
`category_level_2` exactement comme cmhc_list_categories(lang="fr") les
renvoie à cmhc_get_table_options ou à cmhc_get_table_data. Les libellés
français ci-dessous ont été relevés en direct ; les libellés anglais de
docs://cmhc/well-known-categories sont donnés entre parenthèses pour
faire le lien.

## Marché locatif primaire (Enquête sur les logements locatifs de la SCHL)

- category_level_1 = "Marché locatif primaire" (anglais : "Primary
  Rental Market")
- Les sous-catégories (category_level_2) comprennent le taux
  d'inoccupation (%), le taux de disponibilité (%), le loyer moyen ($),
  la variation en % du loyer moyen, le loyer médian ($), l'univers
  locatif et les statistiques sommaires. Vérifiez leur orthographe
  exacte avec cmhc_get_table_options.
- Paires courantes de column_field et row_field (selon
  cmhc_get_table_options) : type de logement (nombre de chambres) en
  colonne avec les périodes historiques en ligne (série nationale), ou
  le type de logement en colonne avec les provinces en ligne (tableau
  croisé courant par province).

## Construction de logements neufs

- category_level_1 = "Marché du neuf" (anglais : "New Housing
  Construction")
- category_level_2 comprend "Mises en chantier d’habitations (données
  réelles)", "Mises en chantier d’habitations (DDA)", "Achèvements",
  "Stocks de logements en construction", "Durée de la construction (en
  mois)" et "Logements écoulés (pour propriétaires-absolues ou en
  copropriété)", entre autres.

## Marché locatif secondaire

- category_level_1 = "Marché locatif secondaire" (anglais :
  "Secondary Rental Market")
- Couvre les "Appartements en copropriété donnés en location" et les
  "Autres types de logements offerts sur le marché locatif secondaire".

## Logements locatifs pour personnes âgées

- category_level_1 = "Logements locatifs pour personnes âgées"
  (anglais : "Seniors' Rental Housing")
- Sous-catégories : "Taux d'inoccupation (%)", "Univers des places
  standards", "Proportion (%) de places standards" et des tableaux sur
  les studios et les chambres individuelles, entre autres.

## Population, ménages et parc de logements / Besoins impérieux

- category_level_1 = "Population, ménages et parc de logement"
  (anglais : "Population, Households and Housing Stock") ou "Besoins
  impérieux en matière de logement" (anglais : "Core Housing Need")
- De nombreuses sous-catégories : type et taille des ménages, revenu,
  prêts hypothécaires, frais de logement, type de structure, période de
  construction et plus. Appelez cmhc_list_categories pour la liste
  complète et à jour.

## Géographie

- Par défaut (sans geography_type ni geography_id), la requête porte
  sur l'ensemble du Canada (geography_type="Country",
  geography_id="1").
- Appelez cmhc_list_provinces pour obtenir les identifiants des
  provinces, puis passez geography_type="Province" avec cet
  identifiant.
- Pour une ville ou une RMR, appelez cmhc_list_metropolitan_areas
  (name="Montréal") et passez geography_type="MetropolitanMajorArea"
  ("RMR" fonctionne aussi) avec cet identifiant : Montréal est "1060".
  Le nom lui-même est accepté comme geography_id quand une seule zone
  le porte.
"""

_GOTCHAS_DOC_FR = """\
# Particularités connues de la SCHL

- **Ce module couvre deux plateformes de la SCHL sans rapport entre
  elles.** Les outils `cmhc_*` interrogent le HMIP
  (www03.cmhc-schl.gc.ca) pour des séries chronologiques et des
  tableaux croisés en direct ; les outils `cmhc_dt_*` interrogent le
  catalogue distinct de « tableaux de données » (www.cmhc-schl.gc.ca)
  pour les publications Excel officielles de chaque édition. Les deux
  n'ont pas les mêmes identifiants de géographie et d'édition (HMIP :
  petits entiers ; tableaux de données : GUID Sitecore comme
  `{9EE6E91C-...}`), et un identifiant de l'une n'est jamais valide
  dans l'autre.
- **Une combinaison de catégorie, de géographie et de champs qui
  n'existe pas renvoie une erreur HTTP 500 avec une page d'erreur
  ASP.NET**, et non un 404 net (confirmé en direct).
  cmhc_get_table_options et cmhc_get_table_data lèvent dans ce cas une
  NotFound typée plutôt qu'une erreur générique du service, mais on ne
  peut vérifier la validité qu'en appelant d'abord les outils de
  découverte (cmhc_list_categories, cmhc_get_table_options).
- **Une cellule peut contenir un marqueur de suppression ou de
  non-applicabilité au lieu d'un nombre.** `"**"` signifie que la
  valeur est supprimée pour des raisons de confidentialité ou qu'elle
  n'est pas statistiquement fiable ; `"++"` signifie qu'une variation en
  pourcentage n'est pas statistiquement significative (uniquement dans
  les tableaux de variation en % du loyer moyen) ; `"n/a"` est un
  troisième marqueur, plus simple, de non-applicabilité. Les trois
  ressortent en `value: null`, le marqueur brut étant conservé dans
  `flag` : vérifiez si `value` est nul avant tout calcul. **À part, un
  simple `"-"` signifie qu'aucun logement n'existe dans l'univers pour
  cette catégorie (définition de la SCHL), pas une valeur supprimée** :
  il ressort en `value: 0`, pas en `null`.
- **Légende de l'indicateur de fiabilité** : `a` = excellente, `b` =
  très bonne, `c` = bonne, `d` = faible (à utiliser avec prudence) ; le
  `flag_legend` de chaque résultat explique les codes qu'il contient, et
  docs://cmhc/fr/methodologie-ell donne les seuils et les règles de
  diffusion de la SCHL.
  Cet indicateur n'existe que dans les tableaux d'enquête par sondage
  (par exemple les taux d'inoccupation et les loyers de l'Enquête sur
  les logements locatifs) ; un tableau de type recensement ou
  administratif (l'Enquête sur les mises en chantier et les
  achèvements, qui compte chaque permis délivré au lieu de sonder) n'a
  aucune colonne d'indicateur, et le `flag` de chaque cellule est
  `null`.
- **Un tableau peut accepter des dimensions de filtre supplémentaires**
  en plus de `column_field` et `row_field` (par exemple `season` :
  avril ou octobre, ou `dwelling_type_desc_en` : en rangée ou
  appartement pour un tableau de l'Enquête sur les logements locatifs) ;
  il est confirmé en direct qu'elles changent réellement les valeurs
  retournées, et pas seulement les libellés. Consultez le champ
  `available_filters` de cmhc_get_table_data (rempli seulement une fois
  un tableau précis résolu) et passez-en un sous-ensemble dans
  `filters` à l'appel suivant ; une clé ou une valeur de filtre
  inconnue lève une erreur claire au lieu d'être ignorée en silence.
- **`lang` change vraiment les noms de catégories, pas seulement le
  texte autour.** Contrairement à la plupart des modules du projet (où
  `lang` ne change que les libellés environnants, les codes et
  identifiants restant fixes), les valeurs de `category_level_1` et de
  `category_level_2` de la SCHL sont des chaînes différentes selon la
  langue (confirmé en direct : « Primary Rental Market » en anglais est
  « Marché locatif primaire » en français, les deux menant au même
  tableau). Une valeur retournée avec `lang="en"` ne donne rien quand on
  la passe à un outil appelé avec `lang="fr"`.
- **Le PIMH nomme une RMR « MetropolitanMajorArea ».** Il répond par
  une erreur à geography_type="CMA" ; ce module traduit donc « CMA »,
  « RMR », « ville », « centre » et des noms semblables. Ses zones
  métropolitaines comprennent aussi des agglomérations de recensement
  et de plus petits centres (225 en tout, 2026-11-03) ;
  cmhc_list_metropolitan_areas les énumère. Certains identifiants
  commencent par zéro (« 0120 » est Barrie) : passez-les en texte.
- **cmhc_get_table_options ne renvoie jamais column_field ni row_field
  au HMIP.** Le faire réduit la réponse du HMIP à une tranche partielle
  autour de ce qui a été passé, au lieu de l'ensemble des options
  valides ; ce module interroge donc volontairement la catégorie seule
  pour tout obtenir d'un coup.
- **`cmhc_dt_*` (tableaux de données) : l'édition la plus récente est
  toujours la première `<option>`, et non celle marquée « selected »**
  (confirmé en direct). Si edition_id ou geography_id est omis,
  cmhc_dt_get_download_url prend donc la première entrée des listes
  `editions` et `geographies` de cmhc_dt_get_table. Les noms de fichiers
  des éditions plus anciennes ne se devinent pas toujours à partir du
  modèle actuel (un fichier de 2021 omettait le suffixe de langue
  qu'avaient ceux de 2022 et 2023) : passez toujours par
  cmhc_dt_get_download_url plutôt que de construire l'URL à la main.
  `category="canadian-housing-survey-data-tables"` ne renvoie
  actuellement aucun tableau avec cmhc_dt_list_tables : ces tableaux se
  trouvent ailleurs sur le site et ne sont pas encore cartographiés.
"""


@resource("docs://cmhc/fr/categories-courantes")
def cmhc_well_known_categories_doc_fr() -> str:
    """Catégories courantes du HMIP de la SCHL : marché locatif, mises en
    chantier, logements pour personnes âgées, population et ménages.
    Version française de docs://cmhc/well-known-categories."""
    return _WELL_KNOWN_CATEGORIES_DOC_FR


@resource("docs://cmhc/fr/pieges")
def cmhc_gotchas_doc_fr() -> str:
    """Particularités connues du HMIP de la SCHL, faciles à manquer.
    Version française de docs://cmhc/gotchas."""
    return _GOTCHAS_DOC_FR


@resource("docs://cmhc/rms-methodology")
def cmhc_rms_methodology_doc() -> str:
    """CMHC Rental Market Survey methodology: October timing, scope (private
    structures of 3+ units, secondary rental market), vacancy and availability
    definitions, a/b/c/d reliability codes, suppression and release rules.
    French version: docs://cmhc/fr/methodologie-ell."""
    return RMS_METHODOLOGY_DOC


@resource("docs://cmhc/fr/methodologie-ell")
def cmhc_rms_methodology_doc_fr() -> str:
    """Méthodologie de l'Enquête sur les logements locatifs de la SCHL :
    octobre, champ, définitions de l'inoccupation et de la disponibilité,
    codes de fiabilité, suppression et diffusion.
    Version française de docs://cmhc/rms-methodology."""
    return RMS_METHODOLOGY_DOC_FR
