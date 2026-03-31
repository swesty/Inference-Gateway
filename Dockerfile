FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (cache layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source
COPY *.py ./
COPY backends/ ./backends/
COPY config.yaml ./

EXPOSE 8080 9101

CMD ["uv", "run", "python", "app.py"]
