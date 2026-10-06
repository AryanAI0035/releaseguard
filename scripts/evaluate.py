import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select

from releaseguard.database import make_database
from releaseguard.ml import load_model, predict
from releaseguard.models import Run, Window
from releaseguard.settings import Settings
from scripts.train import validate_manifest


def metrics(rows, prediction_key):
    scored = [r for r in rows if r[prediction_key] is not None]
    tp = sum(r["fault"] and r[prediction_key] for r in scored)
    fp = sum(not r["fault"] and r[prediction_key] for r in scored)
    fn = sum(r["fault"] and not r[prediction_key] for r in scored)
    tn = sum(not r["fault"] and not r[prediction_key] for r in scored)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "samples": len(rows),
        "scored": len(scored),
        "abstained": len(rows) - len(scored),
        "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "healthy_false_alert_rate": fp / (fp + tn) if fp + tn else None,
    }


def evaluate(session, manifest, folder):
    validate_manifest(manifest)
    rows = []
    experiments = []
    for experiment in manifest["experiments"]:
        if experiment["partition"] != "test":
            continue
        run = session.get(Run, experiment["run_id"])
        if run is None or run.state != "COMPLETED":
            raise ValueError("Test runs must be completed")
        if run.config["variant"] != experiment["variant"]:
            raise ValueError("Manifest label disagrees with actual run")
        run_rows = []
        for endpoint in run.config["endpoints"]:
            bundle = load_model(endpoint["path"], run.config, folder)
            if bundle is None:
                raise ValueError(f"Missing model for {endpoint['path']}")
            if run.id in bundle["training_run_ids"] + bundle["validation_run_ids"]:
                raise ValueError("Test data overlaps model training or validation")
            windows = session.scalars(
                select(Window).where(
                    Window.run_id == run.id,
                    Window.attempt == run.attempt,
                    Window.endpoint_id == endpoint["id"],
                )
            ).all()
            for window in windows:
                prediction = predict(bundle, window.stats)
                fault = endpoint["path"] == "/orders/summary" and experiment["variant"] != "healthy"
                row = {
                    "run_id": run.id,
                    "endpoint": endpoint["path"],
                    "window": window.window,
                    "variant": experiment["variant"],
                    "fault": fault,
                    "model_version": bundle["version"],
                    "ml": prediction["anomaly"] if prediction else None,
                    "baseline": prediction["baseline_anomaly"] if prediction else None,
                    "raw_ml": prediction["raw_ml"] if prediction else None,
                    "raw_baseline": prediction["raw_baseline"] if prediction else None,
                    "score": prediction["score"] if prediction else None,
                    "p95_ms": window.stats["p95_ms"],
                }
                rows.append(row)
                run_rows.append(row)
        scored = [r for r in run_rows if r["ml"] is not None]
        experiments.append(
            {
                "run_id": run.id,
                "fault": experiment["variant"] != "healthy",
                "ml": any(r["ml"] for r in scored) if scored else None,
                "baseline": any(r["baseline"] for r in scored) if scored else None,
                "raw_ml": any(r["raw_ml"] for r in scored) if scored else None,
                "raw_baseline": any(r["raw_baseline"] for r in scored) if scored else None,
            }
        )
    by_scenario = defaultdict(list)
    for row in rows:
        if row["endpoint"] == "/orders/summary":
            by_scenario[row["variant"]].append(row)
    summary = {
        "scope": "Controlled active-probe testbed, not production accuracy",
        "threshold_policy": "95th percentile of healthy validation scores AND p95 increase exceeding both 30% and 10 ms from training reference",
        "window_level": {"ml": metrics(rows, "ml"), "baseline": metrics(rows, "baseline")},
        "run_level": {
            "ml": metrics(experiments, "ml"),
            "baseline": metrics(experiments, "baseline"),
        },
        "raw_window_level": {
            "ml": metrics(rows, "raw_ml"),
            "baseline": metrics(rows, "raw_baseline"),
        },
        "raw_run_level": {
            "ml": metrics(experiments, "raw_ml"),
            "baseline": metrics(experiments, "raw_baseline"),
        },
        "affected_endpoint_by_scenario": {
            name: {"ml": metrics(items, "ml"), "baseline": metrics(items, "baseline")}
            for name, items in by_scenario.items()
        },
        "limitations": [
            "Windows within a run are correlated; use run-level results too.",
            "Only the included endpoints, workload profile, and injected faults were evaluated.",
            "Anomaly scores do not diagnose root cause or guarantee release safety.",
            "A 5% validation window budget does not imply 5% run-level false alerts.",
            "Operational flags include a shared 30%/10 ms budget; raw novelty results are also reported.",
        ],
    }
    return summary, rows


def main():
    parser = argparse.ArgumentParser(description="Evaluate once on held-out experiments")
    parser.add_argument("--manifest", default="results/manifest.json")
    parser.add_argument("--output", default="results/evaluation.json")
    args = parser.parse_args()
    settings = Settings()
    engine, sessions = make_database(settings.database_url)
    with sessions() as session:
        summary, rows = evaluate(
            session, json.loads(Path(args.manifest).read_text()), settings.artifact_dir
        )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2))
    with output.with_suffix(".csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]) if rows else [])
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(summary, indent=2))
    engine.dispose()


if __name__ == "__main__":
    main()
