"""CBSA Customs Tariff: the Departmental Consolidation of the Customs Tariff schedule.

CBSA publishes each edition of the tariff (one per amendment, several a
year) as a Microsoft Access database in English and French; this module
reads it once into Parquet and answers lookups by tariff number and
searches by words or chapter. A separate module from `cbsa` (border wait
times) because it is a different publication with its own terms and
storage. Checked live 2026-10-26; see client.py and accdb.py.
"""

MODULE_NAME = "cbsa_tariff"
MODULE_DESCRIPTION = (
    "Canada's Customs Tariff from the Canada Border Services Agency, tools prefixed "
    "cbsa_tariff_: every heading, tariff item and 10-digit classification number of "
    "chapters 1-99 with its description, unit of measure and rates under each tariff "
    "treatment (Most-Favoured-Nation, General Tariff, and preferential rates under CUSMA, "
    "CETA, CPTPP, the UK, Korea and other agreements), for the edition in force today or on "
    "a past date back to 2018, in English or French. Pairs with cimt_ trade volumes by HS "
    "code. CBSA terms: non-commercial reuse with attribution."
)
MODULE_DESCRIPTION_FR = (
    "Le Tarif des douanes du Canada, de l'Agence des services frontaliers du Canada (ASFC), "
    "outils préfixés cbsa_tariff_ : chaque position, numéro tarifaire et numéro de classement "
    "à 10 chiffres des chapitres 1 à 99 avec sa description, son unité de mesure et ses taux "
    "selon chaque traitement tarifaire (nation la plus favorisée, tarif général, et taux "
    "préférentiels de l'ACEUM, de l'AECG, du PTPGP, du Royaume-Uni, de la Corée et d'autres "
    "accords), pour l'édition en vigueur aujourd'hui ou à une date passée depuis 2018, en "
    "français ou en anglais. Se combine avec les volumes d'échanges par code SH de cimt_. "
    "Conditions de l'ASFC : réutilisation non commerciale avec mention de la source."
)
