### Added

- Every push to `main` rolls the new server image out to the always-on Azure Container
  Apps instance, once the image passes its `/health` check, and fails the run if the new
  revision does not become healthy or answer an MCP handshake. Azure keeps serving the
  previous revision meanwhile. The hourly uptime check now tests the Azure and Render
  endpoints separately.
