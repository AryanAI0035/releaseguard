# Design decisions

## Small persistent worker rather than a broker

Jobs are database rows. One worker is enough for this workload, with atomic conditional claiming and ownership tokens. PostgreSQL supports testing the actual transactional behavior; SQLite makes the local demo accessible. This is not a high-throughput queue or an exactly-once execution guarantee.

## New attempt after interruption

Measurements are time-sensitive. Combining an interrupted window with fresh observations could manufacture a misleading latency distribution. Old attempts remain available in the database but are excluded from final reports.

## ML augments deterministic checks

A missing field or HTTP 500 is explicitly wrong. It does not need anomaly detection. ML addresses performance windows whose joint latency features differ from healthy behavior. Eligibility checks cause abstention if errors or too few valid observations make those features unreliable.

## Fair baseline

Compare Isolation Forest with a robust positive-deviation threshold on the same three transformed features. Both thresholds use the same healthy validation windows. Final test data does not tune either threshold. Run-level reporting avoids pretending correlated windows are independent experimental trials.

The first evaluation exposed excessive novelty alerts on ordinary timing variation. The revised operational policy requires a p95 increase of both 30% and 10 ms from a training-only healthy reference, for both methods. Those are the predeclared release-comparison budgets, not thresholds selected to maximize test accuracy. The initial evaluation is preserved, and a fresh collection evaluates the revised policy. Raw scores/flags remain in the report for honest comparison.

## Fixed target application

The first version uses named GET endpoints on a configured demonstration origin. This keeps the product small, makes faults reproducible, and avoids mutation side effects. General configurable API monitoring can be a later extension with authentication and target controls.

## No LLM integration

Measurements and failed assertions already explain the findings. A generated summary would add dependency and evaluation scope without improving the core engineering demonstration. AI in this version is an evaluated ML model.

## Meaningful limits

- Three endpoints and controlled faults do not establish production generalization.
- Scheduling/notification delivery are future extensions; version 1 runs on demand.
- Warm-up, workload controls, and randomized experiment order reduce but do not eliminate host noise.
- No automatic rollback or claim of root-cause diagnosis.
- The model registry is local and trusted. Do not deserialize artifacts received from an untrusted source.
