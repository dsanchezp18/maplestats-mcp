"""Cross-source guided-workflow MCP prompts (they show in a client's prompt menu).

Each walks the assistant through the tools of several agencies for one
common analyst task, in order, and ends the same way: cite the
provenance and read its caveats and limits before using a number. The
per-source prompts (statcan, boc, cmhc, eccc) cover one source each;
these join them. Each prompt picks its body by ``lang``; the French
bodies are written for a francophone analyst, not translated line by
line. Tool and argument names stay in English because they are code, and
tests/test_planner_prompts.py fails when a body names a tool that does
not exist.
"""

# No `from __future__ import annotations`: FastMCP resolves a prompt's
# parameter types by name, and the stringified `Lang` alias does not resolve.
from typing import Annotated, Literal

from fastmcp.prompts import prompt

Lang = Annotated[Literal["en", "fr"], "Language: 'en' or 'fr'"]

# The closing step every workflow shares.
_CITE = {
    "en": (
        "Finally, for every figure you report: cite provenance.source, provenance.url, "
        "the reference period and provenance.as_of, and quote provenance.licence when it is "
        "set. Read provenance.caveats (MapleStats' fitness-for-use rules, docs://planner/fitness-rules) and "
        "provenance.limits (what was cut) before drawing a conclusion, and pass any caveat "
        "that applies on to the reader. Offer reproduce_code(tool_name=..., arguments=...) "
        "for a script that refetches the same data."
    ),
    "fr": (
        "Enfin, pour chaque chiffre rapporté : citez provenance.source, provenance.url, la "
        "période de référence et provenance.as_of, et reprenez provenance.licence lorsqu'il "
        "est renseigné. Lisez provenance.caveats (les règles d'adéquation à l'usage de "
        "MapleStats, docs://planner/fr/regles-d-usage) et provenance.limits (ce qui a été coupé) avant de "
        "conclure, et signalez au lecteur toute mise en garde qui s'applique. Proposez "
        "reproduce_code(tool_name=..., arguments=...) pour obtenir un script qui récupère "
        "les mêmes données."
    ),
}

_LABOUR = {
    "en": (
        "To build a labour market snapshot for {province}:\n"
        "1. Call statcan_indicators_get_indicators(dataset='economic', "
        "query='unemployment rate', geo_code=<the feed's code: 0 Canada, 1 NL, 2 PE, 3 NS, "
        "4 NB, 5 QC, 6 ON, 7 MB, 8 SK, 9 AB, 10 BC, 11 YT, 12 NT, 13 NU>) for the latest Labour Force Survey "
        "(LFS) headline and the link to its Daily release.\n"
        "2. LFS detail, table 14-10-0287 (labour force characteristics, monthly, seasonally "
        "adjusted): call wds_get_cube_metadata(product_id='14-10-0287', dimension=1, "
        "member_query='{province}') and the other dimensions to build coordinates for "
        "employment, the unemployment rate and the participation rate, then "
        "wds_get_data_from_cube_coord(product_id='14-10-0287', coordinate=..., "
        "latest_n=13) for each, so the year-over-year change is in hand.\n"
        "3. Earnings from the Survey of Employment, Payrolls and Hours (SEPH), table "
        "14-10-0223 (employment and average weekly earnings including overtime, by "
        "province, seasonally adjusted): the same two calls, for average weekly earnings, "
        "all industries.\n"
        "4. LFS and SEPH do not measure the same thing: the LFS is a household survey "
        "(people, by where they live, self-employed included, with sampling error that is "
        "large for small provinces), SEPH counts payroll jobs of employees by where they "
        "work, and it is published about a month after the LFS for the same reference "
        "month. Never add or compare their employment levels; use the LFS for "
        "unemployment and participation, SEPH for earnings, and state each one's "
        "reference month.\n"
        "5. Optional: statcan_daily_get_release_calendar(query='Labour Force Survey') for "
        "the next release date.\n"
    ),
    "fr": (
        "Pour dresser un portrait du marché du travail ({province}) :\n"
        "1. Appelez statcan_indicators_get_indicators(dataset='economic', "
        "query='taux de chômage', geo_code=<code du flux : 0 Canada, 1 T.-N.-L., 2 Î.-P.-É., "
        "3 N.-É., 4 N.-B., 5 Qc, 6 Ont., 7 Man., 8 Sask., 9 Alb., 10 C.-B., 11 Yn, "
        "12 T.N.-O., 13 Nt>, lang='fr') "
        "pour le dernier résultat de l'Enquête sur la population active (EPA) et le lien "
        "vers sa diffusion dans Le Quotidien.\n"
        "2. Détail de l'EPA, tableau 14-10-0287 (caractéristiques de la population active, "
        "données mensuelles désaisonnalisées) : appelez "
        "wds_get_cube_metadata(product_id='14-10-0287', dimension=1, "
        "member_query='{province}') puis les autres dimensions pour composer les "
        "coordonnées de l'emploi, du taux de chômage et du taux d'activité, et "
        "wds_get_data_from_cube_coord(product_id='14-10-0287', coordinate=..., "
        "latest_n=13) pour chacune, afin d'avoir la variation sur douze mois.\n"
        "3. Rémunération selon l'Enquête sur l'emploi, la rémunération et les heures de "
        "travail (EERH), tableau 14-10-0223 (emploi et rémunération hebdomadaire moyenne, "
        "temps supplémentaire compris, par province, désaisonnalisés) : les deux mêmes "
        "appels, pour la rémunération hebdomadaire moyenne, ensemble des industries.\n"
        "4. L'EPA et l'EERH ne mesurent pas la même chose : l'EPA est une enquête auprès "
        "des ménages (des personnes, selon leur lieu de résidence, travailleurs autonomes "
        "compris, avec une erreur d'échantillonnage forte dans les petites provinces), "
        "l'EERH compte les emplois salariés inscrits à la paie selon le lieu de travail, "
        "et paraît environ un mois après l'EPA pour le même mois de référence. N'additionnez "
        "ni ne comparez jamais leurs niveaux d'emploi : prenez l'EPA pour le chômage et "
        "l'activité, l'EERH pour la rémunération, et précisez le mois de référence de "
        "chacune.\n"
        "5. Au besoin : statcan_daily_get_release_calendar(query='Enquête sur la "
        "population active', lang='fr') pour la date de la prochaine diffusion.\n"
    ),
}

_REFRESH = {
    "en": (
        "To refresh an article or table that cites {subject} with the latest release:\n"
        "1. List the StatCan tables (product ids) and vectors the text cites, with the "
        "value and reference period it gives for each.\n"
        "2. Call statcan_daily_get_releases(subject=..., limit=50) to see what was "
        "published since, and statcan_daily_get_release_calendar(query=<survey name>) for "
        "the next scheduled date (dates are plans and can move).\n"
        "3. Check what changed: wds_get_changed_cube_list(date='YYYY-MM-DD') for the "
        "release day, or statcan_delta_list_tables(date='YYYY-MM-DD', product_id=..., "
        "detail=True) for the corrections noted that day.\n"
        "4. Refetch the cited series with wds_get_data_from_vectors(vector_ids=[...], "
        "latest_n=...). Compare every earlier period too: a release revises past values, "
        "not only the newest one. For tables with a real-time history "
        "(statcan_delta_list_real_time_tables lists them), "
        "wds_get_series_as_of(vector_id=..., as_of=<the article's date>) shows what was "
        "published when the text was written, so you can tell a revision from an error.\n"
        "5. Update each figure and sentence, and name the new release date and its Daily "
        "link.\n"
    ),
    "fr": (
        "Pour mettre à jour avec la dernière diffusion un article ou un tableau qui cite "
        "« {subject} » :\n"
        "1. Relevez les tableaux de Statistique Canada (numéros de produit) et les vecteurs "
        "cités, avec la valeur et la période de référence données pour chacun.\n"
        "2. Appelez statcan_daily_get_releases(subject=..., limit=50, lang='fr') pour voir "
        "ce qui a paru depuis, et statcan_daily_get_release_calendar(query=<nom de "
        "l'enquête>, lang='fr') pour la prochaine date prévue (une date prévue peut "
        "changer).\n"
        "3. Repérez ce qui a changé : wds_get_changed_cube_list(date='AAAA-MM-JJ') pour le "
        "jour de diffusion, ou statcan_delta_list_tables(date='AAAA-MM-JJ', "
        "product_id=..., detail=True) pour les corrections signalées ce jour-là.\n"
        "4. Récupérez de nouveau les séries citées avec "
        "wds_get_data_from_vectors(vector_ids=[...], latest_n=...). Comparez aussi les "
        "périodes antérieures : une diffusion révise les valeurs passées, pas seulement la "
        "plus récente. Pour les tableaux qui ont un historique en temps réel "
        "(statcan_delta_list_real_time_tables les énumère), "
        "wds_get_series_as_of(vector_id=..., as_of=<date de l'article>) donne ce qui était "
        "publié au moment de la rédaction : vous distinguerez ainsi une révision d'une "
        "erreur.\n"
        "5. Mettez à jour chaque chiffre et chaque phrase, en indiquant la nouvelle date de "
        "diffusion et le lien vers Le Quotidien.\n"
    ),
}

_HOUSING = {
    "en": (
        "To scan housing affordability in {place}:\n"
        "1. Rents and vacancy (CMHC Rental Market Survey): read docs://cmhc/"
        "well-known-categories, call cmhc_get_table_options(category_level_1=..., "
        "category_level_2=...) to find {place}'s geography, then "
        "cmhc_get_table_data(...) for the vacancy rate and average rent by bedroom type, "
        "with row_field='TIMESERIES' for the history. Keep CMHC's reliability flag with "
        "each value; a null value is suppressed, not zero.\n"
        "2. Shelter prices: CPI table 18-10-0004 (monthly, not seasonally adjusted). Use "
        "wds_get_cube_metadata(product_id='18-10-0004', member_query=...) to find the "
        "geography ({place} or its province) and the shelter and rent components, then "
        "wds_get_data_from_cube_coord(..., latest_n=25) and compare year over year.\n"
        "3. Borrowing costs: read docs://boc/well-known-series and call "
        "boc_get_observations(series_names=[...], recent_months=24) for the policy rate "
        "and the posted 5-year conventional mortgage rate.\n"
        "4. Optional: crea_get_hpi_links for the MLS Home Price Index pages (links and "
        "terms only, no values).\n"
        "5. Keep the measures apart: the CMHC survey is an annual October snapshot of "
        "purpose-built rentals, the CPI rent and shelter indexes measure price change (not "
        "levels, so never divide a rent by them), and the Bank of Canada rates are "
        "national. Say which period each figure refers to.\n"
    ),
    "fr": (
        "Pour faire le point sur l'abordabilité du logement ({place}) :\n"
        "1. Loyers et inoccupation (Enquête sur les logements locatifs de la SCHL) : lisez "
        "docs://cmhc/fr/categories-courantes, appelez "
        "cmhc_get_table_options(category_level_1=..., category_level_2=..., lang='fr') "
        "pour trouver la géographie voulue ({place}), puis cmhc_get_table_data(...) pour le "
        "taux d'inoccupation et le loyer moyen selon le nombre de chambres, avec "
        "row_field='TIMESERIES' pour l'historique. Conservez l'indicateur de fiabilité de "
        "la SCHL avec chaque valeur ; une valeur nulle est supprimée, pas égale à zéro.\n"
        "2. Prix du logement : tableau de l'IPC 18-10-0004 (mensuel, non désaisonnalisé). "
        "Avec wds_get_cube_metadata(product_id='18-10-0004', member_query=...), repérez la "
        "géographie ({place} ou sa province) et les composantes logement et loyer, puis "
        "appelez wds_get_data_from_cube_coord(..., latest_n=25) et comparez d'une année "
        "sur l'autre.\n"
        "3. Coût du crédit : lisez docs://boc/fr/series-courantes et appelez "
        "boc_get_observations(series_names=[...], recent_months=24, lang='fr') pour le "
        "taux directeur et le taux hypothécaire affiché à 5 ans.\n"
        "4. Au besoin : crea_get_hpi_links pour les pages de l'indice des prix des "
        "propriétés MLS (liens et conditions seulement, sans valeurs).\n"
        "5. Ne mélangez pas les mesures : l'enquête de la SCHL est un instantané annuel "
        "d'octobre des logements construits pour la location, les indices du loyer et du "
        "logement de l'IPC mesurent une variation de prix (pas un niveau : ne divisez "
        "jamais un loyer par ces indices) et les taux de la Banque du Canada sont "
        "nationaux. Précisez la période de chaque chiffre.\n"
    ),
}

_INFLATION = {
    "en": (
        "To check inflation{as_of_text}:\n"
        "1. Call statcan_indicators_get_indicators(dataset='economic', "
        "query='consumer price index') for the latest all-items CPI and its Daily link.\n"
        "2. All-items CPI, table 18-10-0004 (not seasonally adjusted, so compare year over "
        "year): wds_get_data_from_vectors(vector_ids=[41690973], latest_n=25) for Canada, "
        "or wds_get_cube_metadata(product_id='18-10-0004', member_query=<province>) for "
        "another geography.\n"
        "3. Core inflation, table 18-10-0256 (CPI-trim and CPI-median, Bank of Canada "
        "definitions): wds_get_cube_metadata(product_id='18-10-0256') for the coordinates, "
        "then wds_get_data_from_cube_coord(product_id='18-10-0256', coordinate=..., "
        "latest_n=13). These measures are revised every month as new data arrive.\n"
        "4. What was known at the time: wds_get_series_as_of(product_id='18-10-0256', "
        "coordinate=..., as_of='YYYY-MM-DD') returns the first estimate as published on "
        "that date (from the real-time table 18-10-0259); compare it with today's value "
        "before judging a past call.\n"
        "5. Context: boc_get_observations(series_names=[...], recent_months=24) for the "
        "policy rate (names in docs://boc/well-known-series), against the 2% target, and "
        "statcan_daily_get_release_calendar(query='Consumer Price Index') for the next "
        "CPI release.\n"
    ),
    "fr": (
        "Pour faire le point sur l'inflation{as_of_text} :\n"
        "1. Appelez statcan_indicators_get_indicators(dataset='economic', "
        "query='indice des prix à la consommation', lang='fr') pour le dernier IPC "
        "d'ensemble et le lien vers Le Quotidien.\n"
        "2. IPC d'ensemble, tableau 18-10-0004 (non désaisonnalisé : comparez d'une année "
        "sur l'autre) : wds_get_data_from_vectors(vector_ids=[41690973], latest_n=25) pour "
        "le Canada, ou wds_get_cube_metadata(product_id='18-10-0004', "
        "member_query=<province>) pour une autre géographie.\n"
        "3. Inflation fondamentale, tableau 18-10-0256 (IPC-tronq et IPC-méd, définitions "
        "de la Banque du Canada) : wds_get_cube_metadata(product_id='18-10-0256') pour les "
        "coordonnées, puis wds_get_data_from_cube_coord(product_id='18-10-0256', "
        "coordinate=..., latest_n=13). Ces mesures sont révisées chaque mois, à mesure que "
        "de nouvelles données arrivent.\n"
        "4. Ce que l'on savait à l'époque : wds_get_series_as_of(product_id='18-10-0256', "
        "coordinate=..., as_of='AAAA-MM-JJ') renvoie la première estimation telle que "
        "publiée à cette date (tableau en temps réel 18-10-0259) ; comparez-la à la valeur "
        "actuelle avant de juger une décision passée.\n"
        "5. Contexte : boc_get_observations(series_names=[...], recent_months=24, "
        "lang='fr') pour le taux directeur (noms dans docs://boc/fr/series-courantes), "
        "face à la cible de 2 %, et statcan_daily_get_release_calendar(query='Indice des "
        "prix à la consommation', lang='fr') pour la prochaine diffusion de l'IPC.\n"
    ),
}

_PEERS = {
    "en": (
        "To compare {province} with its peers on {indicator}:\n"
        "1. Call plan_query(question='{indicator} in {province} compared with other "
        "provinces') for the tables and caveats that fit the indicator.\n"
        "2. Use one table for every province: find it with wds_search_cubes(query=...), "
        "then wds_get_cube_metadata(product_id=..., dimension=1) for the geography "
        "members. Fetch all provinces in one request with sdmx_get_data(product_id=..., "
        "key=...) and an OR key (the build_sdmx_or_key prompt shows how), or call "
        "wds_get_data_from_cube_coord once per province.\n"
        "3. For a quick headline, statcan_indicators_get_indicators(query=..., "
        "geo_code=...) takes one province at a time.\n"
        "4. The provincial agency often has more detail: isq_search_tables (Quebec), "
        "bc_stats_list_files (British Columbia), ab_economic_list_tables (Alberta).\n"
        "5. Compare like with like: the same reference period, the same seasonal "
        "adjustment, rates or per-capita values rather than levels (population from "
        "table 17-10-0009), and remember that survey estimates for small provinces carry "
        "wider sampling error, so a small gap may not be a real difference.\n"
    ),
    "fr": (
        "Pour comparer une province ({province}) aux autres selon l'indicateur « {indicator} » :\n"
        "1. Appelez plan_query(question='{indicator} : {province} et les autres provinces', "
        "lang='fr') pour obtenir les tableaux et les mises en garde adaptés à "
        "l'indicateur.\n"
        "2. Prenez un seul tableau pour toutes les provinces : trouvez-le avec "
        "wds_search_cubes(query=..., lang='fr'), puis "
        "wds_get_cube_metadata(product_id=..., dimension=1) pour les membres de la "
        "géographie. Obtenez toutes les provinces en une seule requête avec "
        "sdmx_get_data(product_id=..., key=...) et une clé OR (le prompt "
        "build_sdmx_or_key explique comment), ou appelez wds_get_data_from_cube_coord "
        "une fois par province.\n"
        "3. Pour un chiffre clé rapide, statcan_indicators_get_indicators(query=..., "
        "geo_code=..., lang='fr') traite une province à la fois.\n"
        "4. L'organisme statistique provincial a souvent plus de détail : "
        "isq_search_tables (Québec), bc_stats_list_files (Colombie-Britannique), "
        "ab_economic_list_tables (Alberta).\n"
        "5. Comparez ce qui est comparable : même période de référence, même traitement "
        "saisonnier, taux ou valeurs par habitant plutôt que niveaux (population : "
        "tableau 17-10-0009) ; les estimations d'enquête des petites provinces ont une "
        "erreur d'échantillonnage plus large, et un petit écart n'est pas forcément une "
        "vraie différence.\n"
    ),
}

_CITE_DATASET = {
    "en": (
        "To find and cite a dataset on {topic}:\n"
        "1. Call plan_query(question=...) to see which agencies cover {topic}, or "
        "search_tools(query=...) to find one tool. For StatCan, "
        "wds_search_cubes(query=...) finds tables and statcan_reference_search_data"
        "(query=...) finds other data products.\n"
        "2. Read the structure before fetching: wds_get_cube_metadata(product_id=...) "
        "gives dimensions, frequency, date range and footnotes (the footnotes often hold "
        "the caveats a citation needs).\n"
        "3. Fetch only what you need; for a whole StatCan table use "
        "wds_get_full_table_download(product_id=...) (a CSV link, no rows inline).\n"
        "4. Write the citation from the provenance: publisher (provenance.source), table "
        "number and title, reference period, release date (provenance.as_of), access date "
        "(provenance.queried_at), provenance.url, and the attribution in "
        "provenance.licence, word for word when it is set.\n"
        "5. For an analyst: reproduce_code(tool_name=..., arguments=...) gives R, Python, "
        "Stata and Julia scripts and reproduce_workbook(tool_name=..., arguments=...) an "
        "Excel workbook of the same rows.\n"
    ),
    "fr": (
        "Pour trouver et citer un jeu de données sur « {topic} » :\n"
        "1. Appelez plan_query(question=..., lang='fr') pour voir quels organismes "
        "couvrent ce sujet, ou search_tools(query=...) pour trouver un outil précis. Pour "
        "Statistique Canada, wds_search_cubes(query=..., lang='fr') trouve les tableaux et "
        "statcan_reference_search_data(query=..., lang='fr') les autres produits de "
        "données.\n"
        "2. Lisez la structure avant de récupérer les données : "
        "wds_get_cube_metadata(product_id=...) donne les dimensions, la fréquence, la "
        "période couverte et les notes de bas de page (qui contiennent souvent les mises en "
        "garde qu'une citation doit reprendre).\n"
        "3. Ne récupérez que le nécessaire ; pour un tableau entier de Statistique Canada, "
        "utilisez wds_get_full_table_download(product_id=...) (un lien CSV, sans les "
        "lignes).\n"
        "4. Rédigez la citation à partir de la provenance : éditeur (provenance.source), "
        "numéro et titre du tableau, période de référence, date de diffusion "
        "(provenance.as_of), date de consultation (provenance.queried_at), provenance.url, "
        "et la mention de licence de provenance.licence, mot pour mot lorsqu'elle est "
        "renseignée.\n"
        "5. Pour un analyste : reproduce_code(tool_name=..., arguments=...) fournit des "
        "scripts R, Python, Stata et Julia, et reproduce_workbook(tool_name=..., "
        "arguments=...) un classeur Excel des mêmes lignes.\n"
    ),
}

# Every body, for the test that checks the tool names they mention.
BODIES: dict[str, dict[str, str]] = {
    "labour_market_snapshot": _LABOUR,
    "refresh_with_latest_release": _REFRESH,
    "housing_affordability_scan": _HOUSING,
    "inflation_check": _INFLATION,
    "compare_province_with_peers": _PEERS,
    "find_and_cite_dataset": _CITE_DATASET,
    "cite": _CITE,
}


def _with_citation(body: str, lang: str) -> str:
    return body + _CITE[lang]


@prompt
def labour_market_snapshot(province: str, lang: Lang = "en") -> str:
    """Guided workflow: a province's labour market from the Labour Force Survey
    (employment, unemployment, participation) and SEPH earnings, with the
    caution on comparing the two. Use lang="fr" for the French version."""
    return _with_citation(_LABOUR[lang].format(province=province), lang)


@prompt
def refresh_with_latest_release(subject: str, lang: Lang = "en") -> str:
    """Guided workflow: bring an article or table up to date with StatCan's
    latest release (release calendar, The Daily, changed tables, revisions and
    vintages). Use lang="fr" for the French version."""
    return _with_citation(_REFRESH[lang].format(subject=subject), lang)


@prompt
def housing_affordability_scan(place: str, lang: Lang = "en") -> str:
    """Guided workflow: housing affordability in a city or province from CMHC
    rents and vacancy, CPI shelter prices and Bank of Canada rates. Use
    lang="fr" for the French version."""
    return _with_citation(_HOUSING[lang].format(place=place), lang)


@prompt
def inflation_check(as_of: str = "", lang: Lang = "en") -> str:
    """Guided workflow: all-items CPI, the Bank of Canada's core measures, and
    the first estimates published at a past date (as_of, YYYY-MM-DD, optional).
    Use lang="fr" for the French version."""
    if as_of:
        as_of_text = (
            f" as it was known on {as_of}"
            if lang == "en"
            else f" telle qu'on la connaissait le {as_of}"
        )
    else:
        as_of_text = ""
    return _with_citation(_INFLATION[lang].format(as_of_text=as_of_text), lang)


@prompt
def compare_province_with_peers(province: str, indicator: str, lang: Lang = "en") -> str:
    """Guided workflow: compare one province with the others on an indicator,
    from one table, like with like. Use lang="fr" for the French version."""
    return _with_citation(_PEERS[lang].format(province=province, indicator=indicator), lang)


@prompt
def find_and_cite_dataset(topic: str, lang: Lang = "en") -> str:
    """Guided workflow: find a dataset on a topic across sources, then cite it
    from its provenance and licence and hand over reproducible code. Use
    lang="fr" for the French version."""
    return _with_citation(_CITE_DATASET[lang].format(topic=topic), lang)
