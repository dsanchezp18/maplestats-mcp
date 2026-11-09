"""CMHC Rental Market Survey methodology, served as docs://cmhc/rms-methodology.

Written from CMHC's own methodology pages, read on 2026-11-09 (three
requests): "Methodology for Rental Market Survey" (published 2024-01-29) and
"Methodology for the Secondary Rental Market Survey" (published 2022-04-05).
The reliability tables are copied from those pages, not derived. Two facts
worth knowing before editing: the RMS page says the availability rate was
collected only from 2005 to 2017 (discontinued in 2018), and that the April
survey was last run in 2015.

The text lives here rather than in resources.py so that file stays a list of
resources; resources.py imports it.
"""

from __future__ import annotations

RMS_METHODOLOGY_URL = (
    "https://www.cmhc-schl.gc.ca/professionals/housing-markets-data-and-research/"
    "housing-research/surveys/methods/methodology-rental-market-survey"
)
SRMS_METHODOLOGY_URL = (
    "https://www.cmhc-schl.gc.ca/professionals/housing-markets-data-and-research/"
    "housing-research/surveys/methods/methodology-secondary-rental-market-survey"
)

RMS_METHODOLOGY_DOC = f"""\
# CMHC Rental Market Survey: methodology

Sources (CMHC, read 2026-11-09):
- Methodology for Rental Market Survey, published 2024-01-29:
  {RMS_METHODOLOGY_URL}
- Methodology for the Secondary Rental Market Survey, published 2022-04-05:
  {SRMS_METHODOLOGY_URL}

## When

- The Rental Market Survey (RMS) is annual and is conducted in the first two
  weeks of October; results reflect market conditions at that time. A table
  labelled 2025 is the October 2025 survey.
- An April survey was also run in some years; it was conducted for the last
  time in 2015 (that is the `season` filter some HMIP tables still offer).

## Scope (the primary rental market)

- A sample survey of all urban areas with populations of 10,000 or more.
- It targets only privately initiated structures with at least 3 rental
  units that have been on the market for at least 3 months: the primary, or
  purpose-built, rental market.
- Social and affordable housing structures or units are not in the frame.
  Owner-occupied units are not counted in a structure's rental unit count.
- Apartment structure: 3 or more rental units, at least one not ground
  oriented. Row (townhouse) structure: 3 or more rental units, all ground
  oriented, side by side with common walls. The universe (unit counts) is
  row and apartment structures of 3 units and over.
- Rents, vacancy, turnover and (until 2017) availability are collected for
  every sampled structure, by telephone interview or site visit, from the
  owner, manager or building superintendent.

## Definitions

- **Vacant**: at the time of the survey the unit is physically unoccupied
  and available for immediate rental (no new lease signed, and not under
  major renovation). The vacancy rate is the share of units that are vacant.
- **Available**: the existing tenant has given or received notice to move
  and no new tenant has signed a lease, or the unit is vacant. Availability
  is therefore always at least vacancy. CMHC collected the availability rate
  only from 2005 to 2017; the series was discontinued in 2018, so there is
  no availability rate for 2018 onward.
- **Turnover**: the unit was occupied by a new tenant who moved in during
  the past 12 months (a unit can turn over more than once).
- **Rent**: what tenants actually pay, with no adjustment for whether heat,
  hydro, parking or hot water is included. For vacant and available units
  it is the owner's asking rent.
- **Average rent**: weighted average over all units, vacant or occupied.
  CMHC also publishes averages for occupied, vacant ("asking"), turnover
  and non-turnover units.
- **Percentage change of average rent**: a same-sample measure, computed on
  structures common to the survey sample in both the previous and current
  year, so it removes the effect of new structures, conversions and sample
  rotation (renovations and unit turnover can still move it). It is
  published only when statistically different from zero. The gap between
  two years' published average rents is not the same measure.

## Reliability codes

CMHC prints a letter beside each estimate (HMIP's CSV has it in the cell's
companion column; this server returns it as the cell's `flag`):

- `a` Excellent, `b` Very good, `c` Good, `d` Poor (use with caution).
- `**` Data suppressed: too unreliable to publish, or confidential (see the
  release rules below). The value is not published.

For averages and totals (average rent) the letter comes from the
coefficient of variation (CV = standard error / estimate, in percent):

| Code | CV (%) |
|---|---|
| a Excellent | over 0, up to 2.5 |
| b Very good | over 2.5, up to 5 |
| c Good | over 5, up to 7.5 |
| d Poor (use with caution) | over 7.5, up to 10 |
| ** suppressed | over 10 |

For proportions (vacancy and availability rates) CMHC uses the CV, the
sampling fraction and the size of the universe. When the rate is 0 and the
sampling fraction is under 100 %, the code depends on the number of
structures in the universe and the sampling fraction (%):

| Structures | (0, 20] | (20, 40] | (40, 60] | (60, 80] | (80, 100) |
|---|---|---|---|---|---|
| 3-10 | ** | ** | ** | ** | ** |
| 11-20 | ** | Poor | Poor | Poor | Good |
| 21-40 | ** | Poor | Poor | Good | Very good |
| 41-80 | ** | Poor | Good | Good | Very good |
| 81+ | ** | Good | Good | Very good | Very good |

Otherwise the code depends on the CV (rows, %) and the rate itself
(columns, %):

| CV | 0 | (0, 5] | (5, 10] | (10, 16.5] | (16.5, 33.3] | (33.3, 50] | 50+ |
|---|---|---|---|---|---|---|---|
| (0, 0.75) | Exc | Exc | Exc | Exc | Exc | VG | VG |
| (0.75, 1.5) | Exc | Exc | Exc | Exc | Exc | Poor | ** |
| (1.5, 3) | Exc | Exc | Exc | VG | Good | ** | ** |
| (3, 6) | Exc | Exc | VG | Good | Poor | ** | ** |
| (6, 10) | Exc | Exc | VG | Good | ** | ** | ** |
| (10, 15) | Exc | Exc | Good | Poor | ** | ** | ** |
| (15, 30) | Exc | Exc | Poor | ** | ** | ** | ** |
| (30, 100) | Exc | Exc | ** | ** | ** | ** | ** |

(Exc = Excellent, VG = Very good.)

## Release and suppression rules

- Unit counts (the rental universe) are always released: they are counts,
  not estimates.
- Every other estimate (vacancy rates, average rents, and so on) is released
  only if it is based on 4 or more responding entities (confidentiality).
- Averages and totals are published only if their CV is 10 % or less.
- A suppressed cell is not zero: report it as not published.

## Other symbols

- `++`: the change in rent is not statistically significant (not different
  from zero). Only in "% Change of Average Rent" tables. This server returns
  `value: null` with `flag: "++"`.
- `-`: no units exist in the universe for this category. This server returns
  `value: 0`.
- `n/a`: not applicable or not available; returned as `value: null`.

## Secondary rental market

The Secondary Rental Market Survey covers rented units the RMS does not:
rented single-detached and semi-detached houses, freehold row homes, duplex
apartments, accessory apartments, rented condominiums, and one or two
apartments in a commercial or other structure. Since 2017 collection is
limited to the Condo Apartment Survey (condominium apartment vacancy and
rent), conducted in September by telephone (condo boards and property
managers, with site visits when no contact is made) in 17 CMAs: Halifax,
Montreal, Quebec, Ottawa, Gatineau, Toronto, Hamilton,
Kitchener-Cambridge-Waterloo, London, Winnipeg, Regina, Saskatoon, Calgary,
Edmonton, Kelowna, Vancouver and Victoria. The Household Rent Survey and the
Condominium Apartment Rent Survey were discontinued in 2017. The same
reliability codes and release rules (4 or more responding entities, CV cut
off at 10 % for averages) apply.
"""

RMS_METHODOLOGY_DOC_FR = f"""\
# Enquête sur les logements locatifs de la SCHL : méthodologie

Sources (SCHL, pages en anglais lues le 2026-11-09) :
- Methodology for Rental Market Survey, publiée le 2024-01-29 :
  {RMS_METHODOLOGY_URL}
- Methodology for the Secondary Rental Market Survey, publiée le 2022-04-05 :
  {SRMS_METHODOLOGY_URL}

## Quand

- L'Enquête sur les logements locatifs (ELL) est annuelle et se déroule
  pendant les deux premières semaines d'octobre ; les résultats reflètent le
  marché à ce moment. Un tableau daté 2025 correspond à l'enquête d'octobre
  2025.
- Une enquête d'avril a aussi été menée certaines années ; la dernière date
  de 2015 (c'est le filtre `season` que certains tableaux du PIMH proposent
  encore).

## Champ (le marché locatif primaire)

- Une enquête par sondage dans toutes les régions urbaines de 10 000
  habitants ou plus.
- Elle vise uniquement les immeubles d'initiative privée d'au moins 3
  logements locatifs, sur le marché depuis au moins 3 mois : le marché
  locatif primaire, c'est-à-dire les logements construits pour la location.
- Les immeubles et logements sociaux ou abordables sont exclus de la base de
  sondage. Les logements occupés par leur propriétaire ne sont pas comptés.
- Immeuble d'appartements : 3 logements locatifs ou plus, dont au moins un
  sans accès direct au niveau du sol. Immeuble en rangée : 3 logements
  locatifs ou plus, tous au niveau du sol, côte à côte avec des murs
  mitoyens. L'univers (nombre de logements) regroupe les immeubles en rangée
  et d'appartements de 3 logements et plus.
- Les loyers, l'inoccupation, le roulement et (jusqu'en 2017) la
  disponibilité sont recueillis pour chaque immeuble de l'échantillon, par
  entrevue téléphonique ou visite, auprès du propriétaire, du gestionnaire ou
  du concierge.

## Définitions

- **Logement vacant (inoccupé)** : au moment de l'enquête, le logement est
  physiquement inoccupé et prêt à être loué immédiatement (aucun nouveau bail
  signé, pas de rénovation majeure en cours). Le taux d'inoccupation est la
  part des logements vacants.
- **Logement disponible** : le locataire actuel a donné ou reçu un avis de
  départ et aucun nouveau locataire n'a signé de bail, ou le logement est
  vacant. La disponibilité est donc toujours au moins égale à
  l'inoccupation. La SCHL n'a recueilli le taux de disponibilité que de 2005
  à 2017 ; la série a cessé en 2018 et il n'y a pas de taux de disponibilité
  pour 2018 et après.
- **Roulement** : un nouveau locataire a emménagé dans le logement au cours
  des 12 derniers mois (un logement peut changer de locataire plus d'une
  fois).
- **Loyer** : ce que paient réellement les locataires, sans ajustement selon
  que le chauffage, l'électricité, le stationnement ou l'eau chaude sont
  compris. Pour un logement vacant ou disponible, c'est le loyer demandé par
  le propriétaire.
- **Loyer moyen** : moyenne pondérée de tous les logements, vacants ou
  occupés. La SCHL publie aussi des moyennes pour les logements occupés,
  vacants (loyer « demandé »), ayant changé de locataire ou non.
- **Variation en pourcentage du loyer moyen** : mesure à échantillon
  constant, calculée sur les immeubles présents dans l'échantillon l'année
  précédente et l'année courante ; elle élimine l'effet des immeubles
  neufs, des conversions et de la rotation de l'échantillon (les rénovations
  et le roulement peuvent encore la faire varier). Elle n'est publiée que si
  elle diffère statistiquement de zéro. L'écart entre les loyers moyens
  publiés de deux années n'est pas la même mesure.

## Codes de fiabilité

La SCHL inscrit une lettre à côté de chaque estimation (dans la colonne
associée du CSV du PIMH ; ce serveur la renvoie dans le `flag` de la
cellule) :

- `a` excellente, `b` très bonne, `c` bonne, `d` faible (à utiliser avec
  prudence).
- `**` donnée supprimée : trop peu fiable pour être publiée, ou
  confidentielle (voir les règles de diffusion ci-dessous). La valeur n'est
  pas publiée.

Pour les moyennes et les totaux (loyer moyen), la lettre dépend du
coefficient de variation (CV = erreur type / estimation, en pourcentage) :

| Code | CV (%) |
|---|---|
| a excellente | plus de 0, jusqu'à 2,5 |
| b très bonne | plus de 2,5, jusqu'à 5 |
| c bonne | plus de 5, jusqu'à 7,5 |
| d faible (avec prudence) | plus de 7,5, jusqu'à 10 |
| ** supprimée | plus de 10 |

Pour les proportions (taux d'inoccupation et de disponibilité), la SCHL
utilise le CV, la fraction de sondage et la taille de l'univers. Quand le
taux vaut 0 et que la fraction de sondage est inférieure à 100 %, le code
dépend du nombre d'immeubles de l'univers et de la fraction de sondage (%) :

| Immeubles | (0, 20] | (20, 40] | (40, 60] | (60, 80] | (80, 100) |
|---|---|---|---|---|---|
| 3-10 | ** | ** | ** | ** | ** |
| 11-20 | ** | Faible | Faible | Faible | Bonne |
| 21-40 | ** | Faible | Faible | Bonne | Très bonne |
| 41-80 | ** | Faible | Bonne | Bonne | Très bonne |
| 81+ | ** | Bonne | Bonne | Très bonne | Très bonne |

Sinon, le code dépend du CV (lignes, %) et du taux lui-même (colonnes, %) :

| CV | 0 | (0, 5] | (5, 10] | (10, 16,5] | (16,5, 33,3] | (33,3, 50] | 50+ |
|---|---|---|---|---|---|---|---|
| (0, 0,75) | Exc | Exc | Exc | Exc | Exc | TB | TB |
| (0,75, 1,5) | Exc | Exc | Exc | Exc | Exc | Faible | ** |
| (1,5, 3) | Exc | Exc | Exc | TB | Bonne | ** | ** |
| (3, 6) | Exc | Exc | TB | Bonne | Faible | ** | ** |
| (6, 10) | Exc | Exc | TB | Bonne | ** | ** | ** |
| (10, 15) | Exc | Exc | Bonne | Faible | ** | ** | ** |
| (15, 30) | Exc | Exc | Faible | ** | ** | ** | ** |
| (30, 100) | Exc | Exc | ** | ** | ** | ** | ** |

(Exc = excellente, TB = très bonne.)

## Règles de diffusion et de suppression

- Le nombre de logements (l'univers locatif) est toujours diffusé : ce sont
  des dénombrements, pas des estimations.
- Toute autre estimation (taux d'inoccupation, loyers moyens, etc.) n'est
  diffusée que si elle repose sur au moins 4 entités répondantes
  (confidentialité).
- Les moyennes et les totaux ne sont publiés que si leur CV est de 10 % ou
  moins.
- Une cellule supprimée ne vaut pas zéro : dites qu'elle n'est pas publiée.

## Autres symboles

- `++` : la variation du loyer n'est pas statistiquement significative (pas
  différente de zéro). Seulement dans les tableaux de variation en % du
  loyer moyen. Ce serveur renvoie `value: null` avec `flag: "++"`.
- `-` : aucun logement n'existe dans l'univers pour cette catégorie. Ce
  serveur renvoie `value: 0`.
- `n/a` : sans objet ou non disponible ; renvoyé comme `value: null`.

## Marché locatif secondaire

L'Enquête sur le marché locatif secondaire porte sur les logements loués que
l'ELL ne couvre pas : maisons individuelles et jumelées louées, maisons en
rangée en propriété absolue, appartements de duplex, appartements
accessoires, copropriétés louées, et un ou deux appartements dans un
immeuble commercial ou autre. Depuis 2017, la collecte se limite à l'Enquête
sur les appartements en copropriété (inoccupation et loyers), menée en
septembre par téléphone (conseils de copropriété et gestionnaires, avec
visites si aucun contact n'est établi) dans 17 RMR : Halifax, Montréal,
Québec, Ottawa, Gatineau, Toronto, Hamilton, Kitchener-Cambridge-Waterloo,
London, Winnipeg, Regina, Saskatoon, Calgary, Edmonton, Kelowna, Vancouver
et Victoria. L'Enquête sur les loyers des ménages et l'Enquête sur les
loyers des appartements en copropriété ont cessé en 2017. Les mêmes codes de
fiabilité et règles de diffusion (au moins 4 entités répondantes, CV limité
à 10 % pour les moyennes) s'appliquent.
"""

# What each `flag` a returned cell can carry means, for TableDataResult.flag_legend.
# A "-" cell (no units in the universe) parses to value 0 with no flag of its own.
FLAG_MEANINGS: dict[str, tuple[str, str]] = {
    "a": ("Excellent reliability", "fiabilité excellente"),
    "b": ("Very good reliability", "fiabilité très bonne"),
    "c": ("Good reliability", "fiabilité bonne"),
    "d": ("Poor reliability: use with caution", "fiabilité faible : à utiliser avec prudence"),
    "**": (
        (
            "Suppressed: too unreliable to publish, or based on fewer than 4 responding "
            "entities; not zero, report it as not published"
        ),
        (
            "Supprimée : trop peu fiable, ou fondée sur moins de 4 entités répondantes ; "
            "ne vaut pas zéro, dites qu'elle n'est pas publiée"
        ),
    ),
    "++": (
        "Change in rent not statistically different from zero",
        "Variation du loyer non statistiquement différente de zéro",
    ),
    "n/a": ("Not applicable or not available", "Sans objet ou non disponible"),
}
