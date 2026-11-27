# E-MoM FRI — Resume Aplikasi dan Stack

**Ringkasan aplikasi dan arsitektur teknologi**  
**Pembaruan:** 24 November 2026

## 1. Ringkasan

E-MoM FRI adalah platform pengolahan rekaman rapat berbasis kecerdasan artifisial untuk Fakultas Rekayasa Industri. Sistem mengubah berkas audio/video menjadi transkrip bahasa Indonesia yang memiliki timestamp dan, bila fitur diarization digunakan, label pembicara.

Prototype saat ini telah menyediakan mesin speech-to-text, aplikasi desktop, dan portal web multi-user. Hasil transkripsi tersedia dalam beberapa format agar dapat dibaca, diberi subtitle, dianalisis, atau diproses lebih lanjut. Generator Minutes of Meeting otomatis—ringkasan, keputusan, action item, PIC, deadline, dan isu terbuka—merupakan tahap pengembangan berikutnya dan belum menjadi fitur produksi.

## 2. Masalah yang Diselesaikan

- Pembuatan notulen manual membutuhkan waktu untuk mendengarkan kembali rekaman.
- Ucapan beberapa peserta sulit dipisahkan dan dikaitkan dengan pembicara.
- Keputusan dan tindak lanjut dapat terlewat.
- Hasil transkripsi manual tidak selalu memiliki timestamp rujukan.
- Rekaman rapat internal dapat bersifat sensitif jika dikirim ke layanan publik.
- Banyak pengguna membutuhkan antrean, penyimpanan, kuota, dan riwayat pemrosesan yang terpusat.

## 3. Pengguna dan Cara Kerja

### 3.1 Pengguna

- Pimpinan dan sekretariat fakultas.
- Program studi dan unit administrasi.
- Laboratorium, kelompok keahlian, dan tim proyek.
- Panitia atau unit yang rutin menyelenggarakan rapat.
- Admin sistem yang mengelola pengguna dan pekerjaan.

### 3.2 Alur Pengguna

1. Pengguna login ke portal.
2. Pengguna membuat folder atau memilih lokasi penyimpanan.
3. Pengguna mengunggah audio/video.
4. Pengguna memilih bahasa, VAD, dan opsi pemisahan pembicara.
5. Job masuk ke antrean.
6. Worker GPU mengambil satu job dan memprosesnya.
7. Portal menampilkan progres dan status.
8. Pengguna meninjau transkrip dan mengunduh hasil.
9. Pada roadmap berikutnya, transkrip diproses menjadi MoM yang dapat diedit dan diekspor.

## 4. Fitur yang Sudah Tersedia

### 4.1 Speech-to-Text

- Model `maleo-ai/whisper-large-v3-turbo-id`.
- faster-whisper dan CTranslate2.
- Bahasa Indonesia.
- VAD untuk menyaring bagian tanpa percakapan.
- GPU NVIDIA atau fallback CPU.

### 4.2 Speaker Diarization

- WhisperX untuk alignment.
- pyannote untuk pemisahan pembicara.
- Pilihan minimum dan maksimum pembicara.
- Segmen bertimestamp dengan label seperti `SPEAKER_00`.

### 4.3 Format Keluaran

- TXT biasa.
- Speaker transcript.
- SRT.
- VTT.
- JSON terstruktur.

### 4.4 Portal

- Login dan logout.
- Wajib ganti password pada login pertama.
- Role admin dan user.
- Manajemen user, kuota, folder, dan file.
- Upload, rename, move, download, stream, dan delete.
- Antrian job, progress, cancel, retry, dan timeout.
- Dashboard admin dan audit log.
- Worker heartbeat dan informasi GPU.

### 4.5 Aplikasi Desktop

- GUI tkinter untuk Windows.
- Pilihan file dan output.
- Progress transkripsi.
- Pemeriksaan FFmpeg, CUDA, dan device.
- Opsi diarization.

## 5. Arsitektur

```text
Browser
   |
   v
Caddy :80/:443
   |
   v
FastAPI Web  -----> PostgreSQL
   |                    ^
   |                    |
   +---- job queue -----+
                        |
                  GPU Worker
                        |
      FFmpeg -> faster-whisper -> WhisperX/pyannote
                        |
                        v
              Local Storage / FRI Mini CDN
```

### 5.1 Service Docker

| Service | Fungsi |
|---|---|
| `caddy` | Reverse proxy, HTTP/HTTPS, body limit, dan timeout upload |
| `web` | FastAPI, halaman portal, autentikasi, file, job, serta admin |
| `db` | PostgreSQL 16 untuk metadata portal, user, file, job, dan transkrip |
| `worker` | Mengambil job, menggunakan GPU, memuat model, dan menyimpan hasil |

### 5.2 Alur Pemrosesan Audio

```text
Upload
  -> validasi ekstensi, ukuran, kuota, dan durasi
  -> simpan lokal atau CDN
  -> submit job
  -> claim job oleh worker
  -> FFmpeg 16 kHz mono
  -> faster-whisper + model Maleo
  -> opsional: WhisperX alignment + pyannote diarization
  -> simpan segments dan transcript
  -> arsip hasil
  -> download/preview pengguna
```

## 6. Stack Teknologi

| Area | Teknologi | Fungsi |
|---|---|---|
| Bahasa | Python 3.12 | Runtime aplikasi desktop, web, dan worker |
| Web framework | FastAPI | Routing, API, dependency injection, upload, dan response |
| ASGI server | Uvicorn | Menjalankan FastAPI |
| UI portal | Jinja2, HTML, CSS, JavaScript | Server-rendered portal dan interaksi upload/progress |
| ORM | SQLAlchemy 2 | Model dan transaksi database |
| Database | PostgreSQL 16 | Data user, folder, file, job, transkrip, worker, dan audit |
| Reverse proxy | Caddy 2 | Akses HTTP/HTTPS dan proxy ke web |
| Container | Docker Engine, Docker Compose v2 | Packaging dan orkestrasi service |
| GPU runtime | NVIDIA Container Toolkit | Memberikan akses GPU ke worker |
| Deep learning | PyTorch 2.8 + CUDA 12.8 | CUDA runtime dan library GPU |
| STT engine | faster-whisper, CTranslate2 | Inference Whisper yang efisien |
| Model STT | Maleo Whisper Large V3 Turbo ID | Transkripsi bahasa Indonesia |
| Alignment | WhisperX | Alignment kata/segmen |
| Diarization | pyannote.audio | Pemisahan pembicara |
| Audio | FFmpeg | Decode, probe, dan normalisasi audio |
| Security | Argon2, itsdangerous, CSRF token | Hash password dan session bertanda |
| HTTP client | httpx | Integrasi FRI Mini CDN |
| Desktop | tkinter | GUI desktop Windows |
| Konfigurasi | `.env`, python-dotenv | Secret dan konfigurasi deployment |

## 7. Model Data Portal

| Entitas | Isi Utama |
|---|---|
| `users` | Username, password hash, role, kuota, dan status |
| `folders` | Struktur folder per user |
| `files` | Metadata audio, lokasi storage, ukuran, dan durasi |
| `jobs` | Status antrean, progress, stage, retry, dan worker |
| `transcripts` | Bahasa, teks, segments JSON, dan durasi |
| `speaker_labels` | Pemetaan label speaker |
| `workers` | Heartbeat, device, GPU, VRAM, dan job aktif |
| `audit_logs` | Aktivitas pengguna dan admin |
| `settings` | Konfigurasi operasional sederhana |

## 8. Keamanan

- Password disimpan menggunakan Argon2.
- Session cookie ditandatangani dan memiliki masa berlaku.
- CSRF protection untuk operasi yang mengubah data.
- Akses file dan folder dibatasi berdasarkan user.
- Role admin untuk operasi administratif.
- Rate limiter pada login.
- Security headers: `X-Content-Type-Options`, `X-Frame-Options`, dan `Referrer-Policy`.
- Secret disimpan melalui `.env` dan tidak dimasukkan ke image.
- Pemrosesan AI dapat dilakukan on-premise agar rekaman tidak dikirim ke layanan transkripsi publik.

## 9. Storage

### 9.1 Local Storage

Audio dapat disimpan di volume Docker `appdata`. Web dan worker memakai volume yang sama sehingga worker dapat mengambil file tanpa transfer eksternal.

### 9.2 FRI Mini CDN

Portal memiliki client untuk:

- Mendapatkan token JWT.
- Upload file.
- Download/stream.
- Hapus file.
- Sinkronisasi file lokal ke CDN.
- Arsip teks hasil transkripsi.

Kondisi terakhir menunjukkan akses HTTPS VM ke domain CDN masih memerlukan penyelesaian routing, hairpin NAT, atau split DNS.

## 10. Deployment

### 10.1 Kebutuhan

- Linux dengan Docker Engine dan Docker Compose v2.
- GPU NVIDIA dan driver yang mendukung CUDA 12.8.
- NVIDIA Container Toolkit.
- Ruang disk untuk image worker, model, database, dan audio.
- FFmpeg sudah disertakan di image.

### 10.2 Menjalankan

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f web worker
```

Worker siap ketika log menampilkan:

```text
Model siap (cuda).
```

Health check:

```bash
curl http://localhost/healthz
```

Hasil yang diharapkan:

```json
{"ok": true}
```

### 10.3 Volume

| Volume | Data |
|---|---|
| `pgdata` | Database PostgreSQL |
| `appdata` | Audio lokal dan work directory |
| `hf-cache` | Model dari Hugging Face |
| `caddy-data` | Data dan sertifikat Caddy |
| `caddy-config` | Konfigurasi internal Caddy |

## 11. Status Implementasi

| Area | Status |
|---|---|
| Desktop STT | Tersedia |
| Web portal | Tersedia, perlu finalisasi deployment publik |
| GPU worker | Tersedia dan telah memuat model |
| Transkripsi bahasa Indonesia | Tersedia |
| Alignment dan diarization | Tersedia pada kode; perlu validasi end-to-end data nyata |
| Local storage | Tersedia |
| FRI Mini CDN | Client tersedia; konektivitas jaringan belum tuntas |
| WAF/Cloudflare | Dalam proses perencanaan/onboarding |
| Generator MoM otomatis | Direncanakan, belum diimplementasikan |
| Editor dan ekspor MoM DOCX | Direncanakan, belum diimplementasikan |

## 12. Rencana Generator MoM

Rancangan alur berikut belum diimplementasikan:

```text
Transcript JSON
  -> gabungkan segmen dan bersihkan filler
  -> mapping speaker ke nama/jabatan
  -> potong berdasarkan token/topik
  -> LLM map: ekstraksi per bagian
  -> LLM reduce: gabung dan deduplikasi
  -> validasi JSON Schema
  -> preview/edit
  -> ekspor Markdown/DOCX
```

Keluaran yang direncanakan:

- Ringkasan eksekutif.
- Pembahasan per topik.
- Keputusan.
- Action item.
- PIC.
- Deadline.
- Isu terbuka.
- Timestamp sumber.

## 13. Struktur Source Code

| Path | Isi |
|---|---|
| `run.py`, `run.bat` | Entry point aplikasi desktop |
| `app/gui.py` | GUI desktop |
| `app/processor.py` | Transkripsi bersama |
| `app/speaker.py` | Alignment dan diarization |
| `app/checks.py` | Pemeriksaan FFmpeg/CUDA/device |
| `app/portal/web/` | FastAPI dan routes |
| `app/portal/worker.py` | Worker GPU |
| `app/portal/models.py` | Model database |
| `app/portal/queue.py` | Antrian job |
| `app/portal/storage.py` | Local storage dan CDN |
| `app/portal/cdn.py` | Client FRI Mini CDN |
| `app/portal/templates/` | Template HTML |
| `deploy/` | Dockerfile dan Caddyfile |
| `docker-compose.yml` | Orkestrasi container |
| `docs/stack.html` | Visual stack dan roadmap |
| `docs/web-portal.html` | Desain portal |

## 14. Dokumen Terkait

- `README.md` — instalasi dan operasional.
- `TODO.md` — daftar pekerjaan singkat.
- `docs/E-Mom FRI - Whats Next.md` — roadmap terperinci.
- `docs/stack.html` — visual stack, flow, model, dan roadmap.
- `docs/web-portal.html` — desain web portal.
- `docs/Doc Inovasi/E-Mom FRI.docx` — dokumen inovasi.

## 15. Kesimpulan

E-MoM FRI sudah memiliki fondasi teknis yang kuat untuk pengolahan rekaman rapat secara on-premise: mesin transkripsi bahasa Indonesia, GPU worker, speaker diarization, aplikasi desktop, portal multi-user, antrian, database, dan beberapa format keluaran. Fokus terdekat adalah menstabilkan akses publik, storage/CDN, backup, monitoring, serta pengujian diarization. Setelah fondasi operasional stabil, pengembangan berlanjut ke generator MoM berbasis LLM lokal, editor, dan ekspor DOCX.
