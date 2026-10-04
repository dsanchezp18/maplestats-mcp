"""Static GTFS schedule feeds of Canadian transit agencies (generic, config-driven).

One module for every agency that publishes an open static GTFS zip with
no key: an agency is one entry in `constants.AGENCIES`, not a new
module (the same rule as the ArcGIS Hub, Socrata and CKAN families).
Edmonton's real-time feeds stay in `ets_*`.

Added 2026-10-02: VIA Rail (Open Government Licence - Canada), GO Transit and
UP Express (Open Government Licence - Ontario - Metrolinx) and twelve BC
Transit systems (BC Transit's open-data terms: limited, revocable,
non-exclusive licence to use, reproduce and redistribute, with attribution).
BC Transit's host builds each zip on request and answers neither HEAD nor
Range, so those agencies set `range_requests=False` and are read from a whole
download held in memory, one file on demand from the link BC Transit
publishes for developers (see docs/findings/municipal-sources.md).

National dataset (2026-10-02): Statistics Canada's Canadian Public Transit
Network Database (23-26-0003, version 1.0 released 2025-01-31, corrected
2025-05-07), 138 feeds compiled from the agencies' own open data. The archive
is one 443 MB zip with a nested `gtfs/<id>/gtfs.zip` per feed, so a feed is
fetched in 16 MB ranges, inflated into memory (bounded at 60 MB) and then
read like a BC Transit zip; the agency key is `national:<id>`. Terms read live:
the product page says the database "is available under the Open Government
License - Canada" and the metadata report that "the data are released under an
Open Government Licence"; the Statistics Canada Open Licence grants a
worldwide, royalty-free licence to "use, reproduce, publish, freely distribute,
or sell the Information" with a source notice, while "intellectual property
rights that third parties may have in the Information shall remain their
property", so every response carries the agency's own licence page and
attribution from data_sources.csv. The module reads the zip and makes one
request every two seconds to www150.statcan.gc.ca. Feeds that overlap a
live agency are listed but refused, TransLink is excluded for its terms, and
feeds with neither a licence page nor an attribution line are excluded.

Quebec regional and ferry feeds (2026-10-03), all listed on Données Québec
under CC BY 4.0: exo's commuter trains and ten bus sectors (exo's eleventh,
citrous, still publishes a 2023 schedule and is left out), RTC Québec City,
STL Laval, STS Sherbrooke, STQ ferries, Trois-Rivières, Rimouski,
Rouyn-Noranda and Salaberry-de-Valleyfield. The agencies' own terms add to
that record in two cases: the RTC asks for a credit line naming the feed's
update date, and the STL's GTFS terms bar commercial use without its written
permission. Their current files are newer than StatCan's 2025 snapshot, so the
same agencies in the national database are marked as served live. The STQ host
serves no byte ranges (a 71 KB zip, read whole).

Terms checked live 2026-10-01: STM (CC BY 4.0), OC Transpo (City of
Ottawa open data terms) and Calgary Transit (Open Government Licence - City
of Calgary) permit reuse and redistribution with attribution. TransLink is
not included: its terms require users to identify themselves to TransLink
and reserve the right to impose conditions, which a public server cannot
satisfy (docs/ROADMAP.md). The Toronto Transit Commission's own download
was removed on 2026-10-03 (not available for automated access under its
terms); its feed in the national database, which records the Open
Government Licence - Toronto and an attribution line for it, is served
like any other national feed.

Confirmed live 2026-10-01 (see docs/ROADMAP.md for the full table):

1. Every included zip except BC Transit's answers HTTP 206, so
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
    "Static GTFS schedules of open Canadian transit agencies (STM bus, OC "
    "Transpo, Calgary Transit, VIA Rail, GO Transit, UP Express, 12 BC Transit "
    "systems, and in Quebec exo trains and buses, RTC, STL, STS, STQ ferries and five "
    "smaller networks, plus about 100 more agencies from Statistics Canada's 2025 Canadian Public "
    "Transit Network Database): list agencies and feeds, search routes and stops, a stop's scheduled "
    "departures on a date, and a route's trips and frequency by hour. Read on demand "
    "from the agency's own zip by HTTP range (BC Transit's host cannot serve ranges, "
    "so its zips are downloaded whole and held in memory for ten minutes); nothing is "
    "written to disk."
)
MODULE_DESCRIPTION_FR = (
    "Horaires GTFS statiques d'organismes de transport en commun canadiens à données "
    "ouvertes (STM autobus, OC Transpo, Calgary Transit, VIA Rail, GO Transit, "
    "UP Express, 12 réseaux de BC Transit et, au Québec, les trains et autobus d'exo, le "
    "RTC, la STL, la STS, les traversiers de la STQ et cinq réseaux régionaux, plus une centaine d'autres organismes de la "
    "Base de données du réseau de transport en commun canadien de Statistique Canada, 2025) : "
    "liste des organismes et des flux, recherche de lignes et d'arrêts, passages "
    "prévus à un arrêt à une date donnée, et nombre de voyages et fréquence horaire "
    "d'une ligne. Lus à la demande dans le zip de l'organisme, par plages HTTP (l'hôte "
    "de BC Transit n'offre pas les plages : ses zips sont téléchargés en entier et "
    "gardés en mémoire dix minutes) ; rien n'est écrit sur le disque."
)
