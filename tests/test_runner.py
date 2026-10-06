import asyncio
import time

import httpx
import pytest

from releaseguard.contracts import check_contract
from releaseguard.runner import measure_window, summarize


def test_contract_error_identifies_field():
    assert "revenue" in check_contract("summary", {"total_orders": 2})
    assert check_contract("summary", {"total_orders": 2, "revenue": 5.0}) is None
    assert check_contract("summary", {"total_orders": "2", "revenue": 5.0}) is not None


def test_failed_requests_do_not_become_valid_latency_samples():
    result = summarize(
        [{"outcome": "OK", "elapsed_ms": 10}, {"outcome": "TIMEOUT", "elapsed_ms": 300}]
    )
    assert result["p95_ms"] == 10
    assert result["counts"]["TIMEOUT"] == 1
    assert summarize([])["p95_ms"] is None


@pytest.mark.parametrize(
    "variant,outcome",
    [
        ("healthy", "OK"),
        ("schema-bug", "CONTRACT_FAILURE"),
        ("timeout", "TIMEOUT"),
    ],
)
def test_real_http_faults(demo_origin, variant, outcome):
    async def measure():
        async with httpx.AsyncClient(timeout=0.08) as client:
            return await measure_window(
                client,
                demo_origin,
                variant,
                {"path": "/orders/summary", "contract": "summary", "expected_status": 200},
                {
                    "seed": 42,
                    "load": 1.0,
                    "severity": 1.0,
                    "probes_per_window": 5,
                    "concurrency": 5,
                    "timeout_seconds": 0.08,
                },
                0,
            )

    start = time.monotonic()
    results = asyncio.run(measure())
    assert all(r["outcome"] == outcome for r in results)
    assert time.monotonic() - start < 2
    if variant == "timeout":
        assert all(r["status_code"] is None and r["response_bytes"] is None for r in results)


def test_http_errors_are_not_retried(demo_origin):
    async def measure():
        async with httpx.AsyncClient() as client:
            return await measure_window(
                client,
                demo_origin,
                "intermittent-500",
                {"path": "/orders/summary", "contract": "summary", "expected_status": 200},
                {
                    "seed": 42,
                    "load": 1.0,
                    "severity": 1.0,
                    "probes_per_window": 30,
                    "concurrency": 5,
                    "timeout_seconds": 0.3,
                },
                0,
            )

    results = asyncio.run(measure())
    assert len(results) == 30
    assert any(r["outcome"] == "HTTP_ERROR" for r in results)
