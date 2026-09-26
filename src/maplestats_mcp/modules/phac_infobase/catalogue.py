"""Curated catalogue of Health Infobase data files.

Every URL, ZIP member and column named here was fetched and checked live
on 2026-09-26 (scripts/smoke_test_phac_infobase.py re-checks them all).
Files were found in each dashboard's page HTML and JavaScript (the
`d3.csv(...)` calls and "Download data" links). Only files with stable
names are listed: a few dashboards load date-stamped files
(YearlyCounts_20260105.csv for the Drug Analysis Service,
Figure_1_CIPARS_R_Combine_12_02_2025.csv) whose names change with each
update, so they are left out.

`date_columns` and `geo_columns` are candidates in order; the first one
present in the file is used, which lets one entry cover English and
French files whose column names differ. Paths are relative to
health-infobase.canada.ca unless absolute.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Kind = Literal["csv", "zip", "api"]

TOPICS: dict[str, tuple[str, str]] = {
    "respiratory": (
        "Respiratory viruses (FluWatch+, laboratory detections, CNISP hospitals)",
        "Virus respiratoires (ÉpiGrippe+, détections en laboratoire, hôpitaux du PCSIN)",
    ),
    "covid19": (
        "COVID-19 epidemiology and vaccination (archived)",
        "Épidémiologie et vaccination COVID-19 (archivées)",
    ),
    "wastewater": ("Wastewater surveillance", "Surveillance des eaux usées"),
    "vaccination": ("Vaccine safety", "Innocuité des vaccins"),
    "substance_use": (
        "Opioids, stimulants and substance use",
        "Opioïdes, stimulants et consommation de substances",
    ),
    "infectious_disease": (
        "Measles, mpox, tuberculosis and other infectious diseases",
        "Rougeole, mpox, tuberculose et autres maladies infectieuses",
    ),
    "chronic_disease": (
        "Chronic disease, cancer and congenital anomalies",
        "Maladies chroniques, cancer et anomalies congénitales",
    ),
    "health_status": (
        "Health status, risk factors and mental health",
        "État de santé, facteurs de risque et santé mentale",
    ),
}


@dataclass(frozen=True)
class Dataset:
    id: str
    topic: str
    title_en: str
    title_fr: str
    description_en: str
    description_fr: str
    url_en: str
    frequency: str
    dashboard_en: str
    dashboard_fr: str | None = None
    url_fr: str | None = None
    kind: Kind = "csv"
    member_en: str | None = None
    member_fr: str | None = None
    encoding_en: str | None = None
    encoding_fr: str | None = None
    date_columns: tuple[str, ...] = ()
    geo_columns: tuple[str, ...] = ()
    notes_en: str | None = None
    notes_fr: str | None = None


_RESP = "/respiratory-virus-surveillance/"
_RESP_FR = "https://sante-infobase.canada.ca/surveillance-virus-respiratoires/"
_RVD = "/src/data/respiratory-virus-detections/"
_RVS = "/src/data/respiratory-virus-surveillance/"
_CNISP = "/cnisp/viral-respiratory-infections.html"
_CNISP_FR = "https://sante-infobase.canada.ca/pcsin/index.html"
_COVID = "/covid-19/"
_COVID_FR = "https://sante-infobase.canada.ca/covid-19/index.html"
_VAX = "/covid-19/vaccine-distribution/"
_VAX_FR = "https://sante-infobase.canada.ca/covid-19/vaccins-distribues/"
_LIVE = "/src/data/covidLive/"
_WW = "/wastewater/"
_WW_FR = "https://sante-infobase.canada.ca/eaux-usees/"
_AEFI = "/vaccination/adverse-events/"
_AEFI_FR = "https://sante-infobase.canada.ca/vaccination/manifestations-cliniques/"
_AEFI_DATA = "/src/data/vaccination/adverse-events/"
_HARMS = "/substance-related-harms/opioids-stimulants/"
_HARMS_FR = "https://sante-infobase.canada.ca/mefaits-associes-aux-substances/opioides-stimulants/"
_SCS = "/supervised-consumption-sites/"
_SCS_FR = "https://sante-infobase.canada.ca/services-consommation-supervisee/"
_SCS_DATA = "/src/data/supervised-consumption-sites/"
_MEASLES = "/measles-rubella/"
_MEASLES_FR = "https://sante-infobase.canada.ca/rougeole-rubeole/"
_MEASLES_DATA = "/src/data/measles-rubella/"
_TB = "/tuberculosis/"
_TB_FR = "https://sante-infobase.canada.ca/tuberculose/"
_TB_DATA = "/src/data/tuberculosis/"

DATASETS: tuple[Dataset, ...] = (
    # Respiratory viruses ----------------------------------------------------
    Dataset(
        id="rvdss_weekly_detections",
        topic="respiratory",
        title_en="Respiratory virus laboratory detections by province and week",
        title_fr="Détections en laboratoire de virus respiratoires par province et semaine",
        description_en=(
            "Tests, detections and percent positive for SARS-CoV-2, influenza, RSV and other "
            "respiratory viruses (RVDSS), by region, province and surveillance week, current season."
        ),
        description_fr=(
            "Tests, détections et pourcentage de positivité pour le SRAS-CoV-2, la grippe, le VRS "
            "et d'autres virus respiratoires (SSDVR), par région, province et semaine, saison en cours."
        ),
        url_en=_RVD + "RVD_WeeklyData.csv",
        frequency="weekly",
        dashboard_en=_RESP,
        dashboard_fr=_RESP_FR,
        date_columns=("date",),
        geo_columns=("province",),
        notes_en="Week-ending dates; 'N/A' where a territory does not test for a virus.",
        notes_fr="Dates de fin de semaine; « N/A » lorsqu'un territoire ne teste pas un virus.",
    ),
    Dataset(
        id="rvdss_lab_current_week",
        topic="respiratory",
        title_en="Respiratory virus tests and detections by reporting laboratory, weekly",
        title_fr="Tests et détections de virus respiratoires par laboratoire, par semaine",
        description_en=(
            "Weekly tests and positives per reporting laboratory or province for SARS-CoV-2, "
            "influenza A (H1, H3, unsubtyped) and B, RSV, parainfluenza, adenovirus, hMPV, "
            "enterovirus/rhinovirus and seasonal coronaviruses."
        ),
        description_fr=(
            "Tests et résultats positifs hebdomadaires par laboratoire déclarant ou province pour "
            "le SRAS-CoV-2, la grippe A (H1, H3, non sous-typée) et B, le VRS, le virus "
            "parainfluenza, l'adénovirus, le MPVh, l'entérovirus/rhinovirus et les coronavirus."
        ),
        url_en=_RVD + "RVD_CurrentWeekTable.csv",
        frequency="weekly",
        dashboard_en=_RESP,
        dashboard_fr=_RESP_FR,
        date_columns=("date",),
        geo_columns=("ReportingLaboratory",),
    ),
    Dataset(
        id="rvdss_lab_season_to_date",
        topic="respiratory",
        title_en="Respiratory virus tests and detections by laboratory, season to date",
        title_fr="Tests et détections de virus respiratoires par laboratoire, cumul de la saison",
        description_en=(
            "Cumulative season-to-date tests and positives per reporting laboratory, same "
            "virus columns as the weekly laboratory table."
        ),
        description_fr=(
            "Tests et résultats positifs cumulés depuis le début de la saison par laboratoire, "
            "mêmes colonnes que le tableau hebdomadaire."
        ),
        url_en=_RVD + "RVD_YTDTable.csv",
        frequency="weekly",
        dashboard_en=_RESP,
        dashboard_fr=_RESP_FR,
        date_columns=("date",),
        geo_columns=("ReportingLaboratory",),
    ),
    Dataset(
        id="rvdss_seasonal_baseline",
        topic="respiratory",
        title_en="Percent positive by week compared with past seasons",
        title_fr="Pourcentage de positivité par semaine comparé aux saisons passées",
        description_en=(
            "Weekly percent positive for each virus in each of the previous seasons and the "
            "pre-pandemic minimum, average and maximum, for comparing the current season."
        ),
        description_fr=(
            "Pourcentage de positivité hebdomadaire de chaque virus lors des saisons précédentes "
            "et minimum, moyenne et maximum prépandémiques, pour comparer la saison en cours."
        ),
        url_en=_RVD + "RVD_BaselineData.csv",
        frequency="weekly",
        dashboard_en=_RESP,
        dashboard_fr=_RESP_FR,
        date_columns=("current_week_end_date",),
        geo_columns=("region",),
    ),
    Dataset(
        id="fluwatch_outbreaks",
        topic="respiratory",
        title_en="Respiratory outbreaks by virus and setting, weekly",
        title_fr="Éclosions respiratoires par virus et milieu, par semaine",
        description_en=(
            "Number of new COVID-19, influenza and RSV outbreaks reported each week by setting "
            "(long-term care, acute care, retirement homes and others), Canada."
        ),
        description_fr=(
            "Nombre de nouvelles éclosions de COVID-19, de grippe et de VRS déclarées chaque "
            "semaine par milieu (soins de longue durée, soins de courte durée, résidences pour "
            "aînés et autres), Canada."
        ),
        url_en=_RVS + "Outbreaks.csv",
        frequency="weekly",
        dashboard_en=_RESP,
        dashboard_fr=_RESP_FR,
        date_columns=("Week_Ending_Date",),
    ),
    Dataset(
        id="fluwatch_fluwatchers",
        topic="respiratory",
        title_en="FluWatchers: self-reported cough and fever, weekly",
        title_fr="Participants d'ÉpiGrippe : toux et fièvre autodéclarées, par semaine",
        description_en=(
            "Number and percent of FluWatchers volunteers reporting cough and fever each week, "
            "with minimum and maximum from earlier seasons."
        ),
        description_fr=(
            "Nombre et pourcentage de bénévoles d'ÉpiGrippe déclarant une toux et de la fièvre "
            "chaque semaine, avec le minimum et le maximum des saisons précédentes."
        ),
        url_en=_RVS + "FluWatchers.csv",
        frequency="weekly",
        dashboard_en=_RESP,
        dashboard_fr=_RESP_FR,
        date_columns=("Week_Ending_Date",),
        notes_en="Rows for earlier seasons carry Metric Min or Max and no week-ending date.",
        notes_fr="Les lignes des saisons passées portent Metric Min ou Max, sans date.",
    ),
    Dataset(
        id="fluwatch_severe_outcomes",
        topic="respiratory",
        title_en="Hospitalizations with COVID-19, influenza and RSV by age group, weekly",
        title_fr="Hospitalisations liées à la COVID-19, à la grippe et au VRS par âge, par semaine",
        description_en=(
            "Weekly hospitalization counts and rates per 100,000 by virus and age group from "
            "provincial and territorial severe outcome surveillance."
        ),
        description_fr=(
            "Nombre et taux hebdomadaires d'hospitalisations pour 100 000 habitants par virus et "
            "groupe d'âge, selon la surveillance provinciale et territoriale des cas graves."
        ),
        url_en=_RVS + "PTSOS_Weekly_Flu_COVID.csv",
        frequency="weekly",
        dashboard_en=_RESP,
        dashboard_fr=_RESP_FR,
        date_columns=("Week_Ending_Date",),
    ),
    Dataset(
        id="fluwatch_pediatric_hospitalizations",
        topic="respiratory",
        title_en="Pediatric hospitalizations and ICU admissions by virus (SPRINT-KIDS), weekly",
        title_fr="Hospitalisations et admissions aux soins intensifs pédiatriques (SPRINT-KIDS)",
        description_en=(
            "Weekly counts and percentages of pediatric hospitalizations (Outcome H) and ICU "
            "admissions (Outcome I) with COVID-19, influenza and RSV by age group, from the "
            "SPRINT-KIDS sentinel network."
        ),
        description_fr=(
            "Nombres et pourcentages hebdomadaires d'hospitalisations pédiatriques (Outcome H) et "
            "d'admissions aux soins intensifs (Outcome I) liées à la COVID-19, à la grippe et au "
            "VRS par groupe d'âge, selon le réseau sentinelle SPRINT-KIDS."
        ),
        url_en=_RVS + "SPRINT_Summary.csv",
        frequency="weekly",
        dashboard_en=_RESP,
        dashboard_fr=_RESP_FR,
        date_columns=("Week_Ending_Date",),
    ),
    Dataset(
        id="cnisp_vri_incidence",
        topic="respiratory",
        title_en="Hospital patients with a viral respiratory infection per 1,000 admissions",
        title_fr="Patients hospitalisés avec une infection respiratoire virale pour 1 000 admissions",
        description_en=(
            "Weekly incidence of hospitalized patients with COVID-19, influenza A or B, or RSV per "
            "1,000 patient admissions, adults, pediatric and all ages, in about 70 CNISP sentinel "
            "hospitals."
        ),
        description_fr=(
            "Incidence hebdomadaire des patients hospitalisés avec la COVID-19, la grippe A ou B ou "
            "le VRS pour 1 000 admissions, adultes, enfants et tous âges, dans environ 70 hôpitaux "
            "sentinelles du PCSIN."
        ),
        url_en="/api/cnisp-vri/table/vri_rates",
        kind="api",
        frequency="weekly",
        dashboard_en=_CNISP,
        dashboard_fr=_CNISP_FR,
        date_columns=("Week",),
        notes_en="Influenza and RSV collection began 2023-01-01; earlier rates are empty.",
        notes_fr="La collecte pour la grippe et le VRS a commencé le 2023-01-01.",
    ),
    Dataset(
        id="cnisp_covid_severity",
        topic="respiratory",
        title_en="COVID-19 hospitalization and ICU admission rates in CNISP hospitals",
        title_fr="Taux d'hospitalisation et d'admission aux soins intensifs COVID-19 (PCSIN)",
        description_en=(
            "Weekly rates of COVID-19 hospitalizations and ICU admissions by age group (adult, "
            "pediatric, all) in CNISP sentinel hospitals since March 2020."
        ),
        description_fr=(
            "Taux hebdomadaires d'hospitalisations et d'admissions aux soins intensifs liées à la "
            "COVID-19 par groupe d'âge dans les hôpitaux sentinelles du PCSIN depuis mars 2020."
        ),
        url_en="/api/cnisp-vri/table/covid_rates",
        kind="api",
        frequency="weekly",
        dashboard_en=_CNISP,
        dashboard_fr=_CNISP_FR,
        date_columns=("Week",),
    ),
    Dataset(
        id="cnisp_vri_outbreaks",
        topic="respiratory",
        title_en="Hospital outbreaks of viral respiratory infections (CNISP), weekly",
        title_fr="Éclosions hospitalières d'infections respiratoires virales (PCSIN)",
        description_en=(
            "Weekly number of COVID-19, influenza and RSV outbreaks in CNISP sentinel hospitals."
        ),
        description_fr=(
            "Nombre hebdomadaire d'éclosions de COVID-19, de grippe et de VRS dans les hôpitaux "
            "sentinelles du PCSIN."
        ),
        url_en="/api/cnisp-vri/table/outbreaks",
        kind="api",
        frequency="weekly",
        dashboard_en=_CNISP,
        dashboard_fr=_CNISP_FR,
        date_columns=("Week",),
    ),
    # COVID-19 (archived) ---------------------------------------------------
    Dataset(
        id="covid19_cases_deaths",
        topic="covid19",
        title_en="COVID-19 cases and deaths by province, weekly (2020 to 2024)",
        title_fr="Cas et décès de COVID-19 par province, par semaine (2020 à 2024)",
        description_en=(
            "Cumulative and weekly COVID-19 cases, deaths and rates per 100,000 by province and "
            "territory, February 2020 to September 2024."
        ),
        description_fr=(
            "Cas, décès et taux de COVID-19 pour 100 000 habitants, cumulés et hebdomadaires, par "
            "province et territoire, de février 2020 à septembre 2024."
        ),
        url_en=_LIVE + "covid19-download.csv",
        frequency="archived",
        dashboard_en=_COVID,
        dashboard_fr=_COVID_FR,
        date_columns=("date",),
        geo_columns=("prname",),
        notes_en="Case counts stop in 2024 ('-'); prnameFR holds French names.",
        notes_fr="Les cas cessent en 2024 (« - »); prnameFR contient les noms français.",
    ),
    Dataset(
        id="covid19_testing",
        topic="covid19",
        title_en="COVID-19 tests and percent positivity by province, weekly (2022 to 2024)",
        title_fr="Tests et positivité COVID-19 par province, par semaine (2022 à 2024)",
        description_en=(
            "Weekly number of COVID-19 tests and percent positive by province and territory, "
            "September 2022 to September 2024."
        ),
        description_fr=(
            "Nombre hebdomadaire de tests de dépistage de la COVID-19 et pourcentage de positivité "
            "par province et territoire, de septembre 2022 à septembre 2024."
        ),
        url_en=_LIVE + "covid19-epiSummary-labIndicators2.csv",
        frequency="archived",
        dashboard_en=_COVID,
        dashboard_fr=_COVID_FR,
        date_columns=("date",),
        geo_columns=("prname",),
    ),
    Dataset(
        id="covid19_cases_by_age_sex",
        topic="covid19",
        title_en="COVID-19 cases, hospitalizations and deaths by age and sex, weekly",
        title_fr="Cas, hospitalisations et décès de COVID-19 par âge et sexe, par semaine",
        description_en=(
            "Weekly counts and rates per 100,000 of COVID-19 cases, hospitalizations and deaths "
            "by age group and gender, Canada, 2020 to 2024."
        ),
        description_fr=(
            "Nombres et taux hebdomadaires pour 100 000 de cas, d'hospitalisations et de décès de "
            "COVID-19 par groupe d'âge et genre, Canada, 2020 à 2024."
        ),
        url_en=_LIVE + "covid19-epiSummary-ageGender.csv",
        frequency="archived",
        dashboard_en=_COVID,
        dashboard_fr=_COVID_FR,
        date_columns=("date",),
    ),
    Dataset(
        id="covid19_hospital_capacity",
        topic="covid19",
        title_en="COVID-19 and non-COVID hospital and ICU occupancy, daily (2020 to 2024)",
        title_fr="Occupation des lits d'hôpital et de soins intensifs, COVID-19 ou non (2020 à 2024)",
        description_en=(
            "Daily ICU and other bed capacity, ventilators, and patients with and without COVID-19 "
            "in hospital, ICU and on ventilation, Canada, April 2020 to March 2024."
        ),
        description_fr=(
            "Capacité quotidienne en lits de soins intensifs et autres, respirateurs, et patients "
            "avec ou sans COVID-19 à l'hôpital, aux soins intensifs et sous ventilation, Canada, "
            "d'avril 2020 à mars 2024."
        ),
        url_en=_LIVE + "covid19-epiSummary-hospVentICU.csv",
        frequency="archived",
        dashboard_en=_COVID,
        dashboard_fr=_COVID_FR,
        date_columns=("Date",),
    ),
    Dataset(
        id="covid19_vaccination_coverage",
        topic="covid19",
        title_en="COVID-19 vaccination coverage by province, weekly (2020 to 2024)",
        title_fr="Couverture vaccinale contre la COVID-19 par province (2020 à 2024)",
        description_en=(
            "Number and percent of people vaccinated (at least one dose, fully, additional doses, "
            "recommended vaccine) by province and territory, December 2020 to June 2024."
        ),
        description_fr=(
            "Nombre et pourcentage de personnes vaccinées (au moins une dose, série complète, "
            "doses supplémentaires, vaccin recommandé) par province et territoire, de décembre "
            "2020 à juin 2024."
        ),
        url_en=_LIVE + "vaccination-coverage-map.csv",
        frequency="archived",
        dashboard_en=_VAX,
        dashboard_fr=_VAX_FR,
        date_columns=("week_end",),
        geo_columns=("prename",),
        notes_en="'>=99' marks top-coded percentages; prfname holds French names.",
        notes_fr="« >=99 » marque les pourcentages plafonnés; prfname contient les noms français.",
    ),
    Dataset(
        id="covid19_vaccination_coverage_age_sex",
        topic="covid19",
        title_en="COVID-19 vaccination coverage by age and sex, weekly (2020 to 2024)",
        title_fr="Couverture vaccinale contre la COVID-19 par âge et sexe (2020 à 2024)",
        description_en=(
            "Number and percent vaccinated by province (PRUID code), age group and sex, "
            "December 2020 to June 2024."
        ),
        description_fr=(
            "Nombre et pourcentage de personnes vaccinées par province (code PRUID), groupe d'âge "
            "et sexe, de décembre 2020 à juin 2024."
        ),
        url_en=_LIVE + "vaccination-coverage-byAgeAndSexOTI.csv",
        frequency="archived",
        dashboard_en=_VAX,
        dashboard_fr=_VAX_FR,
        date_columns=("week_end",),
        geo_columns=("pruid",),
    ),
    Dataset(
        id="covid19_vaccine_doses_administered",
        topic="covid19",
        title_en="COVID-19 vaccine doses administered by province (2021 to 2023)",
        title_fr="Doses de vaccin contre la COVID-19 administrées par province (2021 à 2023)",
        description_en=(
            "Cumulative COVID-19 vaccine doses administered, total and by dose number, by "
            "province and territory, January 2021 to September 2023."
        ),
        description_fr=(
            "Doses cumulatives de vaccin contre la COVID-19 administrées, au total et par numéro "
            "de dose, par province et territoire, de janvier 2021 à septembre 2023."
        ),
        url_en=_LIVE + "vaccination-administration.csv",
        frequency="archived",
        dashboard_en=_VAX,
        dashboard_fr=_VAX_FR,
        date_columns=("report_date",),
        geo_columns=("prename",),
    ),
    Dataset(
        id="covid19_vaccine_doses_distributed",
        topic="covid19",
        title_en="COVID-19 vaccine doses distributed by product and province (2021 to 2023)",
        title_fr="Doses de vaccin contre la COVID-19 distribuées par produit et province",
        description_en=(
            "Cumulative COVID-19 vaccine doses distributed by product (Pfizer-BioNTech, Moderna "
            "and others) and province or federal allocation, January 2021 to July 2023."
        ),
        description_fr=(
            "Doses cumulatives de vaccin contre la COVID-19 distribuées par produit "
            "(Pfizer-BioNTech, Moderna et autres) et par province ou allocation fédérale, de "
            "janvier 2021 à juillet 2023."
        ),
        url_en=_LIVE + "vaccination-distribution.csv",
        frequency="archived",
        dashboard_en=_VAX,
        dashboard_fr=_VAX_FR,
        date_columns=("report_date",),
        geo_columns=("prename",),
    ),
    # Wastewater -------------------------------------------------------------
    Dataset(
        id="wastewater_weekly",
        topic="wastewater",
        title_en="Wastewater viral load by site, city and province, weekly",
        title_fr="Charge virale dans les eaux usées par site, ville et province, par semaine",
        description_en=(
            "Weekly average, minimum and maximum viral load of SARS-CoV-2 (covN2), influenza A "
            "(fluA), influenza B (fluB) and RSV (rsv) in wastewater by site, city, province and "
            "Canada, since 2022."
        ),
        description_fr=(
            "Charge virale hebdomadaire moyenne, minimale et maximale du SRAS-CoV-2 (covN2), de la "
            "grippe A (fluA), de la grippe B (fluB) et du VRS (rsv) dans les eaux usées par site, "
            "ville, province et Canada, depuis 2022."
        ),
        url_en="/src/data/wastewater/wastewater_aggregate.csv",
        frequency="weekly",
        dashboard_en=_WW,
        dashboard_fr=_WW_FR,
        date_columns=("weekstart",),
        geo_columns=("province",),
        notes_en="Filter measureid (covN2, fluA, fluB, rsv) and Location (site, city or 'Canada').",
        notes_fr="Filtrer measureid (covN2, fluA, fluB, rsv) et Location (site, ville ou Canada).",
    ),
    Dataset(
        id="wastewater_latest_trends",
        topic="wastewater",
        title_en="Latest wastewater viral activity level and trend by location",
        title_fr="Dernier niveau et tendance de l'activité virale dans les eaux usées par lieu",
        description_en=(
            "Latest trend (increasing, decreasing, no change) and viral activity level for each "
            "site, city, province and Canada and each virus measure."
        ),
        description_fr=(
            "Dernière tendance (hausse, baisse, aucun changement) et niveau d'activité virale pour "
            "chaque site, ville, province et le Canada, et pour chaque virus."
        ),
        url_en="/src/data/wastewater/wastewater_trend.csv",
        frequency="weekly",
        dashboard_en=_WW,
        dashboard_fr=_WW_FR,
        date_columns=("weekStart",),
        geo_columns=("province",),
    ),
    Dataset(
        id="wastewater_daily",
        topic="wastewater",
        title_en="Wastewater viral load by sampling site, daily",
        title_fr="Charge virale dans les eaux usées par site d'échantillonnage, par jour",
        description_en=(
            "Viral load and seven-day rolling average by sampling date, site and measure "
            "(covN2, fluA, fluB, rsv) and sample fraction."
        ),
        description_fr=(
            "Charge virale et moyenne mobile sur sept jours par date d'échantillonnage, site, "
            "mesure (covN2, fluA, fluB, rsv) et fraction de l'échantillon."
        ),
        url_en="/src/data/wastewater/wastewater_daily.csv",
        frequency="weekly",
        dashboard_en=_WW,
        dashboard_fr=_WW_FR,
        date_columns=("Date",),
        geo_columns=("pruid",),
    ),
    # Vaccine safety ---------------------------------------------------------
    Dataset(
        id="aefi_reports_by_seriousness",
        topic="vaccination",
        title_en="Adverse events following immunization: serious and non-serious reports by year",
        title_fr="Manifestations cliniques après la vaccination : déclarations graves et non graves",
        description_en=(
            "Count and percentage of serious and non-serious adverse event reports by year, for "
            "COVID-19, non-COVID-19 and all vaccines (CAEFISS), 2015 onward."
        ),
        description_fr=(
            "Nombre et pourcentage de déclarations de manifestations cliniques graves et non "
            "graves par année, pour les vaccins contre la COVID-19, les autres vaccins et "
            "l'ensemble (SCSESSI), depuis 2015."
        ),
        url_en=_AEFI_DATA + "figure1.csv",
        frequency="annual",
        dashboard_en=_AEFI,
        dashboard_fr=_AEFI_FR,
        date_columns=("Year",),
    ),
    Dataset(
        id="aefi_reports_by_age_sex",
        topic="vaccination",
        title_en="Adverse events following immunization by age group and sex",
        title_fr="Manifestations cliniques après la vaccination par groupe d'âge et sexe",
        description_en="Serious and non-serious adverse event reports by year, age group and sex.",
        description_fr=(
            "Déclarations de manifestations cliniques graves et non graves par année, groupe "
            "d'âge et sexe."
        ),
        url_en=_AEFI_DATA + "figure2.csv",
        frequency="annual",
        dashboard_en=_AEFI,
        dashboard_fr=_AEFI_FR,
        date_columns=("Year",),
    ),
    Dataset(
        id="aefi_reports_by_vaccine",
        topic="vaccination",
        title_en="Adverse events following immunization by vaccine",
        title_fr="Manifestations cliniques après la vaccination par vaccin",
        description_en=(
            "Serious and non-serious adverse event reports by year, vaccine group and vaccine "
            "(abbreviated names such as HPV, MMR, Zos)."
        ),
        description_fr=(
            "Déclarations de manifestations cliniques graves et non graves par année, groupe de "
            "vaccins et vaccin (abréviations anglaises telles que HPV, MMR, Zos)."
        ),
        url_en=_AEFI_DATA + "figure3.csv",
        frequency="annual",
        dashboard_en=_AEFI,
        dashboard_fr=_AEFI_FR,
        date_columns=("Year",),
        notes_en="'X' marks suppressed small counts.",
        notes_fr="« X » marque les petits nombres supprimés.",
    ),
    Dataset(
        id="aefi_top_adverse_events",
        topic="vaccination",
        title_en="Most frequently reported adverse events by vaccine",
        title_fr="Manifestations cliniques les plus souvent déclarées par vaccin",
        description_en=(
            "Most frequently reported adverse event terms (MedDRA preferred terms) for each "
            "vaccine, with counts and rank, by year and for all years."
        ),
        description_fr=(
            "Termes de manifestations cliniques les plus souvent déclarés (termes MedDRA) pour "
            "chaque vaccin, avec nombre et rang, par année et pour toutes les années."
        ),
        url_en=_AEFI_DATA + "figure4.csv",
        frequency="annual",
        dashboard_en=_AEFI,
        dashboard_fr=_AEFI_FR,
        date_columns=("Year",),
    ),
    # Substance use ----------------------------------------------------------
    Dataset(
        id="opioid_stimulant_harms",
        topic="substance_use",
        title_en="Opioid- and stimulant-related deaths, hospitalizations, ED visits and EMS",
        title_fr="Décès, hospitalisations, visites aux urgences et SMU liés aux opioïdes et stimulants",
        description_en=(
            "Apparent opioid and stimulant toxicity deaths, poisoning hospitalizations, emergency "
            "department visits and EMS responses by province, year or quarter, sex, age group, "
            "substance type and manner of death, since 2016: numbers, crude rates and percents."
        ),
        description_fr=(
            "Décès apparemment liés à une intoxication aux opioïdes et aux stimulants, "
            "hospitalisations, visites aux urgences et interventions des SMU par province, année "
            "ou trimestre, sexe, groupe d'âge, type de substance et type de décès, depuis 2016 : "
            "nombres, taux bruts et pourcentages."
        ),
        url_en="/src/data/substance-related-harms/download/HealthInfobase-SubstanceHarmsData.zip",
        url_fr="/src/data/substance-related-harms/download/SanteInfobase-DonneesMefaitsSubstances.zip",
        kind="zip",
        member_en="SubstanceHarmsData.csv",
        member_fr="DonneesMefaitsSubstances.csv",
        frequency="quarterly",
        dashboard_en=_HARMS,
        dashboard_fr=_HARMS_FR,
        date_columns=("Year_Quarter", "Année_Trimestre"),
        geo_columns=("Region", "Région"),
        notes_en=(
            "Filter Source (Deaths, Hospitalizations, ...), Specific_Measure, Unit (Number, "
            "Crude rate, Percent) and Time_Period (By year, By quarter). 'Suppr.' is suppressed, "
            "'n/a' not available."
        ),
        notes_fr=(
            "Filtrer Source, Mesure_Spéficique (orthographe du fichier), Unité et Période_Temps. "
            "« Suppr. » est supprimé, « n.d. » non disponible."
        ),
    ),
    Dataset(
        id="supervised_consumption_sites_trends",
        topic="substance_use",
        title_en="Supervised consumption sites: visits, clients and overdoses, monthly",
        title_fr="Sites de consommation supervisée : visites, clients et surdoses, par mois",
        description_en=(
            "Monthly national totals of visits, unique clients, non-fatal overdoses, overdoses "
            "treated with naloxone and sites reporting, since March 2020."
        ),
        description_fr=(
            "Totaux nationaux mensuels des visites, clients uniques, surdoses non mortelles, "
            "surdoses traitées à la naloxone et sites déclarants, depuis mars 2020."
        ),
        url_en=_SCS_DATA + "scs-visits-clients-trends.csv",
        frequency="quarterly",
        dashboard_en=_SCS,
        dashboard_fr=_SCS_FR,
        date_columns=("concat_y_m_d",),
    ),
    Dataset(
        id="supervised_consumption_sites_drugs",
        topic="substance_use",
        title_en="Supervised consumption sites: drugs used, monthly",
        title_fr="Sites de consommation supervisée : drogues consommées, par mois",
        description_en=(
            "Monthly number and percent of drugs used at supervised consumption sites (fentanyl, "
            "methamphetamine, heroin, cocaine, hydromorphone and others), national totals."
        ),
        description_fr=(
            "Nombre et pourcentage mensuels des drogues consommées dans les sites de consommation "
            "supervisée (fentanyl, méthamphétamine, héroïne, cocaïne, hydromorphone et autres), "
            "totaux nationaux."
        ),
        url_en=_SCS_DATA + "scs-drugsused.csv",
        frequency="quarterly",
        dashboard_en=_SCS,
        dashboard_fr=_SCS_FR,
        date_columns=("concat_y_m_d",),
    ),
    Dataset(
        id="supervised_consumption_sites_list",
        topic="substance_use",
        title_en="Supervised consumption sites: list with totals per site",
        title_fr="Sites de consommation supervisée : liste et totaux par site",
        description_en=(
            "Each supervised consumption site with city, province, coordinates and total and "
            "monthly-average visits, unique clients, non-fatal overdoses and referrals."
        ),
        description_fr=(
            "Chaque site de consommation supervisée avec ville, province, coordonnées et totaux et "
            "moyennes mensuelles des visites, clients uniques, surdoses non mortelles et "
            "orientations."
        ),
        url_en=_SCS_DATA + "scs-map.csv",
        frequency="quarterly",
        dashboard_en=_SCS,
        dashboard_fr=_SCS_FR,
        geo_columns=("province",),
        notes_en="The last row (province TOTAL) holds national totals.",
        notes_fr="La dernière ligne (province TOTAL) contient les totaux nationaux.",
    ),
    Dataset(
        id="csus_indicators",
        topic="substance_use",
        title_en="Canadian Substance Use Survey indicators (people aged 15+)",
        title_fr="Indicateurs de l'Enquête canadienne sur la consommation de substances (15 ans et +)",
        description_en=(
            "Weighted percentages and confidence limits for alcohol, cannabis, tobacco, vaping, "
            "opioid, stimulant and other drug use and harms, by cycle and breakdown (age, gender, "
            "province and others)."
        ),
        description_fr=(
            "Pourcentages pondérés et limites de confiance pour la consommation d'alcool, de "
            "cannabis, de tabac, de produits de vapotage, d'opioïdes, de stimulants et d'autres "
            "drogues et leurs méfaits, par cycle et ventilation (âge, genre, province et autres)."
        ),
        url_en="/src/data/substance-use/csus/CSUS-Bars.csv",
        url_fr="/src/data/substance-use/csus/FR-CSUS-Bars.csv",
        frequency="periodic",
        dashboard_en="/substance-use/csus/",
        dashboard_fr="https://sante-infobase.canada.ca/consommation-de-substances/eccs/",
        date_columns=("Cycle",),
        notes_en="About 20 MB; filter Topic, Indicator, Breakdown and BreakdownGroup.",
        notes_fr="Environ 20 Mo; filtrer Topic, Indicator, Breakdown et BreakdownGroup.",
    ),
    Dataset(
        id="cpads_indicators",
        topic="substance_use",
        title_en="Postsecondary student alcohol and drug use (CPADS)",
        title_fr="Alcool et drogues chez les étudiants du postsecondaire (ECCADEEP)",
        description_en=(
            "Weighted percentages for alcohol, cannabis, drug use and harms among postsecondary "
            "students by survey cycle and breakdown (Canadian Postsecondary Education Alcohol and "
            "Drug Use Survey)."
        ),
        description_fr=(
            "Pourcentages pondérés de consommation d'alcool, de cannabis et de drogues et de leurs "
            "méfaits chez les étudiants du postsecondaire par cycle et ventilation (Enquête "
            "canadienne sur la consommation d'alcool et de drogues chez les étudiants du "
            "postsecondaire)."
        ),
        url_en="/src/data/substance-use/cpads/CPADS.csv",
        url_fr="/src/data/substance-use/cpads/FR-CPADS.csv",
        frequency="periodic",
        dashboard_en="/substance-use/cpads/",
        dashboard_fr="https://sante-infobase.canada.ca/consommation-de-substances/eccadeep/",
        date_columns=("Cycle",),
    ),
    Dataset(
        id="csads_trends",
        topic="substance_use",
        title_en="Student alcohol and drug use, grades 7 to 12 (CSADS), trends",
        title_fr="Consommation d'alcool et de drogues des élèves de la 7e à la 12e année (ECADE)",
        description_en=(
            "Prevalence and confidence intervals of alcohol, cannabis, vaping and drug use among "
            "students in grades 7 to 12 by school year and subgroup (Canadian Student Alcohol and "
            "Drugs Survey)."
        ),
        description_fr=(
            "Prévalence et intervalles de confiance de la consommation d'alcool, de cannabis, de "
            "produits de vapotage et de drogues chez les élèves de la 7e à la 12e année par année "
            "scolaire et sous-groupe (Enquête canadienne sur l'alcool et les drogues chez les "
            "élèves)."
        ),
        url_en="/src/data/csads/trends.csv",
        url_fr="/src/data/csads/trends-fr.csv",
        frequency="periodic",
        dashboard_en="/substance-use/csads/",
        dashboard_fr="https://sante-infobase.canada.ca/consommation-de-substances/ecade/",
        date_columns=("School Year",),
    ),
    Dataset(
        id="tobacco_sales",
        topic="substance_use",
        title_en="Tobacco product sales by province, annual",
        title_fr="Ventes de produits du tabac par province, annuelles",
        description_en=(
            "Total annual sales volume of cigarettes, cigars, fine-cut and other tobacco products "
            "by province, 2001 onward, from manufacturer and importer reports."
        ),
        description_fr=(
            "Volume annuel total des ventes de cigarettes, cigares, tabac haché fin et autres "
            "produits du tabac par province, depuis 2001, selon les rapports des fabricants et "
            "importateurs."
        ),
        url_en="/src/data/tobacco-sales/reformatted_data_2025.csv",
        frequency="annual",
        dashboard_en="/substance-use/tobacco/sales/",
        dashboard_fr="https://sante-infobase.canada.ca/consommation-de-substances/tabac/ventes/",
        date_columns=("Year",),
        geo_columns=("prename",),
        notes_en="The file name carries the latest data year and changes with each release.",
        notes_fr="Le nom du fichier porte la dernière année de données et change à chaque diffusion.",
    ),
    # Infectious diseases ----------------------------------------------------
    Dataset(
        id="measles_weekly_by_province",
        topic="infectious_disease",
        title_en="Measles cases by week of rash onset and province, current year",
        title_fr="Cas de rougeole par semaine d'apparition de l'éruption et province, année en cours",
        description_en=(
            "Measles cases by epidemiological week of rash onset, one column per province "
            "('48: Alberta', PRUID prefixed) and Canada; last row TOTAL."
        ),
        description_fr=(
            "Cas de rougeole par semaine épidémiologique d'apparition de l'éruption, une colonne "
            "par province (« 48: Alberta », préfixe PRUID) et le Canada; dernière ligne TOTAL."
        ),
        url_en=_MEASLES_DATA + "figure2A-EpiCurvePT.csv",
        frequency="weekly",
        dashboard_en=_MEASLES,
        dashboard_fr=_MEASLES_FR,
    ),
    Dataset(
        id="measles_annual_cases",
        topic="infectious_disease",
        title_en="Measles cases by year since 1998",
        title_fr="Cas de rougeole par année depuis 1998",
        description_en="Number of confirmed measles cases in Canada each year since 1998.",
        description_fr="Nombre de cas confirmés de rougeole au Canada chaque année depuis 1998.",
        url_en=_MEASLES_DATA + "figure3-epi-curve-yearly.csv",
        frequency="weekly",
        dashboard_en=_MEASLES,
        dashboard_fr=_MEASLES_FR,
        date_columns=("Year",),
        notes_en="A final max_cases row holds the chart's axis maximum, not a year.",
        notes_fr="Une dernière ligne max_cases contient le maximum de l'axe, pas une année.",
    ),
    Dataset(
        id="measles_cases_by_province",
        topic="infectious_disease",
        title_en="Measles cases by province, current year",
        title_fr="Cas de rougeole par province, année en cours",
        description_en=(
            "New and total measles cases this year and the latest week of rash onset, by "
            "province and territory."
        ),
        description_fr=(
            "Nouveaux cas et total des cas de rougeole cette année et dernière semaine "
            "d'apparition de l'éruption, par province et territoire."
        ),
        url_en=_MEASLES_DATA + "geographic_distribution.csv",
        frequency="weekly",
        dashboard_en=_MEASLES,
        dashboard_fr=_MEASLES_FR,
        geo_columns=("pt_name",),
    ),
    Dataset(
        id="measles_case_characteristics",
        topic="infectious_disease",
        title_en="Measles case characteristics: age, vaccination, hospitalization, travel",
        title_fr="Caractéristiques des cas de rougeole : âge, vaccination, hospitalisation, voyage",
        description_en=(
            "Counts and percentages of this year's measles cases by age group, sex, vaccination "
            "status, hospitalization, death and exposure, in English and French columns."
        ),
        description_fr=(
            "Nombres et pourcentages des cas de rougeole de l'année par groupe d'âge, sexe, statut "
            "vaccinal, hospitalisation, décès et exposition, colonnes anglaises et françaises."
        ),
        url_en=_MEASLES_DATA + "demographics.csv",
        frequency="weekly",
        dashboard_en=_MEASLES,
        dashboard_fr=_MEASLES_FR,
    ),
    Dataset(
        id="measles_outbreaks",
        topic="infectious_disease",
        title_en="Measles outbreaks by province",
        title_fr="Éclosions de rougeole par province",
        description_en=(
            "Measles outbreaks with start and end dates, total, confirmed and probable cases per "
            "province and a status description in English and French."
        ),
        description_fr=(
            "Éclosions de rougeole avec dates de début et de fin, cas totaux, confirmés et "
            "probables par province et description de la situation en français et en anglais."
        ),
        url_en=_MEASLES_DATA + "outbreaks.csv",
        frequency="weekly",
        dashboard_en=_MEASLES,
        dashboard_fr=_MEASLES_FR,
        date_columns=("date_start",),
        geo_columns=("province",),
    ),
    Dataset(
        id="mpox_cases_by_province",
        topic="infectious_disease",
        title_en="Mpox cases by province and year",
        title_fr="Cas de mpox par province et année",
        description_en="Mpox cases by province and territory, per year since 2022 and all years.",
        description_fr=(
            "Cas de mpox par province et territoire, par année depuis 2022 et toutes années "
            "confondues."
        ),
        url_en="/src/data/mpox/mpox_geographic_spread.csv",
        frequency="periodic",
        dashboard_en="/mpox/",
        dashboard_fr="https://sante-infobase.canada.ca/mpox/",
        date_columns=("Year",),
        geo_columns=("PT",),
        notes_en="Year 'All' rows hold totals since 2022.",
        notes_fr="Les lignes Year « All » contiennent les totaux depuis 2022.",
    ),
    Dataset(
        id="mpox_cases_by_age_gender",
        topic="infectious_disease",
        title_en="Mpox cases by age group and gender",
        title_fr="Cas de mpox par groupe d'âge et genre",
        description_en=(
            "Mpox cases and row percentages by year, age group and gender, English and French "
            "labels in the same file."
        ),
        description_fr=(
            "Cas de mpox et pourcentages par année, groupe d'âge et genre, libellés français et "
            "anglais dans le même fichier."
        ),
        url_en="/src/data/mpox/mpox_cases.zip",
        kind="zip",
        member_en="mpox_demographics.csv",
        frequency="periodic",
        dashboard_en="/mpox/",
        dashboard_fr="https://sante-infobase.canada.ca/mpox/",
        date_columns=("Year",),
    ),
    Dataset(
        id="tuberculosis_incidence_by_province",
        topic="infectious_disease",
        title_en="Tuberculosis cases and incidence by province, 2015 to 2024",
        title_fr="Cas et incidence de la tuberculose par province, 2015 à 2024",
        description_en=(
            "Active tuberculosis cases and incidence per 100,000 by province and territory "
            "(two-letter codes) and Canada, 2015 to 2024."
        ),
        description_fr=(
            "Cas de tuberculose active et incidence pour 100 000 habitants par province et "
            "territoire (codes à deux lettres) et Canada, 2015 à 2024."
        ),
        url_en=_TB_DATA + "TB_incidence_by_PT_2015-2024.csv",
        frequency="annual",
        dashboard_en=_TB,
        dashboard_fr=_TB_FR,
        date_columns=("surveillance_year",),
        geo_columns=("province_territory",),
        notes_en="The file name carries the year range and changes with each annual release.",
        notes_fr="Le nom du fichier porte les années couvertes et change chaque année.",
    ),
    Dataset(
        id="tuberculosis_incidence_by_population",
        topic="infectious_disease",
        title_en="Tuberculosis incidence by birthplace and Indigenous identity",
        title_fr="Incidence de la tuberculose selon le lieu de naissance et l'identité autochtone",
        description_en=(
            "Tuberculosis cases, population and incidence per 100,000 by year for people born "
            "outside Canada, Inuit, First Nations, Métis and Canadian-born non-Indigenous people."
        ),
        description_fr=(
            "Cas de tuberculose, population et incidence pour 100 000 par année chez les "
            "personnes nées à l'étranger, les Inuit, les Premières Nations, les Métis et les "
            "personnes non autochtones nées au Canada."
        ),
        url_en=_TB_DATA + "TB_incidence_by_population_over_time.csv",
        frequency="annual",
        dashboard_en=_TB,
        dashboard_fr=_TB_FR,
        date_columns=("surveillance_year",),
    ),
    Dataset(
        id="tuberculosis_drug_resistance",
        topic="infectious_disease",
        title_en="Tuberculosis drug resistance by year",
        title_fr="Pharmacorésistance de la tuberculose par année",
        description_en=(
            "Number and percent of tuberculosis isolates resistant to at least one first-line "
            "drug, isoniazid, MDR-TB and XDR-TB, by year."
        ),
        description_fr=(
            "Nombre et pourcentage d'isolats de tuberculose résistants à au moins un médicament "
            "de première intention, à l'isoniazide, TB-MR et TB-UR, par année."
        ),
        url_en=_TB_DATA + "TB_resistance_over_time.csv",
        frequency="annual",
        dashboard_en=_TB,
        dashboard_fr=_TB_FR,
        date_columns=("surveillance_year",),
    ),
    Dataset(
        id="emerging_respiratory_pathogens",
        topic="infectious_disease",
        title_en="Human cases of avian influenza, MERS and other emerging respiratory pathogens",
        title_fr="Cas humains de grippe aviaire, de SRMO et d'autres pathogènes respiratoires émergents",
        description_en=(
            "Cumulative human cases, deaths and case fatality of avian influenza subtypes (H5N1, "
            "H7N9, H9N2 and others), swine-origin variants and MERS-CoV by country, with the "
            "date of the last report."
        ),
        description_fr=(
            "Cas humains cumulés, décès et létalité des sous-types de grippe aviaire (H5N1, H7N9, "
            "H9N2 et autres), des variants d'origine porcine et du SRMO-CoV par pays, avec la "
            "date du dernier signalement."
        ),
        url_en="/src/data/human-emerging-respiratory-pathogens/Summary_of_cases.csv",
        frequency="monthly",
        dashboard_en="/human-emerging-respiratory-pathogens-bulletin/",
        dashboard_fr=(
            "https://sante-infobase.canada.ca/bulletin-agents-pathogenes-voies-respiratoires-emergents/"
        ),
        geo_columns=("country",),
    ),
    Dataset(
        id="enteric_outbreaks",
        topic="infectious_disease",
        title_en="Foodborne and enteric illness outbreak investigations, 2008 to 2024",
        title_fr="Enquêtes sur les éclosions de maladies entériques et d'origine alimentaire",
        description_en=(
            "National outbreak investigations with year, onset month, cases, hospitalizations, "
            "deaths, pathogen, and the food source when identified."
        ),
        description_fr=(
            "Enquêtes nationales sur les éclosions avec année, mois d'apparition, cas, "
            "hospitalisations, décès, pathogène et source alimentaire lorsqu'elle est connue."
        ),
        url_en=(
            "/src/data/enteric-outbreak-summaries/"
            "outbreaksummaries_registreeclosions_2008-2024english.csv"
        ),
        frequency="annual",
        dashboard_en="/enteric-illness/outbreaks/",
        dashboard_fr="https://sante-infobase.canada.ca/maladies-enteriques/eclosions/",
        date_columns=("year_dv",),
        notes_en="Windows-1252 encoded; the last row holds totals.",
        notes_fr="Encodé en Windows-1252; la dernière ligne contient les totaux.",
    ),
    Dataset(
        id="notifiable_diseases_annual",
        topic="infectious_disease",
        title_en="Nationally notifiable diseases: reported cases and rates, 1924 to 2016",
        title_fr="Maladies à déclaration obligatoire : cas déclarés et taux, 1924 à 2016",
        description_en=(
            "Annual reported cases and rates per 100,000 for each nationally notifiable disease "
            "(Canadian Notifiable Disease Surveillance System), 1924 to 2016."
        ),
        description_fr=(
            "Cas déclarés et taux annuels pour 100 000 habitants de chaque maladie à déclaration "
            "obligatoire (Système canadien de surveillance des maladies à déclaration "
            "obligatoire), de 1924 à 2016."
        ),
        url_en="https://health.canada.ca/apps/open-data/cndss/extract-1924-2016-en.csv",
        url_fr="https://health.canada.ca/apps/open-data/cndss/extract-1924-2016-fr.csv",
        frequency="archived",
        dashboard_en="https://diseases.canada.ca/notifiable/",
        dashboard_fr="https://maladies.canada.ca/declaration-obligatoire/",
        date_columns=("year", "annee"),
        notes_en=(
            "Notifiable Diseases Online shows data to 2023, but only inside its page scripts; "
            "this 1924-2016 extract is the latest file."
        ),
        notes_fr=(
            "Maladies à déclaration obligatoire en ligne affiche des données jusqu'en 2023, mais "
            "seulement dans ses scripts; cet extrait 1924-2016 est le fichier le plus récent."
        ),
    ),
    Dataset(
        id="hepatitis_c_treatment",
        topic="infectious_disease",
        title_en="People treated for hepatitis C by province, sex and year",
        title_fr="Personnes traitées contre l'hépatite C par province, sexe et année",
        description_en=(
            "Number of people starting hepatitis C antiviral treatment by province (two-letter "
            "codes and Total), sex and year, since 2018."
        ),
        description_fr=(
            "Nombre de personnes commençant un traitement antiviral contre l'hépatite C par "
            "province (codes à deux lettres et Total), sexe et année, depuis 2018."
        ),
        url_en="/src/data/hepatitis-c-treatment/hcvData.csv",
        frequency="annual",
        dashboard_en="/hepatitis-c-treatment/",
        dashboard_fr="https://sante-infobase.canada.ca/traitement-hepatite-c/",
        date_columns=("Year",),
        geo_columns=("Province",),
    ),
    # Chronic disease -------------------------------------------------------
    Dataset(
        id="ccdi_indicators_2018",
        topic="chronic_disease",
        title_en="Canadian Chronic Disease Indicators (CCDI), 2018 edition",
        title_fr="Indicateurs des maladies chroniques au Canada (IMCC), édition 2018",
        description_en=(
            "About 90 chronic disease indicators (determinants, risk factors, prevalence and "
            "incidence of diabetes, cancer, heart disease, COPD and others, health outcomes) with "
            "the latest value, 95% confidence interval and data source."
        ),
        description_fr=(
            "Environ 90 indicateurs de maladies chroniques (déterminants, facteurs de risque, "
            "prévalence et incidence du diabète, du cancer, des cardiopathies, de la MPOC et "
            "autres, résultats de santé) avec la valeur la plus récente, l'intervalle de "
            "confiance à 95 % et la source."
        ),
        url_en="/open/CCDI%202018%20Data%20File%20Open%20Data%20EN%20Nov%207,%202018.csv",
        url_fr="/open/CCDI%202018%20Data%20File%20Open%20Data%20FR%20Nov%207,%202018.csv",
        frequency="archived",
        dashboard_en="/ccdi/",
        notes_en=(
            "Windows-1252; footnote rows at the end. The live CCDI and CCDSS data tools publish "
            "no downloadable file; this 2018 snapshot is the latest."
        ),
        notes_fr=(
            "Windows-1252; notes en fin de fichier. Le fichier français utilise la virgule "
            "décimale (12,2). Les outils IMCC et SCSMC en ligne ne publient aucun fichier."
        ),
    ),
    Dataset(
        id="canadian_cancer_statistics",
        topic="chronic_disease",
        title_en="Canadian cancer data tool: incidence, mortality and survival by cancer type",
        title_fr="Outil de données sur le cancer : incidence, mortalité et survie par type",
        description_en=(
            "New cases, incidence and mortality rates, survival and prevalence by cancer type, "
            "year, age group and sex from the Canadian Cancer Registry and vital statistics."
        ),
        description_fr=(
            "Nouveaux cas, taux d'incidence et de mortalité, survie et prévalence par type de "
            "cancer, année, groupe d'âge et sexe, selon le Registre canadien du cancer et la "
            "statistique de l'état civil."
        ),
        url_en="/src/data/ccdt/ccs12.csv",
        frequency="archived",
        dashboard_en="/ccdt/",
        dashboard_fr="https://sante-infobase.canada.ca/odcc/",
        notes_en="Filter Cancer Type, Measure and Breakdown; Disaggregation holds the year or group.",
        notes_fr="Fichier en anglais seulement; filtrer Cancer Type, Measure et Breakdown.",
    ),
    Dataset(
        id="congenital_anomalies",
        topic="chronic_disease",
        title_en="Congenital anomalies in Canada: births and rates by condition, 2005 to 2014",
        title_fr="Anomalies congénitales au Canada : naissances et taux par anomalie, 2005 à 2014",
        description_en=(
            "Number and rate per 10,000 total births with 95% confidence intervals for neural "
            "tube defects, oral clefts, Down syndrome and other congenital anomalies by year."
        ),
        description_fr=(
            "Nombre et taux pour 10 000 naissances totales avec intervalles de confiance à 95 % "
            "pour les anomalies du tube neural, les fentes orales, le syndrome de Down et d'autres "
            "anomalies congénitales par année."
        ),
        url_en="/open/CA%20data%20English.csv",
        url_fr="/open/CA%20data%20French.csv",
        encoding_fr="cp850",
        frequency="archived",
        dashboard_en="/congenital-anomalies/data-tool/",
        date_columns=("Year",),
        notes_fr="Le fichier français est encodé en page de codes DOS 850 (décodé ici).",
    ),
    # Health status -----------------------------------------------------------
    Dataset(
        id="health_of_people_in_canada",
        topic="health_status",
        title_en="Health of People in Canada dashboard indicators",
        title_fr="Indicateurs du tableau de bord sur la santé des personnes au Canada",
        description_en=(
            "Health status, determinants and outcome indicators (obesity, life expectancy, "
            "chronic conditions, mental health, substance use) for Canada and provinces by sex, "
            "age, income and education, with confidence intervals."
        ),
        description_fr=(
            "Indicateurs d'état de santé, de déterminants et de résultats (obésité, espérance de "
            "vie, maladies chroniques, santé mentale, consommation de substances) pour le Canada "
            "et les provinces par sexe, âge, revenu et scolarité, avec intervalles de confiance."
        ),
        url_en="/src/data/hopic/HoPiC-data-2026.zip",
        kind="zip",
        member_en="IndicatorData",
        frequency="annual",
        dashboard_en="/health-of-people-in-canada-dashboard/",
        dashboard_fr=(
            "https://sante-infobase.canada.ca/tableau-de-bord-sur-la-sante-des-personnes-au-canada/"
        ),
        date_columns=("SingleYear_TimeFrame", "MultiYear_TimeFrame"),
        geo_columns=("Geography",),
        notes_en="The ZIP name carries the edition year and changes with each release.",
        notes_fr="Fichier en anglais seulement; le nom du ZIP change à chaque édition.",
    ),
    Dataset(
        id="risk_factor_atlas",
        topic="health_status",
        title_en="Canadian risk factor atlas: obesity, smoking, drinking and more by area",
        title_fr="Atlas canadien des facteurs de risque : obésité, tabagisme, alcool et plus",
        description_en=(
            "Crude and age-standardized prevalence of obesity, smoking, heavy drinking, physical "
            "inactivity, perceived health and other risk factors by province, health region and "
            "large urban area, age group and sex, 2015-2018."
        ),
        description_fr=(
            "Prévalence brute et normalisée selon l'âge de l'obésité, du tabagisme, de la "
            "consommation excessive d'alcool, de l'inactivité physique, de la santé perçue et "
            "d'autres facteurs de risque par province, région sociosanitaire et grande région "
            "urbaine, groupe d'âge et sexe, 2015-2018."
        ),
        url_en="/src/data/riskFactorAtlas/Map_Data_File.csv",
        frequency="archived",
        dashboard_en="/canadian-risk-factor-atlas/",
        dashboard_fr="https://sante-infobase.canada.ca/atlas-facteurs-risque-canada/",
        date_columns=("Year",),
        geo_columns=("Geo_Label",),
        notes_en="Geo_Label holds upper-case names (ALBERTA) and health region names.",
        notes_fr="Fichier en anglais; Geo_Label contient des noms en majuscules (ALBERTA).",
    ),
    Dataset(
        id="pass_indicators_2018",
        topic="health_status",
        title_en="Physical activity, sedentary behaviour and sleep indicators (PASS), 2018",
        title_fr="Indicateurs de l'activité physique, du comportement sédentaire et du sommeil, 2018",
        description_en=(
            "Physical activity, sedentary behaviour and sleep indicators for children, youth and "
            "adults with value, 95% confidence interval and data source, 2018 edition."
        ),
        description_fr=(
            "Indicateurs de l'activité physique, du comportement sédentaire et du sommeil chez "
            "les enfants, les jeunes et les adultes avec valeur, intervalle de confiance à 95 % "
            "et source, édition 2018."
        ),
        url_en="/open/PASS%202018%20Data%20File%20Open%20Data%20EN%20Nov%207.csv",
        url_fr="/open/PASS%202018%20Data%20File%20Open%20Data%20FR%20Nov%207.csv",
        frequency="archived",
        dashboard_en="/pass/",
        dashboard_fr="https://sante-infobase.canada.ca/apcss/",
        notes_fr="Windows-1252; le fichier français utilise la virgule décimale (24,1).",
    ),
    Dataset(
        id="positive_mental_health_adults",
        topic="health_status",
        title_en="Positive mental health surveillance indicators for adults, 2019 snapshot",
        title_fr="Indicateurs de surveillance de la santé mentale positive chez les adultes, 2019",
        description_en=(
            "Positive mental health outcomes and determinants for adults (self-rated mental "
            "health, life satisfaction, social support and others) by sex, age, income and "
            "province, with confidence intervals and data quality flags."
        ),
        description_fr=(
            "Résultats et déterminants de la santé mentale positive chez les adultes (santé "
            "mentale autoévaluée, satisfaction à l'égard de la vie, soutien social et autres) par "
            "sexe, âge, revenu et province, avec intervalles de confiance et indicateurs de "
            "qualité."
        ),
        url_en="/open/Outputs_Adults_EN_Final.csv",
        url_fr="/open/Outputs_Adults_FR_Final.csv",
        frequency="archived",
        dashboard_en="/positive-mental-health/",
        notes_en="Windows-1252. The live indicator framework tool publishes no newer file.",
        notes_fr="Windows-1252; le fichier français fait 16 Mo à cause de colonnes vides.",
    ),
)

BY_ID: dict[str, Dataset] = {d.id: d for d in DATASETS}
