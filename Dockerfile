FROM python:3.12-slim
WORKDIR /app

# Install system dependencies for psycopg binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir ".[eval]" || pip install --no-cache-dir .

COPY gardener_gopedia/ ./gardener_gopedia/
COPY alembic/ ./alembic/

EXPOSE 18880
CMD ["uvicorn", "gardener_gopedia.main:app", "--host", "0.0.0.0", "--port", "18880"]
