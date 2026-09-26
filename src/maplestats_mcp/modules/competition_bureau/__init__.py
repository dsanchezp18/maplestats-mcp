"""Competition Bureau Canada: the merger-review reports.

The Bureau publishes no open data files (open.canada.ca holds only a link
to the report page, checked 2026-09-25), but its two merger-review
reports are complete HTML tables: the weekly report of reviews opened
since November 2023, ongoing and concluded, and the archived monthly
report of reviews concluded from January 2015 to April 2023. This
module reads both. The Competition Tribunal's decisions site refuses
automated requests (HTTP 403), and enforcement actions and market
studies are news releases and PDFs, so they are not covered.
"""

MODULE_NAME = "competition_bureau"
MODULE_DESCRIPTION = (
    "Competition Bureau Canada merger reviews (competition-bureau.canada.ca, tools "
    "prefixed competition_bureau_): every merger review the Bureau reports, from the "
    "weekly report (about 830 reviews opened since November 2023, ongoing and "
    "concluded) and the archived monthly report (about 1,725 reviews concluded "
    "January 2015 to April 2023). Each review has the parties, opened and concluded "
    "dates (month only in the archive), the NAICS industry code and the outcome: "
    "advance ruling certificate, no action letter, consent agreement, judicial "
    "decision, abandoned, other, or ongoing. Search by party name, NAICS prefix, "
    "outcome and date. Parties may ask to keep a transaction off the report, and "
    "May-October 2023 is covered by neither page."
)
MODULE_DESCRIPTION_FR = (
    "Examens de fusions du Bureau de la concurrence du Canada (outils préfixés "
    "competition_bureau_) : le rapport hebdomadaire (environ 830 examens ouverts "
    "depuis novembre 2023, en cours et conclus) et le rapport mensuel archivé "
    "(environ 1 725 examens conclus de janvier 2015 à avril 2023). Chaque examen "
    "indique les parties, les dates, le code SCIAN et le résultat (certificat de "
    "décision préalable, lettre de non-intervention, consentement, décision "
    "judiciaire, transaction abandonnée, autre ou en cours). Recherche par partie, "
    "préfixe SCIAN, résultat et date."
)
