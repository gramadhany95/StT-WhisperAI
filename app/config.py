"""Konfigurasi aplikasi StT-WhisperAI."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_env_file = PROJECT_ROOT / ".env"
if _env_file.is_file():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file, override=False)
    except ImportError:
        pass

HF_MODEL_ID = os.environ.get("WHISPER_HF_MODEL", "maleo-ai/whisper-large-v3-turbo-id")
HF_MODEL_SUBDIR = os.environ.get("WHISPER_HF_SUBDIR", "ct2-int8")
WHISPER_MODEL_PATH = os.environ.get("WHISPER_MODEL_PATH", "").strip() or None
HF_TOKEN = os.environ.get("HF_TOKEN", os.environ.get("HUGGINGFACE_TOKEN", "")).strip() or None
FORCE_CPU = os.environ.get("FORCE_CPU", "").strip().lower() in ("1", "true", "yes", "on")

INPUT_DIR = PROJECT_ROOT / "input"
OUTPUT_DIR = PROJECT_ROOT / "output"

DEFAULT_LANGUAGE = "id"
SAMPLE_RATE = 16000

AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".m4a", ".ogg", ".webm",
    ".mp4", ".mpeg", ".mpga", ".wma", ".aac",
}
