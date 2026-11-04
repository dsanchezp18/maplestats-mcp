### Added

- The server's Docker image is published to GitHub's container registry as
  `ghcr.io/dsanchezp18/maplestats-mcp` (tags `latest` and the short commit) on every
  push to `main`, after the image passes its `/health` check. Pull requests still
  build and test it without pushing.
