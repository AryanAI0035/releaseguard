import asyncio
import time

import httpx
import numpy as np

from releaseguard.contracts import check_contract


async def probe(client, origin, variant, endpoint, config, sample, index, semaphore):
    params = {
        "seed": config["seed"],
        "sample": sample,
        "load": config["load"],
        "severity": config["severity"],
    }
    url = f"{origin.rstrip('/')}/releases/{variant}{endpoint['path']}"
    async with semaphore:
        start = time.perf_counter()
        result = {
            "probe_index": index,
            "status_code": None,
            "response_bytes": None,
            "outcome": "OK",
            "detail": "",
        }
        try:
            # Network inactivity timeouts and the total wall-clock deadline are separate.
            response = await asyncio.wait_for(
                client.get(url, params=params), timeout=config["timeout_seconds"]
            )
            result["status_code"] = response.status_code
            result["response_bytes"] = len(response.content)
            if response.status_code != endpoint["expected_status"]:
                result.update(outcome="HTTP_ERROR", detail=f"HTTP {response.status_code}")
            else:
                try:
                    error = check_contract(endpoint["contract"], response.json())
                    if error:
                        result.update(outcome="CONTRACT_FAILURE", detail=error)
                except ValueError:
                    result.update(outcome="CONTRACT_FAILURE", detail="Invalid JSON response")
        except (TimeoutError, httpx.TimeoutException):
            result.update(outcome="TIMEOUT", detail="Request deadline exceeded")
        except httpx.RequestError as error:
            result.update(outcome="NETWORK_ERROR", detail=type(error).__name__)
        result["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 3)
        return result


async def measure_window(client, origin, variant, endpoint, config, window):
    semaphore = asyncio.Semaphore(config["concurrency"])
    return await asyncio.gather(
        *[
            probe(
                client,
                origin,
                variant,
                endpoint,
                config,
                window * config["probes_per_window"] + i,
                i,
                semaphore,
            )
            for i in range(config["probes_per_window"])
        ]
    )


def summarize(results):
    valid = [r["elapsed_ms"] for r in results if r["outcome"] == "OK"]
    counts = {
        name: sum(r["outcome"] == name for r in results)
        for name in ("OK", "HTTP_ERROR", "CONTRACT_FAILURE", "TIMEOUT", "NETWORK_ERROR")
    }
    stats = {"samples": len(results), "counts": counts}
    # Failed/censored requests must not be treated as valid latency samples.
    if valid:
        stats.update(
            p50_ms=float(np.median(valid)),
            p95_ms=float(np.percentile(valid, 95)),
            spread_ms=float(np.percentile(valid, 75) - np.percentile(valid, 25)),
        )
    else:
        stats.update(p50_ms=None, p95_ms=None, spread_ms=None)
    return stats
