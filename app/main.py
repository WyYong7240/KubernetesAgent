from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.work_orders import router as work_orders_router
from app.core.config import Settings
from app.db.session import create_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or Settings.from_environment()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = runtime_settings
        app.state.engine = None
        app.state.session_factory = None
        if runtime_settings.database_url:
            engine, session_factory = create_session_factory(runtime_settings.database_url)
            app.state.engine = engine
            app.state.session_factory = session_factory
        yield
        if app.state.engine is not None:
            await app.state.engine.dispose()

    app = FastAPI(
        title="KubernetesAgent Control Plane",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(work_orders_router)

    @app.get("/healthz", tags=["system"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
