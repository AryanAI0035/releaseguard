# ReleaseGuard

**API regression testing with release comparisons and latency anomaly detection.**

[![Checks](https://github.com/AryanAI0035/releaseguard/actions/workflows/checks.yml/badge.svg)](https://github.com/AryanAI0035/releaseguard/actions/workflows/checks.yml)

ReleaseGuard checks whether an API still works correctly after an update. It compares releases, records failed requests, and flags changes in response time. A Streamlit dashboard shows the results, while FastAPI and a background worker handle the checks.

**Stack:** Python · FastAPI · HTTPX · SQLAlchemy · PostgreSQL / SQLite · scikit-learn · Streamlit · Docker · GitHub Actions

## What problem does it solve?

Imagine an online store works correctly today. After an update, the order summary becomes slow or stops returning the revenue field. ReleaseGuard sends requests to both versions, checks the replies, and shows which endpoint needs attention.

A regression is a problem introduced by a change. ReleaseGuard checks response fields and types, request failures, and latency so those problems are easier to spot.

This repository includes a small store API with deliberately faulty versions, so you can reproduce the entire demo locally without paid services or API keys.

## Dashboard

Comparison of a healthy release with the `high-jitter` release:

<img src="docs/dashboard.jpg" alt="ReleaseGuard comparison: orders summary p95 rises from 15.6 ms to 114.7 ms and receives a performance warning; products stay stable" width="1000">

The order summary's p95 increased from **15.6 ms to 114.7 ms**, while the products endpoint stayed close to its baseline. **p95** means 95% of measured responses were at or below that time. Timings shown here come from the included local demo.

## Features

| Feature | Description |
|---|---|
| Compare releases | See changes in response correctness and latency |
| Validate response contracts | Identify missing fields, incorrect types, and invalid responses |
| Check availability | Record HTTP errors, timeouts, and network failures |
| Inspect run history | View saved measurements and the configuration used for each run |
| Queue work safely | Repeated submission of the same request returns the same logical run |
| Recover interrupted work | A worker lease and bounded attempts handle interrupted execution |
| Evaluate anomaly detection | Compare Isolation Forest with a simpler threshold baseline on held-out runs |

## Quick start

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

The quick preset collects 28 independent experiments: 10 healthy training runs, 5 healthy validation runs, 5 healthy test runs, and 8 faulty test runs. Each run has 3 windows of 25 probes per endpoint. Each window is a batch of requests used to calculate latency statistics.

For a larger collection:

```bash
python -m scripts.experiment --preset full --output results/full-manifest.json
python -m scripts.train --manifest results/full-manifest.json
python -m scripts.evaluate --manifest results/full-manifest.json --output results/full-evaluation.json
```

The full preset collects 30 training runs, 10 validation runs, and 30 test runs (10 healthy and 20 faulty). Collection order is randomized, and complete runs stay in separate partitions to avoid data leakage.

With Docker, execute the same commands inside the API container, adding `--api http://localhost:8000` to the experiment command:

```bash
docker compose exec api python -m scripts.experiment --api http://localhost:8000
docker compose exec api python -m scripts.train
docker compose exec api python -m scripts.evaluate
```

New runs use trained models automatically. Historical reports retain the model state used when they ran. The evaluation command independently scores the held-out measurements with frozen models and saves JSON plus window-level CSV. The dashboard reads `results/evaluation.json` by default. For a custom output file, set `EVALUATION_PATH` before starting the dashboard.

## How it works

The dashboard asks the monitor to queue a run. A separate worker makes the HTTP requests, checks their responses, and saves results. This keeps slow checks out of the API request path.

![ReleaseGuard architecture: dashboard, monitor API, database, worker, demo API, and checks](docs/architecture.png)

1. Register a project, supported endpoint contracts, and release variants.
2. Queue a run with an idempotency key and bounded workload.
3. Worker claims the persisted run, warms each endpoint, and performs asynchronous probes.
4. Store measurements and window summaries transactionally.
5. Apply a trained model when one matches the workload; otherwise record why scoring was skipped.
6. Compare completed runs with matching workloads and contract snapshots.

## Measured results

The recorded experiment used **70 runs**: 30 healthy training runs, 10 healthy validation runs, and 30 held-out test runs. The test partition contained 10 healthy runs and 20 runs with performance faults.

| Metric on held-out data | Isolation Forest + latency budget | Threshold baseline + same budget |
|---|---:|---:|
| Window precision | 90.8% | 90.8% |
| Window recall | 98.3% | 98.3% |
| Window F1 | 0.944 | 0.944 |
| Normal/control windows flagged | 6 / 210 | 6 / 210 |
| Faulty runs detected | 20 / 20 | 20 / 20 |
| Healthy runs flagged | 2 / 10 | 2 / 10 |

Both methods produced the same results in this experiment. Raw novelty scoring flagged 9 of 10 healthy test runs for both methods. The operational policy therefore also requires a meaningful latency increase: more than 30% **and** 10 ms. Both raw and filtered results are retained.

The experiment measures HTTP responses from the included demo application with injected faults. See the [saved evaluation](docs/benchmarks/final-evaluation.json), [window-level measurements](docs/benchmarks/final-evaluation.csv), and [verification record](docs/VERIFICATION.md) for the evidence and limitations.

## How the ML model works

Isolation Forest learns the usual response-time patterns for each endpoint and workload. It uses three features: median latency, p95 latency, and the interquartile range (the spread of the middle half of response times). Features are log-transformed before training.

- Training and validation use healthy runs only.
- The threshold is the 95th percentile of healthy validation scores.
- An alert also requires p95 to exceed the training reference by more than 30% and 10 ms.
- A threshold baseline uses the same data and latency requirement for comparison.
- Scoring is skipped for windows with failed requests or fewer than 20 valid responses.
- Release names and injected fault labels are excluded from model inputs.

Raw scores and filtered alerts are saved separately. The [design notes](docs/DESIGN.md) explain the alert policy and the earlier experiment that led to it. Anomaly scores show unusual timing; they are not confidence probabilities or a diagnosis of the cause.

## Run handling

- Same idempotency key and payload returns the same logical run; conflicting reuse returns 409.
- Each run saves a copy of its endpoint configuration.
- Worker ownership uses an atomic conditional database update and a periodically renewed lease.
- Interrupted measurements restart as a new attempt. Reports exclude partial old attempts.
- Attempts are bounded; exhausted work is marked failed.
- Request inactivity timeouts and total wall-clock deadlines are separate.
- Failed probes are not retried, which keeps regression evidence visible.
- Missing/corrupt ML artifacts do not disable functional checks.
- A p95 increase greater than both 30% and 10 ms, or a filtered ML alert, produces a performance warning.

Comparisons require matching workloads and response contracts. Machine load can still affect timing, so a performance warning should be investigated alongside the request evidence.

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

**42 tests passed in GitHub Actions**, covering HTTP faults, concurrent run submission, worker recovery, partial-attempt exclusion, transaction rollback, model corruption, data leakage, API access, and migration upgrade/downgrade. The workflow tests SQLite and PostgreSQL, checks lint and formatting, and builds the Docker image. [View the verified run](https://github.com/AryanAI0035/releaseguard/actions/runs/37493104132).

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

Use the same API key for the API and dashboard. The demo and experiment commands accept `--api-key`; training and evaluation access the database directly. The local launcher assumes ports 8000, 8001, and 8501 are free. The version-1 monitor intentionally accepts only named read-only demo paths; arbitrary Internet monitoring is outside its scope.

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

## Documentation

- [Architecture and design decisions](docs/DESIGN.md)
- [Code walkthrough](docs/WALKTHROUGH.md)
- [Demo workflow](docs/DEMO.md)
- [Test and evaluation evidence](docs/VERIFICATION.md)
- [Engineering review notes](docs/REVIEW.md)

## Current scope

ReleaseGuard provides on-demand checks for three configured GET endpoints, persistent run history, release comparisons, and performance anomaly detection. The included demo application supplies reproducible response, availability, and latency faults.

Measurements describe the tested workload and environment. Performance alerts identify changes that warrant investigation; they do not determine root cause. Future extensions include configurable endpoint contracts, scheduled checks, and notification delivery.
