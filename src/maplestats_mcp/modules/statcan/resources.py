"""Zero-parameter MCP resources for the StatCan module.

Zero-parameter is a hard requirement: any parameter makes FastMCP treat
a decorated function as a ResourceTemplate instead of a FunctionResource.
"""

from __future__ import annotations

from fastmcp.resources import resource

_ADDRESSING_DOC = """\
# Statistics Canada addressing system

StatCan identifies data three ways, all resolvable into each other:

- **productId (PID)**: 8-digit table identifier (18100004 is table
  18-10-0004). Digits 1-2 = subject code, 3-4 = product type, 5-8 =
  sequential number. StatCan prints table numbers as 18-10-0004-01; the
  trailing 2 digits are a view suffix that WDS does not accept, so the
  wds_ tools take 18100004, 18-10-0004, 18-10-0004-01 or 1810000401 and
  cut them to 8 digits.
- **vectorId**: a stable "V" + up to 10 digits, identifying one time
  series. Carried over from legacy CANSIM table numbers for backward
  compatibility.
- **coordinate**: a dot-separated string of member ids, one per
  dimension, always exactly 10 positions (unused dimensions padded
  with "0"), e.g. "2.2.0.0.0.0.0.0.0.0".

Use wds_get_series_info (with vector_id, or product_id + coordinate)
to convert between coordinate and vectorId. SDMX queries use a shorter
key — only the non-time dimensions, no trailing zero padding (see
sdmx_get_structure to find how many non-time dimensions a table has).
"""

_GOTCHAS_DOC = """\
# Known StatCan API gotchas

- **scalarFactorCode is never auto-applied.** A raw observation `value`
  is NOT multiplied by its scalarFactorCode (e.g. "thousands"). Call
  wds_get_code_sets to see the scalar codes, or multiply by the
  observation's scale_multiplier (10 ** scalar_factor_code).
- **Real-time tables.** StatCan's real-time data tables (revision
  histories such as "Historical (real-time) releases of Consumer Price
  Index statistics", 18100259) are ordinary tables in WDS. wds_search_cubes
  marks them real_time=true. MapleStats reads them through WDS only, not
  through the separate real-time viewer service.
- **12am-8:30am ET daily lock window.** WDS returns HTTP 409 for some
  methods during this window while data updates. This surfaces as a
  DataLocked error here, not a generic failure — it means "try again
  after 8:30am ET," not "something is broken."
- **SDMX large-dimension wildcarding is unreliable.** Leaving a
  dimension with more than ~30 codes wildcarded in an SDMX key returns
  a sparse, unpredictable sample, not the full set. Use
  sdmx_get_key_for_dimension to get a complete OR key instead.
- **lastNObservations cannot combine with startPeriod/endPeriod** in
  SDMX queries — StatCan returns HTTP 406 for that combination.
- **StatCan's SDMX REST endpoint returns SDMX-ML (XML), not SDMX-JSON**,
  regardless of the `format` query parameter or Accept header — this
  module parses the real XML directly.
"""


@resource("docs://statcan/addressing")
def statcan_addressing_doc() -> str:
    """Explain StatCan's productId/vectorId/coordinate addressing system. French version: docs://statcan/fr/adressage."""
    return _ADDRESSING_DOC


@resource("docs://statcan/gotchas")
def statcan_gotchas_doc() -> str:
    """List known StatCan API quirks that are easy to get wrong. French version: docs://statcan/fr/pieges."""
    return _GOTCHAS_DOC


_ADDRESSING_DOC_FR = """\
# Système d'adressage de Statistique Canada

Statistique Canada identifie ses données de trois façons, toutes
convertibles les unes dans les autres :

- **productId (PID)** : identifiant de tableau à 8 chiffres (18100004
  désigne le tableau 18-10-0004). Les chiffres 1 et 2 donnent le code
  de sujet, les chiffres 3 et 4 le type de produit, et les chiffres 5 à
  8 le numéro séquentiel. Statistique Canada imprime les numéros de
  tableau sous la forme 18-10-0004-01 ; les 2 derniers chiffres sont un
  suffixe de vue que le SDW n'accepte pas : les outils wds_ prennent
  donc 18100004, 18-10-0004, 18-10-0004-01 ou 1810000401 et les
  ramènent à 8 chiffres.
- **vectorId** : un « V » suivi d'au plus 10 chiffres, qui identifie une
  série chronologique. Il est repris des anciens numéros de tableaux
  CANSIM pour la compatibilité.
- **coordonnée** : chaîne de numéros de membres séparés par des points,
  un par dimension, toujours exactement 10 positions (les dimensions
  inutilisées étant remplies par « 0 »), par exemple
  "2.2.0.0.0.0.0.0.0.0".

Utilisez wds_get_series_info (avec vector_id, ou product_id et
coordinate) pour passer de la coordonnée au vectorId et inversement.
Les requêtes SDMX emploient une clé plus courte : seulement les
dimensions autres que le temps, sans remplissage de zéros à la fin
(voir sdmx_get_structure pour savoir combien un tableau a de dimensions
hors temps).
"""

_GOTCHAS_DOC_FR = """\
# Pièges connus des API de Statistique Canada

- **Le facteur scalaire (scalarFactorCode) n'est jamais appliqué
  automatiquement.** La `value` brute d'une observation n'est PAS
  multipliée par son scalarFactorCode (par exemple « milliers »).
  Appelez wds_get_code_sets pour voir les codes scalaires, ou
  multipliez par le scale_multiplier de l'observation
  (10 ** scalar_factor_code).
- **Tableaux en temps réel.** Les tableaux de données en temps réel de
  Statistique Canada (historiques de révisions comme « Historical
  (real-time) releases of Consumer Price Index statistics », 18100259)
  sont des tableaux ordinaires dans le SDW. wds_search_cubes les marque
  real_time=true. MapleStats les lit uniquement par le SDW, et non par
  le service distinct de visualisation en temps réel.
- **Fenêtre de verrouillage quotidienne, de minuit à 8 h 30 (heure de
  l'Est).** Le SDW renvoie HTTP 409 pour certaines méthodes pendant la
  mise à jour des données. Cela ressort ici comme une erreur
  DataLocked, et non comme un échec générique : cela veut dire
  « réessayez après 8 h 30, heure de l'Est », pas « quelque chose est
  en panne ».
- **Le caractère générique SDMX sur une grande dimension n'est pas
  fiable.** Laisser générique une dimension de plus d'une trentaine de
  codes dans une clé SDMX renvoie un échantillon partiel et
  imprévisible, pas l'ensemble complet. Utilisez
  sdmx_get_key_for_dimension pour obtenir une clé OR complète.
- **`lastNObservations` ne se combine pas avec `startPeriod` ni
  `endPeriod`** dans les requêtes SDMX : Statistique Canada répond par
  HTTP 406 pour cette combinaison.
- **Le point d'accès REST SDMX de Statistique Canada renvoie du SDMX-ML
  (XML), pas du SDMX-JSON**, quel que soit le paramètre de requête
  `format` ou l'en-tête Accept : ce module analyse directement le XML
  réel.
"""


@resource("docs://statcan/fr/adressage")
def statcan_addressing_doc_fr() -> str:
    """Explique le système d'adressage de Statistique Canada : productId,
    vectorId et coordonnée. Version française de docs://statcan/addressing."""
    return _ADDRESSING_DOC_FR


@resource("docs://statcan/fr/pieges")
def statcan_gotchas_doc_fr() -> str:
    """Pièges connus des API de Statistique Canada, faciles à manquer.
    Version française de docs://statcan/gotchas."""
    return _GOTCHAS_DOC_FR
