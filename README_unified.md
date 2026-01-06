# Research & B-Roll Harvester

A fast, sequential pipeline for video creation that downloads videos, generates transcripts, and automatically extracts + downloads relevant images using smart NLP analysis.

## Features

- **Sequential Job Processing**: Paste multiple video links and process them one by one in the background
- **Platform-Aware SRT Generation**: Automatic subtitles for TikTok/Instagram, optional for YouTube
- **Smart Concept Extraction**: Uses NLP to identify visually important concepts from transcripts
- **Browser Automation**: Downloads images using real browser profiles to avoid detection
- **Clean Output Structure**: Each job creates a ready-to-edit bundle with videos, SRT, images, and metadata

## Installation

### Prerequisites

```bash
# Install system dependencies
sudo apt update
sudo apt install -y ffmpeg python3 python3-pip python3-venv

# Install yt-dlp for video downloading
pip install yt-dlp

# Install Whisper for transcription
pip install openai-whisper

# Install spaCy language model
pip install spacy
python -m spacy download en_core_web_sm
```

### Setup

```bash
# Clone the repository
git clone https://github.com/Jamestownkid/dontgoogleme.git
cd dontgoogleme

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser
python -m playwright install chromium
```

## Usage

### First Run

```bash
cd dontgoogleme
source venv/bin/activate
python unified_app.py
```

### Daily Usage

```bash
cd dontgoogleme
source venv/bin/activate
python unified_app.py
```

The app will remember your settings and output directory between runs.

## How It Works

1. **Add Jobs**: Paste video URLs, select platform, enter topic, add notes
2. **Sequential Processing**: Jobs run one at a time in the background
3. **Video Download**: Uses yt-dlp to download videos when possible
4. **SRT Generation**: Whisper transcribes videos (enabled by default for TikTok/Instagram)
5. **Concept Extraction**: NLP analyzes transcripts to find visual concepts
6. **Image Download**: Browser automation fetches relevant images

## Output Structure

Each job creates a folder like: `output/topic_jobid/`

```
topic_jobid/
├── video.mp4              # Downloaded video
├── transcript.srt         # Whisper-generated subtitles
├── images/                # Concept-based image folders
│   ├── roman_empire/      # 001.jpg, 002.jpg, 003.jpg
│   ├── cold_war/          # 001.jpg, 002.jpg, 003.jpg
│   └── ...
├── links.txt              # Original URLs
├── notes.txt              # Your notes
├── job.json               # Job metadata
└── download.log           # Processing logs
```

## Settings

Edit `settings.json` to customize:

- `whisper_model`: "tiny", "base", "small", "medium", "large"
- `images_per_concept`: Images to download per concept
- `max_concepts_per_srt`: Maximum concepts to extract
- `max_total_images`: Overall image limit per job
- `use_visible_browser`: Show browser window during image download
- `srt_youtube_enabled`: Generate SRT for YouTube videos

## Platform Settings

- **TikTok**: Download + SRT enabled by default
- **Instagram**: Download + SRT enabled by default
- **YouTube**: Download only (SRT optional)
- **Other**: Download only (SRT configurable)

## Browser Profile (Anti-Detection)

For better image downloading success:

1. Set `"use_existing_chrome_profile": true` in settings.json
2. Set `"chrome_profile_dir"` to your Chrome profile (e.g., `~/.config/google-chrome`)
3. The app will reuse your browser cookies and session

## Requirements

- Python 3.8+
- ffmpeg
- yt-dlp
- Chrome/Chromium browser
- Pop!_OS or compatible Linux

## License

MIT License - see LICENSE file for details.
