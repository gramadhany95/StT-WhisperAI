"""Transkripsi dengan maleo-ai/whisper-large-v3-turbo-id (faster-whisper) + addon speaker."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Optional

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

from app.checks import configure_runtime, load_audio, resolve_device
from app.config import (
    AUDIO_EXTENSIONS,
    DEFAULT_LANGUAGE,
    HF_MODEL_ID,
    HF_MODEL_SUBDIR,
    HF_TOKEN,
    INPUT_DIR,
    OUTPUT_DIR,
    SAMPLE_RATE,
    WHISPER_MODEL_PATH,
)

configure_runtime()

ProgressFn = Optional[Callable[[Optional[float], str], None]]

_model = None
_device: Optional[str] = None


def _report(on_progress: ProgressFn, fraction: Optional[float], msg: str) -> None:
    if on_progress:
        on_progress(fraction, msg)
    else:
        print(msg, flush=True)


def _model_path() -> str:
    if WHISPER_MODEL_PATH:
        return WHISPER_MODEL_PATH
    from huggingface_hub import snapshot_download

    kwargs = {"repo_id": HF_MODEL_ID, "allow_patterns": f"{HF_MODEL_SUBDIR}/*"}
    try:
        cache = snapshot_download(**kwargs, local_files_only=True)
    except Exception:
        cache = snapshot_download(**kwargs)
    return str(Path(cache) / HF_MODEL_SUBDIR)


def get_model(device: Optional[str] = None, on_progress: ProgressFn = None):
    global _model, _device
    device = resolve_device(device)
    if _model is not None and _device == device:
        return _model

    from faster_whisper import WhisperModel

    _report(on_progress, None, f"Memuat {HF_MODEL_ID} ({device}) — pertama kali bisa beberapa menit...")
    _model = WhisperModel(
        _model_path(),
        device=device,
        compute_type="int8_float16" if device == "cuda" else "int8",
        cpu_threads=4,
    )
    _device = device
    _report(on_progress, 1.0, f"Model siap ({device}).")
    return _model


def ensure_dirs() -> None:
    for d in (INPUT_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", name.strip())
    name = re.sub(r"\s+", "_", name)
    return name.strip("._") or "transcript"


def list_input_files() -> list[Path]:
    ensure_dirs()
    return sorted(
        p for p in INPUT_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
    )


def list_output_files() -> list[Path]:
    ensure_dirs()
    return sorted(p for p in OUTPUT_DIR.iterdir() if p.is_file() and not p.name.startswith("."))


def copy_to_input(src_path: Path) -> Path:
    ensure_dirs()
    if src_path.suffix.lower() not in AUDIO_EXTENSIONS:
        raise ValueError(f"Format tidak didukung: {src_path.suffix}")
    dest = INPUT_DIR / src_path.name
    counter = 1
    while dest.exists():
        dest = INPUT_DIR / f"{src_path.stem}_{counter}{src_path.suffix}"
        counter += 1
    shutil.copy2(src_path, dest)
    return dest


def _ts(seconds: float, sep: str = ".") -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _speaker_text(segments: list[dict]) -> str:
    return "\n\n".join(
        f"[{_ts(s['start'])} --> {_ts(s['end'])}] {s.get('speaker', 'SPEAKER_UNKNOWN')}\n{s['text']}"
        for s in segments
    )


def _write_outputs(result: dict, basename: str, output_format: str) -> Path:
    ensure_dirs()
    base = OUTPUT_DIR / basename
    segments = result["segments"]
    has_speaker = any(s.get("speaker") for s in segments)

    def label(seg: dict) -> str:
        return f"[{seg['speaker']}] {seg['text']}" if seg.get("speaker") else seg["text"]

    if output_format in ("txt", "all"):
        body = _speaker_text(segments) if has_speaker else result["text"]
        base.with_suffix(".txt").write_text(body + "\n", encoding="utf-8")

    if output_format in ("speakers", "all") and has_speaker:
        base.with_suffix(".speakers.txt").write_text(_speaker_text(segments) + "\n", encoding="utf-8")

    if output_format in ("json", "all"):
        base.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if output_format in ("srt", "all"):
        lines = [
            f"{i}\n{_ts(s['start'], ',')} --> {_ts(s['end'], ',')}\n{label(s)}\n"
            for i, s in enumerate(segments, 1)
        ]
        base.with_suffix(".srt").write_text("\n".join(lines), encoding="utf-8")

    if output_format in ("vtt", "all"):
        lines = ["WEBVTT\n"] + [f"{_ts(s['start'])} --> {_ts(s['end'])}\n{label(s)}\n" for s in segments]
        base.with_suffix(".vtt").write_text("\n".join(lines), encoding="utf-8")

    if output_format == "speakers":
        return base.with_suffix(".speakers.txt" if has_speaker else ".txt")
    return base.with_suffix(".txt" if output_format == "all" else f".{output_format}")


def transcribe_file(
    audio_path: Path,
    output_name: Optional[str] = None,
    *,
    language: Optional[str] = None,
    output_format: str = "txt",
    vad_filter: bool = True,
    beam_size: int = 5,
    device: Optional[str] = None,
    use_speaker: bool = False,
    hf_token: Optional[str] = None,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
    on_progress: ProgressFn = None,
) -> dict:
    """Transkripsi audio dari input/ → output/."""
    ensure_dirs()
    device = resolve_device(device)
    basename = sanitize_filename(output_name) if output_name else audio_path.stem
    model = get_model(device, on_progress=on_progress)

    _report(on_progress, 0.03, f"Membaca audio: {audio_path.name}")
    audio = load_audio(audio_path)
    duration = len(audio) / SAMPLE_RATE

    _report(on_progress, 0.05, "Transkripsi...")
    segments, info = model.transcribe(
        audio,
        language=language,
        beam_size=beam_size,
        vad_filter=vad_filter,
    )
    seg_list: list[dict[str, Any]] = []
    for seg in segments:
        text = seg.text.strip()
        if text:
            seg_list.append({"start": float(seg.start), "end": float(seg.end), "text": text})
        if duration > 0:
            frac = 0.05 + (0.55 if use_speaker else 0.9) * min(seg.end / duration, 1.0)
            _report(on_progress, frac, f"Transkripsi… {seg.end:.0f}s / {duration:.0f}s")
    lang = info.language or language or DEFAULT_LANGUAGE

    if use_speaker:
        from app.speaker import diarize

        token = (hf_token or HF_TOKEN or "").strip()
        if not token:
            raise RuntimeError(
                "Addon speaker butuh HF_TOKEN di .env (atau isi di kolom HF Token)."
            )
        seg_list = diarize(
            audio,
            seg_list,
            language=lang,
            device=device,
            hf_token=token,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
            on_progress=on_progress,
        )
        text = _speaker_text(seg_list)
    else:
        text = " ".join(s["text"] for s in seg_list).strip()

    result = {"text": text, "language": lang, "segments": seg_list}
    _report(on_progress, 0.97, "Menyimpan output...")
    output_path = _write_outputs(result, basename, output_format)
    _report(on_progress, 1.0, f"Selesai → output/{output_path.name}")

    return {**result, "output_path": output_path, "basename": basename}
