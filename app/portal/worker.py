"""Worker GPU: ambil job dari antrian satu per satu, transkripsi, simpan hasil.

Jalankan:  python -m app.portal.worker
Skala: jalankan beberapa proses/replika (masing-masing 1 GPU) — antrian aman via SKIP LOCKED.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
import uuid
from typing import Optional

from app.portal import formats, queue, storage
from app.portal.bootstrap import init_db
from app.portal.db import SessionLocal, session_scope
from app.portal.models import Job, Transcript, Worker, utcnow
from app.portal.settings import HF_TOKEN, JOB_TIMEOUT_MIN, WORK_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s worker: %(message)s")
log = logging.getLogger("worker")

HEARTBEAT_SEC = 10
POLL_SEC = 3
SYNC_EVERY_SEC = 3600
PROGRESS_EVERY_SEC = 1.5

WORKER_ID = os.environ.get("WORKER_ID") or f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
_stop = threading.Event()
_state = {"status": "starting", "job_id": None}


class JobAborted(Exception):
    pass


def _gpu_info() -> dict:
    try:
        import torch

        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            return {
                "device": "cuda",
                "gpu_name": torch.cuda.get_device_name(0),
                "vram_total_mb": total // 2**20,
                "vram_used_mb": (total - free) // 2**20,
            }
    except Exception:  # noqa: BLE001
        pass
    return {"device": "cpu", "gpu_name": "", "vram_total_mb": 0, "vram_used_mb": 0}


def _heartbeat_once() -> None:
    info = _gpu_info()
    with session_scope() as db:
        w = db.get(Worker, WORKER_ID)
        if w is None:
            w = Worker(id=WORKER_ID, hostname=socket.gethostname())
            db.add(w)
        w.device, w.gpu_name = info["device"], info["gpu_name"]
        w.vram_total_mb, w.vram_used_mb = info["vram_total_mb"], info["vram_used_mb"]
        w.status, w.current_job_id = _state["status"], _state["job_id"]
        w.last_heartbeat = utcnow()


def _heartbeat_loop() -> None:
    while not _stop.wait(HEARTBEAT_SEC):
        try:
            _heartbeat_once()
        except Exception as exc:  # noqa: BLE001
            log.warning("Heartbeat gagal: %s", exc)


class ProgressReporter:
    """Callback progres: tulis ke DB (di-throttle) + cek cancel/timeout."""

    def __init__(self, job_id: int) -> None:
        self.job_id = job_id
        self.started = time.monotonic()
        self.last_write = 0.0
        self.fraction = 0.0
        self.deadline = self.started + JOB_TIMEOUT_MIN * 60

    def __call__(self, fraction: Optional[float], message: str) -> None:
        if fraction is not None:
            self.fraction = max(self.fraction, min(fraction, 0.99))
        now = time.monotonic()
        if now - self.last_write < PROGRESS_EVERY_SEC:
            return
        self.last_write = now
        if _stop.is_set():
            raise JobAborted("shutdown")
        if now > self.deadline:
            raise JobAborted(f"Melebihi batas waktu {JOB_TIMEOUT_MIN} menit.")
        with session_scope() as db:
            job = db.get(Job, self.job_id)
            if job is None or job.status != "running" or job.worker_id != WORKER_ID:
                raise JobAborted("canceled")
            job.progress, job.stage = self.fraction, message[:255]


def _finish(job_id: int, **fields) -> None:
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != "running" or job.worker_id != WORKER_ID:
            return
        for k, v in fields.items():
            setattr(job, k, v)
        job.finished_at = utcnow()


def run_job(job_id: int) -> None:
    from app.checks import format_error
    from app.processor import transcribe_audio

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        f, options, user_id, title = job.file, dict(job.options or {}), job.user_id, job.title

    reporter = ProgressReporter(job_id)
    try:
        if f.deleted_at is not None:
            raise RuntimeError("File audio sudah dihapus.")
        reporter(0.01, "Menyiapkan audio...")
        with storage.fetch_to_work(f) as path:
            result = transcribe_audio(
                path,
                language=options.get("language"),
                vad_filter=options.get("vad_filter", True),
                use_speaker=bool(options.get("use_speaker")),
                hf_token=HF_TOKEN,
                min_speakers=options.get("min_speakers"),
                max_speakers=options.get("max_speakers"),
                on_progress=reporter,
            )
    except JobAborted as exc:
        reason = str(exc)
        if reason == "shutdown":
            with session_scope() as db:
                job = db.get(Job, job_id)
                if job and job.status == "running" and job.worker_id == WORKER_ID:
                    job.status, job.stage, job.progress, job.worker_id = "queued", "Diantrikan ulang", 0.0, None
                    job.attempts = max(job.attempts - 1, 0)
            log.info("Job #%s dikembalikan ke antrian (worker berhenti)", job_id)
        elif reason == "canceled":
            log.info("Job #%s dibatalkan", job_id)
        else:
            _finish(job_id, status="failed", error=reason, stage="Timeout")
            log.warning("Job #%s timeout", job_id)
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("Job #%s gagal", job_id)
        _finish(job_id, status="failed", error=format_error(exc)[:4000], stage="Gagal")
        return

    reporter.fraction = 0.98
    segments = result["segments"]
    txt = formats.plain_text(segments)
    cdn_txt = storage.archive_text(txt, f"{title or f.display_name}.txt", user_id, job_id)
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != "running" or job.worker_id != WORKER_ID:
            if cdn_txt:
                storage.delete_cdn_file(cdn_txt)
            return
        old = db.get(Transcript, job_id)
        if old:
            if old.cdn_txt_file_id:
                storage.delete_cdn_file(old.cdn_txt_file_id)
            db.delete(old)
            db.flush()
        db.add(Transcript(
            job_id=job_id, language=result["language"], text=txt, segments=segments,
            duration_sec=result.get("duration"), cdn_txt_file_id=cdn_txt,
        ))
        job.status, job.progress, job.stage, job.finished_at = "done", 1.0, "Selesai", utcnow()
    log.info("Job #%s selesai (%d segmen, %.0fs audio, %.0fs proses)",
             job_id, len(segments), result.get("duration") or 0, time.monotonic() - reporter.started)


def _preload_model() -> None:
    from app.processor import get_model

    try:
        get_model(on_progress=lambda _f, msg: log.info(msg))
    except Exception:  # noqa: BLE001
        log.exception("Preload model gagal — akan dicoba lagi saat job pertama")


def main() -> None:
    init_db()
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: _stop.set())

    log.info("Worker %s mulai", WORKER_ID)
    _heartbeat_once()
    threading.Thread(target=_heartbeat_loop, daemon=True).start()
    _state["status"] = "loading"
    _preload_model()
    _state["status"] = "idle"
    _heartbeat_once()

    last_sync = 0.0
    while not _stop.is_set():
        try:
            with SessionLocal() as db:
                n = queue.requeue_stale(db)
                if n:
                    log.warning("%d job macet diantrikan ulang", n)
                job = queue.claim_next(db, WORKER_ID)
                job_id = job.id if job else None
            if job_id is None:
                if time.monotonic() - last_sync > SYNC_EVERY_SEC:
                    last_sync = time.monotonic()
                    with SessionLocal() as db:
                        moved = storage.sync_local_to_cdn(db)
                    if moved:
                        log.info("%d file lokal dipindah ke CDN", moved)
                _stop.wait(POLL_SEC)
                continue
            log.info("Ambil job #%s", job_id)
            _state.update(status="busy", job_id=job_id)
            _heartbeat_once()
            run_job(job_id)
        except Exception:  # noqa: BLE001
            log.exception("Error di loop worker")
            _stop.wait(POLL_SEC)
        finally:
            if _state["job_id"] is not None:
                _state.update(status="idle", job_id=None)
                try:
                    _heartbeat_once()
                except Exception:  # noqa: BLE001
                    pass

    _state["status"] = "stopped"
    try:
        _heartbeat_once()
    except Exception:  # noqa: BLE001
        pass
    log.info("Worker berhenti")


if __name__ == "__main__":
    main()
