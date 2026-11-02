### Added

- Chat demo: under each answer, a panel with a chart, a sortable and filterable table
  with CSV download, and the sources (table number and title linked to the StatCan page,
  vector, geography, unit, release date, reading notes and table cautions), built from
  the tool results rather than the model's text. Reads StatCan WDS and SDMX series and
  Bank of Canada Valet series. Conversations are kept in the browser; New chat and a
  light or dark theme switch are in the header. Modelled on Eurostat Assistant's chat.

### Fixed

- The `Docker images` workflow now starts the chat image and checks `/health`, not only
  builds it: an image missing a module built fine and would have failed on Render.
