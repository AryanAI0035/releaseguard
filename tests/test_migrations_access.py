from concurrent.futures import ThreadPoolExecutor

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from releaseguard.api import create_app
from releaseguard.models import Base
from releaseguard.settings import Settings
from tests.conftest import configure


def test_migration_matches_models_and_round_trips(database, monkeypatch):
    url, engine, _ = database
    Base.metadata.drop_all(engine)  # This fixture owns its isolated schema/database.
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    command.downgrade(config, "base")
    assert "runs" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    assert "runs" in inspect(engine).get_table_names()


def test_optional_api_key_protects_reads_and_writes(database, tmp_path):
    url, _, _ = database
    app = create_app(Settings(database_url=url, artifact_dir=tmp_path, api_key="test-key"))
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/projects").status_code == 401
        assert client.post("/projects", json={"name": "Private"}).status_code == 401
        assert client.get("/projects", headers={"X-API-Key": "test-key"}).status_code == 200


def test_concurrent_idempotent_submission(environment):
    client, _, _ = environment
    _, release = configure(client)
    body = {"release_id": release["id"], "idempotency_key": "concurrent-request"}
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: client.post("/runs", json=body), range(4)))
    assert all(r.status_code == 202 for r in responses)
    assert len({r.json()["id"] for r in responses}) == 1
