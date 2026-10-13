"""Antrian job di Postgres: submit, claim fair-share, posisi, cancel, requeue job macet."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.portal import kv
from app.portal.db import IS_POSTGRES
from app.portal.models import File, Job, User, Worker, utcnow
from app.portal.settings import HEARTBEAT_STALE_SEC, MAX_ATTEMPTS, MAX_QUEUED_PER_USER

ACTIVE = ("queued", "running")
FINAL = ("done", "failed", "canceled")


class QueueError(ValueError):
    pass


def aware(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite mengembalikan datetime tanpa zona waktu; anggap UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def is_paused(db: Session) -> bool:
    return kv.get_flag(db, "queue_paused")


def _order():
    return (Job.priority.desc(), User.last_served_at.asc().nulls_first(), Job.created_at.asc(), Job.id.asc())


def submit(db: Session, user: User, f: File, options: dict, title: str = "") -> Job:
    limit = user.max_queued_jobs or MAX_QUEUED_PER_USER
    active = db.scalar(select(func.count()).select_from(Job).where(Job.user_id == user.id, Job.status.in_(ACTIVE)))
    if active >= limit:
        raise QueueError(f"Batas {limit} job aktif per user tercapai. Tunggu job sebelumnya selesai.")
    job = Job(user_id=user.id, file_id=f.id, type="transcribe", options=options, title=title or f.display_name)
    db.add(job)
    db.commit()
    return job


def claim_next(db: Session, worker_id: str) -> Optional[Job]:
    if is_paused(db):
        return None
    q = select(Job).join(User, User.id == Job.user_id).where(Job.status == "queued").order_by(*_order()).limit(1)
    if IS_POSTGRES:
        q = q.with_for_update(of=Job, skip_locked=True)
    job = db.scalars(q).first()
    if job is None:
        db.rollback()
        return None
    now = utcnow()
    job.status, job.started_at, job.worker_id = "running", now, worker_id
    job.attempts += 1
    job.progress, job.stage, job.error = 0.0, "Memulai...", None
    job.user.last_served_at = now
    db.commit()
    return job


def queued_order(db: Session) -> list[int]:
    q = select(Job.id).join(User, User.id == Job.user_id).where(Job.status == "queued").order_by(*_order())
    return list(db.scalars(q).all())


def positions(db: Session) -> dict[int, int]:
    """job_id → posisi (1 = berikutnya diproses)."""
    return {jid: i + 1 for i, jid in enumerate(queued_order(db))}


def summary(db: Session) -> dict:
    counts = dict(db.execute(select(Job.status, func.count()).where(Job.status.in_(ACTIVE)).group_by(Job.status)).all())
    return {"running": counts.get("running", 0), "queued": counts.get("queued", 0), "paused": is_paused(db)}


def avg_realtime_factor(db: Session) -> Optional[float]:
    """Rata-rata detik proses per detik audio dari 20 job terakhir."""
    rows = db.execute(
        select(Job.started_at, Job.finished_at, File.duration_sec)
        .join(File, File.id == Job.file_id)
        .where(Job.status == "done", File.duration_sec > 0)
        .order_by(Job.finished_at.desc())
        .limit(20)
    ).all()
    ratios = [
        (aware(fin) - aware(st)).total_seconds() / dur
        for st, fin, dur in rows if st and fin and dur
    ]
    return sum(ratios) / len(ratios) if ratios else None


def cancel(db: Session, job: Job) -> None:
    if job.status not in ACTIVE:
        raise QueueError("Job sudah selesai.")
    job.status = "canceled"
    job.finished_at = utcnow()
    job.stage = "Dibatalkan"
    db.commit()


def retry(db: Session, job: Job) -> None:
    if job.status not in ("failed", "canceled"):
        raise QueueError("Hanya job gagal/dibatalkan yang bisa diulang.")
    if job.file.deleted_at is not None:
        raise QueueError("File audio sudah dihapus.")
    job.status, job.progress, job.stage, job.error = "queued", 0.0, "", None
    job.attempts, job.started_at, job.finished_at, job.worker_id = 0, None, None, None
    job.created_at = utcnow()
    db.commit()


def requeue_stale(db: Session) -> int:
    """Job running yang worker-nya berhenti heartbeat → antri lagi (atau gagal setelah MAX_ATTEMPTS)."""
    cutoff = utcnow() - timedelta(seconds=HEARTBEAT_STALE_SEC)
    alive = {w.id for w in db.scalars(select(Worker)).all() if aware(w.last_heartbeat) >= cutoff}
    n = 0
    for job in db.scalars(select(Job).where(Job.status == "running")).all():
        if job.worker_id in alive:
            continue
        if job.attempts >= MAX_ATTEMPTS:
            job.status, job.finished_at = "failed", utcnow()
            job.error = "Worker berhenti saat memproses job (batas percobaan tercapai)."
        else:
            job.status, job.stage, job.progress, job.worker_id = "queued", "Diantrikan ulang", 0.0, None
        n += 1
    if n:
        db.commit()
    return n
