"""
StT-WhisperAI — jalankan dengan GUI desktop (default) atau CLI.

  run.bat                    → GUI (Python 3.12 + CUDA)
  py -3.12 run.py            → sama, tanpa .venv
  py -3.12 run.py --cli -f x → mode CLI

Catatan: gunakan Python 3.12 (bukan 3.14) agar GPU CUDA terdeteksi.
"""

from __future__ import annotations

import argparse
import sys

import whisper

from app.checks import configure_ffmpeg, resolve_device

configure_ffmpeg()
from app.processor import INPUT_DIR, OUTPUT_DIR, list_input_files, transcribe_file


def run_cli(args: argparse.Namespace) -> int:
    if args.list:
        files = list_input_files()
        if not files:
            print(f"Tidak ada file audio di {INPUT_DIR}/")
            return 0
        print(f"File di {INPUT_DIR}/:")
        for f in files:
            print(f"  - {f.name}")
        return 0

    if args.file:
        audio_path = INPUT_DIR / args.file
        if not audio_path.exists():
            print(f"Error: file tidak ditemukan → input/{args.file}")
            return 1
        files = [audio_path]
    else:
        files = list_input_files()
        if not files:
            print(f"Tidak ada file audio di {INPUT_DIR}/")
            return 1
        if args.name and len(files) > 1:
            print("Error: --name hanya untuk satu file (-f).")
            return 1

    print(f"Input : {INPUT_DIR}/")
    print(f"Output: {OUTPUT_DIR}/")
    print(f"Device: {args.device}")
    print("-" * 40)

    for audio_path in files:
        name = args.name if args.name else None
        try:
            transcribe_file(
                audio_path,
                output_name=name,
                model_name=args.model,
                language=args.language,
                task=args.task,
                output_format=args.output_format,
                word_timestamps=args.word_timestamps,
                device=resolve_device(args.device),
            )
        except Exception as exc:
            print(f"  Gagal: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print()

    print("-" * 40)
    print("Selesai.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="StT-WhisperAI")
    parser.add_argument("--cli", action="store_true", help="Mode CLI (tanpa GUI)")
    parser.add_argument("-f", "--file", help="File di input/ (CLI)")
    parser.add_argument("-n", "--name", help="Nama output custom (CLI)")
    parser.add_argument("--model", default="turbo", choices=whisper.available_models())
    parser.add_argument("--language", default=None)
    parser.add_argument("--task", choices=["transcribe", "translate"], default="transcribe")
    parser.add_argument(
        "--format", dest="output_format",
        choices=["txt", "srt", "vtt", "tsv", "json", "all"], default="txt",
    )
    parser.add_argument("--word-timestamps", action="store_true")
    parser.add_argument(
        "--device",
        choices=["cuda", "cpu"],
        default=resolve_device(),
    )
    parser.add_argument("--list", action="store_true", help="Daftar file input/ (CLI)")

    args = parser.parse_args()
    use_cli = args.cli or args.file or args.list

    if not use_cli:
        from app.gui import run_gui
        run_gui()
        return 0

    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
