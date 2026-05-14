# Workers Dockerfile. Build context = repo root.
FROM python:3.11-slim

WORKDIR /app

# System dependencies for psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only the workers package + shared assets
COPY apps/workers-py/pyproject.toml /app/apps/workers-py/
COPY apps/workers-py/src/ /app/apps/workers-py/src/
COPY packages/ /app/packages/
COPY config/ /app/config/
COPY .env.example /app/.env.example

WORKDIR /app/apps/workers-py
RUN pip install --no-cache-dir -e .

# Default to showing help. fly.toml overrides per process group.
CMD ["python", "-m", "workers.cli", "--help"]
