import os
import sys
import asyncio
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from broll_core import (
    APP_DIR,
    load_settings,
    save_settings,
    ensure_dir,
    safe_folder_name,
    generate_srt,
    compute_keyword_image_targets,
    google_images_download,
)

# -------- GUI --------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Auto B‑Roll Generator (SRT → keywords → Google Images)")
        self.geometry("720x520")

        self.settings = load_settings()

        self.video_path = tk.StringVar(value="")
        self.whisper_model = tk.StringVar(value=self.settings["whisper_model"])
        self.images_per_keyword = tk.IntVar(value=self.settings["images_per_keyword"])
        self.max_keywords = tk.IntVar(value=self.settings["max_keywords"])
        self.max_total_images = tk.IntVar(value=self.settings["max_total_images"])
        self.max_scrolls = tk.IntVar(value=self.settings["max_scrolls_per_keyword"])
        self.visible_browser = tk.BooleanVar(value=self.settings["use_visible_browser"])
        self.use_existing_profile = tk.BooleanVar(value=self.settings["use_existing_chrome_profile"])
        self.profile_dir = tk.StringVar(value=self.settings["chrome_profile_dir"])

        self.status = tk.StringVar(value="Ready.")

        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, **pad)

        # Video picker
        row = 0
        ttk.Label(frm, text="Video file:").grid(row=row, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.video_path, width=58).grid(row=row, column=1, sticky="we")
        ttk.Button(frm, text="Browse…", command=self.pick_video).grid(row=row, column=2, sticky="e")

        # Whisper model selector
        row += 1
        ttk.Label(frm, text="Whisper model:").grid(row=row, column=0, sticky="w")
        model_box = ttk.Combobox(frm, textvariable=self.whisper_model, values=["tiny", "base", "small", "medium", "large"], state="readonly")
        model_box.grid(row=row, column=1, sticky="w")

        # Caps
        row += 1
        ttk.Label(frm, text="Images per keyword:").grid(row=row, column=0, sticky="w")
        ttk.Spinbox(frm, from_=1, to=20, textvariable=self.images_per_keyword, width=10).grid(row=row, column=1, sticky="w")
        row += 1
        ttk.Label(frm, text="Max keywords (cap per SRT):").grid(row=row, column=0, sticky="w")
        ttk.Spinbox(frm, from_=1, to=200, textvariable=self.max_keywords, width=10).grid(row=row, column=1, sticky="w")
        row += 1
        ttk.Label(frm, text="Max total images (overall cap):").grid(row=row, column=0, sticky="w")
        ttk.Spinbox(frm, from_=1, to=5000, textvariable=self.max_total_images, width=10).grid(row=row, column=1, sticky="w")
        row += 1
        ttk.Label(frm, text="Max scrolls per keyword (Google pages):").grid(row=row, column=0, sticky="w")
        ttk.Spinbox(frm, from_=1, to=50, textvariable=self.max_scrolls, width=10).grid(row=row, column=1, sticky="w")

        # Browser options
        row += 1
        ttk.Checkbutton(frm, text="Use visible browser window (more human, fewer blocks)", variable=self.visible_browser).grid(row=row, column=0, columnspan=2, sticky="w")

        row += 1
        ttk.Checkbutton(frm, text="Use my existing Chrome profile (cookies/login)", variable=self.use_existing_profile, command=self._toggle_profile).grid(row=row, column=0, columnspan=2, sticky="w")

        row += 1
        ttk.Label(frm, text="Chrome profile directory:").grid(row=row, column=0, sticky="w")
        self.profile_entry = ttk.Entry(frm, textvariable=self.profile_dir, width=58, state=("normal" if self.use_existing_profile.get() else "disabled"))
        self.profile_entry.grid(row=row, column=1, sticky="we")
        self.profile_btn = ttk.Button(frm, text="Pick…", command=self.pick_profile_dir, state=("normal" if self.use_existing_profile.get() else "disabled"))
        self.profile_btn.grid(row=row, column=2, sticky="e")

        # Action buttons
        row += 1
        ttk.Separator(frm).grid(row=row, column=0, columnspan=3, sticky="we", pady=10)

        row += 1
        ttk.Button(frm, text="Run: SRT → keywords → images", command=self.run_all).grid(row=row, column=0, sticky="w")
        ttk.Button(frm, text="Open output folder", command=self.open_output).grid(row=row, column=1, sticky="w")
        ttk.Button(frm, text="Save settings", command=self.save_current_settings).grid(row=row, column=2, sticky="e")

        # Status + log
        row += 1
        ttk.Label(frm, text="Status:").grid(row=row, column=0, sticky="nw")
        self.log = tk.Text(frm, height=10)
        self.log.grid(row=row, column=1, columnspan=2, sticky="nsew")
        frm.rowconfigure(row, weight=1)
        frm.columnconfigure(1, weight=1)

        row += 1
        ttk.Label(frm, textvariable=self.status).grid(row=row, column=0, columnspan=3, sticky="we")

    def _toggle_profile(self):
        enabled = self.use_existing_profile.get()
        self.profile_entry.config(state=("normal" if enabled else "disabled"))
        self.profile_btn.config(state=("normal" if enabled else "disabled"))

    def log_line(self, msg: str):
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.update_idletasks()

    def set_status(self, msg: str):
        self.status.set(msg)
        self.log_line(msg)

    def pick_video(self):
        p = filedialog.askopenfilename(filetypes=[("Video files", "*.mp4 *.mkv *.mov *.m4v *.webm"), ("All files", "*.*")])
        if p:
            self.video_path.set(p)

    def pick_profile_dir(self):
        p = filedialog.askdirectory()
        if p:
            self.profile_dir.set(p)

    def open_output(self):
        # Open output folders in file manager (Linux-friendly)
        out = os.path.join(APP_DIR, "images")
        ensure_dir(out)
        try:
            if sys.platform.startswith("linux"):
                os.system(f'xdg-open "{out}" >/dev/null 2>&1 &')
            elif sys.platform == "darwin":
                os.system(f'open "{out}" >/dev/null 2>&1 &')
            elif sys.platform.startswith("win"):
                os.startfile(out)  # type: ignore
        except Exception:
            pass

    def save_current_settings(self):
        s = dict(self.settings)
        s.update(
            {
                "whisper_model": self.whisper_model.get(),
                "images_per_keyword": int(self.images_per_keyword.get()),
                "max_keywords": int(self.max_keywords.get()),
                "max_total_images": int(self.max_total_images.get()),
                "max_scrolls_per_keyword": int(self.max_scrolls.get()),
                "use_visible_browser": bool(self.visible_browser.get()),
                "use_existing_chrome_profile": bool(self.use_existing_profile.get()),
                "chrome_profile_dir": self.profile_dir.get(),
            }
        )
        save_settings(s)
        self.settings = s
        self.set_status("Settings saved.")

    def run_all(self):
        video = self.video_path.get().strip()
        if not video or not os.path.exists(video):
            messagebox.showerror("Missing video", "Pick a valid video file first.")
            return

        # Persist settings immediately
        self.save_current_settings()

        try:
            self.set_status("Generating SRT with Whisper…")
            srt_path, text = generate_srt(video, self.whisper_model.get())
            self.set_status(f"SRT saved: {srt_path}")

            self.set_status("Planning image downloads from transcript…")
            targets = compute_keyword_image_targets(
                text,
                {
                    "max_keywords": int(self.max_keywords.get()),
                    "images_per_keyword": int(self.images_per_keyword.get()),
                    "max_total_images": int(self.max_total_images.get()),
                    "min_images_per_srt": int(self.settings.get("min_images_per_srt", 20)),
                },
            )
            self.set_status(f"Keywords selected for images: {len(targets)}")

            images_root = os.path.join(APP_DIR, "images")
            ensure_dir(images_root)

            max_scrolls = int(self.max_scrolls.get())

            total_saved = 0
            for kw, need in targets:
                out_dir = os.path.join(images_root, safe_folder_name(kw))
                self.set_status(f"Keyword '{kw}': downloading {need} images…")

                saved = asyncio.run(
                    google_images_download(
                        keyword=kw,
                        out_dir=out_dir,
                        images_needed=need,
                        max_scrolls=max_scrolls,
                        use_visible_browser=bool(self.visible_browser.get()),
                        use_existing_profile=bool(self.use_existing_profile.get()),
                        chrome_profile_dir=self.profile_dir.get().strip(),
                        status_cb=self.set_status,
                    )
                )

                total_saved += saved
                self.set_status(f"Saved {saved} images for '{kw}' (total {total_saved}).")

            self.set_status("Done. SRT + keyword folders + images created.")
            messagebox.showinfo("Done", "Finished generating SRT and downloading images.")

        except Exception as e:
            self.set_status(f"Error: {e}")
            messagebox.showerror("Error", str(e))


if __name__ == "__main__":
    App().mainloop()
