# Verification record

Verified on 6 October 2026 with Python 3.12 on macOS.

## Application checks

- Local launcher applied migrations and started the demo API, monitor API, worker, and Streamlit dashboard.
- Browser submission successfully queued a run.
- Browser release comparison showed healthy run 142 against high-jitter run 147, identifying the affected `/orders/summary` endpoint.
- CLI demonstration exercised all five fault variants. Schema-bug identified the missing revenue field; slow-query and high-jitter produced performance warnings; intermittent-500 and timeout produced availability failures. Control endpoints had no regression finding in this demonstration.
- The final demo used the trained model; historical results were not retroactively changed.

![Verified performance comparison](dashboard.jpg)

## Tests and dependencies

- 40 core test cases passed against SQLite and a real temporary PostgreSQL server.
- 2 additional dashboard cases passed against both databases, verifying that selected comparisons survive new history entries.
- Migration schema matched the SQLAlchemy models; upgrade/downgrade/upgrade passed on both databases.
- Ruff lint and formatting checks passed; dependency consistency check passed.
- Docker Compose configuration validated. Docker image build/container execution were not tested because the local Docker daemon was not running.
- Published as [AryanAI0035/releaseguard](https://github.com/AryanAI0035/releaseguard). Hosted validation status is recorded in [GitHub Actions](https://github.com/AryanAI0035/releaseguard/actions).
- One third-party deprecation warning remains: Starlette's test client currently warns about its HTTPX compatibility path. This did not fail the tests.

## Fresh evaluation of the revised policy

Collection used seed offset 81000 and 70 independent experiment runs:

- 30 healthy training runs.
- 10 healthy validation runs.
- 10 healthy test runs.
- 20 faulty test runs: 10 slow-query and 10 high-jitter.

Each endpoint model used 90 training windows and 30 validation windows. The test set contains 270 endpoint-windows across 30 experiment runs. There are 60 affected endpoint-windows and 210 normal/control windows.

| Method | Operational window precision | Recall | F1 | Normal-window false alerts |
|---|---:|---:|---:|---:|
| Isolation Forest + practical latency budget | 0.908 | 0.983 | 0.944 | 6/210 |
| Threshold baseline + same budget | 0.908 | 0.983 | 0.944 | 6/210 |

Both methods detected all 20 faulty test runs and flagged 2 of 10 healthy test runs. This limited controlled experiment provides no evidence that ML beats the baseline. Run-level false alerts remain meaningful despite better window-level results.

Raw novelty flags were noisy: both raw methods flagged 9 of 10 healthy test runs. The operational policy therefore also requires p95 to exceed its healthy training reference by both 30% and 10 ms. The raw results remain visible in the evaluation JSON and dashboard.

## Development provenance and limits

The first 70-run collection revealed excessive alerts. Its original manifest, CSV, and evaluation are preserved in `docs/benchmarks/initial-*`. It was used as development feedback. The practical latency-change budget already existed in the release-comparison specification; the revised ML policy applies it to both methods. A new collection with different seeds evaluated that revised policy.

All data comes from real HTTP probes of the controlled demo application. Fault behavior, data, and traffic are synthetic. The testbed contains three endpoints and two performance-fault families; it does not establish production generalization, causal diagnosis, or guaranteed release safety. Host scheduling noise can change results on another machine.

## Reproduction

Start the local app, then collect, train, evaluate, and demonstrate:

```bash
python -m scripts.experiment --preset full --seed 81000
python -m scripts.train
python -m scripts.evaluate
python -m scripts.demo
```

Results will have new run IDs and may differ. Inspect `results/evaluation.json` and `results/evaluation.csv` rather than assuming the values in this record apply to a new run.
