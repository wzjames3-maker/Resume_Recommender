FROM python:3.12-slim
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-writer \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
RUN pip install --no-cache-dir "uv" && uv pip install --system --group dev -e .
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
RUN useradd -m appuser && chown -R appuser /app && mkdir -p /tmp/uploads && chown appuser:appuser /tmp/uploads
USER appuser