"""Konfigurasi portal dari environment (.env)."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


SECRET_KEY = os.environ.get("SECRET_KEY", "")
if len(SECRET_KEY) < 32:
    raise RuntimeError("SECRET_KEY di .env wajib diisi (minimal 32 karakter acak).")

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{(PROJECT_ROOT / 'data' / 'portal.db').as_posix()}")

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@localhost")

MAX_QUEUED_PER_USER = _int("MAX_QUEUED_PER_USER", 3)
JOB_TIMEOUT_MIN = _int("JOB_TIMEOUT_MIN", 180)
MAX_UPLOAD_MB = _int("MAX_UPLOAD_MB", 1024)
DEFAULT_QUOTA_MB = _int("DEFAULT_QUOTA_MB", 10240)
MAX_ATTEMPTS = _int("MAX_ATTEMPTS", 3)
HEARTBEAT_STALE_SEC = _int("HEARTBEAT_STALE_SEC", 120)

LOCAL_STORAGE_DIR = Path(os.environ.get("LOCAL_STORAGE_DIR", PROJECT_ROOT / "data" / "storage"))
WORK_DIR = Path(os.environ.get("WORK_DIR", PROJECT_ROOT / "data" / "work"))

CDN_BASE_URL = os.environ.get("CDN_BASE_URL", "").rstrip("/")
CDN_API_KEY = os.environ.get("CDN_API_KEY", "")
CDN_API_SECRET = os.environ.get("CDN_API_SECRET", "")
CDN_ENABLED = bool(CDN_BASE_URL and CDN_API_KEY and CDN_API_SECRET)

HF_TOKEN = os.environ.get("HF_TOKEN", "").strip() or None

COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0").lower() in ("1", "true", "yes")
SESSION_MAX_AGE = 7 * 24 * 3600
DISPLAY_TZ = os.environ.get("DISPLAY_TZ", "Asia/Jakarta")
# Estimasi detik proses per detik audio sebelum ada riwayat job.
DEFAULT_RTF = float(os.environ.get("DEFAULT_RTF", "0.3"))

AUDIO_EXTENSIONS = {
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac", ".m4a": "audio/mp4",
    ".ogg": "audio/ogg", ".webm": "audio/webm", ".mp4": "video/mp4", ".mpeg": "audio/mpeg",
    ".mpga": "audio/mpeg", ".wma": "audio/x-ms-wma", ".aac": "audio/aac",
}
