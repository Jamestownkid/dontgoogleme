from __future__ import annotations
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import threading
import queue

from utils import make_run_folder, write_text, append_log
from downloader import download_all
from whisperer import whisper_srt_for_folder

APP_TITLE = "Tinker Video Collector (yt-dlp + Whisper)"

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("900x720")

        self.ui_queue: "queue.Queue[str]" = queue.Queue()

        self.base_dir_var = tk.StringVar(value=os.path.expanduser("~/Downloads"))
        self.topic_var = tk.StringVar(value="")
        self.subtopic_var = tk.StringVar(value="")
        self.model_var = tk.StringVar(value="small")
        self.lang_var = tk.StringVar(value="en")

        self._build()
        self.bind("<Return>", lambda _e: self.on_go())  # Enter = GO
        self.after(150, self._poll_queue)

    def _build(self):
        pad = {"padx": 10, "pady": 6}

        top = ttk.Frame(self)
        top.pack(fill="x", **pad)

        ttk.Label(top, text="Output base folder:").grid(row=0, column=0, sticky="w")
        base_entry = ttk.Entry(top, textvariable=self.base_dir_var, width=70)
        base_entry.grid(row=0, column=1, sticky="we", padx=(8, 8))
        ttk.Button(top, text="Browse", command=self.choose_base).grid(row=0, column=2)

        ttk.Label(top, text="Topic:").grid(row=1, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.topic_var, width=30).grid(row=1, column=1, sticky="w", padx=(8, 8))

        ttk.Label(top, text="Subtopic:").grid(row=2, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.subtopic_var, width=30).grid(row=2, column=1, sticky="w", padx=(8, 8))

        controls = ttk.Frame(self)
        controls.pack(fill="x", **pad)

        ttk.Label(controls, text="Whisper model:").grid(row=0, column=0, sticky="w")
        ttk.OptionMenu(controls, self.model_var, self.model_var.get(), "tiny", "base", "small", "medium", "large").grid(row=0, column=1, sticky="w", padx=(8, 24))

        ttk.Label(controls, text="Language:").grid(row=0, column=2, sticky="w")
        ttk.Entry(controls, textvariable=self.lang_var, width=8).grid(row=0, column=3, sticky="w", padx=(8, 24))

        self.go_btn = ttk.Button(controls, text="GO (Enter)", command=self.on_go)
        self.go_btn.grid(row=0, column=4, sticky="e")

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, **pad)

        ttk.Label(mid, text="Paste links (one per line):").pack(anchor="w")
        self.links_text = tk.Text(mid, height=12, wrap="word")
        self.links_text.pack(fill="x", expand=False)

        ttk.Label(mid, text="Notes / text (saved as notes.txt):").pack(anchor="w", pady=(10, 0))
        self.notes_text = tk.Text(mid, height=6, wrap="word")
        self.notes_text.pack(fill="x", expand=False)

        ttk.Label(mid, text="Live log:").pack(anchor="w", pady=(10, 0))
        self.log_text = tk.Text(mid, height=18, wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True)

        hint = ttk.Label(self, text="Tip: You can change output folder/topic/subtopic every run. Press Enter to start.")
        hint.pack(anchor="w", padx=12, pady=(0, 10))

    def choose_base(self):
        d = filedialog.askdirectory(title="Choose output base folder")
        if d:
            self.base_dir_var.set(d)

    def _set_log(self, msg: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _poll_queue(self):
        try:
            while True:
                msg = self.ui_queue.get_nowait()
                self._set_log(msg)
        except queue.Empty:
            pass
        self.after(150, self._poll_queue)

    def on_go(self):
        links_raw = self.links_text.get("1.0", "end").strip()
        if not links_raw:
            messagebox.showerror("Missing links", "Paste at least one link.")
            return

        base_dir = self.base_dir_var.get().strip()
        if not base_dir:
            messagebox.showerror("Missing folder", "Choose an output base folder.")
            return

        links = [ln.strip() for ln in links_raw.splitlines() if ln.strip()]
        notes = self.notes_text.get("1.0", "end").rstrip()

        topic = self.topic_var.get()
        subtopic = self.subtopic_var.get()
        model = self.model_var.get()
        lang = self.lang_var.get().strip() or "en"

        out_dir = make_run_folder(base_dir, topic, subtopic)
        log_path = os.path.join(out_dir, "log.txt")

        write_text(os.path.join(out_dir, "links.txt"), "\n".join(links) + "\n")
        write_text(os.path.join(out_dir, "notes.txt"), notes + ("\n" if notes else ""))

        self._set_log(f"Created: {out_dir}")
        self._set_log("Starting yt-dlp downloads...")

        self.go_btn.configure(state="disabled")

        def worker():
            try:
                append_log(log_path, f"Output folder: {out_dir}")
                append_log(log_path, f"Links: {len(links)}")
                append_log(log_path, f"Whisper model: {model} | lang: {lang}")

                ok, bad = download_all(links, out_dir, log_path)
                self.ui_queue.put(f"yt-dlp finished. Success (attempts): {ok} | Failed (attempts): {bad}")
                self.ui_queue.put("Starting Whisper SRT generation in background for videos missing SRT...")

                whisper_srt_for_folder(out_dir, model, log_path, language=lang)
                self.ui_queue.put("Whisper finished (or skipped where SRT already existed).")
                self.ui_queue.put(f"Done. Folder: {out_dir}")
            except Exception as e:
                self.ui_queue.put(f"ERROR: {e}")
            finally:
                self.go_btn.configure(state="normal")

        threading.Thread(target=worker, daemon=True).start()

if __name__ == "__main__":
    App().mainloop()
