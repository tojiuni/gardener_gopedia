"""Shared fixtures: PostgreSQL-only (set GARDENER_TEST_DATABASE_URL)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from gardener_gopedia.main import app


@pytest.fixture
def gardener_pg_url(monkeypatch):
    url = (os.environ.get("GARDENER_TEST_DATABASE_URL") or "").strip()
    if not url.startswith("postgresql"):
        pytest.skip(
            "Set GARDENER_TEST_DATABASE_URL=postgresql+psycopg://user:pass@host:port/dbname "
            "for database tests."
        )
    monkeypatch.setenv("GARDENER_DATABASE_URL", url)
    monkeypatch.setenv("GARDENER_POSTGRES_SCHEMA", "")
    return url


@pytest.fixture
def memory_session(monkeypatch, gardener_pg_url):
    from gardener_gopedia.config import get_settings
    from gardener_gopedia.db import Base, get_engine, init_db
    import gardener_gopedia.db as dbm

    get_settings.cache_clear()
    dbm._engine = None
    dbm._SessionLocal = None
    init_db()
    Session = sessionmaker(bind=get_engine())
    sess = Session()
    try:
        yield sess
    finally:
        sess.close()
        eng = get_engine()
        Base.metadata.drop_all(bind=eng)
        eng.dispose()
        dbm._engine = None
        dbm._SessionLocal = None
        get_settings.cache_clear()


@pytest.fixture
def postgres_app_client(monkeypatch, gardener_pg_url):
    from gardener_gopedia.config import get_settings
    from gardener_gopedia.db import Base, get_engine, init_db
    import gardener_gopedia.db as dbm

    get_settings.cache_clear()
    dbm._engine = None
    dbm._SessionLocal = None
    init_db()
    try:
        with TestClient(app) as c:
            yield c
    finally:
        eng = get_engine()
        Base.metadata.drop_all(bind=eng)
        eng.dispose()
        dbm._engine = None
        dbm._SessionLocal = None
        get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch, gardener_pg_url):
    """(TestClient, dataset_id, dataset_query_id) for /curation API tests."""
    from gardener_gopedia.config import get_settings
    from gardener_gopedia.db import Base, get_engine, init_db
    from gardener_gopedia.models import Dataset, DatasetQuery
    import gardener_gopedia.db as dbm

    get_settings.cache_clear()
    dbm._engine = None
    dbm._SessionLocal = None
    init_db()
    Session = sessionmaker(bind=get_engine())
    sess = Session()
    ds = Dataset(name="api_ds", version="1", curation_tier="bronze")
    sess.add(ds)
    sess.flush()
    dq = DatasetQuery(dataset_id=ds.id, external_id="q1", query_text="hello")
    sess.add(dq)
    sess.commit()
    ds_id, dq_id = ds.id, dq.id
    sess.close()
    try:
        with TestClient(app) as c:
            yield c, ds_id, dq_id
    finally:
        eng = get_engine()
        Base.metadata.drop_all(bind=eng)
        eng.dispose()
        dbm._engine = None
        dbm._SessionLocal = None
        get_settings.cache_clear()
