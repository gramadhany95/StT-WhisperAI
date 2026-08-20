"""Desktop GUI (tkinter) untuk StT-WhisperAI — tanpa HTTP/port."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import whisper
from whisper.tokenizer import LANGUAGES

from app.checks import cuda_available, check_ffmpeg_quiet, configure_ffmpeg, ffmpeg_status, format_error, resolve_device
from app.processor import (
    INPUT_DIR,
    OUTPUT_DIR,
    copy_to_input,
    list_input_files,
    list_output_files,
    transcribe_file,
)

AUDIO_FILETYPES = [
    ("Audio/Video", "*.mp3 *.wav *.flac *.m4a *.ogg *.webm *.mp4 *.mpeg *.mpga *.wma *.aac"),
    ("Semua file", "*.*"),
]


class StTApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("StT-WhisperAI")
        self.minsize(720, 560)
        self.geometry("860x640")

        self._processing = False
        self._build_ui()
        self._refresh_lists()
        if not check_ffmpeg_quiet():
            messagebox.showwarning(
                "ffmpeg tidak ditemukan",
                "Whisper membutuhkan ffmpeg untuk membaca file audio.\n\n"
                "Install: winget install ffmpeg\n"
                "Atau set: set FFMPEG_PATH=C:\\path\\to\\ffmpeg.exe\n"
                "Lalu restart aplikasi.",
            )
        else:
            self.ffmpeg_label.configure(text=ffmpeg_status())

    def _build_ui(self) -> None:
        default_device = resolve_device()
        if cuda_available():
            device_values = ["cuda", "cpu"]
            device_hint = "GPU CUDA"
        else:
            device_values = ["cpu"]
            device_hint = "CPU (CUDA tidak tersedia)"

        header = ttk.Label(
            self,
            text=f"Speech-to-Text Whisper  •  input/ → output/  •  {device_hint}",
            font=("Segoe UI", 10),
        )
        header.pack(fill="x", padx=12, pady=(10, 6))
        self.ffmpeg_label = ttk.Label(
            self,
            text=ffmpeg_status(),
            font=("Segoe UI", 8),
            foreground="gray",
        )
        self.ffmpeg_label.pack(fill="x", padx=12, pady=(0, 4))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=12, pady=4)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # --- Kiri: upload & file list ---
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

        # --- Kanan: pengaturan ---
        right = ttk.LabelFrame(body, text="Pengaturan", padding=8)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        ttk.Label(right, text="Nama output (custom):").pack(anchor="w")
        self.output_name = ttk.Entry(right)
        self.output_name.pack(fill="x", pady=(2, 8))
        ttk.Label(
            right,
            text="Kosongkan = pakai nama file audio",
            font=("Segoe UI", 8),
            foreground="gray",
        ).pack(anchor="w", pady=(0, 8))

        ttk.Label(right, text="Model:").pack(anchor="w")
        self.model_var = tk.StringVar(value="turbo")
        ttk.Combobox(
            right,
            textvariable=self.model_var,
            values=whisper.available_models(),
            state="readonly",
        ).pack(fill="x", pady=(2, 8))

        ttk.Label(right, text="Bahasa:").pack(anchor="w")
        self.lang_var = tk.StringVar(value="Auto")
        ttk.Combobox(
            right,
            textvariable=self.lang_var,
            values=["Auto"] + sorted(LANGUAGES.keys()),
            state="readonly",
        ).pack(fill="x", pady=(2, 8))

        ttk.Label(right, text="Task:").pack(anchor="w")
        self.task_var = tk.StringVar(value="transcribe")
        ttk.Combobox(
            right,
            textvariable=self.task_var,
            values=["transcribe", "translate"],
            state="readonly",
        ).pack(fill="x", pady=(2, 8))

        ttk.Label(right, text="Format output:").pack(anchor="w")
        self.format_var = tk.StringVar(value="txt")
        ttk.Combobox(
            right,
            textvariable=self.format_var,
            values=["txt", "srt", "vtt", "tsv", "json", "all"],
            state="readonly",
        ).pack(fill="x", pady=(2, 8))

        ttk.Label(right, text="Device:").pack(anchor="w")
        self.device_var = tk.StringVar(value=default_device)
        self.device_combo = ttk.Combobox(
            right,
            textvariable=self.device_var,
            values=device_values,
            state="readonly",
        )
        self.device_combo.pack(fill="x", pady=(2, 8))

        self.word_ts_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, text="Word timestamps", variable=self.word_ts_var).pack(anchor="w", pady=4)
        ttk.Label(
            right,
            text="Word timestamps: lebih lambat di Windows (warning Triton aman diabaikan)",
            font=("Segoe UI", 8),
            foreground="gray",
            wraplength=280,
        ).pack(anchor="w", pady=(0, 4))

        self.process_btn = ttk.Button(
            right, text="Proses Transkripsi", command=self._process
        )
        self.process_btn.pack(fill="x", pady=(12, 0))

        # --- Bawah: status & hasil ---
        bottom = ttk.Frame(self)
        bottom.pack(fill="both", expand=True, padx=12, pady=(4, 10))

        status_frame = ttk.LabelFrame(bottom, text="Status", padding=6)
        status_frame.pack(fill="x", pady=(0, 6))
        self.status_var = tk.StringVar(value="Siap. Upload file atau pilih dari daftar.")
        ttk.Label(status_frame, textvariable=self.status_var, wraplength=800).pack(anchor="w")

        out_row = ttk.Frame(bottom)
        out_row.pack(fill="x", pady=(0, 4))
        ttk.Label(out_row, text="Hasil di output/:").pack(side="left")
        ttk.Button(
            out_row, text="Buka folder output", command=lambda: self._open_folder(OUTPUT_DIR)
        ).pack(side="right")

        self.output_list = tk.Listbox(out_row, height=3, exportselection=False)
        self.output_list.pack(fill="x", pady=4)

        result_frame = ttk.LabelFrame(bottom, text="Teks Transkripsi", padding=6)
        result_frame.pack(fill="both", expand=True)
        self.result_text = tk.Text(result_frame, height=10, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(result_frame, command=self.result_text.yview)
        self.result_text.configure(yscrollcommand=scroll.set)
        self.result_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _set_status(self, msg: str) -> None:
        self.status_var.set(msg)
        self.update_idletasks()

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
            name = self.input_list.get(sel[0])
            stem = Path(name).stem
            if not self.output_name.get().strip():
                self.output_name.delete(0, tk.END)
                self.output_name.insert(0, stem)

    def _upload(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Pilih file audio",
            filetypes=AUDIO_FILETYPES,
        )
        if not paths:
            return

        saved = []
        errors = []
        for p in paths:
            try:
                dest = copy_to_input(Path(p))
                saved.append(dest.name)
            except Exception as exc:
                errors.append(f"{Path(p).name}: {exc}")

        self._refresh_lists()
        if saved:
            # Pilih file terakhir yang diupload
            names = [self.input_list.get(i) for i in range(self.input_list.size())]
            if saved[-1] in names:
                idx = names.index(saved[-1])
                self.input_list.selection_clear(0, tk.END)
                self.input_list.selection_set(idx)
                self.input_list.see(idx)
                self._on_input_select()

        if errors:
            messagebox.showwarning("Upload sebagian gagal", "\n".join(errors))
        if saved:
            self._set_status(f"✓ {len(saved)} file disimpan ke input/: {', '.join(saved)}")

    def _get_selected_file(self) -> Path | None:
        sel = self.input_list.curselection()
        if not sel:
            return None
        return INPUT_DIR / self.input_list.get(sel[0])

    def _process(self) -> None:
        if self._processing:
            return

        audio_path = self._get_selected_file()
        if audio_path is None:
            messagebox.showinfo("Pilih file", "Pilih file audio dari daftar input/ terlebih dahulu.")
            return

        output_name = self.output_name.get().strip() or None
        language = None if self.lang_var.get() == "Auto" else self.lang_var.get()

        self._processing = True
        self.process_btn.configure(state="disabled")
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", tk.END)
        self.result_text.configure(state="disabled")
        self._set_status(f"Memproses {audio_path.name}...")

        def worker() -> None:
            try:
                result = transcribe_file(
                    audio_path,
                    output_name=output_name,
                    model_name=self.model_var.get(),
                    language=language,
                    task=self.task_var.get(),
                    output_format=self.format_var.get(),
                    word_timestamps=self.word_ts_var.get(),
                    device=resolve_device(self.device_var.get()),
                    on_status=lambda msg: self.after(0, self._set_status, msg),
                )
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
            self._set_status(f"Error: {friendly.splitlines()[0]}")
            messagebox.showerror("Gagal", friendly)
            return

        text = result["text"]
        lang = result["language"]
        basename = result["basename"]
        fmt = self.format_var.get()
        saved = f"output/{basename}.*" if fmt == "all" else f"output/{basename}.{fmt}"

        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", tk.END)
        self.result_text.insert("1.0", text)
        self.result_text.configure(state="disabled")

        self._set_status(f"✓ Selesai! Bahasa: {lang}  •  Disimpan: {saved}")

    @staticmethod
    def _open_folder(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)


def run_gui() -> None:
    app = StTApp()
    app.mainloop()
