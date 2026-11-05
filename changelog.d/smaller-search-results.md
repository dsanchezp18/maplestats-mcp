### Changed

- `search_tools` results leave out each tool's title and, for a read-only tool, its
  annotations: about 12% less text in every search result, which an assistant re-reads on
  each later turn. A tool that is not read-only keeps its annotations.
- The server instructions and `search_tools` say plainly that the tools it finds run
  through `call_tool`: in the Maple Test, a third of answers tried to call a found tool
  by its own name, and each attempt cost a turn.
