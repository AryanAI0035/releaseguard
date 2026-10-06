# 90-second demonstration

Preparation: start the services, collect experiments, train and evaluate, and run `python -m scripts.demo` once. Use the actual reports rather than entering made-up numbers.

1. **0-15 seconds:** Explain the problem: a passing application can still ship a broken response or slower endpoint. Show the three registered APIs.
2. **15-35 seconds:** Open the healthy run. Show successful assertions and its latency measurements.
3. **35-55 seconds:** Compare it with schema-bug. Expand the missing `revenue` field evidence. Explain that this is a deterministic failure.
4. **55-75 seconds:** Compare it with slow-query/high-jitter. Show before/after p95 and any model flags. Explain that the model scores unusual performance, not cause or confidence.
5. **75-90 seconds:** Open ML evaluation. Show held-out run counts, both methods, and healthy false-alert rates. Briefly mention tested recovery and idempotency.

Before publishing a resume claim, inspect the exact model/baseline metrics and the verification record. A warning is useful evidence, but does not certify a release unsafe; no warning does not certify it safe.
