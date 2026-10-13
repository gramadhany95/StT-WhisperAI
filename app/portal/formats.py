"""Render hasil transkripsi ke txt / speakers / srt / vtt / json."""

from __future__ import annotations

import json
from typing import Any

FORMATS = {
    "txt": ("text/plain; charset=utf-8", "txt"),
    "speakers": ("text/plain; charset=utf-8", "speakers.txt"),
    "srt": ("application/x-subrip; charset=utf-8", "srt"),
    "vtt": ("text/vtt; charset=utf-8", "vtt"),
    "json": ("application/json; charset=utf-8", "json"),
}


def ts(seconds: float, sep: str = ".") -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def apply_labels(segments: list[dict[str, Any]], labels: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    for s in segments:
        s = dict(s)
        if s.get("speaker"):
            s["speaker"] = labels.get(s["speaker"]) or s["speaker"]
        out.append(s)
    return out


def has_speakers(segments: list[dict[str, Any]]) -> bool:
    return any(s.get("speaker") for s in segments)


def speaker_text(segments: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"[{ts(s['start'])} --> {ts(s['end'])}] {s.get('speaker') or 'SPEAKER_UNKNOWN'}\n{s['text']}"
        for s in segments
    )


def plain_text(segments: list[dict[str, Any]]) -> str:
    if has_speakers(segments):
        return speaker_text(segments)
    return " ".join(s["text"] for s in segments).strip()


def render(fmt: str, segments: list[dict[str, Any]], language: str) -> str:
    def label(s: dict) -> str:
        return f"[{s['speaker']}] {s['text']}" if s.get("speaker") else s["text"]

    if fmt == "txt":
        return plain_text(segments) + "\n"
    if fmt == "speakers":
        return speaker_text(segments) + "\n"
    if fmt == "srt":
        return "\n".join(
            f"{i}\n{ts(s['start'], ',')} --> {ts(s['end'], ',')}\n{label(s)}\n"
            for i, s in enumerate(segments, 1)
        )
    if fmt == "vtt":
        return "WEBVTT\n\n" + "\n".join(f"{ts(s['start'])} --> {ts(s['end'])}\n{label(s)}\n" for s in segments)
    if fmt == "json":
        return json.dumps(
            {"language": language, "text": plain_text(segments), "segments": segments},
            ensure_ascii=False, indent=2,
        )
    raise ValueError(fmt)
