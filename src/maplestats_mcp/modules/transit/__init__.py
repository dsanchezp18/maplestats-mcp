"""Static GTFS schedule feeds of Canadian transit agencies (generic, config-driven).

One module for every agency that publishes an open static GTFS zip with
no key: an agency is one entry in `constants.AGENCIES`, not a new
module (the same rule as the ArcGIS Hub, Socrata and CKAN families).
Edmonton's real-time feeds stay in `ets_*`.

Terms checked live 2026-10-01: TTC (Open Government Licence - Toronto),
STM (CC BY 4.0), OC Transpo (City of Ottawa open data terms) and Calgary
Transit (Open Government Licence - City of Calgary) permit reuse and
redistribution with attribution. TransLink is not included: its terms
require users to identify themselves to TransLink and reserve the right to
impose conditions, which a public server cannot satisfy (docs/ROADMAP.md).

Confirmed live 2026-10-01 (see docs/ROADMAP.md for the full table):

1. Every included zip answers `Accept-Ranges: bytes` and HTTP 206, so
   the central directory and any one file can be read without
   downloading the archive. `stop_times.txt` is the exception in size
   (tens of MB compressed) and is the only
   file that has to be scanned; it is streamed in 4 MB ranges, inflated
   incrementally and filtered line by line, so memory stays flat and
   only the matching rows are kept.
2. A feed may omit `calendar.txt` (service then comes from
   `calendar_dates.txt` alone); a missing optional file is treated as
   empty, not as an error.
3. GTFS times run past 24:00:00 for trips after midnight; a departure
   at 25:10:00 on service day D leaves at 01:10 on D+1, so a day's
   listing also takes the previous service day's after-midnight trips.
"""

MODULE_NAME = "transit"
MODULE_DESCRIPTION = (
    "Static GTFS schedules of open Canadian transit agencies (TTC, STM bus, OC "
    "Transpo, Calgary Transit): list agencies and feeds, search "
    "routes and stops, a stop's scheduled departures on a date, and a route's trips "
    "and frequency by hour. Read on demand from the agency's own zip by HTTP range; "
    "nothing is stored."
)
MODULE_DESCRIPTION_FR = (
    "Horaires GTFS statiques d'organismes de transport en commun canadiens à données "
    "ouvertes (TTC, STM autobus, OC Transpo, Calgary Transit) : "
    "liste des organismes et des flux, recherche de lignes et d'arrêts, passages "
    "prévus à un arrêt à une date donnée, et nombre de voyages et fréquence horaire "
    "d'une ligne. Lus à la demande dans le zip de l'organisme, par plages HTTP; rien "
    "n'est conservé."
)
