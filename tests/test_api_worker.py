import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from releaseguard.models import Endpoint, Probe, Run, now
from releaseguard.reports import percentage_change
from releaseguard.worker import claim_run, work_once
from tests.conftest import configure, queue


def test_idempotency_and_conflicting_payload(environment):
    client, sessions, _ = environment
    _, release = configure(client)
    payload = {"release_id": release["id"], "idempotency_key": "same-request"}
    first = client.post("/runs", json=payload)
    second = client.post("/runs", json=payload)
    assert first.json()["id"] == second.json()["id"]
    assert client.post("/runs", json={**payload, "seed": 9}).status_code == 409
    with sessions() as session:
        assert len(session.scalars(select(Run)).all()) == 1


def test_validation_and_missing_resources(environment):
    client, _, _ = environment
    project, release = configure(client)
    assert (
        client.post(
            f"/projects/{project['id']}/endpoints",
            json={
                "name": "Wrong",
                "path": "//example.com",
                "contract": "summary",
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/runs", json={"release_id": release["id"], "idempotency_key": "bad", "windows": 99}
        ).status_code
        == 422
    )
    assert client.get("/runs/9999").status_code == 404
    assert client.get("/projects/9999/history").status_code == 404


def test_real_worker_report_and_comparison(environment):
    client, sessions, settings = environment
    project, release = configure(client)
    baseline = queue(client, release)
    assert work_once(sessions, settings)
    report = client.get(f"/runs/{baseline}/report").json()
    assert report["state"] == "COMPLETED"
    assert all(e["counts"]["OK"] == 25 for e in report["endpoints"])
    assert all(e["ml_scored_windows"] == 0 for e in report["endpoints"])
    fault = client.post(
        f"/projects/{project['id']}/releases",
        json={
            "label": "broken",
            "variant": "schema-bug",
        },
    ).json()
    candidate = queue(client, fault)
    work_once(sessions, settings)
    result = client.get(
        "/comparisons",
        params={
            "baseline_run_id": baseline,
            "candidate_run_id": candidate,
        },
    ).json()
    summary = next(row for row in result["rows"] if row["endpoint"] == "/orders/summary")
    assert "CONTRACT FAILURE" in summary["findings"]
    assert "revenue" in summary["after"]["evidence"][0]["detail"]
    assert summary["after"]["p95_ms"] is None


def test_incompatible_workloads_are_rejected(environment):
    client, sessions, settings = environment
    _, release = configure(client)
    baseline = queue(client, release)
    work_once(sessions, settings)
    candidate = queue(client, release, concurrency=1)
    work_once(sessions, settings)
    assert (
        client.get(
            "/comparisons",
            params={
                "baseline_run_id": baseline,
                "candidate_run_id": candidate,
            },
        ).status_code
        == 409
    )


def test_claim_is_exclusive_and_expired_attempt_recovers(environment):
    client, sessions, settings = environment
    _, release = configure(client)
    run_id = queue(client, release)
    old = claim_run(sessions, settings)
    assert old.id == run_id and old.attempt == 1
    assert claim_run(sessions, settings) is None
    with sessions() as session:
        run = session.get(Run, run_id)
        run.heartbeat_at = now() - timedelta(seconds=settings.lease_seconds + 1)
        session.commit()
    recovered = claim_run(sessions, settings)
    assert recovered.attempt == 2
    assert recovered.lease_token != old.lease_token


def test_recovery_report_excludes_incomplete_attempt(environment):
    client, sessions, settings = environment
    _, release = configure(client)
    run_id = queue(client, release)
    old = claim_run(sessions, settings)
    with sessions() as session:
        endpoint_id = session.scalar(select(Endpoint.id))
        session.add(
            Probe(
                run_id=run_id,
                attempt=old.attempt,
                endpoint_id=endpoint_id,
                window=0,
                probe_index=0,
                elapsed_ms=999,
                outcome="HTTP_ERROR",
                status_code=500,
                detail="Partial old attempt",
            )
        )
        session.get(Run, run_id).heartbeat_at = now() - timedelta(
            seconds=settings.lease_seconds + 1
        )
        session.commit()
    work_once(sessions, settings)
    report = client.get(f"/runs/{run_id}/report").json()
    assert report["state"] == "COMPLETED" and report["attempt"] == 2
    assert all(e["samples"] == 25 and e["counts"]["HTTP_ERROR"] == 0 for e in report["endpoints"])


def test_model_corruption_does_not_stop_checks(environment):
    from releaseguard.ml import profile_key

    client, sessions, settings = environment
    _, release = configure(client)
    run_id = queue(client, release)
    with sessions() as session:
        config = session.get(Run, run_id).config
    settings.artifact_dir.mkdir()
    for endpoint in config["endpoints"]:
        (settings.artifact_dir / f"{profile_key(endpoint['path'], config)}.json").write_text(
            "bad-json"
        )
    work_once(sessions, settings)
    result = client.get(f"/runs/{run_id}/report").json()
    assert result["state"] == "COMPLETED"
    assert all("unavailable" in e["windows"][0]["note"] for e in result["endpoints"])


def test_database_constraint_rolls_back_partial_results(environment):
    client, sessions, _ = environment
    _, release = configure(client)
    run_id = queue(client, release)
    with sessions() as session:
        endpoint_id = session.scalar(select(Endpoint.id))
        args = dict(
            run_id=run_id,
            attempt=1,
            endpoint_id=endpoint_id,
            window=0,
            probe_index=0,
            elapsed_ms=10,
            outcome="OK",
        )
        session.add_all([Probe(**args), Probe(**args)])
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert session.scalars(select(Probe)).all() == []


def test_endpoint_snapshot_survives_configuration_change(environment):
    client, sessions, _ = environment
    _, release = configure(client)
    run_id = queue(client, release)
    with sessions() as session:
        endpoint = session.scalar(select(Endpoint))
        endpoint.name = "Renamed later"
        session.commit()
        config = session.get(Run, run_id).config
        assert config["endpoints"][0]["name"] != "Renamed later"


def test_exhausted_worker_attempts_fail(environment):
    client, sessions, settings = environment
    _, release = configure(client)
    run_id = queue(client, release)
    with sessions() as session:
        run = session.get(Run, run_id)
        run.state = "RUNNING"
        run.attempt = settings.max_attempts
        run.heartbeat_at = now() - timedelta(seconds=settings.lease_seconds + 1)
        session.commit()
    assert claim_run(sessions, settings) is None
    assert client.get(f"/runs/{run_id}").json()["state"] == "FAILED"


def test_heartbeat_preserves_ownership_during_long_window(environment):
    client, sessions, settings = environment
    _, release = configure(client, variant="timeout")
    run_id = queue(client, release, concurrency=1, timeout_seconds=0.1)
    settings.lease_seconds = 0.3
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(work_once, sessions, settings)
        time.sleep(0.7)  # Window is longer than the lease; heartbeat must renew it.
        with sessions() as session:
            run = session.get(Run, run_id)
            assert run.state == "RUNNING"
            assert (now() - run.heartbeat_at).total_seconds() < settings.lease_seconds
        assert claim_run(sessions, settings) is None
        assert future.result(timeout=10)
    assert client.get(f"/runs/{run_id}").json()["attempt"] == 1


def test_percentage_change_handles_missing_reference():
    assert percentage_change(0, 10) is None
    assert percentage_change(None, 10) is None
    assert percentage_change(10, 20) == 100
