import argparse
import json
from pathlib import Path

from sqlalchemy import select

from releaseguard.database import make_database
from releaseguard.ml import features, fit_model
from releaseguard.models import Run, Window
from releaseguard.settings import Settings


def validate_manifest(manifest):
    ids = [e["run_id"] for e in manifest["experiments"]]
    if len(ids) != len(set(ids)):
        raise ValueError("A run occurs more than once; partitions must be disjoint")
    if any(
        e["variant"] != "healthy"
        for e in manifest["experiments"]
        if e["partition"] in ("training", "validation")
    ):
        raise ValueError("Training and threshold validation must use healthy runs")


def training_rows(session, manifest):
    validate_manifest(manifest)
    groups = {}
    for experiment in manifest["experiments"]:
        partition = experiment["partition"]
        if partition not in ("training", "validation"):
            continue
        run = session.get(Run, experiment["run_id"])
        if run is None or run.state != "COMPLETED" or run.config["variant"] != "healthy":
            raise ValueError("Training requires completed healthy runs")
        for endpoint in run.config["endpoints"]:
            group = groups.setdefault(
                endpoint["path"],
                {
                    "training": [],
                    "validation": [],
                    "config": run.config,
                    "ids": {"training": [], "validation": []},
                },
            )
            from releaseguard.ml import profile_key

            if profile_key(endpoint["path"], group["config"]) != profile_key(
                endpoint["path"], run.config
            ):
                raise ValueError("Training runs use incompatible workloads")
            windows = session.scalars(
                select(Window).where(
                    Window.run_id == run.id,
                    Window.attempt == run.attempt,
                    Window.endpoint_id == endpoint["id"],
                )
            ).all()
            for window in windows:
                vector = features(window.stats)
                if vector is not None:
                    group[partition].append(vector)
            group["ids"][partition].append(run.id)
    return groups


def main():
    parser = argparse.ArgumentParser(description="Train endpoint models from healthy runs")
    parser.add_argument("--manifest", default="results/manifest.json")
    args = parser.parse_args()
    settings = Settings()
    manifest = json.loads(Path(args.manifest).read_text())
    engine, sessions = make_database(settings.database_url)
    with sessions() as session:
        groups = training_rows(session, manifest)
    for path, group in groups.items():
        bundle = fit_model(
            group["training"],
            group["validation"],
            path,
            group["config"],
            settings.artifact_dir,
            group["ids"],
        )
        print(f"{path}: model {bundle['version']}; {len(group['training'])} training windows")
    engine.dispose()
    print("Models are ready. New runs will use them; historical reports remain unchanged.")


if __name__ == "__main__":
    main()
