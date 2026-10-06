import argparse
import json
import random
from pathlib import Path

import httpx

from scripts.demo import run_and_wait, seed


def main():
    parser = argparse.ArgumentParser(description="Collect independent HTTP experiments")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--preset", choices=["quick", "full"], default="quick")
    parser.add_argument("--output", default="results/manifest.json")
    parser.add_argument("--seed", type=int, default=1000, help="First independent experiment seed")
    args = parser.parse_args()
    counts = (10, 5, 5, 8) if args.preset == "quick" else (30, 10, 10, 20)
    plan = []
    for partition, count in zip(("training", "validation", "test-healthy", "test-fault"), counts):
        for i in range(count):
            faulty = partition == "test-fault"
            plan.append(
                {
                    "partition": "test" if partition.startswith("test") else partition,
                    "variant": ("slow-query" if i % 2 == 0 else "high-jitter")
                    if faulty
                    else "healthy",
                    "seed": args.seed + len(plan) * 17,
                    "severity": 0.65 + (i % 4) * 0.3 if faulty else 1.0,
                }
            )
    # Interleave partitions to avoid treating one period of machine load as one class.
    random.Random(42).shuffle(plan)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "description": "Controlled HTTP testbed; independent runs, not production traffic",
        "preset": args.preset,
        "workload": {
            "windows": 3,
            "probes_per_window": 25,
            "concurrency": 5,
            "timeout_seconds": 0.3,
            "load": 1.0,
        },
        "experiments": [],
    }
    with httpx.Client(base_url=args.api, timeout=15, headers={"X-API-Key": args.api_key}) as client:
        _, releases = seed(client)
        for i, experiment in enumerate(plan, 1):
            report = run_and_wait(
                client,
                releases[experiment["variant"]],
                **manifest["workload"],
                seed=experiment["seed"],
                severity=experiment["severity"],
            )
            manifest["experiments"].append({**experiment, "run_id": report["id"]})
            output.write_text(json.dumps(manifest, indent=2))
            print(
                f"{i}/{len(plan)}: {experiment['partition']} {experiment['variant']} run {report['id']}",
                flush=True,
            )
    print(f"Saved {output}. Next: python -m scripts.train --manifest {output}")


if __name__ == "__main__":
    main()
