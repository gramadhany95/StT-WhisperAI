"""Job transkripsi: buat, pantau antrian, lihat hasil, unduh."""

from __future__ import annotations

from datetime import timedelta
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.portal import formats, queue, storage
from app.portal.db import get_db
from app.portal.media import LANGUAGE_CHOICES, build_options, speaker_available
from app.portal.models import File, Job, SpeakerLabel, Transcript, User, Worker, utcnow
from app.portal.settings import DEFAULT_RTF, HEARTBEAT_STALE_SEC
from app.portal.web.deps import audit, csrf_protect, current_user, render
from app.portal.web.routes_files import own_file

router = APIRouter()


def own_job(db: Session, user: User, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(404, "Job tidak ditemukan.")
    return job


def alive_workers(db: Session) -> list[Worker]:
    cutoff = utcnow() - timedelta(seconds=HEARTBEAT_STALE_SEC)
    return [w for w in db.scalars(select(Worker)).all() if queue.aware(w.last_heartbeat) >= cutoff]


def queue_view(db: Session) -> dict:
    """Posisi + estimasi waktu tunggu tiap job queued, dan sisa waktu job running."""
    rtf = queue.avg_realtime_factor(db) or DEFAULT_RTF
    n_workers = max(len(alive_workers(db)), 1)
    now = utcnow()
    running = db.scalars(select(Job).where(Job.status == "running")).all()
    remaining: dict[int, float] = {}
    for j in running:
        total = (j.file.duration_sec or 0) * rtf
        if j.progress and j.progress > 0.05 and j.started_at:
            elapsed = (now - queue.aware(j.started_at)).total_seconds()
            total = elapsed / j.progress
            remaining[j.id] = max(total - elapsed, 0)
        else:
            remaining[j.id] = total
    backlog = sum(remaining.values())
    order = queue.queued_order(db)
    durations = dict(db.execute(
        select(Job.id, File.duration_sec).join(File, File.id == Job.file_id).where(Job.id.in_(order))
    ).all()) if order else {}
    wait: dict[int, float] = {}
    for jid in order:
        wait[jid] = backlog / n_workers
        backlog += (durations.get(jid) or 0) * rtf
    return {
        "positions": {jid: i + 1 for i, jid in enumerate(order)},
        "wait": wait,
        "remaining": remaining,
        "summary": {"running": len(running), "queued": len(order), "paused": queue.is_paused(db),
                    "workers": len(alive_workers(db))},
    }


def job_dict(j: Job, qv: dict) -> dict:
    return {
        "id": j.id,
        "title": j.title,
        "file": j.file.display_name,
        "status": j.status,
        "progress": round(j.progress or 0, 3),
        "stage": j.stage,
        "error": j.error,
        "position": qv["positions"].get(j.id),
        "eta_sec": qv["wait"].get(j.id, qv["remaining"].get(j.id)),
        "speaker": bool((j.options or {}).get("use_speaker")),
        "created_at": queue.aware(j.created_at).isoformat(),
        "user": j.user.username,
    }


@router.get("/jobs/new")
def new_job_page(request: Request, file_id: Optional[int] = None, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    files = db.scalars(
        select(File).where(File.user_id == user.id, File.deleted_at.is_(None)).order_by(File.created_at.desc())
    ).all()
    return render(request, "job_new.html", files=files, file_id=file_id, languages=LANGUAGE_CHOICES,
                  speaker_ok=speaker_available())


@router.post("/jobs", dependencies=[Depends(csrf_protect)])
def create_job(
    request: Request,
    file_id: int = Form(...),
    language: str = Form("id"),
    speaker: bool = Form(False),
    min_speakers: Optional[int] = Form(None),
    max_speakers: Optional[int] = Form(None),
    vad: bool = Form(False),
    title: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    f = own_file(db, user, file_id)
    try:
        options = build_options(language, speaker, min_speakers, max_speakers, vad)
        job = queue.submit(db, user, f, options, title.strip()[:255])
    except (ValueError, queue.QueueError) as exc:
        return RedirectResponse(f"/jobs/new?file_id={file_id}&err={quote(str(exc))}", 303)
    audit(db, request, user, "job.submit", f"#{job.id} {f.display_name}")
    db.commit()
    return RedirectResponse(f"/jobs/{job.id}", 303)


@router.get("/jobs")
def jobs_page(request: Request, user: User = Depends(current_user)):
    return render(request, "jobs.html")


@router.get("/api/jobs")
def api_jobs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    qv = queue_view(db)
    jobs = db.scalars(select(Job).where(Job.user_id == user.id).order_by(Job.id.desc()).limit(100)).all()
    return {"summary": qv["summary"], "jobs": [job_dict(j, qv) for j in jobs]}


@router.get("/api/queue/summary")
def api_queue_summary(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return queue_view(db)["summary"]


@router.get("/api/jobs/{job_id}")
def api_job(job_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = own_job(db, user, job_id)
    return job_dict(job, queue_view(db))


@router.get("/jobs/{job_id}")
def job_page(request: Request, job_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = own_job(db, user, job_id)
    transcript = db.get(Transcript, job.id) if job.status == "done" else None
    labels = {}
    segments = []
    speakers: list[str] = []
    if transcript:
        labels = {l.speaker_key: l.display_name for l in db.scalars(
            select(SpeakerLabel).where(SpeakerLabel.job_id == job.id))}
        speakers = sorted({s["speaker"] for s in transcript.segments if s.get("speaker")})
        segments = formats.apply_labels(transcript.segments, labels)
    return render(request, "job_detail.html", job=job, transcript=transcript, segments=segments,
                  speakers=speakers, labels=labels, ts=formats.ts)


@router.post("/jobs/{job_id}/cancel", dependencies=[Depends(csrf_protect)])
def cancel_job(request: Request, job_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = own_job(db, user, job_id)
    try:
        queue.cancel(db, job)
    except queue.QueueError as exc:
        return RedirectResponse(f"/jobs/{job_id}?err={quote(str(exc))}", 303)
    audit(db, request, user, "job.cancel", f"#{job.id}")
    db.commit()
    return RedirectResponse(f"/jobs/{job_id}?msg=Job+dibatalkan", 303)


@router.post("/jobs/{job_id}/retry", dependencies=[Depends(csrf_protect)])
def retry_job(job_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = own_job(db, user, job_id)
    try:
        queue.retry(db, job)
    except queue.QueueError as exc:
        return RedirectResponse(f"/jobs/{job_id}?err={quote(str(exc))}", 303)
    return RedirectResponse(f"/jobs/{job_id}?msg=Job+masuk+antrian+lagi", 303)


@router.post("/jobs/{job_id}/delete", dependencies=[Depends(csrf_protect)])
def delete_job(request: Request, job_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = own_job(db, user, job_id)
    if job.status in queue.ACTIVE:
        return RedirectResponse(f"/jobs/{job_id}?err=Batalkan+job+dulu", 303)
    transcript = db.get(Transcript, job.id)
    if transcript and transcript.cdn_txt_file_id:
        storage.delete_cdn_file(transcript.cdn_txt_file_id)
    db.delete(job)
    audit(db, request, user, "job.delete", f"#{job_id}")
    db.commit()
    return RedirectResponse("/jobs?msg=Job+dihapus", 303)


@router.post("/jobs/{job_id}/speakers", dependencies=[Depends(csrf_protect)])
async def rename_speakers(request: Request, job_id: int, user: User = Depends(current_user),
                          db: Session = Depends(get_db)):
    job = own_job(db, user, job_id)
    form = await request.form()
    existing = {l.speaker_key: l for l in db.scalars(select(SpeakerLabel).where(SpeakerLabel.job_id == job.id))}
    for key, value in form.items():
        if not key.startswith("spk__"):
            continue
        speaker_key, name = key[5:], str(value).strip()[:100]
        if speaker_key in existing:
            if name:
                existing[speaker_key].display_name = name
            else:
                db.delete(existing[speaker_key])
        elif name:
            db.add(SpeakerLabel(job_id=job.id, speaker_key=speaker_key, display_name=name))
    db.commit()
    return RedirectResponse(f"/jobs/{job_id}?msg=Nama+speaker+disimpan", 303)


@router.get("/jobs/{job_id}/download/{fmt}")
def download_transcript(job_id: int, fmt: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = own_job(db, user, job_id)
    transcript = db.get(Transcript, job.id)
    if not transcript or fmt not in formats.FORMATS:
        raise HTTPException(404)
    labels = {l.speaker_key: l.display_name for l in db.scalars(
        select(SpeakerLabel).where(SpeakerLabel.job_id == job.id))}
    segments = formats.apply_labels(transcript.segments, labels)
    media_type, ext = formats.FORMATS[fmt]
    body = formats.render(fmt, segments, transcript.language)
    filename = f"{job.title or job.file.display_name}.{ext}"
    return Response(body, media_type=media_type,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})
