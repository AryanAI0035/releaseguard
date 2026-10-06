from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

from releaseguard.worker import work_once
from tests.conftest import configure, queue


def test_dashboard_keeps_selected_runs_after_history_updates(environment, monkeypatch):
    client, sessions, settings = environment
    project, healthy = configure(client)
    baseline = queue(client, healthy)
    work_once(sessions, settings)
    faulty = client.post(
        f"/projects/{project['id']}/releases",
        json={
            "label": "schema-bug",
            "variant": "schema-bug",
        },
    ).json()
    candidate = queue(client, faulty)
    work_once(sessions, settings)

    def local_request(method, url, **kwargs):
        path = url.removeprefix("http://127.0.0.1:8000")
        kwargs.pop("timeout", None)
        return client.request(method, path, **kwargs)

    monkeypatch.setattr(httpx, "request", local_request)
    monkeypatch.setenv("EVALUATION_PATH", "/nonexistent-releaseguard-evaluation.json")
    page = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "dashboard.py", default_timeout=15
    ).run()
    assert not page.exception
    assert page.selectbox(key="baseline_run_id").value == baseline
    assert page.selectbox(key="candidate_run_id").value == candidate
    assert any("CONTRACT FAILURE" in item.value for item in page.markdown)
    new_run = queue(client, healthy)
    work_once(sessions, settings)
    page.run()
    assert not page.exception
    assert page.selectbox(key="baseline_run_id").value == baseline
    assert page.selectbox(key="candidate_run_id").value == candidate
    assert new_run != baseline
