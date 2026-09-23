FROM python:3.12-slim

RUN groupadd -r appuser && useradd -r -g appuser -m appuser

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY src/ src/

# --locked fails the build if uv.lock is out of date with pyproject.toml,
# rather than silently resolving different versions than were tested.
RUN uv sync --locked --no-dev

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
CMD [".venv/bin/python", "-m", "maple_data_mcp"]
