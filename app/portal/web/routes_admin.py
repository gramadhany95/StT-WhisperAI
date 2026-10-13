"""Portal admin: dashboard, user, semua job, audit log."""

from __future__ import annotations

from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.portal import kv, queue, storage
from app.portal.cdn import CdnError, cdn
from app.portal.db import get_db, session_scope
from app.portal.models import AuditLog, File, Job, User, Worker
from app.portal.security import generate_password, hash_password
from app.portal.settings import CDN_BASE_URL, DEFAULT_QUOTA_MB
from app.portal.web.deps import admin_user, audit, csrf_protect, render
from app.portal.web.routes_jobs import alive_workers, job_dict, queue_view

router = APIRouter(prefix="/admin", dependencies=[Depends(admin_user)])

STATUSES = ("queued", "running", "done", "failed", "canceled")


def _redirect(path: str, msg: str = "", err: str = "") -> RedirectResponse:
    q = f"?msg={quote(msg)}" if msg else (f"?err={quote(err)}" if err else "")
    return RedirectResponse(path + q, 303)


def _sync_now() -> None:
    with session_scope() as db:
        storage.sync_local_to_cdn(db, limit=50, force_check=True)


@router.get("")
def dashboard(request: Request, db: Session = Depends(get_db)):
    alive = {w.id for w in alive_workers(db)}
    workers = db.scalars(select(Worker).order_by(Worker.last_heartbeat.desc())).all()
    counts = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    storage_counts = dict(db.execute(
        select(File.storage, func.count()).where(File.deleted_at.is_(None)).group_by(File.storage)
    ).all())
    return render(
        request, "admin_dashboard.html",
        workers=workers, alive=alive, counts=counts, statuses=STATUSES,
        users=db.scalar(select(func.count()).select_from(User)),
        storage_counts=storage_counts, paused=queue.is_paused(db),
        cdn_enabled=cdn is not None, cdn_base=CDN_BASE_URL,
        cdn_audio=kv.get_flag(db, "cdn_audio_allowed"),
        cdn_checked=kv.get_float(db, "cdn_audio_checked_at"),
    )


@router.post("/queue/{action}", dependencies=[Depends(csrf_protect)])
def queue_toggle(request: Request, action: str, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    if action not in ("pause", "resume"):
        raise HTTPException(404)
    kv.set_flag(db, "queue_paused", action == "pause")
    audit(db, request, admin, f"queue.{action}")
    db.commit()
    return _redirect("/admin", msg="Antrian dijeda." if action == "pause" else "Antrian dilanjutkan.")


@router.post("/cdn/check", dependencies=[Depends(csrf_protect)])
def cdn_check(background: BackgroundTasks, db: Session = Depends(get_db)):
    if cdn is None:
        return _redirect("/admin", err="CDN belum dikonfigurasi di .env.")
    try:
        cdn.ping()
    except CdnError as exc:
        return _redirect("/admin", err=f"CDN tidak bisa diakses: {exc}")
    allowed = storage.cdn_audio_allowed(db, force=True)
    if allowed:
        background.add_task(_sync_now)
        return _redirect("/admin", msg="CDN menerima audio. Sinkronisasi file lokal ke CDN dimulai di background.")
    return _redirect("/admin", msg="CDN terhubung, tapi belum menerima audio — file audio tetap disimpan lokal.")


# ---------- users ----------
def _users_page(request: Request, db: Session, **ctx):
    users = db.scalars(select(User).order_by(User.username)).all()
    usage = dict(db.execute(
        select(File.user_id, func.coalesce(func.sum(File.size_bytes), 0))
        .where(File.deleted_at.is_(None)).group_by(File.user_id)
    ).all())
    return render(request, "admin_users.html", users=users, usage=usage, default_quota=DEFAULT_QUOTA_MB, **ctx)


@router.get("/users")
def users_page(request: Request, db: Session = Depends(get_db)):
    return _users_page(request, db)


@router.post("/users", dependencies=[Depends(csrf_protect)])
def create_user(
    request: Request,
    username: str = Form(...),
    email: str = Form(""),
    password: str = Form(""),
    role: str = Form("user"),
    quota_mb: int = Form(DEFAULT_QUOTA_MB),
    max_queued_jobs: Optional[int] = Form(None),
    admin: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    username = username.strip()
    if not username or not username.replace("_", "").replace(".", "").replace("-", "").isalnum():
        return _users_page(request, db, err="Username hanya boleh huruf, angka, titik, minus, underscore.")
    if db.scalar(select(User).where(func.lower(User.username) == username.lower())):
        return _users_page(request, db, err=f"Username '{username}' sudah dipakai.")
    generated = not password
    password = password or generate_password()
    if len(password) < 8:
        return _users_page(request, db, err="Password minimal 8 karakter.")
    db.add(User(
        username=username, email=email.strip(), password_hash=hash_password(password),
        role="admin" if role == "admin" else "user", must_change_password=True,
        quota_mb=max(quota_mb, 0), max_queued_jobs=max_queued_jobs or None,
    ))
    audit(db, request, admin, "user.create", username)
    db.commit()
    notice = f"User '{username}' dibuat."
    if generated:
        notice += f" Password sementara: {password} — berikan ke user, wajib diganti saat login pertama."
    return _users_page(request, db, notice=notice)


@router.post("/users/{user_id}/update", dependencies=[Depends(csrf_protect)])
def update_user(
    request: Request,
    user_id: int,
    email: str = Form(""),
    role: str = Form("user"),
    is_active: bool = Form(False),
    quota_mb: int = Form(...),
    max_queued_jobs: Optional[int] = Form(None),
    admin: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404)
    if user.id == admin.id and (role != "admin" or not is_active):
        return _users_page(request, db, err="Tidak bisa menonaktifkan / menurunkan role akun sendiri.")
    if user.is_active and not is_active:
        user.session_version += 1
    user.email, user.is_active = email.strip(), is_active
    user.role = "admin" if role == "admin" else "user"
    user.quota_mb, user.max_queued_jobs = max(quota_mb, 0), max_queued_jobs or None
    audit(db, request, admin, "user.update", user.username)
    db.commit()
    return _users_page(request, db, notice=f"User '{user.username}' diperbarui.")


@router.post("/users/{user_id}/reset-password", dependencies=[Depends(csrf_protect)])
def reset_password(request: Request, user_id: int, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404)
    password = generate_password()
    user.password_hash = hash_password(password)
    user.must_change_password = True
    user.session_version += 1
    audit(db, request, admin, "user.reset_password", user.username)
    db.commit()
    return _users_page(request, db, notice=f"Password '{user.username}' direset. Password sementara: {password}")


# ---------- jobs ----------
@router.get("/jobs")
def jobs_page(request: Request, status: str = "", db: Session = Depends(get_db)):
    q = select(Job).order_by(Job.id.desc()).limit(200)
    if status in STATUSES:
        q = q.where(Job.status == status)
    qv = queue_view(db)
    jobs = [job_dict(j, qv) | {"priority": j.priority, "attempts": j.attempts, "worker": j.worker_id,
                               "duration": j.file.duration_sec, "created": j.created_at}
            for j in db.scalars(q).all()]
    return render(request, "admin_jobs.html", jobs=jobs, status=status, statuses=STATUSES, summary=qv["summary"])


@router.post("/jobs/{job_id}/{action}", dependencies=[Depends(csrf_protect)])
def job_action(request: Request, job_id: int, action: str, priority: int = Form(0),
               admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    try:
        if action == "cancel":
            queue.cancel(db, job)
        elif action == "retry":
            queue.retry(db, job)
        elif action == "priority":
            job.priority = max(min(priority, 100), -100)
        else:
            raise HTTPException(404)
    except queue.QueueError as exc:
        return _redirect("/admin/jobs", err=str(exc))
    audit(db, request, admin, f"job.{action}", f"#{job.id}")
    db.commit()
    return _redirect("/admin/jobs", msg=f"Job #{job.id}: {action} OK")


@router.get("/audit")
def audit_page(request: Request, db: Session = Depends(get_db)):
    logs = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(300)).all()
    return render(request, "admin_audit.html", logs=logs)
