# Build from the repository root: docker build -f chat/Dockerfile chat
# The same base as the server's image (../Dockerfile): tag for readers, digest for
# reproducible builds (the digest wins). Refresh both files together:
# docker buildx imagetools inspect python:3.14-slim
FROM python:3.15-slim@sha256:94d3426f1def7db4a106a232ac121bfd975393e5dfd40a619b955fae45fe7913

RUN groupadd -r appuser && useradd -r -g appuser -m appuser
WORKDIR /app

RUN pip install --no-cache-dir uv==0.11.7

# --locked: install exactly what chat/uv.lock pins, and fail the build if the lock
# is out of date with pyproject.toml, as the server's image does.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY app.py results.py ./
COPY static/ static/

USER appuser
EXPOSE 10000
ENV PORT=10000

CMD [".venv/bin/python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "10000"]
