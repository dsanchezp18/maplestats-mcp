### Added

- `bc_transit_*` (3 tools): BC Transit real-time GTFS feeds for the 12 systems
  `transit_*` already schedules (Victoria, Kelowna, Kamloops, Nanaimo and eight
  more), with the same `bct_<system>` keys. `bc_transit_get_vehicle_positions`
  gives live bus positions with occupancy, `bc_transit_get_stop_predictions`
  predicted departures with delays and cancelled trips flagged, and
  `bc_transit_get_service_alerts` detours and stop closures. BC Transit Open
  Data Terms of Use in `provenance.licence`.
