FROM python:3.12-slim

RUN groupadd -r appuser && useradd -r -g appuser -m appuser

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock* README.md ./
COPY src/ src/

RUN uv sync --locked --no-dev || uv sync --no-dev

RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

ENV MAPLE_HOST=0.0.0.0
ENV MAPLE_PORT=8000
ENV MAPLE_TRANSPORT=http

CMD ["uv", "run", "python", "-m", "maple_data_mcp"]
