# Code walkthrough

Read these files in order. The project uses ordinary functions and a few data models so that each step is inspectable.

1. `demo_app/main.py`: returns seeded responses and introduces known faults. Release variants are URL paths rather than a mutable global flag, so concurrent tests cannot accidentally change each other's target.
2. `releaseguard/contracts.py`: Pydantic response models and a helper returning the first useful validation error.
3. `releaseguard/runner.py`: measures one HTTP request, bounds concurrency, and summarizes a measurement window. `perf_counter` measures elapsed duration; database timestamps use UTC.
4. `releaseguard/models.py`: six tables. A project owns endpoints and releases. A release has runs; runs have probes and windows. Models are stored as local versioned files with manifests, not another database table.
5. `releaseguard/api.py`: validates requests and stores immutable run configuration. The idempotency check is backed by a unique database constraint so concurrent submissions cannot create duplicates.
6. `releaseguard/worker.py`: claims one run, renews its lease, writes results for each window, and marks the completed attempt. Writes verify the lease token in the same transaction. A restarted worker starts a new attempt.
7. `releaseguard/reports.py`: reads only a completed run's final attempt. It rejects incompatible release comparisons and shows actual evidence.
8. `releaseguard/ml.py`: extracts three performance features, trains a model, saves a checksummed artifact, and scores eligible windows. It never accepts user-uploaded serialized models.
9. `scripts/experiment.py`, `train.py`, `evaluate.py`: collect real measurements, keep whole runs in separate partitions, fit on healthy data, and evaluate against known injected faults.
10. `dashboard.py`: reads the API and displays results. It has no direct database access.

## Interview questions to answer yourself

- Why use a semaphore instead of starting unlimited requests?
- Why are timeout durations excluded from successful-response latency summaries?
- Why is random window-level train/test splitting misleading?
- Why can a baseline beat Isolation Forest?
- What does a 5% validation-window false-alert budget say about a whole run?
- Why is a database uniqueness constraint still needed after checking for an existing request?
- What happens if a worker finishes after another worker has claimed its expired lease?
- Why don't historical results change after retraining?
- What is simulated, and what was measured through actual HTTP requests?
- What evidence would be needed before claiming production performance?
