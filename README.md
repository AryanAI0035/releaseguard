# ReleaseGuard

**Catch broken API responses and slower releases with Python and machine learning.**

[![Checks](https://github.com/AryanAI0035/releaseguard/actions/workflows/checks.yml/badge.svg)](https://github.com/AryanAI0035/releaseguard/actions/workflows/checks.yml)

ReleaseGuard compares two versions of a small application and shows what changed: missing response fields, server errors, timeouts, or slower responses. It combines ordinary software checks with an evaluated Isolation Forest model, and keeps the evidence in a database.

**Stack:** Python · FastAPI · HTTPX · SQLAlchemy · PostgreSQL / SQLite · scikit-learn · Streamlit · Docker · GitHub Actions

## In simple words

Imagine an online store works correctly today. After an update, the order summary becomes slow or stops returning the revenue field. ReleaseGuard sends requests to both versions, checks the replies, and shows which endpoint needs attention.

- **An API** is how programs request information from each other.
- **A release** is a version of the application.
- **A regression** is something that worked before and became worse after an update.
- **The ML model** looks for unusual response timings. Ordinary checks still catch broken responses and errors without a model.

This repository includes a small store API with deliberately faulty versions, so you can reproduce the entire demo locally without paid services or API keys.

## See it working

This is a **real screenshot from the local app**, showing a healthy release compared with a release that has inconsistent response times.

<img src="docs/dashboard.jpg" alt="ReleaseGuard comparison: orders summary p95 rises from 15.6 ms to 114.7 ms and receives a performance warning; products stay stable" width="420">

The order summary's p95 increased from **15.6 ms to 114.7 ms**, while the products endpoint stayed close to its baseline. **p95** means 95% of measured responses were at or below that time. These values belong to this demo run; they are not a general performance benchmark.

## What you can do

| Feature | What it gives you |
|---|---|
| Compare releases | See changes in response correctness and latency |
| Validate response contracts | Identify missing fields, incorrect types, and invalid responses |
| Check availability | Record HTTP errors, timeouts, and network failures |
| Inspect run history | View saved measurements and the configuration used for each run |
| Queue work safely | Repeated submission of the same request returns the same logical run |
| Recover interrupted work | A worker lease and bounded attempts handle interrupted execution |
| Evaluate ML honestly | Compare Isolation Forest with a simpler threshold baseline on held-out runs |

## Try the demo

## Quick start: Python, no Docker needed

Use **Python 3.12** for the tested setup. Git and an Internet connection are needed for the initial download and dependency installation.

```bash
git clone https://github.com/AryanAI0035/releaseguard.git
cd releaseguard
```

Then create an isolated Python environment and start the app:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m scripts.dev
```

On Windows, activate with `.venv\Scripts\activate` instead. The launcher starts all four Python processes, applies migrations, and registers the demonstration project. SQLite stores the local demo history. Press Ctrl+C to stop the services cleanly.

- Dashboard: http://127.0.0.1:8501
- Interactive API documentation: http://127.0.0.1:8000/docs
- Demonstration application: http://127.0.0.1:8001/docs

In another activated terminal, run the complete fault demonstration:

```bash
python -m scripts.demo
```

Open **Compare releases** and select the healthy baseline and a faulty candidate. Or use **Run checks** to queue your own run and **Refresh results** to update its status.

## PostgreSQL with Docker

```bash
docker compose up --build -d
docker compose exec api python -m scripts.demo --api http://localhost:8000
```

Open the same dashboard address. PostgreSQL uses a named volume; models/results use the local `artifacts/` and `results/` folders. The supplied database credentials are development-only and the UI/API ports bind to localhost.

```bash
docker compose logs -f worker
docker compose down
```

`down` preserves your database. Do not add `-v` unless you want to remove that data.

## Expected demo results

The demo checks three read-only endpoints: `/products`, `/orders/summary`, and `/inventory/SKU-001`. Faults affect the order summary; the other two endpoints help show whether the problem is isolated.

| Release | Deliberate change | Expected finding |
|---|---|---|
| `healthy` | Normal responses | Healthy comparison baseline |
| `schema-bug` | Missing revenue field | Contract failure |
| `slow-query` | Added response delay | Performance warning |
| `intermittent-500` | Some server errors | Availability failure |
| `timeout` | Response exceeds the deadline | Availability failure / insufficient latency evidence |
| `high-jitter` | Inconsistent response times | Performance warning |

`slow-query` simulates delay; it does not profile a real database query. Exact timings vary with machine load.

## Train and evaluate the ML component

Keep the local services running and use another terminal:

```bash
python -m scripts.experiment --preset quick
python -m scripts.train
python -m scripts.evaluate
python -m scripts.demo
```

The quick preset collects 28 independent experiments: 10 healthy training runs, 5 healthy validation runs, 5 healthy test runs, and 8 faulty test runs. Each run has 3 windows of 25 probes per endpoint. It is a smoke evaluation, not a large research benchmark.

For a larger collection:

```bash
python -m scripts.experiment --preset full --output results/full-manifest.json
python -m scripts.train --manifest results/full-manifest.json
python -m scripts.evaluate --manifest results/full-manifest.json --output results/full-evaluation.json
```

The full preset uses 30/10/10/20 runs in those partitions. It randomizes collection order and holds out complete experiment runs. Dataset collection makes real HTTP requests; it does not fabricate model accuracy.

With Docker, execute the same commands inside the API container, adding `--api http://localhost:8000` to the experiment command:

```bash
docker compose exec api python -m scripts.experiment --api http://localhost:8000
docker compose exec api python -m scripts.train
docker compose exec api python -m scripts.evaluate
```

New runs use trained models automatically. Historical reports retain the model state used when they ran. The evaluation command independently scores the held-out measurements with frozen models and saves JSON plus window-level CSV. The dashboard reads `results/evaluation.json` by default.

## How it works

The dashboard asks the monitor to queue a run. A separate worker makes the HTTP requests, checks their responses, and saves results. This keeps slow checks out of the API request path.


```mermaid
flowchart LR
    UI[Streamlit dashboard] --> API[FastAPI monitor]
    API --> DB[(PostgreSQL / local SQLite)]
    DB --> W[Python worker]
    W --> D[Versioned demo APIs]
    W --> C[Response contracts + latency checks]
    W --> ML[Optional Isolation Forest]
    ML --> W
    W --> DB
```

1. Register a project, supported endpoint contracts, and release variants.
2. Queue a run with an idempotency key and bounded workload.
3. Worker claims the persisted run, warms each endpoint, and performs asynchronous probes.
4. Store measurements and window summaries transactionally.
5. Apply a compatible local model when available; otherwise record why ML abstained.
6. Compare completed runs with matching workloads and contract snapshots.

Supported demo variants: `healthy`, `schema-bug`, `slow-query`, `intermittent-500`, `timeout`, and `high-jitter`. Faults affect `/orders/summary`; the other endpoints act as controls. The slow-query variant simulates delay—it does not profile a real slow query.

## Measured results

A fresh controlled experiment used **70 runs**: 30 healthy training runs, 10 healthy validation runs, and 30 held-out test runs. The test partition contained 10 healthy runs and 20 runs with performance faults.

| Metric on held-out data | Isolation Forest + latency budget | Threshold baseline + same budget |
|---|---:|---:|
| Window precision | 90.8% | 90.8% |
| Window recall | 98.3% | 98.3% |
| Window F1 | 0.944 | 0.944 |
| Normal/control windows flagged | 6 / 210 | 6 / 210 |
| Faulty runs detected | 20 / 20 | 20 / 20 |
| Healthy runs flagged | 2 / 10 | 2 / 10 |

**The ML model did not beat the simpler baseline in this experiment.** Raw novelty scoring flagged 9 of 10 healthy test runs for both methods. The operational policy therefore also requires a meaningful latency increase: more than 30% **and** 10 ms. Both raw and filtered results are retained.

These are real HTTP measurements of synthetic faults in a local testbed, not production accuracy. See the [saved evaluation](docs/benchmarks/final-evaluation.json), [window-level measurements](docs/benchmarks/final-evaluation.csv), and [verification record](docs/VERIFICATION.md) for the evidence and limitations.

## ML design

- One model per endpoint and workload profile.
- Features: log-transformed median latency, p95 latency, and latency interquartile range.
- Fit only healthy training windows; require at least 20 training and 5 validation windows.
- Choose the anomaly threshold using the 95th percentile of held-out healthy validation scores.
- Operational flags also require p95 to exceed its healthy training reference by both 30% and 10 ms. Apply this same practical-change budget to ML and the baseline.
- Compare with a robust latency-threshold baseline using the same validation data.
- Never input release names, injected fault labels, seed, or severity to the model.
- Abstain when a window has failures/censored responses or fewer than 20 valid responses.
- Report window-level and run-level performance, confusion counts, and false alerts.
- Preserve raw novelty results separately, so the practical-change filter cannot hide noisy model behavior.

The model does **not** diagnose root cause. Scores are not confidence probabilities. A validation-window threshold does not guarantee the same test or run-level false-alert rate. A simpler baseline may outperform ML; the report shows both.

An initial experiment exposed excessive raw novelty alerts on healthy timing variation. That report is preserved in `docs/benchmarks/initial-evaluation.json`. The practical latency budget was already specified for release comparisons; the revised ML policy applies it consistently and is evaluated on newly collected runs. Do not interpret good budget-filtered results as proof that ML outperforms a simple rule.

## Reliability behavior

- Same idempotency key and payload returns the same logical run; conflicting reuse returns 409.
- Endpoint configurations are snapshotted for historical interpretation.
- Worker ownership uses an atomic conditional database update and a periodically renewed lease.
- Interrupted measurements restart as a new attempt. Reports exclude partial old attempts.
- Attempts are bounded; exhausted work is marked failed.
- Request inactivity timeouts and total wall-clock deadlines are separate.
- Failed probes are not retried, which keeps regression evidence visible.
- Missing/corrupt ML artifacts do not disable functional checks.
- The comparison rule is visible: a p95 increase greater than both 30% and 10 ms, or an ML flag, produces a performance warning.

These are controlled active-probe measurements. Matching workload settings do not remove all host-load confounders. No warning is not a guarantee of release safety.

## Tests and code quality

```bash
pytest -q
ruff check .
ruff format --check .
```

SQLite tests run by default; PostgreSQL variants skip unless `TEST_DATABASE_URL` is set. Use a dedicated test database. Each PostgreSQL test owns an isolated temporary schema and cleans up only that schema.

```bash
export TEST_DATABASE_URL="postgresql+psycopg://USER:PASSWORD@localhost/releaseguard_test"
pytest -q
```

Tests cover real HTTP faults, idempotency (including concurrent submission), worker leases/recovery, partial-attempt exclusion, transaction rollback, model corruption, data leakage checks, API access, and migration upgrade/downgrade. The GitHub workflow runs both database variants with a PostgreSQL service and builds the container. Performance experiments remain separate from timing-sensitive CI assertions.

## Troubleshooting

| Problem | What to check |
|---|---|
| Dashboard or API will not start | Ports 8501, 8000, and 8001 must be free. Read the launcher's startup message. |
| Run stays queued | Keep the launcher running; the worker must be active. With Docker, inspect `docker compose logs worker`. |
| ML is unavailable | Train a model using the commands above. Functional checks work before training. |
| No release comparison is available | Run `python -m scripts.demo`, then refresh the dashboard. |
| No evaluation report appears | Run collection, training, and evaluation in that order. |
| Package installation fails | Check that your environment uses Python 3.12 and that dependency downloads can reach the Internet. |

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| DATABASE_URL | sqlite:///./data/releaseguard.db | SQLAlchemy database URL |
| DEMO_ORIGIN | http://127.0.0.1:8001 | Fixed demonstration target |
| ARTIFACT_DIR | artifacts | Local model registry and artifacts |
| API_ORIGIN | http://127.0.0.1:8000 | Dashboard's monitor API |
| API_KEY | empty | Optional key protecting API reads/writes |
| EVALUATION_PATH | results/evaluation.json | Dashboard evaluation report |

Use the same API key for the API and dashboard. CLI commands support `--api-key`. The local launcher assumes ports 8000, 8001, and 8501 are free. The version-1 monitor intentionally accepts only named read-only demo paths; arbitrary Internet monitoring is outside its scope.

## Project layout

```text
releaseguard/   API, database, contracts, probes, worker, reports, ML
demo_app/       Controlled healthy and faulty FastAPI releases
scripts/        Launcher, demo, collection, training, evaluation
tests/          Unit, HTTP, SQLite/PostgreSQL, recovery, migrations
migrations/    Versioned initial schema
dashboard.py   Streamlit interface
docs/          Design, code walkthrough, demo guide, verification
```

## Learn and present it

Start with [the code walkthrough](docs/WALKTHROUGH.md), then [the demo guide](docs/DEMO.md). Read [the design decisions](docs/DESIGN.md) for the tradeoffs you should be able to explain in an interview. [Verification](docs/VERIFICATION.md) records what was actually checked and its limitations.

Resume wording after reviewing and understanding the code:

> Built ReleaseGuard, a Python/FastAPI API regression monitor with persistent run history, asynchronous checks, and release-to-release contract and latency comparisons.
>
> Evaluated Isolation Forest against a threshold baseline on held-out HTTP experiments; reported detection performance and healthy false-alert rates.
>
> Implemented idempotent run submission and recoverable worker execution, verified through automated tests and CI configuration.

Add numeric results only when you can explain their test conditions. Check the [latest CI run](https://github.com/AryanAI0035/releaseguard/actions) for hosted validation.

## Scope and authorship

This is a focused learning and portfolio project: three supported demo endpoints, active HTTP probes, and controlled fault scenarios. It does not diagnose root cause or guarantee that a release is safe. Arbitrary public-URL monitoring, production authentication, distributed deployment, and live Salesforce integration are outside this version's scope.

The project was built with AI assistance and kept readable for study and extension. The [review notes](docs/AI_REVIEW.md) explain concrete issues found and corrected. Before presenting it as your project, run it, understand the design, and make changes you can explain.
