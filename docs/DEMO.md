# Demo workflow

Start the services with `python -m scripts.dev`. In another activated terminal, run `python -m scripts.demo` to collect a healthy baseline and all five fault scenarios.

1. Open **Results** and select the healthy run to inspect successful requests and latency measurements.
2. Select the `schema-bug` run and expand the order summary evidence to see the missing `revenue` field.
3. Open **Compare releases**. Select the healthy baseline and either `slow-query` or `high-jitter` as the candidate to see the p95 change.
4. Inspect the `intermittent-500` and `timeout` runs to see how availability failures are recorded.
5. After collecting experiments, training, and evaluating, open **ML evaluation** to compare both methods and their false-alert counts.

The full setup and training commands are in the [README](../README.md). Timings vary with machine load; the faulty response behavior is defined in `demo_app/main.py`.
