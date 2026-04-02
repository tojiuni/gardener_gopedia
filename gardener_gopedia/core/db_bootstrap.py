"""CLI / scripts: create Postgres schema (if configured) and SQLAlchemy tables."""

from __future__ import annotations

import sys

from sqlalchemy import create_engine, text


def ensure_postgres_schema() -> None:
    from gardener_gopedia.core.config import get_settings

    s = get_settings()
    url = (s.database_url or "").strip()
    schema = (s.postgres_schema or "").strip()
    if not schema:
        return
    # DDL without search_path (schema may not exist yet).
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        conn.commit()
    engine.dispose()


def run_init_db() -> None:
    from gardener_gopedia.core.config import get_settings
    from gardener_gopedia.core.db import init_db

    ensure_postgres_schema()
    s = get_settings()
    init_db()
    print("Gardener DB initialized:", s.database_url.split("@")[-1] if "@" in s.database_url else s.database_url)


def main() -> None:
    from gardener_gopedia.core.config import get_settings

    get_settings.cache_clear()
    try:
        run_init_db()
    except Exception as e:
        print("init-db failed:", e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
