"""StT-WhisperAI — buka GUI desktop. Jalankan lewat run.bat."""

from __future__ import annotations

from app.checks import configure_runtime

configure_runtime()

from app.gui import run_gui  # noqa: E402

if __name__ == "__main__":
    run_gui()
