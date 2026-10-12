"""Desktop GUI (tkinter) untuk StT-WhisperAI."""

from __future__ import annotations

import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app.checks import configure_runtime, cuda_available, ffmpeg_status, format_error, resolve_device
from app.config import HF_MODEL_ID, HF_TOKEN, INPUT_DIR, OUTPUT_DIR
from app.languages import LANGUAGE_LABELS, code_to_label, label_to_code
from app.processor import copy_to_input, get_model, list_input_files, list_output_files, transcribe_file

AUDIO_FILETYPES = [
    ("Audio/Video", "*.mp3 *.wav *.flac *.m4a *.ogg *.webm *.mp4 *.mpeg *.mpga *.wma *.aac"),
    ("Semua file", "*.*"),
]


class StTApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("StT-WhisperAI")
        self.minsize(760, 600)
        self.geometry("880x680")

        self._processing = False
        self._model_ready = False
        self._indeterminate = False
        self._build_ui()
        self._refresh_lists()

        if not configure_runtime():
            messagebox.showwarning("ffmpeg tidak ditemukan", format_error(RuntimeError("ffmpeg")))
        self._preload_model()

    # ---------- UI ----------
    def _build_ui(self) -> None:
        gpu = cuda_available()
        device_hint = "GPU CUDA" if gpu else "CPU"

        ttk.Label(
            self,
            text=f"Speech-to-Text  •  {HF_MODEL_ID}  •  {device_hint}",
            font=("Segoe UI", 10),
        ).pack(fill="x", padx=12, pady=(10, 2))
        ttk.Label(self, text=ffmpeg_status(), font=("Segoe UI", 8), foreground="gray").pack(
            fill="x", padx=12, pady=(0, 4)
        )

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=12, pady=4)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(body, text="File Audio (input/)", padding=8)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        btn_row = ttk.Frame(left)
        btn_row.pack(fill="x", pady=(0, 6))
        ttk.Button(btn_row, text="Upload File...", command=self._upload).pack(side="left")
        ttk.Button(btn_row, text="Refresh", command=self._refresh_lists).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Buka folder input", command=lambda: self._open_folder(INPUT_DIR)).pack(side="left")
        self.input_list = tk.Listbox(left, height=12, selectmode="single", exportselection=False)
        self.input_list.pack(fill="both", expand=True)
        self.input_list.bind("<<ListboxSelect>>", self._on_input_select)

        right = ttk.LabelFrame(body, text="Pengaturan", padding=8)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        ttk.Label(right, text="Nama output (kosong = nama file audio):").pack(anchor="w")
        self.output_name = ttk.Entry(right)
        self.output_name.pack(fill="x", pady=(2, 8))

        ttk.Label(right, text="Bahasa:").pack(anchor="w")
        self.lang_var = tk.StringVar(value="Indonesian")
        ttk.Combobox(right, textvariable=self.lang_var, values=LANGUAGE_LABELS, state="readonly").pack(
            fill="x", pady=(2, 8)
        )

        ttk.Label(right, text="Format output:").pack(anchor="w")
        self.format_var = tk.StringVar(value="txt")
        ttk.Combobox(
            right, textvariable=self.format_var,
            values=["txt", "speakers", "srt", "vtt", "json", "all"], state="readonly",
        ).pack(fill="x", pady=(2, 8))

        ttk.Label(right, text="Device:").pack(anchor="w")
        self.device_var = tk.StringVar(value=resolve_device())
        ttk.Combobox(
            right, textvariable=self.device_var,
            values=["cuda", "cpu"] if gpu else ["cpu"], state="readonly",
        ).pack(fill="x", pady=(2, 8))

        self.vad_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(right, text="VAD filter (lewati bagian hening)", variable=self.vad_var).pack(anchor="w", pady=2)

        sp = ttk.LabelFrame(right, text="Addon Speaker (WhisperX)", padding=6)
        sp.pack(fill="x", pady=(8, 0))
        self.speaker_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(sp, text="Pisahkan speaker + timestamp presisi", variable=self.speaker_var).pack(anchor="w")
        ttk.Label(sp, text="HF Token:").pack(anchor="w", pady=(4, 0))
        self.hf_token = ttk.Entry(sp, show="*")
        self.hf_token.pack(fill="x", pady=(2, 4))
        if HF_TOKEN:
            self.hf_token.insert(0, HF_TOKEN)
        row = ttk.Frame(sp)
        row.pack(fill="x")
        ttk.Label(row, text="Min speaker").pack(side="left")
        self.min_speakers = ttk.Spinbox(row, from_=0, to=20, width=4)
        self.min_speakers.set(0)
        self.min_speakers.pack(side="left", padx=(4, 12))
        ttk.Label(row, text="Max").pack(side="left")
        self.max_speakers = ttk.Spinbox(row, from_=0, to=20, width=4)
        self.max_speakers.set(0)
        self.max_speakers.pack(side="left", padx=4)

        self.process_btn = ttk.Button(right, text="Proses Transkripsi", command=self._process)
        self.process_btn.pack(fill="x", pady=(12, 0))

        bottom = ttk.Frame(self)
        bottom.pack(fill="both", expand=True, padx=12, pady=(4, 10))

        status = ttk.LabelFrame(bottom, text="Status", padding=6)
        status.pack(fill="x", pady=(0, 6))
        top_row = ttk.Frame(status)
        top_row.pack(fill="x")
        self.status_var = tk.StringVar(value="Memuat model...")
        ttk.Label(top_row, textvariable=self.status_var, wraplength=720).pack(side="left", anchor="w")
        self.pct_var = tk.StringVar(value="")
        ttk.Label(top_row, textvariable=self.pct_var, font=("Segoe UI", 9, "bold")).pack(side="right")
        self.progress = ttk.Progressbar(status, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(6, 0))

        out_row = ttk.Frame(bottom)
        out_row.pack(fill="x", pady=(0, 4))
        ttk.Label(out_row, text="Hasil di output/:").pack(side="left")
        ttk.Button(out_row, text="Buka folder output", command=lambda: self._open_folder(OUTPUT_DIR)).pack(side="right")
        self.output_list = tk.Listbox(bottom, height=3, exportselection=False)
        self.output_list.pack(fill="x", pady=(0, 4))

        result = ttk.LabelFrame(bottom, text="Teks Transkripsi", padding=6)
        result.pack(fill="both", expand=True)
        self.result_text = tk.Text(result, height=10, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(result, command=self.result_text.yview)
        self.result_text.configure(yscrollcommand=scroll.set)
        self.result_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    # ---------- progress ----------
    def _set_progress(self, fraction: float | None, msg: str) -> None:
        self.status_var.set(msg)
        if fraction is None:
            if not self._indeterminate:
                self.progress.configure(mode="indeterminate")
                self.progress.start(12)
                self._indeterminate = True
            self.pct_var.set("")
            return
        if self._indeterminate:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self._indeterminate = False
        pct = max(0.0, min(100.0, fraction * 100.0))
        self.progress["value"] = pct
        self.pct_var.set(f"{pct:.0f}%")

    def _progress_cb(self, fraction: float | None, msg: str) -> None:
        self.after(0, self._set_progress, fraction, msg)

    # ---------- model ----------
    def _preload_model(self) -> None:
        self._set_progress(None, "Memuat model AI — pertama kali bisa beberapa menit...")

        def worker() -> None:
            try:
                get_model(self.device_var.get(), on_progress=self._progress_cb)
                self.after(0, self._on_model_ready, None)
            except Exception as exc:
                self.after(0, self._on_model_ready, exc)

        threading.Thread(target=worker, daemon=True).start()

    def _on_model_ready(self, error: Exception | None) -> None:
        if error:
            self._set_progress(0.0, "Gagal memuat model.")
            messagebox.showerror("Model", format_error(error))
            return
        self._model_ready = True
        self._set_progress(0.0, "Siap. Upload file atau pilih dari daftar.")
        self.pct_var.set("")

    # ---------- files ----------
    def _refresh_lists(self) -> None:
        self.input_list.delete(0, tk.END)
        for path in list_input_files():
            self.input_list.insert(tk.END, path.name)
        self.output_list.delete(0, tk.END)
        for path in list_output_files():
            self.output_list.insert(tk.END, path.name)

    def _on_input_select(self, _event=None) -> None:
        sel = self.input_list.curselection()
        if sel:
            self.output_name.delete(0, tk.END)
            self.output_name.insert(0, Path(self.input_list.get(sel[0])).stem)

    def _upload(self) -> None:
        paths = filedialog.askopenfilenames(title="Pilih file audio", filetypes=AUDIO_FILETYPES)
        if not paths:
            return
        saved, errors = [], []
        for p in paths:
            try:
                saved.append(copy_to_input(Path(p)).name)
            except Exception as exc:
                errors.append(f"{Path(p).name}: {exc}")
        self._refresh_lists()
        if saved:
            names = list(self.input_list.get(0, tk.END))
            idx = names.index(saved[-1])
            self.input_list.selection_clear(0, tk.END)
            self.input_list.selection_set(idx)
            self.input_list.see(idx)
            self._on_input_select()
            self.status_var.set(f"✓ {len(saved)} file disimpan ke input/")
        if errors:
            messagebox.showwarning("Upload sebagian gagal", "\n".join(errors))

    # ---------- process ----------
    def _process(self) -> None:
        if self._processing:
            return
        if not self._model_ready:
            messagebox.showinfo("Tunggu", "Model masih dimuat.")
            return
        sel = self.input_list.curselection()
        if not sel:
            messagebox.showinfo("Pilih file", "Pilih file audio dari daftar input/ dulu.")
            return

        audio_path = INPUT_DIR / self.input_list.get(sel[0])
        use_speaker = self.speaker_var.get()
        hf_tok = self.hf_token.get().strip() or None
        if use_speaker and not hf_tok:
            messagebox.showwarning("Addon Speaker", "Isi HF Token (atau HF_TOKEN di .env).")
            return

        kwargs = dict(
            output_name=self.output_name.get().strip() or None,
            language=label_to_code(self.lang_var.get()),
            output_format=self.format_var.get(),
            vad_filter=self.vad_var.get(),
            device=self.device_var.get(),
            use_speaker=use_speaker,
            hf_token=hf_tok,
            min_speakers=int(self.min_speakers.get() or 0) or None,
            max_speakers=int(self.max_speakers.get() or 0) or None,
            on_progress=self._progress_cb,
        )

        self._processing = True
        self.process_btn.configure(state="disabled")
        self._show_text("")
        self._set_progress(0.0, f"Memproses {audio_path.name}...")

        def worker() -> None:
            try:
                result = transcribe_file(audio_path, **kwargs)
                self.after(0, self._on_done, result, None)
            except Exception as exc:
                self.after(0, self._on_done, None, exc)

        threading.Thread(target=worker, daemon=True).start()

    def _on_done(self, result: dict | None, error: Exception | None) -> None:
        self._processing = False
        self.process_btn.configure(state="normal")
        self._refresh_lists()
        if error:
            friendly = format_error(error)
            self._set_progress(0.0, f"Error: {friendly.splitlines()[0]}")
            messagebox.showerror("Gagal", friendly)
            return
        self._show_text(result["text"])
        self._set_progress(
            1.0,
            f"✓ Selesai  •  Bahasa: {code_to_label(result['language'])}  •  output/{result['output_path'].name}",
        )

    def _show_text(self, text: str) -> None:
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", tk.END)
        self.result_text.insert("1.0", text)
        self.result_text.configure(state="disabled")

    @staticmethod
    def _open_folder(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)  # noqa: S606


def run_gui() -> None:
    StTApp().mainloop()
