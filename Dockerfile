FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.6.14 /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (cache layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source
COPY *.py ./
COPY backends/ ./backends/
COPY config.yaml ./

RUN useradd --create-home appuser
USER appuser

EXPOSE 8080 9101

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')"

CMD ["uv", "run", "python", "app.py"]
