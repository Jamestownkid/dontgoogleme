# Tinker Video Collector (yt-dlp + Whisper SRT)

## What it does
- Paste links (YouTube / TikTok / others supported by yt-dlp)
- Choose an output base folder + optional Topic/Subtopic
- Press **Enter** or **Go**
- App creates a new folder, saves:
  - `links.txt`
  - `notes.txt`
  - `log.txt`
- Downloads videos with **yt-dlp**
- If a video has no `.srt`, it runs **Whisper** to generate `.srt` in the background

## Prereqs (Linux)
You need ffmpeg:

```bash
sudo apt update
sudo apt install -y ffmpeg
```

## Install (Python)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip wheel
pip install -r requirements.txt
```

### Torch note
Whisper uses PyTorch. `pip install -r requirements.txt` usually pulls it in, but on some systems you may need to install torch separately.

## Run
```bash
python app.py
```

## Notes
- First Whisper run will download the selected model (tiny/base/small/medium/large) automatically.
- TikTok downloads may sometimes fail due to platform changes/rate limits. Those links remain saved in `links.txt` and the app continues.
