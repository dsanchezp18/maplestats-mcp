### Changed

- MapleStats now accepts fastmcp 4.2 (`fastmcp>=4.0.3,<4.3`; it was capped
  below 4.2). `search_tools` and `call_tool` are now built from fastmcp's
  public APIs instead of overriding private methods of its BM25 search, and
  the search index is MapleStats' own. Their names, schemas, descriptions,
  output and ranking are unchanged.
