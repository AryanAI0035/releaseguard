import argparse
import time
import uuid

import httpx

from releaseguard.contracts import PATHS, VARIANTS


def checked(response):
    response.raise_for_status()
    return response.json()


def seed(client):
    projects = checked(client.get("/projects"))
    project = next((p for p in projects if p["name"] == "Demo store"), None)
    if project is None:
        project = checked(client.post("/projects", json={"name": "Demo store"}))
    project_id = project["id"]
    registered = checked(client.get(f"/projects/{project_id}/endpoints"))
    for path, contract in PATHS.items():
        if not any(e["path"] == path for e in registered):
            checked(
                client.post(
                    f"/projects/{project_id}/endpoints",
                    json={
                        "name": contract.title(),
                        "path": path,
                        "contract": contract,
                    },
                )
            )
    releases = checked(client.get(f"/projects/{project_id}/releases"))
    for variant in sorted(VARIANTS):
        if not any(r["variant"] == variant for r in releases):
            releases.append(
                checked(
                    client.post(
                        f"/projects/{project_id}/releases",
                        json={
                            "label": variant,
                            "variant": variant,
                        },
                    )
                )
            )
    return project_id, {r["variant"]: r["id"] for r in releases}


def run_and_wait(client, release_id, **options):
    body = {"release_id": release_id, "idempotency_key": str(uuid.uuid4()), **options}
    run = checked(client.post("/runs", json=body))
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        state = checked(client.get(f"/runs/{run['id']}"))
        if state["state"] == "COMPLETED":
            return checked(client.get(f"/runs/{run['id']}/report"))
        if state["state"] == "FAILED":
            raise RuntimeError(state["error"])
        time.sleep(0.15)
    raise TimeoutError("Run did not finish. Check that the worker is running.")


def main():
    parser = argparse.ArgumentParser(description="Create and exercise the demo project")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--seed-only", action="store_true")
    parser.add_argument("--api-key", default="")
    args = parser.parse_args()
    with httpx.Client(base_url=args.api, timeout=15, headers={"X-API-Key": args.api_key}) as client:
        project_id, releases = seed(client)
        print(f"Demo project {project_id} is ready")
        if args.seed_only:
            return
        baseline = run_and_wait(client, releases["healthy"])
        print(f"Healthy baseline: run {baseline['id']}")
        for variant in ("schema-bug", "slow-query", "intermittent-500", "timeout", "high-jitter"):
            candidate = run_and_wait(client, releases[variant])
            comparison = checked(
                client.get(
                    "/comparisons",
                    params={
                        "baseline_run_id": baseline["id"],
                        "candidate_run_id": candidate["id"],
                    },
                )
            )
            print(f"\n{variant}: run {candidate['id']}")
            for row in comparison["rows"]:
                print(f"  {row['endpoint']}: {', '.join(row['findings'])}")


if __name__ == "__main__":
    main()
