import os
import sys
import asyncio
from typing import Optional

from broll_core import (
    APP_DIR,
    load_settings,
    ensure_dir,
    safe_folder_name,
    srt_file_to_text,
    compute_keyword_image_targets,
    google_images_download,
)


def log(msg: str):
    print(msg, flush=True)


async def process_single_srt(srt_path: str, out_root: str, settings: dict) -> int:
    text = srt_file_to_text(srt_path)
    if not text.strip():
        log(f"[skip] Empty text in {srt_path}")
        return 0

    targets = compute_keyword_image_targets(text, settings)
    if not targets:
        log(f"[skip] No keywords extracted for {os.path.basename(srt_path)}")
        return 0

    max_scrolls = int(settings.get("max_scrolls_per_keyword", 6))
    use_visible = bool(settings.get("use_visible_browser", True))
    use_existing_profile = bool(settings.get("use_existing_chrome_profile", False))
    chrome_profile_dir = settings.get("chrome_profile_dir", "")

    total_saved = 0

    async def run_for_keyword(kw: str, need: int) -> int:
        out_dir = os.path.join(out_root, safe_folder_name(kw))

        def status_cb(m: str):
            log(f"[{os.path.basename(srt_path)}] {m}")

        saved = await google_images_download(
            keyword=kw,
            out_dir=out_dir,
            images_needed=need,
            max_scrolls=max_scrolls,
            use_visible_browser=use_visible,
            use_existing_profile=use_existing_profile,
            chrome_profile_dir=chrome_profile_dir,
            status_cb=status_cb,
        )
        return saved

    for kw, need in targets:
        log(f"[{os.path.basename(srt_path)}] Keyword '{kw}' → {need} images")
        saved = await run_for_keyword(kw, need)
        total_saved += saved

    return total_saved


async def main(folder_or_file: str, out_base: Optional[str] = None):
    settings = load_settings()

    if os.path.isfile(folder_or_file):
        srt_files = [folder_or_file]
        base_name = os.path.splitext(os.path.basename(folder_or_file))[0]
        out_root = out_base or os.path.join(APP_DIR, "images", safe_folder_name(base_name))
    else:
        srt_files = [
            os.path.join(folder_or_file, fn)
            for fn in os.listdir(folder_or_file)
            if fn.lower().endswith(".srt")
        ]
        if not srt_files:
            log(f"No .srt files found in {folder_or_file}")
            return
        base_name = os.path.basename(os.path.abspath(folder_or_file))
        out_root = out_base or os.path.join(APP_DIR, "images", safe_folder_name(base_name))

    ensure_dir(out_root)

    log(f"Using output root: {out_root}")
    total = 0
    for srt in srt_files:
        log(f"Processing SRT: {srt}")
        saved = await process_single_srt(
            srt,
            out_root=out_root,
            settings={
                "max_keywords": int(settings.get("max_keywords", 20)),
                "images_per_keyword": int(settings.get("images_per_keyword", 3)),
                "max_total_images": int(settings.get("max_total_images", 60)),
                "min_images_per_srt": int(settings.get("min_images_per_srt", 20)),
                "max_scrolls_per_keyword": int(settings.get("max_scrolls_per_keyword", 6)),
                "use_visible_browser": bool(settings.get("use_visible_browser", True)),
                "use_existing_chrome_profile": bool(settings.get("use_existing_chrome_profile", False)),
                "chrome_profile_dir": settings.get("chrome_profile_dir", ""),
            },
        )
        log(f"Saved {saved} images for {os.path.basename(srt)}")
        total += saved

    log(f"Done. Total images saved: {total}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python srt_to_images.py <srt_file_or_folder> [output_folder]", file=sys.stderr)
        sys.exit(1)
    target = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    asyncio.run(main(target, out))


