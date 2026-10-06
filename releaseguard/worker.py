import asyncio
import logging
import time
import uuid
from datetime import timedelta

import httpx
from sqlalchemy import or_, select, update

from releaseguard.database import initialize, make_database
from releaseguard.ml import load_model, predict
from releaseguard.models import Probe, Run, Window, now
from releaseguard.runner import measure_window, probe, summarize
from releaseguard.settings import Settings

logger = logging.getLogger(__name__)


def claim_run(sessions, settings):
    """Conditional updates keep two workers from owning the same run."""
    cutoff = now() - timedelta(seconds=settings.lease_seconds)
    eligible = or_(Run.state == "QUEUED", (Run.state == "RUNNING") & (Run.heartbeat_at < cutoff))
    with sessions() as session:
        candidates = session.scalars(select(Run).where(eligible).order_by(Run.id).limit(10)).all()
        for run in candidates:
            token = str(uuid.uuid4())
            if run.attempt >= settings.max_attempts:
                session.execute(
                    update(Run)
                    .where(Run.id == run.id, eligible)
                    .values(
                        state="FAILED",
                        error="Worker attempts exhausted",
                        completed_at=now(),
                    )
                )
                session.commit()
                continue
            result = session.execute(
                update(Run)
                .where(
                    Run.id == run.id,
                    eligible,
                    Run.attempt == run.attempt,
                )
                .values(
                    state="RUNNING",
                    attempt=run.attempt + 1,
                    lease_token=token,
                    heartbeat_at=now(),
                    error=None,
                ),
                execution_options={"synchronize_session": False},
            )
            session.commit()
            if result.rowcount == 1:
                session.expire_all()
                return session.get(Run, run.id)
    return None


def heartbeat(sessions, run):
    with sessions() as session:
        changed = session.execute(
            update(Run)
            .where(
                Run.id == run.id,
                Run.lease_token == run.lease_token,
                Run.state == "RUNNING",
            )
            .values(heartbeat_at=now())
        )
        session.commit()
        return changed.rowcount == 1


def save_window(sessions, run, endpoint, window_index, results, stats, prediction, bundle, note):
    with sessions() as session:
        # Lock/verify ownership in the same transaction as the result writes.
        changed = session.execute(
            update(Run)
            .where(
                Run.id == run.id,
                Run.lease_token == run.lease_token,
                Run.state == "RUNNING",
            )
            .values(heartbeat_at=now())
        )
        if changed.rowcount != 1:
            session.rollback()
            raise RuntimeError("Run lease was lost")
        for result in results:
            session.add(
                Probe(
                    run_id=run.id,
                    attempt=run.attempt,
                    endpoint_id=endpoint["id"],
                    window=window_index,
                    **result,
                )
            )
        session.add(
            Window(
                run_id=run.id,
                attempt=run.attempt,
                endpoint_id=endpoint["id"],
                window=window_index,
                stats=stats,
                model_version=bundle["version"] if bundle else None,
                anomaly_score=prediction["score"] if prediction else None,
                anomaly=prediction["anomaly"] if prediction else None,
                ml_note=note,
            )
        )
        session.commit()


async def measure_run(sessions, settings, run):
    config = run.config
    async with httpx.AsyncClient(
        timeout=config["timeout_seconds"],
        follow_redirects=False,
        trust_env=False,
        limits=httpx.Limits(max_connections=config["concurrency"]),
    ) as client:
        for endpoint in config["endpoints"]:
            if not heartbeat(sessions, run):
                raise RuntimeError("Run lease was lost")
            # A warm-up probe is intentionally omitted from stored performance observations.
            await probe(
                client,
                config["origin"],
                config["variant"],
                endpoint,
                config,
                1_000_000,
                0,
                asyncio.Semaphore(1),
            )
            bundle = None
            model_error = None
            try:
                bundle = load_model(endpoint["path"], config, settings.artifact_dir)
            except Exception as error:
                logger.warning("ML unavailable for %s: %s", endpoint["path"], error)
                model_error = "Model unavailable; functional checks still run"
            for window_index in range(config["windows"]):
                results = await measure_window(
                    client, config["origin"], config["variant"], endpoint, config, window_index
                )
                stats = summarize(results)
                prediction = None
                note = model_error or "Baseline not ready"
                if bundle is not None:
                    try:
                        prediction = predict(bundle, stats)
                        note = "Scored" if prediction else "Insufficient valid samples"
                    except Exception as error:
                        logger.warning("ML scoring failed: %s", error)
                        note = "Model unavailable; functional checks still run"
                save_window(
                    sessions, run, endpoint, window_index, results, stats, prediction, bundle, note
                )
    with sessions() as session:
        session.execute(
            update(Run)
            .where(
                Run.id == run.id,
                Run.lease_token == run.lease_token,
                Run.state == "RUNNING",
            )
            .values(state="COMPLETED", completed_at=now(), heartbeat_at=now())
        )
        session.commit()


async def execute_run(sessions, settings, run):
    async def keep_lease_alive():
        while True:
            await asyncio.sleep(settings.lease_seconds / 3)
            if not heartbeat(sessions, run):
                return

    lease_task = asyncio.create_task(keep_lease_alive())
    try:
        await measure_run(sessions, settings, run)
    finally:
        lease_task.cancel()
        try:
            await lease_task
        except asyncio.CancelledError:
            pass


def work_once(sessions, settings):
    run = claim_run(sessions, settings)
    if run is None:
        return False
    logger.info("Processing run %s, attempt %s", run.id, run.attempt)
    try:
        asyncio.run(execute_run(sessions, settings, run))
    except Exception as error:
        logger.exception("Run %s failed", run.id)
        with sessions() as session:
            session.execute(
                update(Run)
                .where(
                    Run.id == run.id,
                    Run.lease_token == run.lease_token,
                    Run.state == "RUNNING",
                )
                .values(
                    state="QUEUED" if run.attempt < settings.max_attempts else "FAILED",
                    error=f"{type(error).__name__}: {error}"[:500],
                )
            )
            session.commit()
    return True


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings()
    engine, sessions = make_database(settings.database_url)
    initialize(engine)
    try:
        while True:
            if not work_once(sessions, settings):
                time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("Worker stopped; an unfinished lease can be recovered")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
