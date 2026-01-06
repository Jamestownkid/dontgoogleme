Auto B‑Roll Generator (v2)

What it does
- Pick a video
- Whisper generates SRT + full transcript text
- spaCy extracts the most frequent NOUN/PROPN keywords (cap per SRT)
- For each keyword, it opens Google Images in a real browser (Playwright) and downloads N images

Why “uses my browser”
- This app can launch a VISIBLE Chrome/Chromium window (like you’re browsing)
- Optionally it can reuse YOUR existing Chrome profile folder (cookies/login), which makes it behave even more like you

IMPORTANT:
Using your existing profile means Playwright will open Chrome with that profile folder.
Don’t run multiple Chromes using the same profile at the same time.

Install (Linux / Pop!_OS)
1) Install ffmpeg system-wide:
   sudo apt update && sudo apt install -y ffmpeg

2) Create venv + install deps:
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt

3) Install spaCy language model:
   python -m spacy download en_core_web_sm

4) Install Playwright browser:
   python -m playwright install chromium

Run
  python app.py

Outputs
- srt/output.srt
- images/<keyword>/001.jpg etc

Chrome profile directory (if you enable “Use my existing Chrome profile”)
Typical Linux paths:
- Google Chrome: ~/.config/google-chrome
- Chromium:     ~/.config/chromium

You can select either of those folders in the app.
