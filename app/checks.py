"""Deteksi dan konfigurasi ffmpeg untuk Whisper."""

from __future__ import annotations

import glob
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

import torch

FFMPEG_INSTALL_HINT = (
    "ffmpeg tidak ditemukan. Whisper membutuhkan ffmpeg untuk membaca audio.\n\n"
    "Install:\n"
    "  winget install ffmpeg\n\n"
    "Atau set path manual:\n"
    "  set FFMPEG_PATH=C:\\path\\to\\ffmpeg.exe\n\n"
    "Setelah install, restart terminal/aplikasi."
)

_FFMPEG_PATH: Optional[str] = None
_CONFIGURED = False


def _win_get_ffmpeg_paths() -> list[Path]:
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return []
    pattern = os.path.join(
        local, "Microsoft", "WinGet", "Packages", "*", "*", "bin", "ffmpeg.exe"
    )
    return [Path(p) for p in glob.glob(pattern)]


def _candidate_paths() -> list[Path]:
    candidates: list[Path] = []

    env_path = os.environ.get("FFMPEG_PATH", "").strip().strip('"')
    if env_path:
        candidates.append(Path(env_path))

    which = shutil.which("ffmpeg")
    if which:
        candidates.append(Path(which))

    if sys.platform == "win32":
        candidates.extend(_win_get_ffmpeg_paths())
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        candidates.extend([
            Path(program_files) / "ffmpeg" / "bin" / "ffmpeg.exe",
            Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
            Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "chocolatey" / "bin" / "ffmpeg.exe",
            Path.home() / "scoop" / "shims" / "ffmpeg.exe",
        ])
    else:
        candidates.extend([
            Path("/usr/bin/ffmpeg"),
            Path("/usr/local/bin/ffmpeg"),
            Path("/opt/homebrew/bin/ffmpeg"),
        ])

    return candidates


def find_ffmpeg() -> Optional[str]:
    global _FFMPEG_PATH
    if _FFMPEG_PATH:
        return _FFMPEG_PATH

    for path in _candidate_paths():
        if path.is_file():
            _FFMPEG_PATH = str(path.resolve())
            return _FFMPEG_PATH
    return None


def configure_ffmpeg() -> bool:
    """Pastikan ffmpeg bisa dipakai Whisper (PATH + patch load_audio)."""
    global _CONFIGURED
    if _CONFIGURED:
        return find_ffmpeg() is not None

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        _CONFIGURED = True
        return False

    bin_dir = str(Path(ffmpeg).parent)
    path_env = os.environ.get("PATH", "")
    if bin_dir.lower() not in path_env.lower():
        os.environ["PATH"] = bin_dir + os.pathsep + path_env

    _patch_whisper_audio(ffmpeg)
    _CONFIGURED = True
    return True


def _patch_whisper_audio(ffmpeg_path: str) -> None:
    """Ganti perintah ffmpeg di whisper.audio.load_audio dengan path penuh."""
    import whisper.audio as whisper_audio

    if getattr(whisper_audio.load_audio, "_stt_patched", False):
        return

    original = whisper_audio.load_audio

    def load_audio_patched(file: str, sr: int = whisper_audio.SAMPLE_RATE):
        from subprocess import CalledProcessError, run

        cmd = [
            ffmpeg_path,
            "-nostdin",
            "-threads", "0",
            "-i", file,
            "-f", "s16le",
            "-ac", "1",
            "-acodec", "pcm_s16le",
            "-ar", str(sr),
            "-",
        ]
        try:
            out = run(cmd, capture_output=True, check=True).stdout
        except CalledProcessError as e:
            raise RuntimeError(f"Failed to load audio: {e.stderr.decode()}") from e

        import numpy as np
        return np.frombuffer(out, np.int16).flatten().astype(np.float32) / 32768.0

    load_audio_patched._stt_patched = True  # type: ignore[attr-defined]
    whisper_audio.load_audio = load_audio_patched


def cuda_available() -> bool:
    return torch.cuda.is_available()


def resolve_device(requested: Optional[str] = None) -> str:
    if requested is None:
        return "cuda" if cuda_available() else "cpu"
    if requested == "cuda" and not cuda_available():
        return "cpu"
    return requested


def check_ffmpeg() -> None:
    if not configure_ffmpeg():
        raise RuntimeError(FFMPEG_INSTALL_HINT)


def check_ffmpeg_quiet() -> bool:
    return configure_ffmpeg()


def ffmpeg_status() -> str:
    path = find_ffmpeg()
    if path:
        return f"ffmpeg: {path}"
    return "ffmpeg: tidak ditemukan"


def format_error(exc: BaseException) -> str:
    if isinstance(exc, (FileNotFoundError, OSError)):
        msg = str(exc).lower()
        winerror = getattr(exc, "winerror", None)
        errno = getattr(exc, "errno", None)
        if "ffmpeg" in msg or winerror == 2 or errno == 2:
            if find_ffmpeg():
                return (
                    f"Gagal menjalankan ffmpeg.\n\n"
                    f"Path terdeteksi: {find_ffmpeg()}\n\n"
                    f"Detail: {exc}"
                )
            return FFMPEG_INSTALL_HINT
        return f"File tidak ditemukan: {exc}"

    msg = str(exc)
    if "cuda" in msg.lower() and "is_available" in msg.lower():
        return (
            "CUDA tidak tersedia di komputer ini. "
            "Pilih Device: cpu di pengaturan, lalu coba lagi."
        )
    return msg
