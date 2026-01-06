import os
import re
import json
import shutil
from typing import Callable, Tuple, List

import whisper
import spacy
import requests
from playwright.async_api import async_playwright


APP_DIR = os.path.abspath(os.path.dirname(__file__))
DEFAULTS_PATH = os.path.join(APP_DIR, "settings.json")


# -------- Settings --------
DEFAULT_SETTINGS = {
    "whisper_model": "base",
    "images_per_keyword": 3,
    "max_keywords": 20,
    "max_total_images": 60,
    "max_scrolls_per_keyword": 6,
    "use_visible_browser": True,
    "use_existing_chrome_profile": False,
    "chrome_profile_dir": "",
    # New: soft minimum images per SRT (we try to reach or exceed this)
    "min_images_per_srt": 20,
}


def load_settings() -> dict:
    if os.path.exists(DEFAULTS_PATH):
        try:
            with open(DEFAULTS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = dict(DEFAULT_SETTINGS)
            merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
            return merged
        except Exception:
            return dict(DEFAULT_SETTINGS)
    return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict) -> None:
    with open(DEFAULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


# -------- Helpers --------
def safe_folder_name(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9_\- ]+", "", s)
    s = re.sub(r"\s+", "_", s)
    return s[:80] if s else "keyword"


def ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)


def which_browser_executable():
    # Prefer user's installed Chrome/Chromium if present.
    candidates = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]
    for c in candidates:
        path = shutil.which(c)
        if path:
            return path
    return None


# -------- SRT generation (from raw video, for local files) --------
def format_srt_time(seconds: float) -> str:
    # HH:MM:SS,mmm
    ms = int(round(seconds * 1000))
    h = ms // (3600 * 1000)
    ms -= h * 3600 * 1000
    m = ms // (60 * 1000)
    ms -= m * 60 * 1000
    s = ms // 1000
    ms -= s * 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def generate_srt(video_path: str, whisper_model_name: str) -> Tuple[str, str]:
    """Run Whisper on a local video file and write a single SRT file.

    Returns: (srt_path, full_transcript_text)
    """
    model = whisper.load_model(whisper_model_name)
    result = model.transcribe(video_path)

    srt_dir = os.path.join(APP_DIR, "srt")
    ensure_dir(srt_dir)
    srt_path = os.path.join(srt_dir, "output.srt")

    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(result["segments"], 1):
            f.write(f"{i}\n")
            f.write(f"{format_srt_time(seg['start'])} --> {format_srt_time(seg['end'])}\n")
            f.write(seg["text"].strip() + "\n\n")

    return srt_path, result.get("text", "")


# -------- Keyword extraction (nouns + proper nouns) --------
_NLP = None


def _get_nlp():
    global _NLP
    if _NLP is None:
        _NLP = spacy.load("en_core_web_sm")
    return _NLP


def extract_keywords(text: str, max_keywords: int) -> List[str]:
    """Extract up to max_keywords NOUN/PROPN lemmas from text using spaCy."""
    nlp = _get_nlp()
    doc = nlp(text)
    freq = {}
    for token in doc:
        if token.is_stop:
            continue
        if token.pos_ not in ("NOUN", "PROPN"):
            continue
        t = token.lemma_.strip().lower()
        if len(t) < 3:
            continue
        if not re.match(r"^[a-z0-9][a-z0-9\-\_ ]*$", t):
            continue
        freq[t] = freq.get(t, 0) + 1

    # Sort by frequency then alphabetically for stability.
    items = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [k for k, _ in items[:max_keywords]]


# -------- Google Images scraping via Playwright (real browser window option) --------
async def google_images_download(
    keyword: str,
    out_dir: str,
    images_needed: int,
    max_scrolls: int,
    use_visible_browser: bool,
    use_existing_profile: bool,
    chrome_profile_dir: str,
    status_cb: Callable[[str], None] | None = None,
    timestamp_based_naming: bool = False,
    timestamps: list = None,
    start_counter: int = 0,
) -> int:
    """Download up to images_needed images for a keyword into out_dir."""
    ensure_dir(out_dir)

    browser_exe = which_browser_executable()

    async with async_playwright() as p:
        # Use persistent context to better mimic "normal browsing"
        # and optionally reuse the user's existing Chrome profile (cookies, etc.)
        launch_args = []
        if use_visible_browser:
            launch_args += ["--start-maximized"]
        else:
            launch_args += ["--disable-gpu"]

        if use_existing_profile and chrome_profile_dir:
            user_data_dir = chrome_profile_dir
        else:
            # Local persistent profile (still more "real" than stateless context)
            user_data_dir = os.path.join(APP_DIR, ".playwright_profile")

        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=(not use_visible_browser),
            executable_path=browser_exe,
            args=launch_args,
            viewport=None,
        )

        page = await context.new_page()
        await page.goto("https://www.google.com/imghp?hl=en", wait_until="domcontentloaded")

        # Search - try multiple selectors for Google Images search input
        search_selectors = [
            "input[name='q']:not([type='hidden'])",
            "textarea[name='q']",
            "input[aria-label*='Search']",
            "textarea[aria-label*='Search']",
            "input.gLFyf",  # Common Google search input class
            "textarea.gLFyf"
        ]

        search_input = None
        for selector in search_selectors:
            try:
                search_input = await page.wait_for_selector(selector, timeout=5000)
                if search_input:
                    break
            except:
                continue

        if not search_input:
            raise Exception("Could not find Google Images search input")

        await search_input.fill(keyword)
        await page.keyboard.press("Enter")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(2000)  # Give more time for images to load

        seen = set()
        saved = 0

        def set_status(msg: str):
            if status_cb:
                status_cb(msg)

        set_status(f"Searching images for: {keyword}")

        # Main loop: scroll + click thumbnails to get original URLs
        for scroll_i in range(max_scrolls):
            # Thumbnails currently in DOM - try multiple selectors
            thumb_selectors = [
                "img.Q4LuWd",
                "img.YQ4gaf",
                "img.rg_i",
                "img[data-src]",
                "img[src*='http']",
                "div.H8Rx8c img",  # Common Google Images thumbnail container
                "div[data-ved] img"
            ]

            thumbs = []
            for selector in thumb_selectors:
                try:
                    thumbs = await page.query_selector_all(selector)
                    if thumbs and len(thumbs) > 0:
                        break
                except Exception:
                    continue

            if not thumbs or len(thumbs) == 0:
                set_status(f"No thumbnails found with any selector for '{keyword}'")
                break

            for idx in range(len(thumbs)):
                if saved >= images_needed:
                    break

                thumb = thumbs[idx]
                try:
                    await thumb.click(timeout=1500)
                except Exception:
                    continue

                await page.wait_for_timeout(350)

                # In the side panel, try multiple selectors for the large image
                image_selectors = [
                    "img.n3VNCb",
                    "img.sFlh5c",
                    "img.iPVvYb",
                    "img.r48jcc",
                    "img.pT0Scc",
                    "img.H8Rx8c",
                    "div[data-ved] img",
                    "img[alt*='" + keyword + "']"
                ]

                candidates = []
                for selector in image_selectors:
                    candidates = await page.query_selector_all(selector)
                    if candidates:
                        break
                url = None
                for c in candidates:
                    try:
                        src = await c.get_attribute("src")
                    except Exception:
                        continue
                    if not src:
                        continue
                    if src.startswith("http") and "gstatic.com" not in src:
                        url = src
                        break
                if not url:
                    # fallback: allow gstatic if nothing else
                    for c in candidates:
                        try:
                            src = await c.get_attribute("src")
                        except Exception:
                            continue
                        if src and src.startswith("http"):
                            url = src
                            break

                if not url or url in seen:
                    continue

                seen.add(url)
                # Generate filename based on timestamp or counter
                if timestamp_based_naming and timestamps and (start_counter + saved) < len(timestamps):
                    timestamp = timestamps[start_counter + saved]
                    safe_keyword = keyword.replace(' ', '_').replace('/', '_')[:30]  # Limit length
                    filename = os.path.join(out_dir, f"{timestamp}_{safe_keyword}.jpg")
                else:
                    # Fallback: use concept name + counter
                    safe_keyword = keyword.replace(' ', '_').replace('/', '_')[:20]  # Limit length
                    filename = os.path.join(out_dir, f"{safe_keyword}_{saved+1:02d}.jpg")
                try:
                    set_status(f"Downloading {saved+1}/{images_needed} for '{keyword}'")
                    r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                    if r.status_code == 200 and len(r.content) > 1000:
                        with open(filename, "wb") as f:
                            f.write(r.content)
                        saved += 1
                except Exception:
                    continue

            if saved >= images_needed:
                break

            set_status(f"Scrolling… ({scroll_i+1}/{max_scrolls}) for '{keyword}'")
            await page.mouse.wheel(0, 1200)
            await page.wait_for_timeout(700)

        await context.close()
        return saved


def srt_file_to_text(srt_path: str) -> str:
    """Convert an .srt file into plain text by stripping indices/timestamps."""
    lines: List[str] = []
    with open(srt_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line:
                continue
            # Skip numeric indices
            if re.match(r"^\d+$", line):
                continue
            # Skip timestamp lines
            if "-->" in line:
                continue
            lines.append(line.strip())
    return " ".join(lines)


def compute_keyword_image_targets(
    text: str,
    settings: dict,
) -> List[Tuple[str, int]]:
    """Given transcript text and settings, decide how many images to fetch per keyword.

    Returns list of (keyword, images_needed).
    Tries to ensure at least min_images_per_srt overall, but respects max_total_images.
    """
    max_keywords = int(settings.get("max_keywords", 20))
    per_kw_default = int(settings.get("images_per_keyword", 3))
    max_total = int(settings.get("max_total_images", 60))
    min_per_srt = int(settings.get("min_images_per_srt", 20))

    keywords = extract_keywords(text, max_keywords)
    if not keywords:
        return []

    # First-pass simple allocation
    total_if_default = per_kw_default * len(keywords)
    target_total = max(min_per_srt, min(total_if_default, max_total))

    # Evenly distribute target_total over keywords (ceil to avoid being under)
    per_kw = max(1, (target_total + len(keywords) - 1) // len(keywords))
    per_kw = min(per_kw, max_total)  # hard safety

    remaining = max_total
    out: List[Tuple[str, int]] = []
    for kw in keywords:
        if remaining <= 0:
            break
        need = min(per_kw, remaining)
        out.append((kw, need))
        remaining -= need

    return out



