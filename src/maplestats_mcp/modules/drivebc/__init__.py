"""DriveBC road events (BC Ministry of Transportation and Transit, Open511 API).

`api.open511.gov.bc.ca` serves DriveBC's implementation of the Open511
standard: the active road events on provincial highways (construction and
maintenance, incidents, road conditions), the 11 Ministry districts
("areas") and the jurisdiction record. No key is needed.

Confirmed live 2026-10-03, not taken from the help page alone:

1. Licence. The BC Data Catalogue record `open511-drivebc-api` and the API
   help page both put the data under the Open Government Licence - British
   Columbia; the API itself is under the BC Government API Terms of Use,
   which ask users to acknowledge the source as the licence sets out. The
   DriveBC website's own `www.drivebc.ca/api` is a different service under
   an access-only licence and is not used.
2. 239 active events in one response with `limit=500` (the documented
   maximum; the default page is 50). The response has no total count, only
   `pagination.offset`, so the client pages until a short page comes back.
   Event types seen: CONSTRUCTION (211), INCIDENT (17), ROAD_CONDITION (11);
   severities MINOR and MAJOR; every event has `roads` and `areas` lists,
   a `schedule.intervals` list of ISO 8601 intervals with an open end
   (`2026-09-24T18:02/`), and Point or LineString geography.
3. The host rate-limits hard: requests two to three seconds apart
   alternated between HTTP 200 and an HTML "429 - Too Many Requests" page
   with no Retry-After. The client therefore makes one request every five
   seconds at most, fetches the whole active list once and filters it in
   memory (cached three minutes), rather than passing each filter upstream.
4. Field names starting with `+` (`+ivr_message`, `+linear_reference_km`)
   are DriveBC extensions; `+ivr_message` repeats `description`.
5. Content is English only (the jurisdiction lists `languages: ["en"]`).
"""

MODULE_NAME = "drivebc"
MODULE_DESCRIPTION = (
    "DriveBC road events on British Columbia's provincial highways (Open511 API, "
    "Open Government Licence - British Columbia): active construction and maintenance, "
    "incidents and road conditions with severity, road, direction, lane state, schedule "
    "and location, filtered by type, severity, district, highway, bounding box or text; "
    "one event in full with its geometry; counts by type, severity, district or road; "
    "and the 11 Ministry districts. English only."
)
MODULE_DESCRIPTION_FR = (
    "Événements routiers de DriveBC sur les routes provinciales de la "
    "Colombie-Britannique (API Open511, Licence du gouvernement ouvert – "
    "Colombie-Britannique) : travaux et entretien en cours, incidents et état des "
    "routes avec gravité, route, direction, état des voies, horaire et emplacement, "
    "filtrés par type, gravité, district, route, zone ou texte ; un événement complet "
    "avec sa géométrie ; décomptes par type, gravité, district ou route ; et les 11 "
    "districts du ministère. Contenu en anglais seulement."
)
