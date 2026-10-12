"""Addon speaker (WhisperX): alignment timestamp + diarization pyannote."""

from __future__ import annotations

import gc
from typing import Any, Callable, Optional

import numpy as np

ProgressFn = Optional[Callable[[Optional[float], str], None]]

# Rentang progress bar total (transkripsi memakai 0–60%)
_ALIGN_RANGE = (0.60, 0.72)
_DIARIZE_RANGE = (0.72, 0.95)


def _scaled(on_progress: ProgressFn, rng: tuple[float, float], label: str):
    def cb(pct: float) -> None:
        if on_progress:
            lo, hi = rng
            on_progress(lo + (hi - lo) * min(max(pct, 0.0), 100.0) / 100.0, f"{label} {pct:.0f}%")
    return cb


def _free(device: str) -> None:
    gc.collect()
    if device == "cuda":
        import torch

        torch.cuda.empty_cache()


def diarize(
    audio: np.ndarray,
    segments: list[dict[str, Any]],
    *,
    language: str,
    device: str,
    hf_token: str,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
    on_progress: ProgressFn = None,
) -> list[dict[str, Any]]:
    """Return segmen dengan key 'speaker' (SPEAKER_00, SPEAKER_01, ...)."""
    if not segments:
        return segments

    import whisperx
    from whisperx.diarize import DiarizationPipeline

    if on_progress:
        on_progress(_ALIGN_RANGE[0], "Speaker: memuat model alignment...")
    align_model, metadata = whisperx.load_align_model(language_code=language, device=device)
    try:
        aligned = whisperx.align(
            segments,
            align_model,
            metadata,
            audio,
            device,
            return_char_alignments=False,
            progress_callback=_scaled(on_progress, _ALIGN_RANGE, "Speaker: alignment"),
        )
    finally:
        del align_model
        _free(device)

    if on_progress:
        on_progress(_DIARIZE_RANGE[0], "Speaker: memuat model diarization...")
    try:
        pipeline = DiarizationPipeline(token=hf_token, device=device)
    except Exception as exc:
        raise RuntimeError(
            "Hugging Face gated: token belum punya akses ke model diarization. "
            "Accept agreement di huggingface.co/pyannote/speaker-diarization-community-1"
        ) from exc
    try:
        diarized = pipeline(
            audio,
            min_speakers=min_speakers or None,
            max_speakers=max_speakers or None,
            progress_callback=_scaled(on_progress, _DIARIZE_RANGE, "Speaker: diarization"),
        )
    finally:
        del pipeline
        _free(device)

    aligned = whisperx.assign_word_speakers(diarized, aligned)

    out: list[dict[str, Any]] = []
    for seg in aligned.get("segments", []):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        out.append({
            "start": float(seg.get("start") or 0.0),
            "end": float(seg.get("end") or 0.0),
            "text": text,
            "speaker": seg.get("speaker") or "SPEAKER_UNKNOWN",
        })
    return out
