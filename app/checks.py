"""Konfigurasi runtime: DLL CUDA (Windows), ffmpeg, pemilihan device."""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Optional

import numpy as np

from app.config import FORCE_CPU, SAMPLE_RATE

warnings.filterwarnings("ignore", message="pkg_resources is deprecated", category=UserWarning)

FFMPEG_INSTALL_HINT = (
    "ffmpeg tidak ditemukan. Dibutuhkan untuk membaca audio.\n\n"
    "Install:  winget install ffmpeg\n"
    "atau set FFMPEG_PATH=C:\\path\\to\\ffmpeg.exe di .env\n\n"
    "Setelah install, buka ulang aplikasi."
)

_FFMPEG_PATH: Optional[str] = None
_CONFIGURED = False


def _add_dll_dir(directory: Path) -> None:
    if not directory.is_dir():
        return
    d = str(directory)
    if d.lower() not in os.environ.get("PATH", "").lower():
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(d)
        except OSError:
            pass


def _configure_cuda_dlls() -> None:
    """CTranslate2 memakai cuBLAS 12 + cuDNN 9 yang dibawa PyTorch (torch/lib)."""
    if sys.platform != "win32":
        return
    import torch

    _add_dll_dir(Path(torch.__file__).resolve().parent / "lib")


def _ffmpeg_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.environ.get("FFMPEG_PATH", "").strip().strip('"')
    if env_path:
        candidates.append(Path(env_path))
    which = shutil.which("ffmpeg")
    if which:
        candidates.append(Path(which))
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            pattern = os.path.join(local, "Microsoft", "WinGet", "Packages", "*", "*", "bin", "ffmpeg.exe")
            candidates.extend(Path(p) for p in glob.glob(pattern))
        candidates.extend([
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ffmpeg" / "bin" / "ffmpeg.exe",
            Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
            Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "chocolatey" / "bin" / "ffmpeg.exe",
            Path.home() / "scoop" / "shims" / "ffmpeg.exe",
        ])
    return candidates


def find_ffmpeg() -> Optional[str]:
    global _FFMPEG_PATH
    if _FFMPEG_PATH:
        return _FFMPEG_PATH
    for path in _ffmpeg_candidates():
        if path.is_file():
            _FFMPEG_PATH = str(path.resolve())
            return _FFMPEG_PATH
    return None


def configure_runtime() -> bool:
    """Panggil sekali di awal. Return True jika ffmpeg tersedia."""
    global _CONFIGURED
    if not _CONFIGURED:
        _configure_cuda_dlls()
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            # whisperx.load_audio memanggil "ffmpeg" lewat PATH
            _add_dll_dir(Path(ffmpeg).parent)
        _CONFIGURED = True
    return find_ffmpeg() is not None


def ffmpeg_status() -> str:
    path = find_ffmpeg()
    return f"ffmpeg: {path}" if path else "ffmpeg: tidak ditemukan"


def load_audio(path: str | Path, sr: int = SAMPLE_RATE) -> np.ndarray:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(FFMPEG_INSTALL_HINT)
    cmd = [
        ffmpeg, "-nostdin", "-threads", "0", "-i", str(path),
        "-f", "s16le", "-ac", "1", "-acodec", "pcm_s16le", "-ar", str(sr), "-",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, check=True).stdout
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Gagal membaca audio: {e.stderr.decode(errors='ignore')}") from e
    return np.frombuffer(out, np.int16).flatten().astype(np.float32) / 32768.0


def cuda_available() -> bool:
    if FORCE_CPU:
        return False
    import torch

    return torch.cuda.is_available()


def resolve_device(requested: Optional[str] = None) -> str:
    if requested == "cpu" or not cuda_available():
        return "cpu"
    return "cuda"


def format_error(exc: BaseException) -> str:
    msg = str(exc)
    low = msg.lower()
    if ".dll" in low and ("cudnn" in low or "cublas" in low):
        return (
            "DLL CUDA tidak ditemukan.\n\n"
            "Tutup aplikasi lalu jalankan ulang run.bat (dependensi akan dicek ulang),\n"
            "atau set FORCE_CPU=1 di .env.\n\n"
            f"Detail: {msg}"
        )
    if "ffmpeg" in low:
        return FFMPEG_INSTALL_HINT if not find_ffmpeg() else msg
    if "401" in msg or "gated" in low or ("accept" in low and "huggingface" in low):
        return (
            "Akses model diarization ditolak Hugging Face.\n\n"
            "1. Login ke huggingface.co lalu accept agreement:\n"
            "   https://huggingface.co/pyannote/speaker-diarization-community-1\n"
            "2. Pastikan HF_TOKEN di .env valid.\n\n"
            f"Detail: {msg}"
        )
    return msg
