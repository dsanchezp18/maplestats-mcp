# Build from the repository root: docker build -f chat/Dockerfile chat
FROM python:3.12-slim

RUN groupadd -r appuser && useradd -r -g appuser -m appuser
WORKDIR /app

RUN pip install --no-cache-dir uv==0.11.7

# --locked: install exactly what chat/uv.lock pins, and fail the build if the lock
# is out of date with pyproject.toml, as the server's image does.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY app.py ./
COPY static/ static/

USER appuser
EXPOSE 10000
ENV PORT=10000

CMD [".venv/bin/python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "10000"]
