FEATURES (v2)

Core
- One-click pipeline: Video → Whisper transcript → SRT file → keyword extraction → Google Images download
- Whisper model selection: tiny/base/small/medium/large
- Outputs organized cleanly:
  - srt/output.srt
  - images/<keyword>/###.jpg

Keyword intelligence
- Extracts NOUN + PROPN (proper nouns) using spaCy POS tagging
- Filters stopwords and tiny tokens
- Ranks keywords by frequency in the transcript
- User-controlled caps:
  - Max keywords per SRT (cap per SRT)
  - Images per keyword
  - Max total images overall (hard cap)
  - Max scrolls per keyword (“pages” cap)

Browser behavior (to reduce blocks)
- Uses Playwright with a *persistent* browser context (more like a real user than raw HTTP scraping)
- “Visible browser” mode opens an actual window so Google treats it like browsing
- Optional “Use my existing Chrome profile”:
  - Reuses your cookies/session/logins
  - Helps reduce captchas/blocks (not guaranteed, but usually better)

Safety / stability
- Deduplicates URLs during scraping
- Timeouts + basic validation for downloads
- Saves settings to settings.json so you don’t reconfigure each time

Known limits (honest)
- Google can still rate-limit if you spam hundreds of searches quickly
- Image relevance depends on extracted keywords
- Full-res URLs depend on Google’s current DOM; selectors may need tweaking over time

Suggested next upgrades (easy to add)
- Phrase extraction (noun chunks like “Roman Empire” instead of single tokens)
- Named-entity filtering (PERSON/ORG/LOC only)
- Per-keyword “prompt expansion” (e.g., keyword + “photo”/“map”/“diagram”)
- Cache / resume support (skip existing folders)
