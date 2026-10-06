import os
import socket
import threading
import time
import uuid

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url

from demo_app.main import app as demo_app
from releaseguard.api import create_app
from releaseguard.database import initialize, make_database
from releaseguard.settings import Settings


@pytest.fixture(scope="session")
def demo_origin():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(demo_app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(origin + "/health", timeout=0.2).is_success:
                break
        except httpx.RequestError:
            time.sleep(0.05)
    else:
        raise RuntimeError("Demo server did not start")
    yield origin
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(params=["sqlite", "postgres"])
def database(request, tmp_path):
    master_engine = None
    schema = None
    if request.param == "postgres":
        base_url = os.getenv("TEST_DATABASE_URL")
        if not base_url:
            pytest.skip("Set TEST_DATABASE_URL to exercise PostgreSQL too")
        schema = "rgtest_" + uuid.uuid4().hex
        master_engine, _ = make_database(base_url)
        with master_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = make_url(base_url).update_query_dict({"options": f"-csearch_path={schema}"})
        url = url.render_as_string(hide_password=False)
    else:
        url = f"sqlite:///{tmp_path / 'test.db'}"
    engine, sessions = make_database(url)
    initialize(engine)
    yield url, engine, sessions
    engine.dispose()
    if master_engine is not None:
        with master_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        master_engine.dispose()


@pytest.fixture
def environment(database, tmp_path, demo_origin):
    url, engine, sessions = database
    settings = Settings(database_url=url, demo_origin=demo_origin, artifact_dir=tmp_path / "models")
    app = create_app(settings)
    with TestClient(app) as client:
        yield client, sessions, settings


def configure(client, variant="healthy"):
    project = client.post("/projects", json={"name": "Test project"}).json()
    for path, contract in (("/products", "products"), ("/orders/summary", "summary")):
        response = client.post(
            f"/projects/{project['id']}/endpoints",
            json={
                "name": contract,
                "path": path,
                "contract": contract,
            },
        )
        assert response.status_code == 201
    release = client.post(
        f"/projects/{project['id']}/releases",
        json={
            "label": variant,
            "variant": variant,
        },
    ).json()
    return project, release


def queue(client, release, **options):
    response = client.post(
        "/runs",
        json={
            "release_id": release["id"],
            "idempotency_key": uuid.uuid4().hex,
            "windows": 1,
            "probes_per_window": 25,
            **options,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["id"]
