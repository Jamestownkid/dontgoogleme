from __future__ import annotations
import os
import subprocess
from utils import append_log

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}

def has_any_srt_for(stem: str, folder: str) -> bool:
    # If yt-dlp wrote subtitles, they'll be like:
    #   title [id].en.srt   or   title [id].srt
    # We'll consider any file that starts with the stem and ends with .srt as existing subtitles.
    for fn in os.listdir(folder):
        if fn.lower().endswith(".srt") and fn.startswith(stem):
            return True
    return False

def whisper_srt_for_folder(folder: str, model: str, log_path: str, language: str = "en") -> None:
    """Generate SRT for videos lacking SRT using whisper CLI (background-safe)."""
    append_log(log_path, f"[whisper] Using model={model} language={language}")

    for fn in os.listdir(folder):
        ext = os.path.splitext(fn)[1].lower()
        if ext not in VIDEO_EXTS:
            continue

        stem = os.path.splitext(fn)[0]
        if has_any_srt_for(stem, folder):
            append_log(log_path, f"[whisper] Skip (SRT exists): {fn}")
            continue

        in_path = os.path.join(folder, fn)
        append_log(log_path, f"[whisper] START {fn}")

        try:
            # whisper CLI outputs: <stem>.srt (and other formats if requested)
            cmd = [
                "whisper",
                in_path,
                "--model", model,
                "--language", language,
                "--output_format", "srt",
                "--output_dir", folder,
                "--fp16", "False",
            ]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            append_log(log_path, proc.stdout.strip() if proc.stdout else "")
            if proc.returncode == 0:
                append_log(log_path, f"[whisper] DONE  {fn}")
            else:
                append_log(log_path, f"[whisper] FAIL  {fn} (code={proc.returncode})")
        except FileNotFoundError:
            append_log(log_path, "[whisper] ERROR: whisper CLI not found. Install openai-whisper.")
            return
        except Exception as e:
            append_log(log_path, f"[whisper] ERROR: {e}")
