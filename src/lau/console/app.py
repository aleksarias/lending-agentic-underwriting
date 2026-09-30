"""FastAPI application factory for the Underwriting Console.

Serves the JSON API under /api (routers in lau.console.routers) and, when built, the React app from
console/web/dist with client-side routing fallback.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from lau.console.routers import ROUTER_MODULES  # noqa: E402
from lau.credentials import CredentialsMissingError  # noqa: E402
from lau.settings import ROOT  # noqa: E402

WEB_DIST = Path(os.environ.get("LAU_CONSOLE_DIST", ROOT / "console" / "web" / "dist"))


def create_app() -> FastAPI:
    app = FastAPI(
        title="Underwriting Console API", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for name in ROUTER_MODULES:
        module = importlib.import_module(f"lau.console.routers.{name}")
        app.include_router(module.router, prefix="/api")

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.exception_handler(PermissionError)
    def _denied(_request, exc: PermissionError):  # AccessDeniedError is a PermissionError
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(CredentialsMissingError)
    def _no_identity(_request, exc: CredentialsMissingError):
        # e.g. the read-only ui identity has not been created on Databricks yet (`lau init`)
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    if WEB_DIST.exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(status_code=404)
            candidate = WEB_DIST / path
            if path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(WEB_DIST / "index.html")

    return app


app = create_app()
