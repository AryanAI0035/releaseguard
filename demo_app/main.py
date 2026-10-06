import asyncio
import random

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from releaseguard.contracts import VARIANTS

app = FastAPI(title="ReleaseGuard demonstration application")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/releases/{variant}/{path:path}")
async def endpoint(
    variant: str,
    path: str,
    seed: int = Query(0, ge=0),
    sample: int = Query(0, ge=0),
    load: float = Query(1.0, ge=0.5, le=2.0),
    severity: float = Query(1.0, ge=0.1, le=3.0),
):
    """Explicit variants keep baseline and candidate immutable during a run."""
    if variant not in VARIANTS:
        raise HTTPException(404, "Unknown demo release")
    payloads = {
        "products": {"items": [{"id": 1, "name": "Notebook", "price": 49.0}]},
        "orders/summary": {"total_orders": 120, "revenue": 5880.0},
        "inventory/SKU-001": {"sku": "SKU-001", "available": 42},
    }
    if path not in payloads:
        raise HTTPException(404, "Unknown demo endpoint")
    rng = random.Random(f"{seed}:{sample}:{path}")
    delay = (0.008 + rng.uniform(0, 0.006)) * load
    affected = path == "orders/summary"
    if affected and variant == "slow-query":
        # Simulate a query delay; this is not a claim of SQL query profiling.
        delay += 0.045 * severity
    if affected and variant == "timeout":
        delay += 1.0 * severity
    if affected and variant == "high-jitter" and rng.random() < 0.25:
        delay += 0.10 * severity
    await asyncio.sleep(delay)
    if affected and variant == "intermittent-500" and rng.random() < 0.30:
        return JSONResponse({"error": "Injected server failure"}, status_code=500)
    if affected and variant == "schema-bug":
        return {"total_orders": 120}  # revenue is deliberately missing
    return payloads[path]
