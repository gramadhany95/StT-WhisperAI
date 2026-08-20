"""Core processing logic for StT-WhisperAI."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional

import torch
import whisper
from whisper.utils import get_writer

from app.checks import check_ffmpeg, configure_ffmpeg, resolve_device

# Konfigurasi ffmpeg sedini mungkin (WinGet sering tidak ada di PATH)
configure_ffmpeg()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_ROOT / "input"
OUTPUT_DIR = PROJECT_ROOT / "output"

AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".m4a", ".ogg", ".webm",
    ".mp4", ".mpeg", ".mpga", ".wma", ".aac",
}

_model = None
_model_name: Optional[str] = None
_device: Optional[str] = None


def ensure_dirs() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", "_", name)
    return name.strip("._") or "transcript"


def list_input_files() -> list[Path]:
    ensure_dirs()
    return sorted(
        p for p in INPUT_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
    )


def copy_to_input(src_path: Path) -> Path:
    """Salin file audio ke folder input/, handle duplikat nama."""
    ensure_dirs()
    ext = src_path.suffix.lower()
    if ext not in AUDIO_EXTENSIONS:
        raise ValueError(f"Format tidak didukung: {ext}")

    dest = INPUT_DIR / src_path.name
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        counter = 1
        while dest.exists():
            dest = INPUT_DIR / f"{stem}_{counter}{suffix}"
            counter += 1

    shutil.copy2(src_path, dest)
    return dest


def list_output_files() -> list[Path]:
    ensure_dirs()
    return sorted(
        p for p in OUTPUT_DIR.iterdir()
        if p.is_file() and not p.name.startswith(".")
    )


def get_model(model_name: str, device: str, on_status=None):
    global _model, _model_name, _device
    if _model is None or _model_name != model_name or _device != device:
        msg = f"Memuat model '{model_name}' ({device})..."
        if on_status:
            on_status(msg)
        else:
            print(msg)
        _model = whisper.load_model(model_name, device=device)
        _model_name = model_name
        _device = device
    return _model


def transcribe_file(
    audio_path: Path,
    output_name: Optional[str] = None,
    *,
    model_name: str = "turbo",
    language: Optional[str] = None,
    task: str = "transcribe",
    output_format: str = "txt",
    word_timestamps: bool = False,
    device: Optional[str] = None,
    on_status=None,
) -> dict:
    """Transkripsi satu file audio, simpan ke output/."""
    ensure_dirs()
    check_ffmpeg()
    device = resolve_device(device)

    basename = sanitize_filename(output_name) if output_name else audio_path.stem
    model = get_model(model_name, device, on_status=on_status)

    msg = f"Memproses: {audio_path.name}"
    if on_status:
        on_status(msg)
    else:
        print(msg)

    result = model.transcribe(
        str(audio_path),
        language=language,
        task=task,
        word_timestamps=word_timestamps,
        verbose=False,
    )

    writer = get_writer(output_format, str(OUTPUT_DIR))
    fake_path = str(OUTPUT_DIR / f"{basename}{audio_path.suffix}")
    writer(result, fake_path)

    ext = "txt" if output_format == "all" else output_format
    output_path = OUTPUT_DIR / f"{basename}.{ext}"
    text = result.get("text", "").strip()
    lang = result.get("language", "-")

    if on_status:
        if output_format == "all":
            on_status(f"Selesai → output/{basename}.*")
        else:
            on_status(f"Selesai → output/{basename}.{ext}")
    else:
        print(f"  Bahasa: {lang}")
        if output_format == "all":
            print(f"  Disimpan: output/{basename}.*")
        else:
            print(f"  Disimpan: output/{basename}.{ext}")
        preview = text[:120] + ("..." if len(text) > 120 else "")
        print(f"  Preview: {preview}")

    return {
        "text": text,
        "language": lang,
        "output_path": output_path,
        "basename": basename,
    }
