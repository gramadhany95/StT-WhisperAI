# E-MoM FRI — What's Next

**Dokumen rencana pengembangan**  
**Pembaruan:** 24 November 2026

## 1. Tujuan

Dokumen ini merangkum kondisi E-MoM FRI saat ini, pekerjaan yang perlu diselesaikan, serta fitur yang sudah direncanakan tetapi belum diimplementasikan. Urutan pengerjaan menempatkan stabilitas portal dan keamanan data sebagai prioritas sebelum pengembangan generator Minutes of Meeting (MoM) otomatis.

## 2. Kemampuan yang Sudah Tersedia

### 2.1 Mesin Speech-to-Text

- Transkripsi bahasa Indonesia menggunakan `maleo-ai/whisper-large-v3-turbo-id`.
- Inference melalui faster-whisper dan CTranslate2.
- Akselerasi GPU NVIDIA dengan PyTorch 2.8 dan CUDA 12.8.
- Normalisasi audio menggunakan FFmpeg.
- Dukungan format MP3, M4A, WAV, FLAC, OGG, WebM, MP4, MPEG, WMA, dan AAC.
- Keluaran TXT, speaker transcript, SRT, VTT, dan JSON.

### 2.2 Pemisahan Pembicara

- Alignment menggunakan WhisperX.
- Diarization menggunakan `pyannote/speaker-diarization-community-1`.
- Opsi jumlah minimum dan maksimum pembicara.
- Label speaker dan timestamp pada segmen transkrip.

### 2.3 Aplikasi Desktop

- GUI desktop berbasis tkinter untuk Windows.
- Pemeriksaan FFmpeg, CUDA, dan perangkat komputasi.
- Progress proses dan pilihan pemisahan pembicara.
- Mode GPU maupun fallback CPU.

### 2.4 Web Portal

- FastAPI, Jinja2, PostgreSQL, dan worker GPU.
- Login, ganti password awal, session cookie, CSRF protection, dan password Argon2.
- Peran admin dan user.
- Manajemen user, kuota, folder, file, dan audit log.
- Antrian pekerjaan dengan satu job aktif per worker.
- Progress, pembatalan, retry, timeout, dan pemulihan job stale.
- Penyimpanan lokal dengan rancangan sinkronisasi ke FRI Mini CDN.
- Deployment Docker Compose: Caddy, web, database, dan worker.

### 2.5 Verifikasi yang Sudah Dilakukan

- Docker dan NVIDIA Container Toolkit berhasil mendeteksi GPU.
- Container database dan web mencapai status healthy.
- Worker berhasil memuat model pada CUDA.
- Health endpoint mengembalikan `{"ok":true}`.
- Alur login, pembuatan folder, upload, transkripsi, unduh, dan hapus pernah diuji end-to-end dengan penyimpanan lokal.

## 3. Kondisi dan Blocker Saat Ini

### 3.1 Akses Publik Portal

Portal masih memerlukan onboarding melalui Cloudflare dan Web Application Firewall Telkom University. Origin yang diajukan adalah server internal, sedangkan domain publik direncanakan memakai subdomain `virtualfri.id`.

Yang perlu diselesaikan:

- Domain publik dan endpoint WAF.
- Origin WAF menuju Caddy pada port internal.
- TLS end-to-end dan `COOKIE_SECURE=1`.
- Forwarding header `Host`, `X-Forwarded-For`, dan `X-Forwarded-Proto`.
- Metode GET, POST, PUT, dan DELETE.
- Header `X-CSRF-Token`.
- Batas ukuran serta timeout upload audio.

### 3.2 Koneksi FRI Mini CDN

VM masih meresolusikan `cdn-fri.virtualfri.id` ke alamat publik yang tidak dapat diakses melalui HTTPS dari jaringan internal. Dibutuhkan salah satu solusi berikut:

- Hairpin NAT/NAT loopback pada gateway.
- Split DNS yang mengarahkan domain CDN ke IP privat.
- Perbaikan routing/firewall outbound TCP 443.

Di sisi aplikasi, kegagalan koneksi jaringan dari `httpx` belum dibungkus menjadi `CdnError`. Akibatnya, ketika konfigurasi CDN aktif tetapi CDN tidak dapat dihubungi, upload dapat berakhir dengan HTTP 500 alih-alih fallback ke penyimpanan lokal.

### 3.3 Pengujian Diarization

Diarization tersedia pada kode, tetapi perlu pengujian end-to-end menggunakan:

- `HF_TOKEN` yang valid.
- Persetujuan akses model pyannote di Hugging Face.
- Rekaman rapat nyata dengan beberapa pembicara.
- Evaluasi ketepatan label speaker dan pergantian pembicara.

### 3.4 Batas Upload di Cloudflare/WAF

Portal saat ini mengirim satu file melalui satu request `PUT`. Batas aplikasi dapat mencapai sekitar 1 GB, sedangkan batas efektif Cloudflare/WAF mungkin lebih kecil. Perlu diputuskan:

- Menyesuaikan batas upload portal dengan batas WAF; atau
- Mengimplementasikan chunked/resumable upload.

## 4. Prioritas Pengembangan

## P0 — Stabilitas dan Kesiapan Produksi

- [ ] Selesaikan akses publik melalui Cloudflare dan WAF.
- [ ] Perbaiki routing/split DNS menuju FRI Mini CDN.
- [ ] Tangani seluruh `httpx.HTTPError` sebagai `CdnError` agar fallback lokal selalu bekerja.
- [ ] Uji upload ketika CDN aktif, CDN menolak MIME, CDN timeout, dan CDN offline.
- [ ] Tetapkan batas upload berdasarkan limit WAF.
- [ ] Tambahkan backup terjadwal PostgreSQL dan uji proses restore.
- [ ] Dokumentasikan prosedur deploy, update, rollback, backup, restore, dan troubleshooting.
- [ ] Tambahkan monitoring kapasitas disk, database, worker heartbeat, antrean, serta job gagal.

**Kriteria selesai:** portal dapat diakses melalui HTTPS, upload tidak menghasilkan HTTP 500 ketika CDN terganggu, dan prosedur pemulihan telah diuji.

## P1 — Kualitas Transkripsi dan Speaker

- [ ] Uji diarization dengan rekaman rapat nyata.
- [ ] Siapkan dataset evaluasi: 2–3 rekaman dan transkrip referensi.
- [ ] Ukur waktu proses terhadap durasi audio.
- [ ] Catat koreksi kata, istilah, nama orang, dan pergantian speaker.
- [ ] Tambahkan glosarium istilah FRI, nama unit, proyek, dan singkatan.
- [ ] Sediakan pemetaan `SPEAKER_00` menjadi nama dan jabatan.
- [ ] Tambahkan tes otomatis untuk format keluaran.

**Kriteria selesai:** hasil transkrip dan speaker telah dibandingkan dengan referensi manual serta memiliki catatan kualitas yang dapat diulang.

## P2 — MVP Generator MoM

Fitur berikut sudah direncanakan, tetapi belum diimplementasikan:

- [ ] Buat service LLM terpisah; portal hanya memanggil API.
- [ ] Tentukan runtime: Ollama atau llama.cpp.
- [ ] Bandingkan model lokal untuk bahasa Indonesia, misalnya Qwen, Gemma, dan Sahabat-AI.
- [ ] Buat modul praproses untuk menggabungkan segmen pendek dan membersihkan filler tanpa mengubah makna.
- [ ] Implementasikan pemotongan transkrip berdasarkan token dan batas topik.
- [ ] Implementasikan ekstraksi map-reduce untuk rapat panjang.
- [ ] Gunakan structured output dengan JSON Schema.
- [ ] Tambahkan validasi, retry, dan pencatatan respons yang gagal.
- [ ] Deduplikasi keputusan dan action item pada tahap reduce.
- [ ] Wajibkan timestamp sumber pada setiap poin penting.

Skema keluaran minimum:

```json
{
  "topik": [],
  "ringkasan_eksekutif": "",
  "keputusan": [],
  "action_items": [],
  "isu_terbuka": []
}
```

Setiap action item minimal memiliki tugas, PIC, deadline jika disebutkan, status kepastian, dan timestamp rujukan.

**Kriteria selesai:** satu transkrip JSON dapat diproses melalui CLI/API menjadi MoM terstruktur yang valid dan dapat ditelusuri ke sumber.

## P3 — Integrasi MoM ke Portal

- [ ] Tambahkan halaman atau tab MoM.
- [ ] Pilih transkrip yang akan diproses.
- [ ] Form metadata rapat: judul, tanggal, lokasi, agenda, dan peserta.
- [ ] Pemetaan label speaker ke nama dan jabatan.
- [ ] Progress pembuatan MoM.
- [ ] Preview yang dapat diedit.
- [ ] Regenerasi per bagian tanpa mengulang seluruh dokumen.
- [ ] Ekspor Markdown dan DOCX.
- [ ] Simpan versi draft, hasil edit, dan riwayat regenerasi.
- [ ] Audit penggunaan LLM dan error tanpa menyimpan secret.

**Kriteria selesai:** pengguna dapat membuat, meninjau, mengedit, menyimpan, dan mengunduh MoM dari portal.

## P4 — Fitur Lanjutan

- [ ] Beberapa template MoM sesuai jenis rapat.
- [ ] Provider cloud opsional untuk rapat yang tidak sensitif.
- [ ] Approval workflow sebelum MoM dipublikasikan.
- [ ] Pencarian lintas transkrip dan MoM.
- [ ] Dashboard keputusan dan action item.
- [ ] Pengingat deadline serta status tindak lanjut.
- [ ] Integrasi kalender, email, atau sistem internal FRI.
- [ ] Dukungan worker multi-GPU dan penjadwalan berdasarkan kapasitas.

## 5. Pengujian yang Perlu Ditambahkan

### 5.1 Autentikasi dan Otorisasi

- Login berhasil/gagal dan rate limit.
- Wajib ganti password.
- Session expiration dan logout.
- CSRF pada seluruh operasi mutasi.
- User tidak dapat mengakses file, folder, job, atau transkrip milik user lain.
- Hak admin dan user.

### 5.2 File dan Storage

- Upload setiap format yang didukung.
- File kosong, format palsu, ukuran melebihi batas, dan kuota habis.
- Penyimpanan lokal, CDN, serta fallback.
- Sinkronisasi lokal ke CDN.
- Download, stream, rename, move, dan delete.

### 5.3 Queue dan Worker

- Submit, claim, cancel, retry, timeout, dan shutdown.
- Job dikembalikan ke antrean saat worker berhenti.
- Batas percobaan job.
- Heartbeat worker dan deteksi stale.
- GPU tidak tersedia dan fallback CPU.

### 5.4 MoM

- JSON Schema valid.
- Timestamp selalu merujuk segmen yang ada.
- Tidak membuat PIC atau deadline yang tidak disebutkan.
- Deduplikasi keputusan/action item.
- Rapat pendek, panjang, tanpa keputusan, dan dengan pembicara tidak dikenal.

## 6. Urutan Eksekusi yang Direkomendasikan

1. Tuntaskan WAF, CDN, fallback lokal, backup, dan monitoring.
2. Validasi transkripsi dan diarization pada data nyata.
3. Bangun MVP MoM sebagai CLI/API terpisah.
4. Evaluasi beberapa model terhadap MoM manual.
5. Integrasikan model terpilih ke portal.
6. Tambahkan editor, ekspor DOCX, template, dan workflow approval.
7. Kembangkan pencarian serta pelacakan action item.

## 7. Risiko dan Mitigasi

| Risiko | Dampak | Mitigasi |
|---|---|---|
| CDN/WAF tidak tersedia | Upload gagal atau portal tidak dapat diakses | Fallback lokal, retry, monitoring, dan runbook |
| VRAM tidak cukup | Worker gagal atau lambat | Muat STT dan LLM bergantian atau pisahkan server |
| Salah diarization | PIC salah | Mapping manual speaker dan timestamp verifikasi |
| Halusinasi LLM | Keputusan/action item tidak sesuai | Structured output, timestamp wajib, approval pengguna |
| Upload file besar | Ditolak Cloudflare/WAF | Limit yang jelas atau resumable upload |
| Data rapat sensitif | Kebocoran informasi | On-premise, least privilege, audit, TLS, dan retention policy |
| Disk penuh | Job serta database terganggu | Monitoring, kuota, lifecycle file, backup, dan cleanup |

## 8. Definisi Selesai Produk

E-MoM FRI dianggap siap digunakan secara operasional apabila:

- Portal tersedia melalui HTTPS dan WAF.
- Upload tetap aman saat CDN normal maupun terganggu.
- Transkripsi dan diarization telah diuji pada rapat nyata.
- Backup dan restore berhasil diuji.
- MoM menampilkan sumber timestamp dan wajib direview manusia.
- Dokumen MoM dapat diedit serta diekspor ke DOCX/Markdown.
- Admin memiliki monitoring, audit, dan prosedur penanganan insiden.
