# Tag for readers, digest for reproducible builds (the digest wins). Refresh both
# together: docker buildx imagetools inspect python:3.12-slim
FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

RUN groupadd -r appuser && useradd -r -g appuser -m appuser

WORKDIR /app

# Pinned: an unpinned uv could read uv.lock differently from the version that wrote it.
RUN pip install --no-cache-dir uv==0.11.7

COPY pyproject.toml uv.lock README.md ./
COPY src/ src/

# --locked fails the build if uv.lock is out of date with pyproject.toml,
# rather than silently resolving different versions than were tested.
RUN uv sync --locked --no-dev

# PUMF, CIPO patent and StatCan open-database (LODE) caches; named volumes
# mounted here inherit this owner.
RUN mkdir -p /data/pumf /data/ip_horizons /data/lode \
    && chown appuser:appuser /data/pumf /data/ip_horizons /data/lode

USER appuser

EXPOSE 8000

ENV MAPLE_HOST=0.0.0.0
ENV MAPLE_PORT=8000
ENV MAPLE_TRANSPORT=http

# Probes whichever scheme the server is actually serving: with
# MAPLE_SSL_CERTFILE set, uvicorn terminates TLS and plain http fails.
# Certificate verification is skipped because this only checks liveness
# of the local process, whose cert need not name "localhost".
HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD python -c "import os, ssl, urllib.request; scheme = 'https' if os.environ.get('MAPLE_SSL_CERTFILE') else 'http'; urllib.request.urlopen(scheme + '://localhost:' + os.environ.get('MAPLE_PORT', '8000') + '/health', context=ssl._create_unverified_context(), timeout=5)"

# Run the synced virtualenv directly: `uv run` would re-check (and could
# try to re-sync) the environment on every container start.
CMD [".venv/bin/python", "-m", "maplestats_mcp"]
