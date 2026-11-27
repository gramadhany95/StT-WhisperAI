# TODO — StT-WhisperAI

Dokumen ini merangkum pekerjaan lanjutan dari `docs/stack.html`.

## Prioritas saat ini — Web Portal + Docker

- [ ] Stabilkan web portal dan alur antrean job.
- [x] Verifikasi deployment Docker dengan GPU NVIDIA.
- [x] Uji login, pembuatan folder, upload, transkripsi, unduh, dan hapus secara end-to-end.
- [ ] Uji diarization setelah `HF_TOKEN` dikonfigurasi.
- [x] Uji penyimpanan audio lokal.
- [ ] Uji sinkronisasi ke FRI Mini CDN setelah kredensial CDN dikonfigurasi.
- [ ] Tambahkan pengujian untuk autentikasi, manajemen user, dan pemulihan job gagal.
- [ ] Dokumentasikan prosedur deployment, update, backup, dan troubleshooting.

## LLM / Minutes of Meeting — Ditahan

Dikerjakan setelah web portal stabil. LLM akan berjalan di server terpisah dan dipanggil melalui API.

### Fase 0 — Persiapan

- [ ] Cek kapasitas VRAM dengan `nvidia-smi`.
- [ ] Tentukan runtime LLM dan lokasi penyimpanan model.
- [ ] Siapkan 2–3 transkrip rapat nyata dan satu MoM manual sebagai pembanding.

### Fase 1 — Prototipe CLI

- [ ] Buat perintah `py -3.12 -m app.mom output/xxx.json`.
- [ ] Hasilkan MoM dalam format Markdown.
- [ ] Bandingkan 2–3 model dan pilih yang paling akurat untuk action item.

### Fase 2 — Kualitas

- [ ] Terapkan structured output dengan JSON schema dan mekanisme retry.
- [ ] Gabungkan segmen, hapus filler, dan lakukan deduplikasi pada tahap reduce.
- [ ] Tambahkan glosarium istilah serta nama proyek.
- [ ] Tambahkan pemetaan label speaker ke nama dan jabatan.
- [ ] Sertakan timestamp pada topik, keputusan, dan action item.

### Fase 3 — Integrasi

- [ ] Tambahkan fitur MoM pada web portal.
- [ ] Sediakan form metadata rapat dan pemetaan speaker.
- [ ] Tampilkan progress proses pembuatan MoM.
- [ ] Sediakan preview yang dapat diedit.
- [ ] Tambahkan ekspor Markdown dan DOCX.

### Fase 4 — Opsional

- [ ] Tambahkan pilihan provider cloud untuk rapat yang tidak sensitif.
- [ ] Tambahkan regenerasi per bagian.
- [ ] Sediakan beberapa template MoM.

## Selesai

- [x] Transkripsi dengan faster-whisper dan model Maleo.
- [x] Dukungan GPU CUDA 12.8.
- [x] Alignment dan diarization speaker dengan WhisperX/pyannote.
- [x] Aplikasi desktop tkinter.
- [x] Output TXT, speaker transcript, SRT, VTT, dan JSON.
