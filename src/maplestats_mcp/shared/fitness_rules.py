"""Fitness-for-use rules: when and how a number from a source can be used.

Each rule is a short caution, in English and French, attached to tools (by
name prefix) and to StatCan tables (by 8-digit product id). shared/fitness.py
indexes them; notes_for() returns the ones a tool call matches.

Every rule rests on the official pages in its `sources`, read on 2026-10-27,
and every product id was checked live that day with WDS getCubeMetadata (title
and footnotes; tests/test_fitness.py pins the list). `checked` says what each
source confirmed, so a later edit can re-read the same thing. A caution that
could not be confirmed from an official page is left out rather than written
from memory: the point of these notes is that an assistant can trust them.

French text is written with plain spaces; notes_for() adds the no-break
spaces French punctuation takes (i18n.french_text).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FitnessRule:
    key: str
    title_en: str
    title_fr: str
    note_en: str
    note_fr: str
    sources: tuple[str, ...]
    checked: str
    tool_prefixes: tuple[str, ...] = ()
    # Tool prefixes the rule does not reach although a broader prefix does
    # ("statcan_census_profile_archive_" under "statcan_census_profile_").
    exclude_prefixes: tuple[str, ...] = ()
    product_ids: tuple[int, ...] = ()


_LFS_TABLES = (14100287, 14100355, 14100288)
_SEPH_TABLES = (14100223, 14100220, 14100201, 14100222)
_LOW_INCOME_TABLES = (11100135, 11100136, 11100066, 11100104, 11100090, 11100093, 11100232)

RULES: tuple[FitnessRule, ...] = (
    FitnessRule(
        key="lfs-vs-seph",
        title_en="Labour Force Survey vs Survey of Employment, Payrolls and Hours",
        title_fr=(
            "Enquête sur la population active et Enquête sur l'emploi, la rémunération "
            "et les heures de travail"
        ),
        note_en=(
            "LFS and SEPH employment are different measures: do not compare their levels. "
            "The LFS is a household survey that counts employed people (a person with two "
            "jobs counts once), including the self-employed and agriculture; SEPH counts "
            "payroll jobs, so it leaves out the self-employed and agriculture, fishing and "
            "trapping, private household services and religious organisations. LFS "
            "estimates carry sampling error; preliminary SEPH estimates are revised. Compare "
            "trends over several months, not one month's change. For earnings in a detailed "
            "industry, such as provincial and territorial public administration (NAICS 912), "
            "use SEPH (14-10-0203 monthly, 14-10-0204 annual) and say why: the LFS wage "
            "table 14-10-0064 stops at broad sectors ('Public administration' as a whole)."
        ),
        note_fr=(
            "L'emploi de l'EPA et celui de l'EERH sont deux mesures différentes : n'en "
            "comparez pas les niveaux. L'EPA, enquête auprès des ménages, compte des "
            "personnes occupées (une personne qui a deux emplois compte une fois), y compris "
            "les travailleurs autonomes et l'agriculture; l'EERH compte des emplois "
            "rémunérés, sans les travailleurs autonomes ni l'agriculture, la pêche et le "
            "piégeage, les services aux ménages privés et les organisations religieuses. "
            "Les estimations de l'EPA comportent une erreur d'échantillonnage; les "
            "estimations provisoires de l'EERH sont révisées. Comparez les tendances sur "
            "plusieurs mois, pas la variation d'un seul mois. Pour la rémunération d'une "
            "industrie détaillée, comme les administrations publiques provinciales et "
            "territoriales (SCIAN 912), prenez l'EERH (14-10-0203 mensuel, 14-10-0204 "
            "annuel) et dites pourquoi : le tableau des salaires de l'EPA 14-10-0064 "
            "s'arrête aux grands secteurs (« Administrations publiques » dans leur ensemble)."
        ),
        sources=(
            "https://www150.statcan.gc.ca/n1/pub/75-005-m/75-005-m2026001-eng.htm",
            "https://www150.statcan.gc.ca/n1/pub/71-543-g/71-543-g2025001-eng.htm#a8",
            "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410020101",
        ),
        checked=(
            "75-005-M2026001 (30 July 2026): LFS counts people, SEPH payroll jobs; LFS has "
            "sampling error, SEPH preliminary data are revised; examine trends across "
            "several months; levels cannot be fully reconciled. LFS Guide 2025 section 8: "
            "multiple jobholders counted once in LFS, per job in SEPH; LFS includes "
            "self-employed, unpaid family workers, agriculture. SEPH table footnotes "
            "(14-10-0201, -0220, -0222, -0223): industrial aggregate excludes agriculture, "
            "fishing and trapping, private household services, religious organisations and "
            "military personnel."
        ),
        product_ids=_LFS_TABLES + _SEPH_TABLES + (14100064, 14100203, 14100204),
    ),
    FitnessRule(
        key="lfs-sampling-variability",
        title_en="Labour Force Survey: sampling variability and revisions",
        title_fr="Enquête sur la population active : variabilité d'échantillonnage et révisions",
        note_en=(
            "LFS figures are survey estimates. Table 14-10-0287 publishes the standard error "
            "of each estimate, of its month-to-month change and of its year-over-year change "
            "(the Statistics dimension). A change is significant at the 5% level only when "
            "the change plus or minus two standard errors excludes zero, which many small "
            "monthly moves do not. Statistics Canada releases estimates with a CV up to "
            "16.5% freely, with a warning up to 33.3%, and not above; estimates under a "
            "minimum size (1,500 for Canada) are suppressed. Seasonally adjusted series are "
            "revised once a year."
        ),
        note_fr=(
            "Les chiffres de l'EPA sont des estimations d'enquête. Le tableau 14-10-0287 "
            "publie l'erreur type de chaque estimation, de sa variation d'un mois à l'autre "
            "et de sa variation d'une année à l'autre (dimension Statistiques). Une variation "
            "n'est significative au seuil de 5 % que si l'intervalle de plus ou moins deux "
            "erreurs types autour d'elle exclut zéro, ce qui n'est pas le cas de bien des "
            "petites variations mensuelles. Statistique Canada diffuse sans réserve les "
            "estimations dont le CV ne dépasse pas 16,5 %, avec une mise en garde jusqu'à "
            "33,3 %, et pas au-delà; les estimations sous un seuil minimal (1\u00a0500 pour le "
            "Canada) sont supprimées. Les séries désaisonnalisées sont révisées une fois "
            "par année."
        ),
        sources=(
            "https://www150.statcan.gc.ca/n1/pub/71-543-g/71-543-g2025001-eng.htm#a7",
            "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410028701",
        ),
        checked=(
            "LFS Guide 2025 section 7: 95% interval is two standard errors, a change is "
            "significant at 5% when its interval excludes zero; CV categories 16.5% and "
            "33.3%; Table 7.4 minimum size for release, Canada 1.5 thousand. WDS metadata "
            "for 14-10-0287: Statistics dimension has 'Standard error of estimate', '... of "
            "month-to-month change', '... of year-over-year change'. Footnote on "
            "14-10-0287, -0355, -0288: seasonally adjusted series revised on an annual "
            "basis."
        ),
        product_ids=_LFS_TABLES,
    ),
    FitnessRule(
        key="seph-january-2026-level-shift",
        title_en="SEPH: level shift in January 2026",
        title_fr="EERH : décalage de niveau en janvier 2026",
        note_en=(
            "Statistics Canada flags a possible temporary level shift in SEPH estimates "
            "from January 2026, to be corrected with the revised estimates of March 2027: "
            "use caution when comparing later months with earlier ones."
        ),
        note_fr=(
            "Statistique Canada signale un possible décalage de niveau temporaire dans les "
            "estimations de l'EERH à partir de janvier 2026, qui sera corrigé avec les "
            "estimations révisées de mars 2027 : soyez prudent en comparant les mois "
            "suivants aux mois antérieurs."
        ),
        sources=("https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410020101",),
        checked=(
            "WDS footnote on 14-10-0201 and 14-10-0220: 'With the release of January 2026 "
            "estimates, a temporary level shift may be observed. This will be adjusted with "
            "the release of revised estimates in March 2027'. Not present on 14-10-0222 or "
            "14-10-0223, so not keyed to them."
        ),
        product_ids=(14100201, 14100220),
    ),
    FitnessRule(
        key="census-random-rounding",
        title_en="2021 Census: random rounding",
        title_fr="Recensement de 2021 : arrondissement aléatoire",
        note_en=(
            "2021 Census values, totals included, are randomly rounded up or down to a "
            "multiple of 5 or 10 for confidentiality. Totals and subtotals are rounded "
            "independently, so parts may not sum to the published total and percentages "
            "from rounded counts may not add to 100: use the published total, do not "
            "rebuild it from its parts, and expect small counts to be imprecise."
        ),
        note_fr=(
            "Pour protéger la confidentialité, les valeurs du Recensement de 2021, totaux "
            "compris, sont arrondies au hasard vers le haut ou vers le bas à un multiple de "
            "5 ou de 10. Totaux et sous-totaux sont arrondis séparément : la somme des "
            "parties peut différer du total publié et des pourcentages calculés sur des "
            "comptes arrondis peuvent ne pas totaliser 100. Utilisez le total publié sans "
            "le reconstituer à partir des parties, et tenez les petits comptes pour "
            "imprécis."
        ),
        sources=("https://www150.statcan.gc.ca/n1/daily-quotidien/241025/dq241025b-eng.htm",),
        checked=(
            "The Daily, 25 October 2024 (2021 Census study), note: values, including totals, "
            "randomly rounded up or down to a multiple of '5' or '10'; totals and subtotals "
            "independently rounded; percentages may not add to 100%. The Census Profile's "
            "own 'About' page (www12.statcan.gc.ca) answers 403 from this container, so it "
            "is not cited. Population and dwelling counts tables (98-10-0001, -0002) are not "
            "keyed: their footnotes say nothing of rounding."
        ),
        tool_prefixes=("statcan_census_profile_",),
        # The archive covers 2001-2016; the source read speaks of 2021 only.
        exclude_prefixes=("statcan_census_profile_archive_",),
    ),
    FitnessRule(
        key="census-geography-vintage",
        title_en="Census geography changes between censuses",
        title_fr="La géographie du recensement change d'un recensement à l'autre",
        note_en=(
            "Census boundaries change between censuses. On 2021 boundaries Canada has 41 "
            "CMAs and 111 CAs: Fredericton, Drummondville, Red Deer, Kamloops, Chilliwack "
            "and Nanaimo became CMAs, and Ottawa-Gatineau and Windsor took in former CAs. "
            "2021 tables restate 2016 counts on 2021 boundaries where an area changed, so a "
            "2016 figure from a 2016 product may cover a different area. Compare places "
            "only on the same boundaries, and say which census geography a figure uses."
        ),
        note_fr=(
            "Les limites du recensement changent d'un recensement à l'autre. Selon les "
            "limites de 2021, le Canada compte 41 RMR et 111 AR : Fredericton, "
            "Drummondville, Red Deer, Kamloops, Chilliwack et Nanaimo sont devenues des RMR, "
            "et Ottawa-Gatineau et Windsor ont intégré d'anciennes AR. Les tableaux de 2021 "
            "rajustent les chiffres de 2016 aux limites de 2021 quand une région a changé : "
            "un chiffre de 2016 tiré d'un produit de 2016 peut donc viser un autre "
            "territoire. Ne comparez des lieux que selon les mêmes limites, et précisez la "
            "géographie de recensement de chaque chiffre."
        ),
        sources=(
            "https://www150.statcan.gc.ca/n1/daily-quotidien/220209/dq220209a-eng.htm",
            "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810000201",
        ),
        checked=(
            "The Daily, 9 February 2022: results on 2021 boundaries; 41 CMAs and 111 CAs; "
            "six new CMAs named; Ottawa-Gatineau expanded to Arnprior and Carleton Place, "
            "Windsor to Leamington. WDS footnotes on 98-10-0002: 'boundary change since the "
            "2016 Census that resulted in an adjustment to the 2016 population and/or "
            "dwelling counts'."
        ),
        tool_prefixes=("statcan_census_profile_", "statcan_geo_"),
        product_ids=(98100001, 98100002),
    ),
    FitnessRule(
        key="low-income-lines",
        title_en="Poverty and low income: MBM, LIM and LICO are different lines",
        title_fr="Pauvreté et faible revenu : la MPC, la MFR et les SFR sont des seuils distincts",
        note_en=(
            "Name the line and base with every rate: they measure different things. The "
            "Market Basket Measure (MBM), Canada's Official Poverty Line, is the regional "
            "cost of a basket of goods and services for a modest, basic standard of living; "
            "the after-tax Low Income Measure (LIM-AT) is relative, under half the median "
            "adjusted household income; the Low Income Cut-offs (LICO) rest on 1992 "
            "spending patterns. MBM bases differ too: the 2023 base is official since "
            "November 2025 with thresholds back to 2020, and Canadian Income Survey "
            "releases no longer carry 2018-base estimates; Statistics Canada suggests its "
            "MBM Poverty Index for trends across bases. Small groups and the territories "
            "have large sampling variability. The Canadian Income Survey (11-10-0135) is "
            "annual for Canada and the provinces; for smaller areas use the 2021 Census "
            "(LIM-AT, by age, in the Census Profile), which is 2020 income, a year raised by "
            "pandemic benefits, and a different line."
        ),
        note_fr=(
            "Nommez le seuil et la base avec chaque taux : ils ne mesurent pas la même "
            "chose. La mesure du panier de consommation (MPC), seuil officiel de la pauvreté "
            "au Canada, est le coût régional d'un panier de biens et de services "
            "correspondant à un niveau de vie modeste et de base; la mesure de faible revenu "
            "après impôt (MFR-ApI) est relative, sous la moitié du revenu médian ajusté des "
            "ménages; les seuils de faible revenu (SFR) reposent sur les habitudes de "
            "dépenses de 1992. Les bases de la MPC diffèrent aussi : la base de 2023 est "
            "officielle depuis novembre 2025, avec des seuils depuis 2020, et les "
            "diffusions de l'Enquête canadienne sur le revenu ne donnent plus d'estimations "
            "selon la base de 2018; Statistique Canada propose son indice de pauvreté de la "
            "MPC pour suivre une tendance d'une base à l'autre. Les petits groupes et les "
            "territoires ont une forte variabilité d'échantillonnage. L'Enquête canadienne "
            "sur le revenu (11-10-0135) est annuelle pour le Canada et les provinces; pour "
            "de plus petites régions, prenez le Recensement de 2021 (MFR-ApI, par âge, dans "
            "le Profil du recensement), qui porte sur le revenu de 2020, une année gonflée "
            "par les prestations liées à la pandémie, et sur un autre seuil."
        ),
        sources=(
            "https://www150.statcan.gc.ca/n1/pub/75f0002m/75f0002m2016002-eng.htm",
            "https://www150.statcan.gc.ca/n1/pub/75f0002m/75f0002m2025003-eng.htm",
            "https://www150.statcan.gc.ca/n1/daily-quotidien/251107/dq251107f-eng.htm",
            "https://www150.statcan.gc.ca/n1/daily-quotidien/260429/dq260429a-eng.htm",
        ),
        checked=(
            "75F0002M2016002: LICO from 1992 expenditure data; LIM below half the median "
            "adjusted household income; MBM is the cost of a predetermined basket. "
            "75F0002M2025003: MBM is Canada's Official Poverty Line; bases reflect data and "
            "resources of their time. The Daily 7 Nov 2025: 2023-base thresholds back to "
            "2020; MBM Poverty Index for trends across bases; future CIS releases drop "
            "2018-base estimates. The Daily 29 Apr 2026 (CIS 2024): 2023-base methodology "
            "official since November 2025; LIM-AT at 50% of median adjusted after-tax "
            "income; sampling variability for small groups, caution for territories. WDS "
            "metadata for 11-10-0135: Low income lines dimension lists LIM-AT, LICO 1992 "
            "base before and after tax, and MBM 2023, 2018, 2008 and 2000 bases."
        ),
        product_ids=_LOW_INCOME_TABLES,
    ),
    FitnessRule(
        key="cpi-revisions",
        title_en="Consumer Price Index: what is revised",
        title_fr="Indice des prix à la consommation : ce qui est révisé",
        note_en=(
            "The official CPI (not seasonally adjusted, table 18-10-0004) is never revised "
            "once published. Seasonally adjusted indexes (18-10-0006) are the only CPI "
            "series revised: one month after release, and each January for the past 36 "
            "months; each is adjusted on its own, so they do not add up to the all-items "
            "index. The basket weights are updated every year since 2022."
        ),
        note_fr=(
            "L'IPC officiel (non désaisonnalisé, tableau 18-10-0004) n'est jamais révisé une "
            "fois publié. Les indices désaisonnalisés (18-10-0006) sont les seules séries de "
            "l'IPC révisées : un mois après leur diffusion, puis chaque janvier pour les 36 "
            "mois précédents; chacun est désaisonnalisé séparément, de sorte qu'ils ne "
            "s'additionnent pas pour donner l'ensemble. Les pondérations du panier sont "
            "mises à jour chaque année depuis 2022."
        ),
        sources=(
            "https://www150.statcan.gc.ca/n1/pub/62-553-x/2023001/chap-2-eng.htm",
            "https://www150.statcan.gc.ca/n1/pub/62-553-x/2023001/chap-1-eng.htm",
        ),
        checked=(
            "The Canadian CPI Reference Paper (62-553-X, 2023), 2.7: official CPI not "
            "revised; seasonally adjusted indices the only CPI series revised, one month "
            "after release and each January for the past 36 months. 1.60: seasonally "
            "adjusted independently, not consistent in aggregation. 1.62 and 8.10: basket "
            "updated every year since 2022 (the 2021 basket update)."
        ),
        product_ids=(18100004, 18100006),
    ),
    FitnessRule(
        key="core-cpi-revisions",
        title_en="Bank of Canada core inflation measures are revised",
        title_fr="Les mesures de l'inflation fondamentale de la Banque du Canada sont révisées",
        note_en=(
            "CPI-trim and CPI-median are built from seasonally adjusted prices and are "
            "revised: since the January 2026 CPI, each January revises the past three years "
            "and every other month revises one past month. CPI-common is revised as its "
            "factor model is re-estimated on all past data. Today's value for a past month "
            "may differ from what was first published: for what was known on a date, use "
            "table 18-10-0259 (real-time releases) or wds_get_series_as_of."
        ),
        note_fr=(
            "L'IPC-tronq et l'IPC-méd sont calculés sur des prix désaisonnalisés et sont "
            "révisés : depuis l'IPC de janvier 2026, chaque mois de janvier révise les trois "
            "années précédentes et les autres mois révisent un mois passé. L'IPC-comm est "
            "révisé quand son modèle factoriel est réestimé sur toutes les données passées. "
            "La valeur actuelle d'un mois passé peut donc différer de la première "
            "publication : pour ce qu'on savait à une date donnée, utilisez le tableau "
            "18-10-0259 (diffusions en temps réel) ou wds_get_series_as_of."
        ),
        sources=(
            "https://www150.statcan.gc.ca/n1/daily-quotidien/260217/dq260217a-eng.htm",
            "https://www150.statcan.gc.ca/n1/pub/62-553-x/2023001/chap-2-eng.htm",
            "https://www.bankofcanada.ca/rates/price-indexes/cpi/",
        ),
        checked=(
            "The Daily, 17 Feb 2026 (CPI January 2026), note to readers: CPI-median and "
            "CPI-trim use seasonally adjusted data; previously revised over seven years; now "
            "back three years each January and one historical month otherwise; CPI-common "
            "policy unchanged. 62-553-X 2.8: core measures are revised; CPI-common because "
            "its factor model is estimated over all historical data. Bank of Canada CPI "
            "page: definitions of CPI-trim and CPI-median. WDS: 18-10-0259 is 'Historical "
            "(real-time) releases of CPI statistics, measures of core inflation'."
        ),
        product_ids=(18100256, 18100259),
    ),
    FitnessRule(
        key="gdp-industry-vs-expenditure",
        title_en="GDP: monthly by industry vs quarterly expenditure-based; chained dollars",
        title_fr="PIB : mensuel par industrie et trimestriel en termes de dépenses; dollars enchaînés",
        note_en=(
            "Monthly GDP by industry (36-10-0434) is at basic prices; quarterly "
            "expenditure-based GDP (36-10-0104) is at market prices. They are estimated "
            "differently, so their growth rates can differ, and both are revised as new "
            "data arrive. Real values in chained (2017) dollars are not additive: "
            "components do not sum to their aggregate, and the gap grows with distance "
            "from 2017. To split growth into parts, use the 'Contributions to percent "
            "change' series of 36-10-0104 rather than adding or subtracting chained levels."
        ),
        note_fr=(
            "Le PIB mensuel par industrie (36-10-0434) est aux prix de base; le PIB "
            "trimestriel en termes de dépenses (36-10-0104) est aux prix du marché. Ils sont "
            "estimés différemment, de sorte que leurs taux de croissance peuvent différer, "
            "et les deux sont révisés à mesure que de nouvelles données arrivent. Les "
            "valeurs réelles en dollars enchaînés (2017) ne sont pas additives : les "
            "composantes ne totalisent pas leur agrégat, et l'écart grandit à mesure qu'on "
            "s'éloigne de 2017. Pour décomposer la croissance, utilisez les séries "
            "« Contributions à la variation en pourcentage » de 36-10-0104 plutôt que "
            "d'additionner ou de soustraire des niveaux enchaînés."
        ),
        sources=(
            "https://www150.statcan.gc.ca/n1/daily-quotidien/260929/dq260929a-eng.htm",
            "https://www150.statcan.gc.ca/n1/pub/13-017-x/2008001/themes/ch02/5213339-eng.htm",
            "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3610043401",
        ),
        checked=(
            "The Daily, 29 Sep 2026 (GDP by industry, July 2026), note to readers: basic "
            "prices, chained volume with 2017 reference year; expenditure-based GDP at "
            "market prices; the two can differ; each release revises earlier months. Guide "
            "to the Income and Expenditure Accounts (13-017-X) 2.165-2.171: chain Fisher "
            "series not additive, non-additivity grows with distance from the reference "
            "period; additive contributions to change recommended. WDS footnote on "
            "36-10-0434: 'Aggregates are not always equal to the sum of their components'; "
            "36-10-0104 Prices dimension includes 'Contributions to percent change'."
        ),
        product_ids=(36100434, 36100104),
    ),
    FitnessRule(
        key="classification-versions",
        title_en="Industry and occupation classifications change (NAICS, NOC)",
        title_fr="Les classifications des industries et des professions changent (SCIAN, CNP)",
        note_en=(
            "These tables classify industries by NAICS 2022 (monthly GDP by industry since "
            "its 28 November 2025 release) or occupations by NOC 2021. Series on earlier "
            "versions (NAICS 2017 and before, NOC 2016) are terminated series or separate "
            "inactive tables, such as 14-10-0296 on NOC 2016: codes do not match one for "
            "one across versions, so do not splice an old and a new series without "
            "checking the concordance."
        ),
        note_fr=(
            "Ces tableaux classent les industries selon le SCIAN 2022 (le PIB mensuel par "
            "industrie depuis sa diffusion du 28 novembre 2025) ou les professions selon la "
            "CNP 2021. Les séries selon des versions antérieures (SCIAN 2017 et avant, CNP "
            "2016) sont des séries terminées ou des tableaux inactifs distincts, comme "
            "14-10-0296 selon la CNP 2016 : les codes ne se correspondent pas un pour un "
            "d'une version à l'autre, ne raccordez donc pas une ancienne série à une "
            "nouvelle sans vérifier la concordance."
        ),
        sources=(
            "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3610043401",
            "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410020101",
            "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410042101",
            "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410029601",
        ),
        checked=(
            "WDS footnotes: 36-10-0434 adopted NAICS 2022 v1.0 with the 28 Nov 2025 "
            "release; 14-10-0201, -0220, -0222, -0223 and LFS 14-10-0355 use NAICS 2022, and "
            "14-10-0201 and -0220 carry terminated series on NAICS 2017, 2012, 2007 and "
            "2002; 14-10-0421 and -0416 use NOC 2021; 14-10-0296 ('inactive', archived, "
            "ends December 2022) uses NOC 2016."
        ),
        product_ids=(
            36100434,
            14100201,
            14100220,
            14100222,
            14100223,
            14100355,
            14100421,
            14100416,
            14100296,
        ),
    ),
    FitnessRule(
        key="pumf-weights-and-release",
        title_en="Public use microdata: weights and release rules",
        title_fr="Microdonnées à grande diffusion : poids et règles de diffusion",
        note_en=(
            "Estimates from a PUMF must use its survey weight; unweighted counts describe "
            "the sample, not the population. Each survey's user guide (in the file's ZIP) "
            "sets its release rules: the LFS PUMF, for one, calls an estimate acceptable "
            "with 5 or more respondents and a CV under 15%, marginal (with a warning) up to "
            "35%, and not for release beyond. PUMFs leave out sample-design detail, so "
            "variances come from the guide's method (bootstrap weights where provided), "
            "not from standard software formulas."
        ),
        note_fr=(
            "Les estimations tirées d'un FMGD doivent utiliser son poids d'enquête; des "
            "comptes non pondérés décrivent l'échantillon, pas la population. Le guide de "
            "l'utilisateur de chaque enquête (dans le ZIP du fichier) fixe ses règles de "
            "diffusion : celui du FMGD de l'EPA, par exemple, juge une estimation "
            "acceptable si au moins 5 répondants y contribuent et si son CV est inférieur à "
            "15 %, marginale (avec une mise en garde) jusqu'à 35 %, et non diffusable "
            "au-delà. Les FMGD omettent les détails du plan d'échantillonnage : la variance "
            "se calcule selon la méthode du guide (poids bootstrap s'ils sont fournis), pas "
            "avec les formules standard des logiciels."
        ),
        sources=("https://www150.statcan.gc.ca/n1/pub/71m0001x/71m0001x2021001-eng.htm",),
        checked=(
            "LFS PUMF User Guide 2025 (UserGuide_LFS_PUMF_2025_ENG.pdf in the September "
            "2026 CSV ZIP from the page cited), 5.1: survey weights (FINALWT) must be used "
            "for all estimation; 5.2 Table 5: acceptable n>=5 and CV<15%, marginal 15-35% "
            "with warning, unacceptable n<5 or CV>35%; 6.0: sample-design detail cannot be "
            "in a PUMF, Poisson bootstrap approximates the variance."
        ),
        tool_prefixes=("statcan_pumf_",),
    ),
    FitnessRule(
        key="cmhc-rental-market-reliability",
        title_en="CMHC Rental Market Survey: reliability codes and rent changes",
        title_fr="Enquête sur les logements locatifs de la SCHL : codes de fiabilité et variation des loyers",
        note_en=(
            "CMHC marks each Rental Market Survey estimate a (excellent), b (very good), c "
            "(good) or d (poor, use with caution); ** means suppressed, either too "
            "unreliable or based on fewer than 4 responding entities. The survey is taken in "
            "October. For rent growth use CMHC's published percent change of average rent, "
            "computed on structures common to both years; the gap between two years' "
            "average rents also reflects new and changed units in the sample."
        ),
        note_fr=(
            "La SCHL attribue à chaque estimation de l'Enquête sur les logements locatifs "
            "une cote a (excellente), b (très bonne), c (bonne) ou d (médiocre, à utiliser "
            "avec prudence); ** signale une donnée supprimée, trop peu fiable ou fondée sur "
            "moins de 4 entités répondantes. L'enquête a lieu en octobre. Pour la hausse "
            "des loyers, prenez la variation en pourcentage du loyer moyen publiée par la "
            "SCHL, calculée sur les immeubles présents les deux années; l'écart entre les "
            "loyers moyens de deux années reflète aussi les logements nouveaux ou modifiés "
            "de l'échantillon."
        ),
        sources=(
            (
                "https://www.cmhc-schl.gc.ca/professionals/housing-markets-data-and-research/"
                "housing-research/surveys/methods/methodology-rental-market-survey"
            ),
        ),
        checked=(
            "CMHC 'Methodology for Rental Market Survey': conducted in the first two weeks "
            "of October; reliability A-D by CV (A <=2.5, B <=5, C <=7.5, D <=10, suppressed "
            "above); proportions coded A, B, C, D (poor, use with caution) and ** suppressed; "
            "released only if based on 4 or more responding entities; percent change of "
            "average rent uses structures common to the sample in both years."
        ),
        # Only the data tools: listing categories or provinces returns no estimate.
        tool_prefixes=("cmhc_get_table_data", "cmhc_dt_get_table"),
    ),
    FitnessRule(
        key="cpi-annual-average",
        title_en="CPI: annual average inflation vs December over December",
        title_fr="IPC : inflation en moyenne annuelle et de décembre à décembre",
        note_en=(
            "Annual inflation for a calendar year is the change between two annual average "
            "indexes, which Statistics Canada publishes each January in table 18-10-0005-01 "
            "and computes from the published, rounded indexes. Read it there: averaging the "
            "12 monthly values of 18-10-0004-01 yourself can differ by 0.1 point, and the "
            "December-to-December change is a different measure. Say which one you report."
        ),
        note_fr=(
            "L'inflation d'une année civile est la variation entre deux indices en moyenne "
            "annuelle, que Statistique Canada publie chaque janvier dans le tableau "
            "18-10-0005-01 et calcule à partir des indices publiés arrondis. Prenez-la dans "
            "ce tableau : la moyenne des 12 valeurs mensuelles de 18-10-0004-01 calculée par "
            "vous peut différer de 0,1 point, et la variation de décembre à décembre est une "
            "autre mesure. Précisez laquelle vous donnez."
        ),
        sources=("https://www150.statcan.gc.ca/n1/pub/62-553-x/2023001/chap-2-eng.htm",),
        checked=(
            "The Canadian CPI Reference Paper (62-553-X, 2023), chapter 2: 'Each year with "
            "the release of the December CPI in January, annual average indices are produced "
            "for all of the published monthly indices'; 'annual average percentage changes, "
            "which compare two consecutive annual average price indices'; 'Percentage changes "
            "(monthly, 12-month and annual average) ... are always calculated with the "
            "published rounded indices.' WDS: 18-10-0005 is 'Consumer Price Index, annual "
            "average, not seasonally adjusted'. Read 2026-11-02."
        ),
        product_ids=(18100004, 18100005),
    ),
    FitnessRule(
        key="cpi-city-coverage",
        title_en="CPI: what is published for cities",
        title_fr="IPC : ce qui est publié pour les villes",
        note_en=(
            "Most CPI components are published for Canada and the provinces only. Mortgage "
            "interest cost is published for Canada alone: no province or city has it. For "
            "Toronto, tables 18-10-0004 and 18-10-0005 publish six series only: All-items, "
            "Shelter, Rented accommodation, Owned accommodation, Water, fuel and electricity, "
            "and All-items (1992=100). A city figure for any other component does not exist; "
            "say so and offer the national or provincial figure instead."
        ),
        note_fr=(
            "La plupart des composantes de l'IPC ne sont publiées que pour le Canada et les "
            "provinces. Le coût de l'intérêt hypothécaire n'est publié que pour le Canada : "
            "aucune province ni aucune ville ne l'a. Pour Toronto, les tableaux 18-10-0004 et "
            "18-10-0005 ne publient que six séries : Ensemble, Logement, Logement locatif, "
            "Logement en propriété, Eau, combustible et électricité, et Ensemble (1992=100). "
            "Un chiffre municipal pour une autre composante n'existe pas : dites-le et "
            "proposez le chiffre national ou provincial."
        ),
        sources=(
            "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810000401",
            "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810000501",
        ),
        checked=(
            "WDS getSeriesInfoFromCubePidCoord on 2026-11-02, both tables: every geography "
            "with member 85 'Mortgage interest cost' returns a series only for Canada; "
            "Toronto (geography 16) with each of the 359/361 product members returns a "
            "series only for All-items, Shelter, Rented accommodation, Owned accommodation, "
            "Water, fuel and electricity, and All-items (1992=100)."
        ),
        product_ids=(18100004, 18100005),
    ),
    FitnessRule(
        key="cmhc-rms-universe",
        title_en="CMHC Rental Market Survey tables: survey rents and which structures",
        title_fr="Tableaux de l'Enquête sur les logements locatifs : loyers d'enquête et immeubles visés",
        note_en=(
            "These tables republish CMHC's Rental Market Survey, taken in the first two weeks "
            "of October and labelled with its year. Average rent is what tenants actually "
            "pay, over occupied and vacant units in privately initiated structures; it is "
            "not an asking rent for vacant units or a rent from listing sites. Check the "
            "structure type: 34-10-0130 (vacancy) and the 'row and apartment structures of "
            "three units and over' member of 34-10-0133 (rent) cover the survey's whole "
            "universe; 34-10-0127 covers apartment structures of six units and over only, "
            "and its rates differ. Most series start later than their table: 34-10-0133 "
            "starts in 1987, but Toronto's two-bedroom rent has values from 1992. Read a "
            "series' data before stating its first year."
        ),
        note_fr=(
            "Ces tableaux reprennent l'Enquête sur les logements locatifs de la SCHL, menée "
            "pendant les deux premières semaines d'octobre et datée de son année. Le loyer "
            "moyen est celui que paient réellement les locataires, sur les logements occupés "
            "et vacants des immeubles d'initiative privée ; ce n'est pas un loyer demandé "
            "pour un logement vacant ni un loyer de sites d'annonces. Vérifiez le type "
            "d'immeuble : le tableau 34-10-0130 (inoccupation) et le membre « logements en "
            "bandes et immeubles d'appartements de trois logements et plus » de 34-10-0133 "
            "(loyers) couvrent tout l'univers de l'enquête ; 34-10-0127 ne couvre que les "
            "immeubles de six logements et plus, et ses taux diffèrent. La plupart des séries "
            "commencent après leur tableau : 34-10-0133 commence en 1987, mais le loyer des "
            "deux chambres à Toronto a des valeurs depuis 1992. Lisez les données d'une série "
            "avant d'en donner la première année."
        ),
        sources=(
            (
                "https://www.cmhc-schl.gc.ca/professionals/housing-markets-data-and-research/"
                "housing-research/surveys/methods/methodology-rental-market-survey"
            ),
            "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3410013001",
            "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3410012701",
        ),
        checked=(
            "CMHC 'Methodology for Rental Market Survey', read 2026-11-02: privately "
            "initiated, 'all row projects and apartment structures with three or more "
            "units'; 'conducted during the first 2 weeks of October'; rent is 'the actual "
            "amount tenants pay', average rent covers vacant and occupied units; asking rent "
            "applies to vacant units. WDS titles: 34-10-0130 'vacancy rates, row and "
            "apartment structures of three units and over ... weighted average'; 34-10-0127 "
            "'vacancy rates, apartment structures of six units and over'; 34-10-0133 "
            "'average rents for areas with a population of 10,000 and over', Type of "
            "structure member 3 'Row and apartment structures of three units and over'. "
            "getDataFromVectorsAndLatestNPeriods for v3823103 (Toronto, row and apartment, "
            "two bedroom), latestN=200: rows from 1987-01-01, values null until 1992-01-01."
        ),
        product_ids=(34100127, 34100130, 34100133),
    ),
    FitnessRule(
        key="income-unit-and-dollars",
        title_en="Income tables: families or individuals, constant dollars",
        title_fr="Tableaux du revenu : familles ou particuliers, dollars constants",
        note_en=(
            "Table 11-10-0190 is in constant dollars of its latest income year "
            "(inflation-adjusted), so growth read from it is real growth: do not set it "
            "beside growth in current dollars, such as rents, without saying so. Its "
            "'Economic families and persons not in an economic family' member counts each "
            "family, and each person living alone or with non-relatives, once. Income of "
            "individuals (11-10-0238, 11-10-0239) is per person aged 15 and over and much "
            "lower. Use the unit the question asks for (household or family vs person) and "
            "name it. This survey has no household unit: a household (everyone in a dwelling) "
            "is the Census unit, so for 'household income' give the 2021 Census Profile's "
            "median total income of household (2020 income, raised by pandemic benefits) and "
            "this table's figure as the recent alternative, naming each. Incomes are skewed, "
            "so the median is the typical income: asked for 'average income', give the median "
            "beside the average (these tables have both) and say which is which."
        ),
        note_fr=(
            "Le tableau 11-10-0190 est en dollars constants de sa dernière année de revenu "
            "(corrigés de l'inflation) : la croissance qu'on en tire est réelle, à ne pas "
            "comparer à une croissance en dollars courants, comme celle des loyers, sans le "
            "dire. Son membre « Familles économiques et personnes hors famille économique » "
            "compte une fois chaque famille et chaque personne seule ou vivant avec des "
            "personnes non apparentées. Le revenu des particuliers (11-10-0238, 11-10-0239) "
            "est par personne de 15 ans et plus, et bien plus bas. Prenez l'unité que la "
            "question demande (ménage ou famille, ou personne) et nommez-la. Cette enquête n'a "
            "pas d'unité ménage : le ménage (toutes les personnes d'un logement) est l'unité "
            "du Recensement; pour le « revenu des ménages », donnez le revenu total médian des "
            "ménages du Profil du recensement de 2021 (revenu de 2020, gonflé par les "
            "prestations liées à la pandémie) et le chiffre de ce tableau comme solution plus "
            "récente, en nommant chacun. Les revenus sont asymétriques, la médiane est donc le "
            "revenu typique : si l'on demande le « revenu moyen », donnez la médiane à côté de "
            "la moyenne (ces tableaux ont les deux) et dites laquelle est laquelle."
        ),
        sources=(
            "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1110019001",
            "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1110023901",
        ),
        checked=(
            "WDS getCubeMetadata 2026-11-02: 11-10-0190 income concepts carry memberUomCode "
            "455 ('2024 constant dollars' in getCodeSets); footnotes define an economic "
            "family as two or more related persons in the same dwelling and a person not in "
            "an economic family as one living alone or with unrelated others, and say 2022 "
            "onwards covers persons aged 15 and over. 11-10-0238 is 'Distribution of market, "
            "total and after-tax income of individuals'; 11-10-0239 is 'Income of "
            "individuals by age group, gender and income source'. 2026-11-03: 11-10-0239 "
            "Statistics members include 'Average income (excluding zeros)' and 'Median "
            "income (excluding zeros)'; 11-10-0190 income concepts pair each average with a "
            "median. Census Profile 2021 characteristic 229 'Median total income of household "
            "in 2020 ($)', Alberta 96,000; 11-10-0190 Alberta median total income 2024 for "
            "economic families and persons not in an economic family 96,600 (v96414571)."
        ),
        product_ids=(11100190, 11100238, 11100239),
    ),
    FitnessRule(
        key="trade-basis",
        title_en="Merchandise trade: customs or balance-of-payments basis",
        title_fr="Commerce de marchandises : base douanière ou base de la balance des paiements",
        note_en=(
            "Table 12-10-0011 holds each trade flow twice, on a customs basis and on a "
            "balance-of-payments basis, each unadjusted and seasonally adjusted. Statistics "
            "Canada's monthly trade release reports the balance-of-payments basis, seasonally "
            "adjusted, in millions of dollars: use that for a headline figure (exports, "
            "imports or the balance, total or with a partner) unless the question names "
            "another, and say which basis and adjustment you used. The CIMT database "
            "(cimt_ tools) is customs basis and not seasonally adjusted: use it for detail "
            "by product (HS code) or province, not for the headline total."
        ),
        note_fr=(
            "Le tableau 12-10-0011 contient chaque flux deux fois, sur une base douanière et "
            "sur la base de la balance des paiements, chacun non désaisonnalisé et "
            "désaisonnalisé. Le communiqué mensuel de Statistique Canada sur le commerce "
            "donne la base de la balance des paiements, désaisonnalisée, en millions de "
            "dollars : prenez celle-là pour un chiffre principal (exportations, importations "
            "ou solde, au total ou avec un partenaire), sauf si la question en nomme une "
            "autre, et dites quelle base et quel ajustement vous avez pris. La base CIMT "
            "(outils cimt_) est sur une base douanière et non désaisonnalisée : prenez-la "
            "pour le détail par produit (code SH) ou par province, pas pour le total principal."
        ),
        sources=(
            "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1210001101",
            "https://www150.statcan.gc.ca/n1/en/catalogue/65F0013X",
        ),
        checked=(
            "WDS getCubeMetadata 2026-11-03 for 12-10-0011 'International merchandise trade "
            "for all countries and by Principal Trading Partners, monthly': dimensions Trade "
            "(Import, Export, Trade Balance), Basis (Customs, Balance of payments), Seasonal "
            "adjustment (Unadjusted, Seasonally adjusted). Maple Test v2 C-14 (2026-11-03): "
            "exports to the United States, August 2026, balance of payments seasonally "
            "adjusted $54,346.5 million (v87008956); an answer from CIMT gave the customs, "
            "unadjusted $52.19 billion."
        ),
        tool_prefixes=("cimt_",),
        product_ids=(12100011,),
    ),
    FitnessRule(
        key="building-permits-adjustment",
        title_en="Building permits: seasonally adjusted headline",
        title_fr="Permis de bâtir : chiffre principal désaisonnalisé",
        note_en=(
            "Table 34-10-0292 gives the value of permits four ways: unadjusted or seasonally "
            "adjusted, in current or constant dollars. Statistics Canada's monthly release "
            "reports the seasonally adjusted value in current dollars: lead with that unless "
            "the question asks for another, and name the one you report. Values are in "
            "thousands of dollars."
        ),
        note_fr=(
            "Le tableau 34-10-0292 donne la valeur des permis de quatre façons : non "
            "désaisonnalisée ou désaisonnalisée, en dollars courants ou constants. Le "
            "communiqué mensuel de Statistique Canada donne la valeur désaisonnalisée en "
            "dollars courants : donnez-la d'abord, sauf si la question en demande une autre, "
            "et nommez celle que vous donnez. Les valeurs sont en milliers de dollars."
        ),
        sources=("https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3410029201",),
        checked=(
            "WDS getCubeMetadata 2026-11-03 for 34-10-0292 'Building permits, by type of "
            "structure and type of work': dimension 'Seasonal adjustment, value type' with "
            "members Unadjusted, current; Seasonally adjusted, current; Unadjusted, constant "
            "dollars; Seasonally adjusted, constant dollars. Maple Test v2 C-16: August 2026, "
            "seasonally adjusted current $13,571,697 thousand (v1675119645), unadjusted "
            "$13,199,762 thousand (v1675115467)."
        ),
        product_ids=(34100292,),
    ),
    FitnessRule(
        key="jobbank-wage-estimates",
        title_en="Job Bank wages: estimates from several sources, not a StatCan table",
        title_fr="Salaires du Guichet-Emplois : estimations de plusieurs sources, pas un tableau de StatCan",
        note_en=(
            "Job Bank wages are ESDC estimates, not a Statistics Canada table. The main source "
            "is the Labour Force Survey; where it is too thin ESDC uses Small Area Estimation, "
            "Employment Insurance survey data, the Census or administrative data, so the source "
            "and reference period differ between cells (read data_source and reference_period "
            "on each row). Low and high are in most cases the 10th and 90th percentiles; "
            "median is the prevailing wage. Some cells are suppressed for quality or "
            "confidentiality, and some regions show the wage of their province or of Canada as "
            "an approximation. Wages ignore experience, and some occupations are annual, not "
            "hourly."
        ),
        note_fr=(
            "Les salaires du Guichet-Emplois sont des estimations d'EDSC, et non un tableau de "
            "Statistique Canada. La source principale est l'Enquête sur la population active; "
            "lorsque l'échantillon est trop mince, EDSC utilise l'estimation pour petits "
            "domaines, les données d'enquête de l'assurance-emploi, le Recensement ou des "
            "données administratives : la source et la période de référence varient donc d'une "
            "cellule à l'autre (lisez data_source et reference_period sur chaque ligne). Les "
            "salaires bas et élevés correspondent le plus souvent aux 10e et 90e centiles; la "
            "médiane est le salaire courant. Certaines cellules sont supprimées pour des "
            "raisons de qualité ou de confidentialité, et certaines régions affichent le "
            "salaire de leur province ou du Canada comme approximation. Les salaires ne "
            "tiennent pas compte de l'expérience, et certaines professions sont annuelles, non "
            "horaires."
        ),
        sources=("https://www.jobbank.gc.ca/trend-analysis/search-wages/wage-methodology",),
        checked=(
            "Job Bank 'Wage methodology' page, read 2026-11-03: low wage in most cases the 10th "
            "percentile, high wage the 90th, median the prevailing wage; primary source the "
            "Labour Force Survey, data may be suppressed for confidentiality or quality; other "
            "sources Small Area Estimation, EI program survey data, the Census, provincial and "
            "administrative data (CIHI, CMA); where wages cannot be determined, wages from "
            "another region, the province or Canada may be used as an approximate value; LFS "
            "excludes the territories and reserves; wages do not account for experience; annual "
            "wages for occupations with many self-employed workers."
        ),
        tool_prefixes=(
            "jobbank_get_wages",
            "jobbank_compare_occupations",
            "jobbank_search_occupations",
        ),
    ),
    FitnessRule(
        key="ircc-processing-times-snapshot",
        title_en="IRCC processing times: current estimates, not a time series",
        title_fr="Délais de traitement d'IRCC : estimations actuelles, pas une série chronologique",
        note_en=(
            "IRCC processing times are point-in-time estimates from its 'Check processing "
            "times' tool, replaced when IRCC updates them (the page says weekly; permanent "
            "residence times monthly), with no history kept: do not read them as a trend, and "
            "quote the last-updated date. A time runs from receipt of a complete application to "
            "a decision and varies with volumes and complexity; some are forward-looking "
            "estimates for a new application, others reflect how long it took to process 80% "
            "of past applications. An individual application can take longer."
        ),
        note_fr=(
            "Les délais de traitement d'IRCC sont des estimations ponctuelles de son outil "
            "« Vérifiez les délais de traitement », remplacées à chaque mise à jour (la page "
            "indique chaque semaine; chaque mois pour la résidence permanente), sans "
            "historique : ne les lisez pas comme une tendance, et citez la date de mise à jour. "
            "Un délai court de la réception d'une demande complète jusqu'à la décision et varie "
            "selon le volume et la complexité des demandes; certains sont des estimations "
            "prospectives pour une nouvelle demande, d'autres reflètent le temps qu'il a fallu "
            "pour traiter 80 % des demandes passées. Une demande donnée peut prendre plus de "
            "temps."
        ),
        sources=(
            (
                "https://www.canada.ca/en/immigration-refugees-citizenship/services/application/"
                "check-processing-times.html"
            ),
        ),
        checked=(
            "IRCC 'Check processing times' page, read 2026-11-03: 'Updated weekly' next to the "
            "last-update date; historical times are how long it took to process 80% of "
            "applications; the processing time starts when IRCC receives a complete "
            "application and ends with a decision; times vary with the type of application, "
            "completeness, volumes and verification. flpt-en.json states flpt_interval "
            "'monthly' for permanent residence and citizenship."
        ),
        tool_prefixes=("ircc_processing_get_time",),
    ),
)
