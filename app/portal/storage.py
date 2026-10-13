"""Penyimpanan file user: FRI Mini CDN, dengan fallback lokal untuk tipe yang ditolak CDN."""

from __future__ import annotations

import io
import logging
import shutil
import time
import uuid
import wave
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.portal import kv
from app.portal.cdn import CdnError, CdnRejected, cdn
from app.portal.models import File, Job
from app.portal.settings import LOCAL_STORAGE_DIR, WORK_DIR

log = logging.getLogger(__name__)

_AUDIO_CHECK_TTL = 3600


def _probe_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 800)
    return buf.getvalue()


def cdn_audio_allowed(db: Session, force: bool = False) -> bool:
    """Cek (dengan cache 1 jam) apakah CDN menerima audio, memakai file uji kecil."""
    if cdn is None:
        return False
    checked = kv.get_float(db, "cdn_audio_checked_at") or 0.0
    if not force and time.time() - checked < _AUDIO_CHECK_TTL:
        return kv.get_flag(db, "cdn_audio_allowed")
    try:
        fid = cdn.upload_bytes(_probe_wav(), "probe.wav", "audio/wav", {"source": "stt-portal", "probe": True})
        cdn.delete(fid)
        allowed = True
    except CdnRejected:
        allowed = False
    except CdnError as exc:
        log.warning("Cek audio CDN gagal: %s", exc)
        return kv.get_flag(db, "cdn_audio_allowed")
    kv.set_flag(db, "cdn_audio_allowed", allowed)
    kv.set_setting(db, "cdn_audio_checked_at", str(time.time()))
    db.commit()
    return allowed


def _local_dest(user_id: int, suffix: str) -> tuple[Path, str]:
    rel = f"users/{user_id}/{uuid.uuid4().hex}{suffix.lower()}"
    dest = LOCAL_STORAGE_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest, rel


def save_upload(db: Session, tmp_path: Path, original_name: str, mime: str, user_id: int) -> dict:
    """Simpan file upload. Return {storage, cdn_file_id, local_path}."""
    if cdn is not None and cdn_audio_allowed(db):
        try:
            fid = cdn.upload(tmp_path, original_name, mime, {"source": "stt-portal", "user_id": user_id})
            return {"storage": "cdn", "cdn_file_id": fid, "local_path": None}
        except CdnRejected:
            kv.set_flag(db, "cdn_audio_allowed", False)
            kv.set_setting(db, "cdn_audio_checked_at", str(time.time()))
        except CdnError as exc:
            log.warning("Upload CDN gagal, simpan lokal: %s", exc)
    dest, rel = _local_dest(user_id, Path(original_name).suffix)
    shutil.move(str(tmp_path), dest)
    return {"storage": "local", "cdn_file_id": None, "local_path": rel}


def local_abspath(f: File) -> Path:
    return LOCAL_STORAGE_DIR / (f.local_path or "")


@contextmanager
def open_cdn_stream(f: File) -> Iterator[Iterator[bytes]]:
    assert cdn is not None and f.cdn_file_id is not None
    with cdn.stream(f.cdn_file_id) as r:
        yield r.iter_bytes(256 * 1024)


@contextmanager
def fetch_to_work(f: File) -> Iterator[Path]:
    """Path lokal file untuk diproses worker (unduh dari CDN bila perlu)."""
    if f.storage == "local":
        yield local_abspath(f)
        return
    assert cdn is not None and f.cdn_file_id is not None
    dest = WORK_DIR / f"{uuid.uuid4().hex}{Path(f.original_name).suffix.lower()}"
    try:
        cdn.download_to(f.cdn_file_id, dest)
        yield dest
    finally:
        dest.unlink(missing_ok=True)


def delete_content(f: File) -> None:
    try:
        if f.storage == "local" and f.local_path:
            local_abspath(f).unlink(missing_ok=True)
        elif f.storage == "cdn" and f.cdn_file_id and cdn is not None:
            cdn.delete(f.cdn_file_id)
    except (OSError, CdnError) as exc:
        log.warning("Gagal hapus isi file %s: %s", f.id, exc)


def delete_cdn_file(file_id: int) -> None:
    if cdn is None:
        return
    try:
        cdn.delete(file_id)
    except CdnError as exc:
        log.warning("Gagal hapus file CDN %s: %s", file_id, exc)


def archive_text(text: str, filename: str, user_id: int, job_id: int) -> Optional[int]:
    if cdn is None or not text:
        return None
    try:
        return cdn.upload_bytes(
            text.encode("utf-8"), filename, "text/plain",
            {"source": "stt-portal", "user_id": user_id, "job_id": job_id, "kind": "transcript"},
        )
    except CdnError as exc:
        log.warning("Arsip transkrip ke CDN gagal: %s", exc)
        return None


def sync_local_to_cdn(db: Session, limit: int = 20, force_check: bool = False) -> int:
    """Pindahkan file lokal ke CDN jika CDN sudah menerima audio."""
    if cdn is None or not cdn_audio_allowed(db, force=force_check):
        return 0
    busy = select(Job.file_id).where(Job.status == "running")
    files = db.scalars(
        select(File)
        .where(File.storage == "local", File.deleted_at.is_(None), File.id.not_in(busy))
        .limit(limit)
    ).all()
    moved = 0
    for f in files:
        path = local_abspath(f)
        if not path.is_file():
            continue
        try:
            fid = cdn.upload(path, f.original_name, f.mime, {"source": "stt-portal", "user_id": f.user_id})
        except CdnRejected:
            kv.set_flag(db, "cdn_audio_allowed", False)
            db.commit()
            break
        except CdnError as exc:
            log.warning("Sinkron file %s gagal: %s", f.id, exc)
            continue
        f.storage, f.cdn_file_id, f.local_path = "cdn", fid, None
        db.commit()
        path.unlink(missing_ok=True)
        moved += 1
    return moved
