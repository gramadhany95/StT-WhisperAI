# StT-WhisperAI

Aplikasi desktop speech-to-text (tkinter) memakai model
[maleo-ai/whisper-large-v3-turbo-id](https://huggingface.co/maleo-ai/whisper-large-v3-turbo-id)
lewat faster-whisper, dengan addon pemisahan speaker dari
[WhisperX](https://github.com/m-bain/whisperX).

## Menjalankan

```bat
run.bat
```

Pertama kali, `run.bat` memasang dependensi otomatis (Python 3.12):
PyTorch 2.8 CUDA 12.8, lalu `requirements-app.txt` (whisperx 3.8.6, faster-whisper, ctranslate2 4.6+).

Kebutuhan:
- Python 3.12 (`py -3.12`)
- GPU NVIDIA dengan driver terbaru (opsional; tanpa GPU otomatis CPU)
- ffmpeg (`winget install ffmpeg`)

## Addon speaker

Isi `HF_TOKEN` di `.env` dan accept agreement
[pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1).
Centang **Pisahkan speaker** di aplikasi.

## Struktur

| Path | Isi |
|------|-----|
| `run.bat` / `run.py` | Entry point GUI |
| `app/gui.py` | Tampilan |
| `app/processor.py` | Transkripsi + simpan output |
| `app/speaker.py` | Addon WhisperX (alignment + diarization) |
| `app/checks.py` | ffmpeg, DLL CUDA, device |
| `input/`, `output/` | File audio dan hasil |
