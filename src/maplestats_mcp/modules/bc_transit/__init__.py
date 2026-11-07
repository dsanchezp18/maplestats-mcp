"""BC Transit GTFS-Realtime feeds (bct.tmix.se/gtfs-realtime).

BC Transit's static schedules are already served by `transit_*` (agency
keys `bct_victoria` and so on); this module reads the real-time feeds that
bctransit.com/open-data links for the same systems. They are Protocol
Buffers, decoded with `gtfs-realtime-bindings` as in `modules/ets/`.

Confirmed live 2026-11-07 (Victoria, operator id 48, and all eleven other
systems the static module covers):

1. Three feeds, all anonymous, each taking `?operatorIds=N`:
   `alerts.pb` (Victoria 5 KB, 26 alerts), `vehiclepositions.pb` (19 KB,
   126 vehicles) and `tripupdates.pb` (581 KB, 399 trips, 13,695 stop
   updates). The header says GTFS-RT 1.0, FULL_DATASET.
2. Route ids carry a system suffix: "55-VIC", "1-VIC". The static
   routes.txt uses the same ids, with route_short_name "55". Stop ids are
   the stop codes printed at the stop ("101567"), also as in stops.txt.
3. Trips can be CANCELED (19 of 399 on 2026-11-07); a cancelled trip still
   lists its stops, each marked SKIPPED with a predicted time. Those must
   be flagged, not read as "the next bus".
4. Trips that have not started carry delay 0 (the schedule repeated).
   Uncertainty is mostly 0, running trips included (Victoria route 55:
   delay 141 s, uncertainty 0); only some trips report 30.
5. Alert headers are generic ("DETOUR"); the detail is in the
   description. Translations have no language tag; the text is English.
6. Vehicles carry occupancy_status, current_status and congestion_level;
   vehicle id and label are the same long number.
"""

MODULE_NAME = "bc_transit"
MODULE_DESCRIPTION = (
    "BC Transit real-time GTFS feeds for 12 systems (Victoria, Kelowna, Kamloops, Nanaimo, "
    "Prince George, Fraser Valley, North Okanagan, Comox Valley, Cowichan Valley, Campbell "
    "River, Squamish, Whistler): live bus positions with occupancy, stop predictions with "
    "delays and cancelled trips, and service alerts. Schedules are in transit_* (agency "
    "'bct_<system>')."
)
MODULE_DESCRIPTION_FR = (
    "Flux GTFS en temps réel de BC Transit pour 12 réseaux (Victoria, Kelowna, Kamloops, "
    "Nanaimo, Prince George, Fraser Valley, North Okanagan, Comox Valley, Cowichan Valley, "
    "Campbell River, Squamish, Whistler) : positions des autobus en direct avec "
    "achalandage, prévisions de passage aux arrêts avec retards et trajets annulés, et avis "
    "de service. Les horaires sont dans transit_* (agence 'bct_<réseau>')."
)
