from __future__ import annotations
import os
from datetime import datetime

def safe_name(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    # Keep it filesystem-friendly
    keep = []
    for ch in s:
        if ch.isalnum() or ch in (" ", "_", "-", ".", "(", ")", "[", "]"):
            keep.append(ch)
        else:
            keep.append("_")
    out = "".join(keep).strip()
    # Collapse repeated spaces/underscores
    while "  " in out:
        out = out.replace("  ", " ")
    while "__" in out:
        out = out.replace("__", "_")
    return out[:80] if len(out) > 80 else out

def make_run_folder(base_dir: str, topic: str = "", subtopic: str = "") -> str:
    os.makedirs(base_dir, exist_ok=True)
    t = safe_name(topic)
    st = safe_name(subtopic)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    parts = [p for p in (t, st, f"batch_{ts}") if p]
    folder_name = "__".join(parts)
    out = os.path.join(base_dir, folder_name)
    os.makedirs(out, exist_ok=True)
    return out

def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

def append_log(log_path: str, line: str) -> None:
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")
