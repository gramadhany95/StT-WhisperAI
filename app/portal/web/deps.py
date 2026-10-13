"""Dependency bersama: sesi login, CSRF, render template, audit."""

from __future__ import annotations

import hmac
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.portal.db import get_db
from app.portal.models import AuditLog, User
from app.portal.queue import aware
from app.portal.security import COOKIE_NAME, read_session
from app.portal.settings import COOKIE_SECURE, DISPLAY_TZ, MAX_UPLOAD_MB, SESSION_MAX_AGE

PORTAL_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(PORTAL_DIR / "templates"))
_tz = ZoneInfo(DISPLAY_TZ)


class AuthRedirect(Exception):
    def __init__(self, url: str) -> None:
        self.url = url


def _fmt_dt(dt: Optional[datetime]) -> str:
    return aware(dt).astimezone(_tz).strftime("%d %b %Y %H:%M") if dt else "-"


def _fmt_size(n: Optional[int]) -> str:
    size = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""


def _fmt_dur(sec: Optional[float]) -> str:
    if not sec:
        return "-"
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


templates.env.filters.update(dt=_fmt_dt, size=_fmt_size, dur=_fmt_dur)
templates.env.globals.update(MAX_UPLOAD_MB=MAX_UPLOAD_MB)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def set_session_cookie(response: Any, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME, token, max_age=SESSION_MAX_AGE, httponly=True, samesite="lax", secure=COOKIE_SECURE
    )


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    sess = read_session(request.cookies.get(COOKIE_NAME))
    user = db.get(User, sess["uid"]) if sess else None
    if not user or not user.is_active or user.session_version != sess.get("sv"):
        raise AuthRedirect("/login")
    if user.must_change_password and request.url.path not in ("/change-password", "/logout"):
        raise AuthRedirect("/change-password")
    request.state.user = user
    request.state.csrf = sess["csrf"]
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Khusus admin.")
    return user


async def csrf_protect(request: Request, user: User = Depends(current_user)) -> None:
    expected = request.state.csrf
    token = request.headers.get("x-csrf-token")
    if token is None and request.headers.get("content-type", "").startswith(
        ("application/x-www-form-urlencoded", "multipart/form-data")
    ):
        token = (await request.form()).get("csrf")
    if not token or not hmac.compare_digest(str(token), expected):
        raise HTTPException(403, "Token CSRF tidak valid. Muat ulang halaman lalu coba lagi.")


def render(request: Request, name: str, status_code: int = 200, **ctx: Any):
    ctx.setdefault("user", getattr(request.state, "user", None))
    ctx.setdefault("csrf", getattr(request.state, "csrf", ""))
    ctx.setdefault("msg", request.query_params.get("msg", ""))
    ctx.setdefault("err", request.query_params.get("err", ""))
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def audit(db: Session, request: Request, user: Optional[User], action: str, target: str = "") -> None:
    db.add(AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else "",
        action=action,
        target=target[:255],
        ip=client_ip(request),
    ))
