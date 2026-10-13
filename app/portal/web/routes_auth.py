"""Login, logout, ganti password."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.portal.db import get_db
from app.portal.models import User, utcnow
from app.portal.security import (
    COOKIE_NAME,
    hash_password,
    login_limiter,
    make_session,
    read_session,
    validate_new_password,
    verify_password,
)
from app.portal.web.deps import audit, client_ip, csrf_protect, current_user, render, set_session_cookie

router = APIRouter()


@router.get("/")
def index(request: Request):
    return RedirectResponse("/files" if read_session(request.cookies.get(COOKIE_NAME)) else "/login", 303)


@router.get("/login")
def login_page(request: Request):
    return render(request, "login.html")


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    ip = client_ip(request)
    if login_limiter.blocked(ip):
        return render(request, "login.html", 429, err="Terlalu banyak percobaan gagal. Coba lagi 5 menit lagi.")
    user = db.scalar(select(User).where(func.lower(User.username) == username.strip().lower()))
    if not user or not user.is_active or not verify_password(user.password_hash, password):
        login_limiter.fail(ip)
        audit(db, request, user, "login.failed", username[:64])
        db.commit()
        return render(request, "login.html", 401, err="Username atau password salah.", username=username)
    login_limiter.reset(ip)
    user.last_login_at = utcnow()
    audit(db, request, user, "login")
    db.commit()
    resp = RedirectResponse("/change-password" if user.must_change_password else "/files", 303)
    set_session_cookie(resp, make_session(user.id, user.session_version))
    return resp


@router.post("/logout", dependencies=[Depends(csrf_protect)])
def logout():
    resp = RedirectResponse("/login", 303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


@router.get("/change-password")
def change_password_page(request: Request, user: User = Depends(current_user)):
    return render(request, "change_password.html")


@router.post("/change-password", dependencies=[Depends(csrf_protect)])
def change_password(
    request: Request,
    current: str = Form(...),
    new: str = Form(...),
    confirm: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(user.password_hash, current):
        return render(request, "change_password.html", 400, err="Password saat ini salah.")
    problem = validate_new_password(new, confirm)
    if not problem and new == current:
        problem = "Password baru harus berbeda dari password lama."
    if problem:
        return render(request, "change_password.html", 400, err=problem)
    user.password_hash = hash_password(new)
    user.must_change_password = False
    user.session_version += 1
    audit(db, request, user, "password.change")
    db.commit()
    resp = RedirectResponse("/files?msg=Password+berhasil+diganti", 303)
    set_session_cookie(resp, make_session(user.id, user.session_version))
    return resp
