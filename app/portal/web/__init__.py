"""Aplikasi FastAPI portal transkripsi."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.portal.bootstrap import bootstrap
from app.portal.db import SessionLocal
from app.portal.web import routes_admin, routes_auth, routes_files, routes_jobs
from app.portal.web.deps import PORTAL_DIR, AuthRedirect, render

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _wants_json(request: Request) -> bool:
    return request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", "")


def create_app() -> FastAPI:
    bootstrap()
    app = FastAPI(title="STT Portal", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=str(PORTAL_DIR / "static")), name="static")
    for module in (routes_auth, routes_files, routes_jobs, routes_admin):
        app.include_router(module.router)

    @app.exception_handler(AuthRedirect)
    async def _auth_redirect(request: Request, exc: AuthRedirect):
        if _wants_json(request):
            return JSONResponse({"detail": "Sesi berakhir, silakan login lagi."}, status_code=401)
        return RedirectResponse(exc.url, 303)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: HTTPException):
        if _wants_json(request):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return render(request, "error.html", exc.status_code, code=exc.status_code, detail=exc.detail)

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.get("/healthz")
    def healthz():
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"ok": True}

    return app


app = create_app()
