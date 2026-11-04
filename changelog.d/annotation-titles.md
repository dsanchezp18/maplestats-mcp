### Fixed

- Every tool's title is now also in its `annotations.title`. Claude's connectors
  directory reads the title from there and flagged `search_tools`, `call_tool` and
  `plan_query` as untitled.
