# StT-WhisperAI

Speech-to-text memakai model
[maleo-ai/whisper-large-v3-turbo-id](https://huggingface.co/maleo-ai/whisper-large-v3-turbo-id)
lewat faster-whisper, dengan addon pemisahan speaker dari
[WhisperX](https://github.com/m-bain/whisperX). Tersedia dua cara pakai:

- **Aplikasi desktop** (tkinter, Windows) — `run.bat`
- **Web portal** (Docker, server Linux + GPU NVIDIA) — multi-user, antrian job, file management via FRI Mini CDN

Desain lengkap portal: `docs/web-portal.html`.

## Aplikasi desktop

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
Centang **Pisahkan speaker** di aplikasi / portal.

## Web portal (Docker)

Service: `caddy` (reverse proxy, port 80/443) → `web` (FastAPI) → `db` (PostgreSQL 16) ← `worker` (GPU).
Worker mengambil satu job sekaligus dari antrian; tambah kapasitas dengan menambah replika worker di GPU lain.

### Kebutuhan server

- Linux dengan GPU NVIDIA + driver ≥ 570 (CUDA 12.8)
- Docker Engine + Docker Compose v2
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
  — cek: `docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi`
- Disk ±20 GB (image worker ±10 GB + model + audio)

### Deploy

```bash
git clone <repo> stt && cd stt
cp env.example .env      # lalu isi: SECRET_KEY, ADMIN_PASSWORD, POSTGRES_PASSWORD,
                         # HF_TOKEN, CDN_API_KEY, CDN_API_SECRET, PUBLIC_HOST
docker compose up -d --build
docker compose logs -f worker   # tunggu "Model siap (cuda)"
```

Buka `http://<ip-server>/`, login dengan `ADMIN_USERNAME` / `ADMIN_PASSWORD`, lalu ganti password.
Admin membuat akun user di menu **Admin → User**.

- `PUBLIC_HOST=:80` → HTTP via IP server. Isi domain (mis. `stt.domain.id`, DNS sudah mengarah ke server)
  untuk HTTPS otomatis, lalu set `COOKIE_SECURE=1`.
- Upload pertama worker mengunduh model (±1,6 GB) ke volume `hf-cache`.

### Operasional

| Perintah | Fungsi |
|----------|--------|
| `docker compose ps` | Status service |
| `docker compose logs -f web worker` | Log |
| `docker compose up -d --build` | Update setelah `git pull` |
| `docker compose exec db pg_dump -U stt stt > backup.sql` | Backup database |

Data tersimpan di volume `pgdata` (database), `appdata` (audio lokal + file sementara), `hf-cache` (model).

### Storage audio

Selama FRI Mini CDN belum menerima MIME audio, audio disimpan di volume `appdata`.
Setelah admin CDN mengizinkan audio, klik **Admin → Cek CDN & sinkron** (atau tunggu worker, tiap jam saat idle)
untuk memindahkan file lokal ke CDN. Salinan `.txt` hasil transkrip selalu diarsipkan ke CDN.

### Tes lokal tanpa Docker (Windows)

```bat
py -3.12 -m pip install -r requirements-web.txt
py -3.12 -m uvicorn app.portal.web:app --port 8000
py -3.12 -m app.portal.worker
```

Tanpa `DATABASE_URL`, portal memakai SQLite di `data/portal.db`.

## Struktur

| Path | Isi |
|------|-----|
| `run.bat` / `run.py` | Entry point GUI desktop |
| `app/gui.py` | Tampilan desktop |
| `app/processor.py` | Transkripsi (dipakai desktop + worker) |
| `app/speaker.py` | Addon WhisperX (alignment + diarization) |
| `app/checks.py` | ffmpeg, DLL CUDA, device |
| `app/portal/` | Web portal: model DB, antrian, CDN, worker, web (FastAPI) |
| `deploy/`, `docker-compose.yml` | Dockerfile web/worker, Caddyfile |
| `docs/` | Dokumen stack & desain portal |
| `input/`, `output/` | File audio dan hasil (desktop) |
