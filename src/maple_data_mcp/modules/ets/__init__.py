"""Edmonton Transit Service (ETS) GTFS-Realtime feeds (gtfs.edmonton.ca).

ETS's static GTFS schedule is already a data.edmonton.ca Socrata
dataset (reachable through `socrata_*` with `portal="edmonton"`); the
realtime feeds are not, because they are binary Protocol Buffers served
from ETS's own TransitMaster web service. Decoding them is the one
reason this project pins `gtfs-realtime-bindings`.

Confirmed live 2026-09-22:

1. Three feeds, all GTFS-RT 2.0, all anonymous: `Vehicle/
   VehiclePositions.pb` (~260 vehicles, ~25 KB), `TripUpdate/
   TripUpdates.pb` (~1,200 trips, ~1.6 MB), and `Alert/Alerts.pb`
   (~100 alerts). Each regenerates roughly every 30 seconds.
2. Trip updates carry ETS extensions beyond the core spec: per-stop
   `scheduled_time` alongside the predicted `time` and `delay`, and a
   `trip_properties` block with `trip_headsign`. Vehicle entities carry
   `stop_id`/`current_stop_sequence` and speed in metres per second.
3. Most alerts (95 of 100 when checked) list `informed_entity`
   route/stop ids; a few carry only free text, so route filtering on
   alerts also searches the header text for the route number.
"""

MODULE_NAME = "ets"
MODULE_DESCRIPTION = (
    "Edmonton Transit Service real-time GTFS feeds: live bus/LRT vehicle "
    "positions, per-stop arrival/departure predictions with delays, and "
    "service alerts (detours, stop closures). The static schedule is in "
    "data.edmonton.ca via socrata_* (portal='edmonton')."
)
MODULE_DESCRIPTION_FR = (
    "Flux GTFS en temps réel d'Edmonton Transit Service : positions en "
    "direct des autobus et du SLR, prévisions d'arrivée/départ par arrêt "
    "avec retards, et avis de service (détours, fermetures d'arrêts). "
    "L'horaire statique est sur data.edmonton.ca via socrata_* "
    "(portal='edmonton')."
)
