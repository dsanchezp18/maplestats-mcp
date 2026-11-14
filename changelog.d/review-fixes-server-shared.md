### Fixed

- Hosted server: one module that fails to import no longer stops the startup
  preload. The other modules still load before the port opens and the
  `search_tools` index is still built; the broken module is logged and its
  tools say it failed to load.
- A tool whose module failed to import now fails at once on every later call,
  with the same `[module_unavailable]` error. Each call used to re-run the
  whole import on the server's event loop before failing, holding up every
  other request meanwhile. A module whose resources or prompts fail to import
  is remembered the same way, and its tools are reported as unavailable.
- Tools that read published CSV files (CER, GC InfoBase and others) no longer
  hold up the server while a large file is parsed. Decoding and splitting a
  file of up to 40 MB now runs in the file-parsing pool, where Excel files
  were already parsed.
- Error codes and fix hints now follow the error a tool actually raised. An
  invalid-argument error raised while handling an outage was coded
  `[upstream_unavailable]` with a "the source is down, retry" hint, and
  counted under that code in `/stats`; it is now `[invalid_input]`.

### Security

- Excel workbooks whose ZIP parts unpack to more XML than the server will load
  (400 MB in all, or 32 MB for a part read whole, such as the shared strings)
  are refused before they are opened, with an error that says to download the
  file from the portal instead. A small crafted file could otherwise hold a
  parsing worker for tens of seconds where no time limit could stop it.
- The error a caller sees when a module fails to load gives the exception type
  and a message with server file paths removed; the full text stays in the
  server log.
