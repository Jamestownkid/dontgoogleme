from __future__ import annotations
import subprocess
from typing import List, Tuple
import os
from utils import append_log

def download_all(links: List[str], out_dir: str, log_path: str) -> Tuple[int, int]:
    """Download links with yt-dlp into out_dir.

    Returns: (success_count, fail_count)
    """
    success = 0
    fail = 0

    # Output template: keep title, avoid overly long paths
    out_tmpl = os.path.join(out_dir, "%(title).150s [%(id)s].%(ext)s")

    for link in links:
        link = link.strip()
        if not link:
            continue

        append_log(log_path, f"[yt-dlp] START  {link}")
        try:
            cmd = [
                "yt-dlp",
                "--no-progress",
                "--newline",
                "--ignore-errors",
                "--no-abort-on-error",
                "--restrict-filenames",
                "--merge-output-format", "mp4",
                "--write-subs",
                "--write-auto-subs",
                "--sub-format", "srt",
                "--sub-langs", "en.*,en",
                "-o", out_tmpl,
                link,
            ]
            # We capture output into log
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            append_log(log_path, proc.stdout.strip() if proc.stdout else "")
            # yt-dlp uses exit code 0 even with some ignored errors; treat empty download as fail-ish
            if proc.returncode == 0:
                success += 1
                append_log(log_path, f"[yt-dlp] DONE   {link}")
            else:
                fail += 1
                append_log(log_path, f"[yt-dlp] FAIL   {link} (code={proc.returncode})")
        except FileNotFoundError:
            fail += 1
            append_log(log_path, "[yt-dlp] ERROR: yt-dlp not found. Install with: pip install yt-dlp")
        except Exception as e:
            fail += 1
            append_log(log_path, f"[yt-dlp] ERROR: {e}")

    return success, fail
