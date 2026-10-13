"""Probe audio dengan ffprobe + validasi opsi transkripsi."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from app.languages import LANGUAGES
from app.portal.settings import HF_TOKEN

LANGUAGE_CHOICES = [("auto", "Auto (deteksi otomatis)")] + sorted(
    ((code, name.title()) for code, name in LANGUAGES.items()), key=lambda x: x[1]
)


def _ffprobe() -> Optional[str]:
    found = shutil.which("ffprobe")
    if found:
        return found
    try:
        from app.checks import find_ffmpeg
    except ImportError:
        return None
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        cand = Path(ffmpeg).with_name(Path(ffmpeg).name.replace("ffmpeg", "ffprobe"))
        if cand.is_file():
            return str(cand)
    return None


def probe_duration(path: Path) -> Optional[float]:
    """Durasi audio (detik), atau None jika file tidak bisa dibaca sebagai audio."""
    exe = _ffprobe()
    if not exe:
        raise RuntimeError("ffprobe tidak ditemukan (install ffmpeg).")
    r = subprocess.run(
        [exe, "-v", "error", "-select_streams", "a:0", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, timeout=120,
    )
    try:
        return float(r.stdout.strip().splitlines()[0]) if r.returncode == 0 else None
    except (ValueError, IndexError):
        return None


def speaker_available() -> bool:
    return bool(HF_TOKEN)


def build_options(language: str, speaker: bool, min_speakers: Optional[int], max_speakers: Optional[int],
                  vad: bool = True) -> dict:
    lang = None if language in ("", "auto") else language
    if lang is not None and lang not in LANGUAGES:
        raise ValueError("Bahasa tidak dikenal.")
    if speaker and not speaker_available():
        raise ValueError("Addon speaker belum aktif (HF_TOKEN belum diisi di server).")
    opts: dict = {"language": lang, "vad_filter": bool(vad), "use_speaker": bool(speaker)}
    if speaker:
        mn = min_speakers if min_speakers and min_speakers > 0 else None
        mx = max_speakers if max_speakers and max_speakers > 0 else None
        if mn and mx and mn > mx:
            raise ValueError("Min speaker tidak boleh lebih besar dari max speaker.")
        opts.update(min_speakers=mn, max_speakers=mx)
    return opts
