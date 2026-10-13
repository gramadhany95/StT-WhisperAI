"""File management: folder, upload, rename, pindah, hapus, unduh/putar."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.portal import queue, storage
from app.portal.db import get_db
from app.portal.media import LANGUAGE_CHOICES, build_options, probe_duration, speaker_available
from app.portal.models import File, Folder, Job, User, utcnow
from app.portal.settings import AUDIO_EXTENSIONS, MAX_UPLOAD_MB, WORK_DIR
from app.portal.web.deps import audit, csrf_protect, current_user, render

router = APIRouter()


def used_bytes(db: Session, user_id: int) -> int:
    return db.scalar(
        select(func.coalesce(func.sum(File.size_bytes), 0)).where(File.user_id == user_id, File.deleted_at.is_(None))
    ) or 0


def own_file(db: Session, user: User, file_id: int) -> File:
    f = db.get(File, file_id)
    if not f or f.user_id != user.id or f.deleted_at is not None:
        raise HTTPException(404, "File tidak ditemukan.")
    return f


def own_folder(db: Session, user: User, folder_id: Optional[int]) -> Optional[Folder]:
    if not folder_id:
        return None
    folder = db.get(Folder, folder_id)
    if not folder or folder.user_id != user.id:
        raise HTTPException(404, "Folder tidak ditemukan.")
    return folder


def _breadcrumbs(db: Session, folder: Optional[Folder]) -> list[Folder]:
    trail = []
    while folder is not None:
        trail.append(folder)
        folder = db.get(Folder, folder.parent_id) if folder.parent_id else None
    return list(reversed(trail))


def _back(folder_id: Optional[int], **params: str) -> RedirectResponse:
    q = [f"folder={folder_id}"] if folder_id else []
    q += [f"{k}={quote(v)}" for k, v in params.items()]
    return RedirectResponse("/files" + ("?" + "&".join(q) if q else ""), 303)


@router.get("/files")
def files_page(request: Request, folder: Optional[int] = None, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    current = own_folder(db, user, folder)
    fid = current.id if current else None
    subfolders = db.scalars(
        select(Folder).where(Folder.user_id == user.id, Folder.parent_id.is_(fid) if fid is None else Folder.parent_id == fid)
        .order_by(Folder.name)
    ).all()
    files = db.scalars(
        select(File).where(
            File.user_id == user.id, File.deleted_at.is_(None),
            File.folder_id.is_(None) if fid is None else File.folder_id == fid,
        ).order_by(File.created_at.desc())
    ).all()
    latest: dict[int, Job] = {}
    if files:
        for job in db.scalars(select(Job).where(Job.file_id.in_([f.id for f in files])).order_by(Job.id)).all():
            latest[job.file_id] = job
    all_folders = db.scalars(select(Folder).where(Folder.user_id == user.id).order_by(Folder.name)).all()
    return render(
        request, "files.html",
        folder=current, subfolders=subfolders, files=files, latest=latest, all_folders=all_folders,
        breadcrumbs=_breadcrumbs(db, current), used=used_bytes(db, user.id), quota=user.quota_mb * 1024 * 1024,
        languages=LANGUAGE_CHOICES, speaker_ok=speaker_available(),
        accept=",".join(AUDIO_EXTENSIONS),
    )


@router.post("/folders", dependencies=[Depends(csrf_protect)])
def create_folder(request: Request, name: str = Form(...), parent_id: Optional[int] = Form(None),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    parent = own_folder(db, user, parent_id)
    name = name.strip()[:255]
    if not name:
        return _back(parent_id, err="Nama folder kosong.")
    db.add(Folder(user_id=user.id, parent_id=parent.id if parent else None, name=name))
    db.commit()
    return _back(parent_id, msg=f"Folder '{name}' dibuat.")


@router.post("/folders/{folder_id}/rename", dependencies=[Depends(csrf_protect)])
def rename_folder(folder_id: int, name: str = Form(...), user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    folder = own_folder(db, user, folder_id)
    if name.strip():
        folder.name = name.strip()[:255]
        db.commit()
    return _back(folder.parent_id, msg="Folder diganti nama.")


@router.post("/folders/{folder_id}/delete", dependencies=[Depends(csrf_protect)])
def delete_folder(folder_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    folder = own_folder(db, user, folder_id)
    has_children = db.scalar(select(Folder.id).where(Folder.parent_id == folder.id).limit(1))
    has_files = db.scalar(select(File.id).where(File.folder_id == folder.id, File.deleted_at.is_(None)).limit(1))
    if has_children or has_files:
        return _back(folder.parent_id, err="Folder tidak kosong.")
    parent_id = folder.parent_id
    db.delete(folder)
    db.commit()
    return _back(parent_id, msg="Folder dihapus.")


def _finish_upload(tmp: Path, name: str, size: int, folder_id: Optional[int], options: Optional[dict],
                   user_id: int, db: Session, request: Request) -> dict:
    try:
        duration = probe_duration(tmp)
        if not duration:
            raise HTTPException(400, "File tidak bisa dibaca sebagai audio.")
        ext = Path(name).suffix.lower()
        mime = AUDIO_EXTENSIONS[ext]
        saved = storage.save_upload(db, tmp, name, mime, user_id)
    finally:
        tmp.unlink(missing_ok=True)
    user = db.get(User, user_id)
    f = File(
        user_id=user_id, folder_id=folder_id, display_name=Path(name).stem[:255], original_name=name[:255],
        mime=mime, size_bytes=size, duration_sec=duration, **saved,
    )
    db.add(f)
    audit(db, request, user, "file.upload", f"{name} ({saved['storage']})")
    db.commit()
    result = {"id": f.id, "storage": f.storage, "duration": duration}
    if options is not None:
        try:
            job = queue.submit(db, user, f, options)
            result["job_id"] = job.id
        except queue.QueueError as exc:
            result["job_error"] = str(exc)
    return result


@router.put("/api/files/upload", dependencies=[Depends(csrf_protect)])
async def upload(
    request: Request,
    name: str,
    folder_id: Optional[int] = None,
    auto_job: int = 0,
    language: str = "id",
    speaker: int = 0,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    name = Path(name.replace("\\", "/")).name.strip()
    if Path(name).suffix.lower() not in AUDIO_EXTENSIONS:
        raise HTTPException(400, f"Format tidak didukung. Gunakan: {', '.join(AUDIO_EXTENSIONS)}")
    await run_in_threadpool(own_folder, db, user, folder_id)
    options = None
    if auto_job:
        try:
            options = build_options(language, bool(speaker), min_speakers, max_speakers)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    remaining = user.quota_mb * 1024 * 1024 - await run_in_threadpool(used_bytes, db, user.id)
    declared = int(request.headers.get("content-length") or 0)
    if declared > max_bytes:
        raise HTTPException(413, f"File melebihi batas {MAX_UPLOAD_MB} MB.")
    if declared > remaining:
        raise HTTPException(413, "Kuota penyimpanan tidak cukup.")

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    tmp = WORK_DIR / f"upload-{uuid.uuid4().hex}{Path(name).suffix.lower()}"
    size = 0
    try:
        with open(tmp, "wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > max_bytes or size > remaining:
                    raise HTTPException(413, "File melebihi batas ukuran / kuota.")
                out.write(chunk)
        if size == 0:
            raise HTTPException(400, "File kosong.")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    result = await run_in_threadpool(_finish_upload, tmp, name, size, folder_id, options, user.id, db, request)
    return JSONResponse(result, status_code=201)


@router.post("/files/{file_id}/rename", dependencies=[Depends(csrf_protect)])
def rename_file(file_id: int, name: str = Form(...), user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    f = own_file(db, user, file_id)
    if name.strip():
        f.display_name = name.strip()[:255]
        db.commit()
    return _back(f.folder_id, msg="Nama file diganti.")


@router.post("/files/{file_id}/move", dependencies=[Depends(csrf_protect)])
def move_file(file_id: int, folder_id: Optional[int] = Form(None), user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    f = own_file(db, user, file_id)
    old = f.folder_id
    target = own_folder(db, user, folder_id)
    f.folder_id = target.id if target else None
    db.commit()
    return _back(old, msg="File dipindahkan.")


@router.post("/files/{file_id}/delete", dependencies=[Depends(csrf_protect)])
def delete_file(request: Request, file_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = own_file(db, user, file_id)
    jobs = db.scalars(select(Job).where(Job.file_id == f.id, Job.status.in_(queue.ACTIVE))).all()
    if any(j.status == "running" for j in jobs):
        return _back(f.folder_id, err="File sedang diproses. Batalkan job dulu.")
    for j in jobs:
        queue.cancel(db, j)
    storage.delete_content(f)
    f.deleted_at = utcnow()
    audit(db, request, user, "file.delete", f.original_name)
    db.commit()
    return _back(f.folder_id, msg="File dihapus. Transkrip yang sudah jadi tetap tersimpan.")


def file_response(f: File, inline: bool):
    filename = f.display_name
    ext = Path(f.original_name).suffix
    if not filename.lower().endswith(ext.lower()):
        filename += ext
    disposition = "inline" if inline else "attachment"
    if f.storage == "local":
        path = storage.local_abspath(f)
        if not path.is_file():
            raise HTTPException(404, "Isi file tidak ditemukan di storage.")
        return FileResponse(path, media_type=f.mime, filename=filename, content_disposition_type=disposition)

    def body():
        with storage.open_cdn_stream(f) as chunks:
            yield from chunks

    headers = {"Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename)}",
               "Content-Length": str(f.size_bytes)}
    return StreamingResponse(body(), media_type=f.mime, headers=headers)


@router.get("/files/{file_id}/download")
def download_file(file_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return file_response(own_file(db, user, file_id), inline=False)


@router.get("/files/{file_id}/stream")
def stream_file(file_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return file_response(own_file(db, user, file_id), inline=True)
