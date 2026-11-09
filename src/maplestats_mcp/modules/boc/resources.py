"""Zero-parameter MCP resources for the boc module.

Zero-parameter is a hard requirement: any parameter makes FastMCP treat
a decorated function as a ResourceTemplate instead of a FunctionResource.

Every series/group name below was looked up live against the real Valet
API this session (not copied from documentation prose) - series names
and codes on Valet do change over time (e.g. legacy CANSIM-style codes
alongside newer descriptive ones for the same concept), so this is
meant to be re-verified periodically rather than treated as permanent.
"""

from __future__ import annotations

from fastmcp.resources import resource

_WELL_KNOWN_SERIES_DOC = """\
# Well-known Bank of Canada Valet series and groups

Verified live against https://www.bankofcanada.ca/valet/ this session.
Use boc_search_series/boc_search_groups to find others - this is a
starting point for the series that matter most for economic analysis,
not an exhaustive list of the ~16,000 series Valet carries.

## Exchange rates

- `FXUSDCAD` - USD/CAD daily average exchange rate.
- `FXEURCAD` - EUR/CAD daily average exchange rate.
- Group `FX_RATES_DAILY` - daily average exchange rates for ~27
  currencies against CAD (published once per business day, ~16:30 ET).
- `FXMUSDCAD`, `FXAUSDCAD` - monthly and annual averages of the daily
  rate (`FXM{ccy}CAD`, `FXA{ccy}CAD` for the other currencies).
- These are indicative rates: a single daily average per currency, not
  the rate a bank or dealer transacts at.
- Legacy: `IEXE0101` is the old noon USD/CAD rate, last value
  2017-04-28. The Bank stopped its noon and closing rates then and has
  published the single daily average since 2017-05-01; `FXUSDCAD`
  replaces it (and `FX{ccy}CAD` the other `{CCY}_NOON` series). Valet
  still serves the legacy series for their history; boc_search_series
  and boc_get_series mark them `status: discontinued` with their
  `last_observation` and `successor`.
- Group `CEER` family - Canadian effective exchange rate indexes
  (trade-weighted, not a single bilateral rate).

## Key interest rates

- `V39079` - target for the overnight rate (business daily), also
  called the policy interest rate.
- `STATIC_ATABLE_V39079` - the same target for the overnight rate,
  end-of-month frequency instead of business daily.
- `V80691311` - prime rate (the base lending rate financial
  institutions set from the policy rate).

## CPI / inflation

- `V41690973` - Total CPI (the headline all-items Consumer Price
  Index, monthly).
- `V41690914` - Total CPI, seasonally adjusted.
- `STATIC_TOTALCPICHANGE` - Total CPI, percentage change year-over-
  year (unadjusted).
- `CPI_TRIM`, `CPI_MEDIAN`, `CPI_COMMON` - the Bank's three preferred
  core-inflation measures (CPI-trim, CPI-median, CPI-common).
- Group `CPI_MONTHLY` - Total CPI plus all of the above core measures
  in one group.

## Commodity prices

- `W.BCPI` - weekly Bank of Canada Commodity Price Index (BCPI),
  total.
- Groups `BCPI_WEEKLY`, `BCPI_MONTHLY`, `BCPI_ANNUAL` - the BCPI family
  (total and by commodity group - energy, metals and minerals,
  forestry, agriculture, fish) at each publication frequency.
"""

_GOTCHAS_DOC = """\
# Known Bank of Canada Valet API gotchas

- **`recent`/`recent_weeks`/`recent_months`/`recent_years` cannot be
  combined with `start_date`/`end_date`.** Valet returns HTTP 400 for
  that combination; boc_get_observations/boc_get_group_observations
  raise InvalidInput for it before making a request.
- **Multi-series observation rows are not always merged by date.**
  Requesting series that share a publication frequency (e.g. two daily
  FX rates) merges them into one row per date. Requesting series of
  genuinely different frequencies together (e.g. a daily FX rate and a
  monthly CPI series) under a `recent*` filter returns separate,
  unmerged rows - each row's `values` only has the series that
  actually has data for that date. Check each row's keys rather than
  assuming every requested series appears in every row.
- **Legacy series are still listed and served, with no end date.**
  Valet keeps discontinued series (the noon exchange rates, last value
  2017-04-28; 3-month bankers' acceptances, last 2018-12-31) beside the
  current ones, and its metadata has no status or end date. MapleStats
  marks a series `discontinued` when its newest observation is far
  older than its frequency allows (about 90 days for a daily series,
  400 for monthly, 2 years for quarterly, 4 for annual), and names a
  `successor` only for the Bank's known replacement (the noon and
  closing rates by the `FX*` daily averages).
- **Observation values are JSON strings, not numbers**, even for a
  purely numeric series - already parsed to `float | None` in this
  module's ObservationsResult, but worth knowing if comparing against
  a raw Valet response.
- **Endpoint naming is inconsistent between single-item and
  observation responses.** `/series/{name}/json` uses `seriesDetails`
  (plural, includes a `name` field); `/observations/.../json` uses
  `seriesDetail` (singular, keyed by series code, no `name` field
  inside each entry). For groups, both `/groups/{name}/json` and the
  group observations use `groupDetail` (the former was `groupDetails`
  until October 2026), but only the former has a `name` field -
  GroupObservationsResult.group.name is filled in from the caller's own
  group_name argument for this reason.
"""


_WELL_KNOWN_SERIES_DOC_FR = """\
# Séries et groupes courants de l'API Valet de la Banque du Canada

Vérifié en direct sur https://www.bankofcanada.ca/valet/ pour cette
session. Servez-vous de boc_search_series et boc_search_groups pour
trouver les autres : cette liste est un point de départ pour les séries
les plus utiles à l'analyse économique, pas un inventaire des quelque
16 000 séries de Valet. Les identifiants de séries restent identiques
en anglais et en français ; seuls les libellés changent.

## Taux de change

- `FXUSDCAD` : taux de change moyen quotidien USD/CAD.
- `FXEURCAD` : taux de change moyen quotidien EUR/CAD.
- Groupe `FX_RATES_DAILY` : taux de change moyens quotidiens d'environ
  27 devises par rapport au dollar canadien (publiés chaque jour
  ouvrable, vers 16 h 30, heure de l'Est).
- `FXMUSDCAD`, `FXAUSDCAD` : moyennes mensuelle et annuelle du taux
  quotidien (`FXM{devise}CAD`, `FXA{devise}CAD` pour les autres devises).
- Ce sont des taux indicatifs : une seule moyenne quotidienne par
  devise, pas le taux auquel une banque ou un courtier effectue une
  transaction.
- Ancienne série : `IEXE0101` est l'ancien taux à midi USD/CAD, dernière
  valeur le 28 avril 2017. La Banque a alors cessé de publier ses taux à
  midi et de clôture et publie le taux moyen quotidien depuis le 1er mai
  2017 ; `FXUSDCAD` le remplace (et `FX{devise}CAD` les autres séries
  `{DEVISE}_NOON`). Valet sert toujours les anciennes séries pour leur
  historique ; boc_search_series et boc_get_series les marquent
  `status: discontinued` avec leur `last_observation` et leur
  `successor`.
- Famille de groupes `CEER` : indices du taux de change effectif du
  dollar canadien (pondérés selon les échanges commerciaux, donc pas un
  taux bilatéral).

## Principaux taux d'intérêt

- `V39079` : cible du taux au jour le jour (quotidien, jours ouvrables),
  aussi appelée taux directeur.
- `STATIC_ATABLE_V39079` : la même cible du taux au jour le jour, mais à
  fréquence de fin de mois plutôt que quotidienne.
- `V80691311` : taux préférentiel (le taux de base que les institutions
  financières fixent à partir du taux directeur).

## IPC et inflation

- `V41690973` : IPC global (l'indice des prix à la consommation de
  l'ensemble des produits, mensuel).
- `V41690914` : IPC global, désaisonnalisé.
- `STATIC_TOTALCPICHANGE` : IPC global, variation en pourcentage sur
  douze mois (non désaisonnalisé).
- `CPI_TRIM`, `CPI_MEDIAN`, `CPI_COMMON` : les trois mesures de
  l'inflation fondamentale privilégiées par la Banque (IPC-tronq,
  IPC-méd et IPC-comm).
- Groupe `CPI_MONTHLY` : l'IPC global et toutes les mesures
  fondamentales ci-dessus dans un même groupe.

## Prix des produits de base

- `W.BCPI` : indice hebdomadaire des prix des produits de base de la
  Banque du Canada (IPPB), total.
- Groupes `BCPI_WEEKLY`, `BCPI_MONTHLY`, `BCPI_ANNUAL` : la famille de
  l'IPPB (total et par groupe de produits : énergie, métaux et
  minéraux, produits forestiers, agriculture, pêche) à chaque
  fréquence de publication.
"""

_GOTCHAS_DOC_FR = """\
# Pièges connus de l'API Valet de la Banque du Canada

- **`recent`, `recent_weeks`, `recent_months` et `recent_years` ne se
  combinent pas avec `start_date` et `end_date`.** Valet répond par une
  erreur HTTP 400 ; boc_get_observations et boc_get_group_observations
  lèvent InvalidInput avant d'envoyer la requête.
- **Les lignes d'observations de plusieurs séries ne sont pas toujours
  fusionnées par date.** Des séries de même fréquence de publication
  (deux taux de change quotidiens, par exemple) sont fusionnées en une
  ligne par date. Des séries de fréquences vraiment différentes
  (un taux de change quotidien et un IPC mensuel) demandées ensemble
  avec un filtre `recent*` donnent des lignes séparées et non fusionnées :
  le `values` de chaque ligne ne contient que la série qui a une donnée
  à cette date. Vérifiez les clés de chaque ligne au lieu de supposer
  que chaque série demandée y figure.
- **Les anciennes séries restent listées et servies, sans date de fin.**
  Valet conserve des séries abandonnées (les taux de change à midi,
  dernière valeur le 28 avril 2017 ; les acceptations bancaires à
  3 mois, dernière valeur le 31 décembre 2018) à côté des séries
  courantes, et ses métadonnées n'ont ni statut ni date de fin.
  MapleStats marque une série `discontinued` quand sa plus récente
  observation est bien plus ancienne que sa fréquence ne le permet
  (environ 90 jours pour une série quotidienne, 400 pour une série
  mensuelle, 2 ans pour une trimestrielle, 4 pour une annuelle), et ne
  nomme un `successor` que pour le remplacement connu de la Banque (les
  taux à midi et de clôture par les moyennes quotidiennes `FX*`).
- **Les valeurs d'observation sont des chaînes JSON, pas des nombres**,
  même pour une série purement numérique. L'objet ObservationsResult de ce
  module les convertit déjà en `float | None`, mais il faut le savoir si
  vous comparez avec une réponse brute de Valet.
- **Les noms de champs diffèrent entre la réponse d'une série et celle des
  observations.** `/series/{name}/json` utilise `seriesDetails` (pluriel,
  avec un champ `name`) ; `/observations/.../json` utilise `seriesDetail`
  (singulier, indexé par code de série, sans champ `name` dans chaque
  entrée). Pour les groupes, `/groups/{name}/json` et les observations
  de groupe utilisent tous deux `groupDetail` (le premier s'appelait
  `groupDetails` jusqu'en octobre 2026), mais seul le premier a un champ
  `name` : GroupObservationsResult.group.name est donc rempli à partir de
  l'argument group_name de l'appelant.
"""


@resource("docs://boc/well-known-series")
def boc_well_known_series_doc() -> str:
    """List well-known Bank of Canada Valet series/groups for FX, interest
    rates, CPI/inflation, and commodity prices. French version: docs://boc/fr/series-courantes."""
    return _WELL_KNOWN_SERIES_DOC


@resource("docs://boc/gotchas")
def boc_gotchas_doc() -> str:
    """List known Bank of Canada Valet API quirks that are easy to get wrong. French version: docs://boc/fr/pieges."""
    return _GOTCHAS_DOC


@resource("docs://boc/fr/series-courantes")
def boc_well_known_series_doc_fr() -> str:
    """Liste des séries et groupes courants de l'API Valet de la Banque du
    Canada : taux de change, taux d'intérêt, IPC et inflation, prix des
    produits de base. Version française de docs://boc/well-known-series."""
    return _WELL_KNOWN_SERIES_DOC_FR


@resource("docs://boc/fr/pieges")
def boc_gotchas_doc_fr() -> str:
    """Pièges connus de l'API Valet de la Banque du Canada, faciles à
    manquer. Version française de docs://boc/gotchas."""
    return _GOTCHAS_DOC_FR
