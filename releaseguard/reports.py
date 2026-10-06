from sqlalchemy import select

from releaseguard.models import Probe, Release, Window
from releaseguard.runner import summarize


def run_info(run):
    return {
        "id": run.id,
        "release_id": run.release_id,
        "state": run.state,
        "attempt": run.attempt,
        "error": run.error,
        "created_at": run.created_at.isoformat() + "Z",
        "completed_at": run.completed_at.isoformat() + "Z" if run.completed_at else None,
    }


def report(session, run):
    result = {**run_info(run), "config": run.config, "endpoints": []}
    if run.state != "COMPLETED":
        return result
    for endpoint in run.config["endpoints"]:
        probes = session.scalars(
            select(Probe)
            .where(
                Probe.run_id == run.id,
                Probe.attempt == run.attempt,
                Probe.endpoint_id == endpoint["id"],
            )
            .order_by(Probe.window, Probe.probe_index)
        ).all()
        windows = session.scalars(
            select(Window)
            .where(
                Window.run_id == run.id,
                Window.attempt == run.attempt,
                Window.endpoint_id == endpoint["id"],
            )
            .order_by(Window.window)
        ).all()
        stats = summarize([{"outcome": p.outcome, "elapsed_ms": p.elapsed_ms} for p in probes])
        evidence = [
            {
                "window": p.window,
                "probe": p.probe_index,
                "outcome": p.outcome,
                "detail": p.detail,
                "elapsed_ms": p.elapsed_ms,
            }
            for p in probes
            if p.outcome != "OK"
        ][:20]
        result["endpoints"].append(
            {
                "name": endpoint["name"],
                "path": endpoint["path"],
                **stats,
                "ml_flagged_windows": sum(w.anomaly is True for w in windows),
                "ml_scored_windows": sum(w.anomaly is not None for w in windows),
                "windows": [
                    {
                        "index": w.window,
                        "stats": w.stats,
                        "score": w.anomaly_score,
                        "flagged": w.anomaly,
                        "model_version": w.model_version,
                        "note": w.ml_note,
                    }
                    for w in windows
                ],
                "evidence": evidence,
            }
        )
    return result


def percentage_change(before, after):
    if before is None or after is None or before <= 0:
        return None
    return round((after - before) / before * 100, 2)


def compare(session, baseline, candidate):
    if baseline.state != "COMPLETED" or candidate.state != "COMPLETED":
        raise ValueError("Both runs must be completed")
    base_release = session.get(Release, baseline.release_id)
    new_release = session.get(Release, candidate.release_id)
    if (
        base_release.project_id != new_release.project_id
        or baseline.config_hash != candidate.config_hash
    ):
        raise ValueError("Runs have incompatible projects, endpoint contracts, or workloads")
    before = report(session, baseline)
    after = report(session, candidate)
    rows = []
    for old, new in zip(before["endpoints"], after["endpoints"], strict=True):
        labels = []
        if new["counts"]["CONTRACT_FAILURE"]:
            labels.append("CONTRACT FAILURE")
        if any(new["counts"][k] for k in ("HTTP_ERROR", "TIMEOUT", "NETWORK_ERROR")):
            labels.append("AVAILABILITY FAILURE")
        p95_change = percentage_change(old["p95_ms"], new["p95_ms"])
        # Transparent comparison rule; the ML model is additional evidence.
        if (
            p95_change is not None and p95_change > 30 and new["p95_ms"] - old["p95_ms"] > 10
        ) or new["ml_flagged_windows"]:
            labels.append("PERFORMANCE WARNING")
        if new["p95_ms"] is None:
            labels.append("INSUFFICIENT LATENCY DATA")
        rows.append(
            {
                "endpoint": new["path"],
                "before": old,
                "after": new,
                "p95_change_percent": p95_change,
                "findings": labels or ["No regression detected in these checks"],
            }
        )
    return {
        "baseline_run_id": baseline.id,
        "candidate_run_id": candidate.id,
        "baseline_label": base_release.label,
        "candidate_label": new_release.label,
        "comparison_rule": "p95 increases by more than 30% AND 10 ms, or ML flags a window",
        "rows": rows,
        "limitations": "Controlled active probes; no guarantee of release safety or root cause",
    }
