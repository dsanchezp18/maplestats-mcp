### Fixed

- The HTTP server (`python -m maplestats_mcp`) and the chat demo keep an idle connection open
  for 130 s instead of uvicorn's 5 s. Behind a proxy that reuses connections for longer
  (Render's), a request sent down a connection uvicorn had just closed failed at the proxy
  with a plain-text 502, which the chat demo showed as "The demo server did not answer".
