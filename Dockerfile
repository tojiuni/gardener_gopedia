FROM python:3.12-slim
WORKDIR /app

# gcc + libpq5: ir-measures(pytrec-eval-terrier) C 확장 컴파일 + psycopg binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc build-essential libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
# [eval] 제외 — ragas/openai/langfuse 는 선택적 평가 기능으로 K8s 런타임에 불필요
RUN pip install --no-cache-dir .

COPY gardener_gopedia/ ./gardener_gopedia/
COPY alembic/ ./alembic/
COPY dataset/ ./dataset/

EXPOSE 18880
CMD ["uvicorn", "gardener_gopedia.main:app", "--host", "0.0.0.0", "--port", "18880"]
