import hashlib
import json
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from releaseguard.contracts import CONTRACT_VERSION, PATHS, VARIANTS
from releaseguard.database import initialize, make_database
from releaseguard.models import Endpoint, Project, Release, Run
from releaseguard.reports import compare, report, run_info
from releaseguard.settings import Settings


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class EndpointInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    path: str
    contract: str
    expected_status: int = Field(200, ge=100, le=599)

    @model_validator(mode="after")
    def supported_endpoint(self):
        if PATHS.get(self.path) != self.contract:
            raise ValueError("Choose a supported demo path and its matching contract")
        return self


class ReleaseInput(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    variant: str

    @model_validator(mode="after")
    def supported_variant(self):
        if self.variant not in VARIANTS:
            raise ValueError("Unsupported release variant")
        return self


class RunInput(BaseModel):
    release_id: int
    idempotency_key: str = Field(min_length=1, max_length=100)
    windows: int = Field(3, ge=1, le=10)
    probes_per_window: int = Field(25, ge=1, le=100)
    concurrency: int = Field(5, ge=1, le=10)
    timeout_seconds: float = Field(0.3, ge=0.05, le=2)
    seed: int = Field(42, ge=0, le=1_000_000)
    load: float = Field(1.0, ge=0.5, le=2)
    severity: float = Field(1.0, ge=0.1, le=3)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def create_app(settings=None):
    settings = settings or Settings()
    engine, sessions = make_database(settings.database_url)

    @asynccontextmanager
    async def lifespan(_):
        initialize(engine)
        yield
        engine.dispose()

    def session_dependency():
        with sessions() as session:
            yield session

    def access(x_api_key: str | None = Header(None)):
        if settings.api_key:
            import secrets

            if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
                raise HTTPException(401, "Invalid API key")

    app = FastAPI(title="ReleaseGuard", version="1.0.0", lifespan=lifespan)
    app.state.sessions = sessions
    app.state.engine = engine

    def get_or_404(session, model, object_id):
        item = session.get(model, object_id)
        if item is None:
            raise HTTPException(404, f"{model.__name__} not found")
        return item

    def commit_unique(session):
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "An entry with that unique value already exists") from None

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready(session=Depends(session_dependency)):
        try:
            session.execute(text("SELECT 1"))
        except Exception:
            raise HTTPException(503, "Database unavailable") from None
        return {"status": "ready"}

    @app.get("/projects", dependencies=[Depends(access)])
    def projects(session=Depends(session_dependency)):
        return [{"id": p.id, "name": p.name} for p in session.scalars(select(Project))]

    @app.post("/projects", status_code=201, dependencies=[Depends(access)])
    def add_project(body: ProjectInput, session=Depends(session_dependency)):
        item = Project(name=body.name)
        session.add(item)
        commit_unique(session)
        return {"id": item.id, "name": item.name}

    @app.get("/projects/{project_id}/endpoints", dependencies=[Depends(access)])
    def endpoints(project_id: int, session=Depends(session_dependency)):
        get_or_404(session, Project, project_id)
        return [
            {
                "id": e.id,
                "name": e.name,
                "path": e.path,
                "contract": e.contract,
                "expected_status": e.expected_status,
            }
            for e in session.scalars(select(Endpoint).where(Endpoint.project_id == project_id))
        ]

    @app.post("/projects/{project_id}/endpoints", status_code=201, dependencies=[Depends(access)])
    def add_endpoint(project_id: int, body: EndpointInput, session=Depends(session_dependency)):
        get_or_404(session, Project, project_id)
        item = Endpoint(project_id=project_id, **body.model_dump())
        session.add(item)
        commit_unique(session)
        return {"id": item.id, **body.model_dump()}

    @app.get("/projects/{project_id}/releases", dependencies=[Depends(access)])
    def releases(project_id: int, session=Depends(session_dependency)):
        get_or_404(session, Project, project_id)
        return [
            {"id": r.id, "label": r.label, "variant": r.variant}
            for r in session.scalars(select(Release).where(Release.project_id == project_id))
        ]

    @app.post("/projects/{project_id}/releases", status_code=201, dependencies=[Depends(access)])
    def add_release(project_id: int, body: ReleaseInput, session=Depends(session_dependency)):
        get_or_404(session, Project, project_id)
        item = Release(project_id=project_id, **body.model_dump())
        session.add(item)
        commit_unique(session)
        return {"id": item.id, **body.model_dump()}

    @app.post("/runs", status_code=202, dependencies=[Depends(access)])
    def queue_run(body: RunInput, session=Depends(session_dependency)):
        payload = body.model_dump()
        request_hash = digest(payload)
        existing = session.scalar(select(Run).where(Run.idempotency_key == body.idempotency_key))
        if existing:
            if existing.request_hash != request_hash:
                raise HTTPException(409, "Idempotency key was used for a different request")
            return run_info(existing)
        release = get_or_404(session, Release, body.release_id)
        endpoints = session.scalars(
            select(Endpoint).where(Endpoint.project_id == release.project_id).order_by(Endpoint.id)
        ).all()
        if not endpoints:
            raise HTTPException(422, "Register at least one endpoint")
        if len(endpoints) > 10:
            raise HTTPException(422, "At most 10 endpoints per run")
        config = {k: v for k, v in payload.items() if k not in ("release_id", "idempotency_key")}
        config.update(
            origin=settings.demo_origin,
            variant=release.variant,
            contract_version=CONTRACT_VERSION,
            endpoints=[
                {
                    "id": e.id,
                    "name": e.name,
                    "path": e.path,
                    "contract": e.contract,
                    "expected_status": e.expected_status,
                }
                for e in endpoints
            ],
        )
        # Deliberate release faults and random seeds may differ in comparable runs.
        comparable = {k: v for k, v in config.items() if k not in ("variant", "seed", "severity")}
        item = Run(
            release_id=release.id,
            idempotency_key=body.idempotency_key,
            request_hash=request_hash,
            config=config,
            config_hash=digest(comparable),
        )
        session.add(item)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            existing = session.scalar(
                select(Run).where(Run.idempotency_key == body.idempotency_key)
            )
            if existing and existing.request_hash == request_hash:
                return run_info(existing)
            raise HTTPException(409, "Idempotency key conflict") from None
        return run_info(item)

    @app.get("/runs/{run_id}", dependencies=[Depends(access)])
    def run_status(run_id: int, session=Depends(session_dependency)):
        return run_info(get_or_404(session, Run, run_id))

    @app.get("/runs/{run_id}/report", dependencies=[Depends(access)])
    def run_report(run_id: int, session=Depends(session_dependency)):
        return report(session, get_or_404(session, Run, run_id))

    @app.get("/comparisons", dependencies=[Depends(access)])
    def comparison(
        baseline_run_id: int, candidate_run_id: int, session=Depends(session_dependency)
    ):
        try:
            return compare(
                session,
                get_or_404(session, Run, baseline_run_id),
                get_or_404(session, Run, candidate_run_id),
            )
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.get("/projects/{project_id}/history", dependencies=[Depends(access)])
    def history(
        project_id: int,
        limit: int = Query(30, ge=1, le=100),
        offset: int = Query(0, ge=0),
        session=Depends(session_dependency),
    ):
        get_or_404(session, Project, project_id)
        rows = session.scalars(
            select(Run)
            .join(Release)
            .where(Release.project_id == project_id)
            .order_by(Run.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [run_info(r) for r in rows]

    return app


app = create_app()
