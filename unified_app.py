#!/usr/bin/env python3
"""
Unified Research & B-Roll Harvester
Fast, sequential pipeline for video creation with smart image concept extraction
"""

import os
import sys
import json
import time
import threading
import queue
import asyncio
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
import re

# Core dependencies
import whisper
import spacy
import requests
from playwright.async_api import async_playwright

# Local modules
from broll_core import (
    generate_srt, extract_keywords, compute_keyword_image_targets,
    google_images_download, safe_folder_name, ensure_dir,
    which_browser_executable, load_settings, save_settings
)


class JobStatus(Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing"
    IMAGES = "images"
    DONE = "done"
    ERROR = "error"


class Platform(Enum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"
    OTHER = "other"


@dataclass
class Job:
    id: str
    url: str
    platform: Platform
    output_dir: str
    topic: str
    notes: str = ""
    status: JobStatus = JobStatus.QUEUED
    progress: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

    def __post_init__(self):
        if not self.id:
            self.id = f"{int(time.time())}_{hash(self.url) % 10000}"


class NLPConceptExtractor:
    """Smart concept extraction using spaCy + scoring"""

    def __init__(self):
        self.nlp = None

    def _load_model(self):
        if self.nlp is None:
            self.nlp = spacy.load("en_core_web_sm")

    def extract_concepts(self, srt_text: str, max_concepts: int = 20) -> List[str]:
        """Extract smart visual concepts from SRT text using NLP pipeline"""
        self._load_model()

        # Clean SRT text (remove timestamps and indices)
        clean_text = self._clean_srt_text(srt_text)

        # Get all sentences
        sentences = [s.strip() for s in clean_text.split('.') if s.strip()]

        concepts = []
        seen_concepts = set()

        # First pass: extract named entities (highest priority)
        for sentence in sentences:
            if not sentence:
                continue

            doc = self.nlp(sentence)
            for ent in doc.ents:
                if ent.label_ in ['PERSON', 'ORG', 'GPE', 'LOC', 'EVENT', 'PRODUCT', 'WORK_OF_ART']:
                    concept = ent.text.strip()
                    if len(concept) > 2 and concept not in seen_concepts:
                        concepts.append(concept)
                        seen_concepts.add(concept)
                        if len(concepts) >= max_concepts:
                            break

            if len(concepts) >= max_concepts:
                break

        # Second pass: extract noun phrases and important nouns
        if len(concepts) < max_concepts:
            for sentence in sentences:
                if not sentence:
                    continue

                score = self._score_sentence_visual_importance(sentence)
                if score < 0.2:  # Lower threshold for second pass
                    continue

                sentence_concepts = self._extract_concepts_from_sentence(sentence)

                for concept in sentence_concepts:
                    if (concept not in seen_concepts and
                        len(concept) > 3 and  # Longer concepts
                        len(concept.split()) <= 4):  # Not too many words
                        concepts.append(concept)
                        seen_concepts.add(concept)

                        if len(concepts) >= max_concepts:
                            break

                if len(concepts) >= max_concepts:
                    break

        return concepts[:max_concepts]

    def _clean_srt_text(self, srt_text: str) -> str:
        """Remove SRT formatting and timestamps"""
        lines = srt_text.split('\n')
        clean_lines = []

        for line in lines:
            line = line.strip()
            # Skip empty lines, numbers, timestamps
            if not line or line.isdigit() or '-->' in line:
                continue
            clean_lines.append(line)

        return ' '.join(clean_lines)

    def _score_sentence_visual_importance(self, sentence: str) -> float:
        """Score sentence for visual concept potential"""
        self._load_model()
        doc = self.nlp(sentence.lower())

        score = 0.0

        # Count visual indicators
        visual_words = {
            'see', 'look', 'watch', 'view', 'appear', 'show', 'display',
            'imagine', 'picture', 'visual', 'scene', 'image', 'photo',
            'building', 'place', 'location', 'city', 'country', 'world'
        }

        emotion_words = {
            'amazing', 'beautiful', 'stunning', 'incredible', 'awesome',
            'terrible', 'horrible', 'scary', 'exciting', 'dramatic'
        }

        action_words = {
            'fight', 'battle', 'war', 'revolution', 'change', 'transform',
            'build', 'create', 'destroy', 'discover', 'invent', 'explore'
        }

        # Score based on content
        words = set(token.lemma_.lower() for token in doc)
        score += len(words.intersection(visual_words)) * 0.3
        score += len(words.intersection(emotion_words)) * 0.2
        score += len(words.intersection(action_words)) * 0.2

        # Score based on named entities (high visual potential)
        entities = [ent for ent in doc.ents if ent.label_ in ['PERSON', 'ORG', 'GPE', 'LOC', 'EVENT']]
        score += len(entities) * 0.4

        # Score based on noun phrases (potential concepts)
        noun_phrases = [chunk for chunk in doc.noun_chunks if len(chunk) > 1]
        score += len(noun_phrases) * 0.1

        return min(score, 1.0)  # Cap at 1.0

    def _extract_concepts_from_sentence(self, sentence: str) -> List[str]:
        """Extract potential image concepts from a sentence"""
        self._load_model()
        doc = self.nlp(sentence)

        concepts = []

        # Named entities (highest priority)
        for ent in doc.ents:
            if ent.label_ in ['PERSON', 'ORG', 'GPE', 'LOC', 'EVENT']:
                concepts.append(ent.text.strip())

        # Noun phrases (medium priority)
        for chunk in doc.noun_chunks:
            concept = chunk.text.strip()
            if len(concept.split()) > 1 and concept not in concepts:
                concepts.append(concept)

        # Important nouns (lower priority)
        for token in doc:
            if (token.pos_ in ['NOUN', 'PROPN'] and
                not token.is_stop and
                len(token.text) > 3 and
                token.text not in concepts):
                concepts.append(token.text)

        return concepts


class JobProcessor:
    """Handles background job processing"""

    def __init__(self, settings: Dict[str, Any], status_callback=None):
        self.settings = settings
        self.status_callback = status_callback
        self.nlp_extractor = NLPConceptExtractor()

    async def process_job(self, job: Job) -> None:
        """Process a single job through all stages"""
        try:
            job.started_at = datetime.now()
            job.status = JobStatus.DOWNLOADING
            self._update_status(job)

            # Create job directory (just topic name, no subtopics)
            job_dir = os.path.join(job.output_dir, safe_folder_name(job.topic))
            ensure_dir(job_dir)

            # Save job metadata
            self._save_job_metadata(job, job_dir)

            # Stage 1: Download video
            await self._download_video(job, job_dir)

            # Stage 2: Generate SRT (if enabled)
            srt_path = None
            if self._should_generate_srt(job):
                job.status = JobStatus.TRANSCRIBING
                self._update_status(job)
                srt_path = await self._generate_srt(job, job_dir)

            # Stage 3: Extract concepts and download images
            if srt_path and os.path.exists(srt_path):
                job.status = JobStatus.ANALYZING
                self._update_status(job)

                concepts = await self._extract_concepts(srt_path)

                job.status = JobStatus.IMAGES
                self._update_status(job)

                await self._download_images(job, job_dir, concepts)

            job.status = JobStatus.DONE
            job.completed_at = datetime.now()
            self._update_status(job)

        except Exception as e:
            job.status = JobStatus.ERROR
            job.error = str(e)
            job.completed_at = datetime.now()
            self._update_status(job)

    def _update_status(self, job: Job):
        if self.status_callback:
            self.status_callback(job)

    def _save_job_metadata(self, job: Job, job_dir: str):
        """Save job information to files"""
        # links.txt
        with open(os.path.join(job_dir, "links.txt"), "w") as f:
            f.write(f"{job.url}\n")

        # notes.txt
        with open(os.path.join(job_dir, "notes.txt"), "w") as f:
            f.write(job.notes + "\n" if job.notes else "")

        # job.json
        job_data = {
            "id": job.id,
            "url": job.url,
            "platform": job.platform.value,
            "topic": job.topic,
            "created_at": job.created_at.isoformat(),
            "status": job.status.value
        }
        with open(os.path.join(job_dir, "job.json"), "w") as f:
            json.dump(job_data, f, indent=2)

    async def _download_video(self, job: Job, job_dir: str) -> str:
        """Download video using yt-dlp"""
        import subprocess
        import asyncio

        job.progress = "Downloading video..."
        self._update_status(job)

        try:
            # Run yt-dlp as subprocess
            cmd = [
                "yt-dlp",
                "--output", os.path.join(job_dir, "%(title)s.%(ext)s"),
                "--merge-output-format", "mp4",
                job.url
            ]

            # Run in subprocess and capture output
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=job_dir
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise Exception(f"yt-dlp failed: {error_msg}")

            # Find the downloaded video file
            for file in os.listdir(job_dir):
                if file.endswith(('.mp4', '.mkv', '.webm', '.mov')) and not file.endswith('.temp'):
                    return os.path.join(job_dir, file)

            raise Exception("No video file found after download")

        except FileNotFoundError:
            raise Exception("yt-dlp not found. Please install with: pip install yt-dlp")
        except Exception as e:
            raise Exception(f"Download failed: {str(e)}")

    def _should_generate_srt(self, job: Job) -> bool:
        """Determine if SRT should be generated based on platform and settings"""
        if job.platform == Platform.TIKTOK:
            return True
        elif job.platform == Platform.INSTAGRAM:
            return True
        elif job.platform == Platform.YOUTUBE:
            return self.settings.get("srt_youtube_enabled", False)
        else:
            return self.settings.get("srt_other_enabled", False)

    async def _generate_srt(self, job: Job, job_dir: str) -> str:
        """Generate SRT using Whisper"""
        # Find video file
        video_file = None
        for file in os.listdir(job_dir):
            if file.endswith(('.mp4', '.mkv', '.webm', '.mov')):
                video_file = os.path.join(job_dir, file)
                break

        if not video_file:
            raise Exception("No video file found for SRT generation")

        job.progress = "Generating SRT..."
        self._update_status(job)

        srt_path, _ = generate_srt(video_file, self.settings["whisper_model"])
        # Move SRT to job directory
        final_srt = os.path.join(job_dir, "transcript.srt")
        os.rename(srt_path, final_srt)

        return final_srt

    async def _extract_concepts(self, srt_path: str) -> List[str]:
        """Extract visual concepts from SRT"""
        with open(srt_path, 'r', encoding='utf-8') as f:
            srt_text = f.read()

        concepts = self.nlp_extractor.extract_concepts(srt_text, self.settings["max_concepts_per_srt"])
        return concepts

    async def _download_images(self, job: Job, job_dir: str, concepts: List[str]):
        """Download images for concepts with smart search and Wikipedia fallback"""
        images_dir = os.path.join(job_dir, "images")
        ensure_dir(images_dir)

        # Extract timestamps from SRT for naming
        timestamps = self._extract_srt_timestamps(job_dir)

        total_images = 0
        image_counter = 0

        for i, concept in enumerate(concepts):
            job.progress = f"Images: {concept} ({i+1}/{len(concepts)})"
            self._update_status(job)

            # Calculate images needed for this concept
            images_per_concept = max(1, self.settings["images_per_concept"])
            if total_images + images_per_concept > self.settings["max_total_images"]:
                images_per_concept = max(1, self.settings["max_total_images"] - total_images)

            if images_per_concept <= 0:
                break

            # Smart search: try normal search first
            saved = await google_images_download(
                keyword=concept,
                out_dir=images_dir,
                images_needed=images_per_concept,
                max_scrolls=self.settings["max_scrolls_per_keyword"],
                use_visible_browser=False,  # Always background
                use_existing_profile=self.settings["use_existing_chrome_profile"],
                chrome_profile_dir=self.settings["chrome_profile_dir"],
                status_cb=None,
                timestamp_based_naming=True,
                timestamps=timestamps,
                start_counter=image_counter
            )

            # If normal search didn't get enough, try Wikipedia search
            wiki_needed = images_per_concept - saved
            wiki_saved = 0

            if wiki_needed > 0:
                job.progress = f"Wikipedia: {concept} ({i+1}/{len(concepts)})"
                self._update_status(job)

                # Search with "Wikipedia" added for better quality images
                wiki_keyword = f"{concept} Wikipedia"
                wiki_saved = await google_images_download(
                    keyword=wiki_keyword,
                    out_dir=images_dir,
                    images_needed=wiki_needed,
                    max_scrolls=self.settings["max_scrolls_per_keyword"],
                    use_visible_browser=False,  # Background
                    use_existing_profile=self.settings["use_existing_chrome_profile"],
                    chrome_profile_dir=self.settings["chrome_profile_dir"],
                    status_cb=None,
                    timestamp_based_naming=True,
                    timestamps=timestamps,
                    start_counter=image_counter + saved
                )

            saved_total = saved + wiki_saved
            total_images += saved_total
            image_counter += saved_total

            if total_images >= self.settings["max_total_images"]:
                break


class UnifiedApp(tk.Tk):
    """Main application with job queue"""

    def __init__(self):
        super().__init__()
        self.title("Research & B-Roll Harvester")
        self.geometry("1200x800")

        # Track settings window
        self.settings_window = None

        # Set pink theme
        self.configure(bg='#FFE4E1')  # Misty Rose background
        style = ttk.Style()
        style.configure('TFrame', background='#FFE4E1')
        style.configure('TLabel', background='#FFE4E1', foreground='#8B008B')  # Dark Magenta text
        style.configure('TButton', background='#FFB6C1', foreground='#8B008B')  # Light Pink buttons
        style.configure('TEntry', fieldbackground='#FFF0F5')  # Lavender Blush
        style.configure('TCombobox', fieldbackground='#FFF0F5')
        style.configure('TSpinbox', fieldbackground='#FFF0F5')
        style.configure('TLabelframe', background='#FFE4E1', foreground='#8B008B')
        style.configure('TLabelframe.Label', background='#FFE4E1', foreground='#8B008B', font=('Arial', 10, 'bold'))
        style.configure('TCheckbutton', background='#FFE4E1', foreground='#8B008B')

        # Load settings
        self.settings = self._load_app_settings()

        # Job management
        self.jobs: Dict[str, Job] = {}
        self.job_queue = queue.Queue()
        self.current_job: Optional[Job] = None
        self.job_processor = JobProcessor(self.settings, self._on_job_status_update)

        # UI setup
        self._setup_ui()

        # Start job processor thread
        self.processing_thread = threading.Thread(target=self._process_jobs_loop, daemon=True)
        self.processing_thread.start()

        # Enter key binding removed - only button click submits

    def _load_app_settings(self) -> Dict[str, Any]:
        """Load application settings"""
        defaults = {
            "whisper_model": "base",
            "images_per_concept": 3,
            "max_concepts_per_srt": 15,
            "max_total_images": 50,
            "max_scrolls_per_keyword": 6,
            "use_visible_browser": True,
            "use_existing_chrome_profile": False,
            "chrome_profile_dir": "",
            "srt_youtube_enabled": False,
            "srt_other_enabled": False,
        }

        try:
            settings_file = os.path.join(os.path.dirname(__file__), "settings.json")
            with open(settings_file, "r") as f:
                loaded = json.load(f)
                defaults.update(loaded)
        except FileNotFoundError:
            pass

        return defaults

    def _save_app_settings(self, settings: dict):
        """Save application settings"""
        try:
            settings_file = os.path.join(os.path.dirname(__file__), "settings.json")
            with open(settings_file, "w") as f:
                json.dump(settings, f, indent=2)
            print(f"Settings saved to {settings_file}")
        except Exception as e:
            print(f"Error saving settings: {e}")
            messagebox.showerror("Save Error", f"Could not save settings: {e}")

    def _setup_ui(self):
        """Setup the main UI"""
        # Main container
        main_frame = ttk.Frame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Left panel - Job queue
        left_panel = ttk.Frame(main_frame, width=300)
        left_panel.pack(side="left", fill="y", padx=(0, 10))
        left_panel.pack_propagate(False)

        ttk.Label(left_panel, text="Job Queue", font=("Arial", 12, "bold")).pack(pady=(0, 10))

        # Job list
        self.job_listbox = tk.Listbox(left_panel, height=25)
        self.job_listbox.pack(fill="both", expand=True)
        self.job_listbox.bind("<<ListboxSelect>>", self._on_job_selected)

        # Error box (bottom of left)
        error_frame = ttk.LabelFrame(left_panel, text="Error Box", height=200)
        error_frame.pack(fill="x", pady=(10, 0))
        error_frame.pack_propagate(False)

        self.error_text = scrolledtext.ScrolledText(error_frame, height=8, wrap="word")
        self.error_text.pack(fill="both", expand=True)

        # Right panel - Input and controls
        right_panel = ttk.Frame(main_frame)
        right_panel.pack(side="right", fill="both", expand=True)

        # Output directory selection
        dir_frame = ttk.Frame(right_panel)
        dir_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(dir_frame, text="Output Directory:").grid(row=0, column=0, sticky="w")
        self.output_dir_var = tk.StringVar(value=os.path.expanduser("~/Downloads/broll_jobs"))
        ttk.Entry(dir_frame, textvariable=self.output_dir_var, width=50).grid(row=0, column=1, padx=(10, 5))
        ttk.Button(dir_frame, text="Browse", command=self._choose_output_dir).grid(row=0, column=2)

        # Input area
        input_frame = ttk.LabelFrame(right_panel, text="Add New Job")
        input_frame.pack(fill="x", pady=(0, 10))

        # Large URL input for multiple links
        ttk.Label(input_frame, text="Video URLs (paste multiple links):").grid(row=0, column=0, sticky="nw", padx=5, pady=2)
        self.url_text = tk.Text(input_frame, height=12, width=80, wrap="word", font=("Arial", 10))
        self.url_text.grid(row=0, column=1, columnspan=2, padx=5, pady=2, sticky="we")
        ttk.Label(input_frame, text="Paste as many video links as you want (one per line)", font=("Arial", 8)).grid(row=1, column=1, columnspan=2, sticky="w", padx=5)

        # SRT and Image Generator selection
        ttk.Label(input_frame, text="SRT & Image Generator:").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        self.platform_var = tk.StringVar(value="tiktok")
        platform_combo = ttk.Combobox(input_frame, textvariable=self.platform_var,
                                    values=["tiktok", "youtube", "instagram", "other"], state="readonly")
        platform_combo.grid(row=2, column=1, padx=5, pady=2, sticky="w")
        ttk.Label(input_frame, text="Select platform - only matching links will generate SRT & images", font=("Arial", 8)).grid(row=3, column=1, columnspan=2, sticky="w", padx=5)

        # Topic input
        ttk.Label(input_frame, text="Topic:").grid(row=4, column=0, sticky="w", padx=5, pady=2)
        self.topic_var = tk.StringVar()
        ttk.Entry(input_frame, textvariable=self.topic_var, width=40).grid(row=4, column=1, columnspan=2, padx=5, pady=2, sticky="we")

        # Notes
        ttk.Label(input_frame, text="Notes:").grid(row=5, column=0, sticky="nw", padx=5, pady=2)
        self.notes_text = tk.Text(input_frame, height=3, width=50)
        self.notes_text.grid(row=5, column=1, columnspan=2, padx=5, pady=2, sticky="we")

        # Buttons
        btn_frame = ttk.Frame(input_frame)
        btn_frame.grid(row=6, column=0, columnspan=3, pady=10)

        ttk.Button(btn_frame, text="Add Job", command=self._add_job).pack(side="left", padx=(0, 10))
        ttk.Button(btn_frame, text="Settings", command=self._show_settings).pack(side="left", padx=(0, 10))
        ttk.Button(btn_frame, text="Open Output", command=self._open_output_dir).pack(side="left")

        # Status area
        status_frame = ttk.LabelFrame(right_panel, text="Status")
        status_frame.pack(fill="both", expand=True)

        self.status_text = scrolledtext.ScrolledText(status_frame, height=15, wrap="word")
        self.status_text.pack(fill="both", expand=True)

        # Configure grid weights
        input_frame.columnconfigure(1, weight=1)

    def _choose_output_dir(self):
        """Choose output directory"""
        dir_path = filedialog.askdirectory(title="Choose Output Directory")
        if dir_path:
            self.output_dir_var.set(dir_path)

    def _add_job(self):
        """Add jobs to the queue with smart platform filtering"""
        urls_text = self.url_text.get("1.0", "end").strip()
        if not urls_text:
            messagebox.showerror("Error", "Please enter video URLs")
            return

        platform_str = self.platform_var.get()
        try:
            platform = Platform(platform_str)
        except ValueError:
            messagebox.showerror("Error", f"Invalid platform: {platform_str}")
            return

        topic = self.topic_var.get().strip()
        if not topic:
            topic = f"{platform_str.title()} Batch"

        output_dir = self.output_dir_var.get().strip()
        if not output_dir:
            messagebox.showerror("Error", "Please select an output directory")
            return

        notes = self.notes_text.get("1.0", "end").strip()

        # Parse all URLs
        all_urls = [url.strip() for url in urls_text.split('\n') if url.strip()]
        if not all_urls:
            messagebox.showerror("Error", "Please enter video URLs")
            return

        # Smart filtering: only process URLs that match the selected platform
        platform_domains = {
            Platform.TIKTOK: ['tiktok.com', 'vm.tiktok.com'],
            Platform.YOUTUBE: ['youtube.com', 'youtu.be'],
            Platform.INSTAGRAM: ['instagram.com'],
            Platform.OTHER: []  # Accept any URL for other
        }

        domains = platform_domains.get(platform, [])
        matching_urls = []
        skipped_urls = []

        for url in all_urls:
            if platform == Platform.OTHER or any(domain in url for domain in domains):
                matching_urls.append(url)
            else:
                skipped_urls.append(url)

        if not matching_urls:
            messagebox.showerror("Error", f"No {platform_str} URLs found in the list")
            return

        # Create jobs for matching URLs
        jobs_added = 0
        for url in matching_urls:
            job_topic = f"{topic} - {jobs_added + 1}" if len(matching_urls) > 1 else topic

            job = Job(
                id="",
                url=url,
                platform=platform,
                output_dir=output_dir,
                topic=job_topic,
                notes=notes
            )

            # Add to jobs dict and queue
            self.jobs[job.id] = job
            self.job_queue.put(job)
            jobs_added += 1

        # Update UI
        self._update_job_list()
        self._log_status(f"Added {jobs_added} job(s) for {platform_str}")

        # Show summary in error box
        summary = f"✅ Added {jobs_added} {platform_str} jobs\n"
        if skipped_urls:
            summary += f"⏭️  Skipped {len(skipped_urls)} non-{platform_str} URLs\n"
        self._show_error(summary)

        # Clear input fields
        self.url_text.delete("1.0", "end")
        self.topic_var.set("")
        self.notes_text.delete("1.0", "end")

    def _extract_topic_from_url(self, url: str) -> str:
        """Extract a basic topic from URL"""
        # Simple extraction - can be improved
        if "tiktok.com" in url:
            return "TikTok Video"
        elif "youtube.com" in url or "youtu.be" in url:
            return "YouTube Video"
        elif "instagram.com" in url:
            return "Instagram Video"
        else:
            return f"Video {len(self.jobs) + 1}"

    def _update_job_list(self):
        """Update the job list display"""
        self.job_listbox.delete(0, "end")
        for job in self.jobs.values():
            status_emoji = {
                JobStatus.QUEUED: "⏳",
                JobStatus.DOWNLOADING: "⬇️",
                JobStatus.TRANSCRIBING: "🎤",
                JobStatus.ANALYZING: "🔍",
                JobStatus.IMAGES: "🖼️",
                JobStatus.DONE: "✅",
                JobStatus.ERROR: "❌"
            }.get(job.status, "❓")

            display_text = f"{status_emoji} {job.topic}"
            if job.progress:
                display_text += f" - {job.progress}"

            self.job_listbox.insert("end", display_text)

    def _on_job_selected(self, event):
        """Handle job selection - show in error box"""
        selection = self.job_listbox.curselection()
        if selection:
            index = selection[0]
            job_id = list(self.jobs.keys())[index]
            job = self.jobs[job_id]

            # Display job info in error box
            info = f"""📋 Job Details:
ID: {job.id}
URL: {job.url}
Platform: {job.platform.value}
Topic: {job.topic}
Status: {job.status.value}
Created: {job.created_at.strftime('%Y-%m-%d %H:%M:%S')}

Progress: {job.progress}
"""

            if job.error:
                info += f"\n❌ Error: {job.error}"

            if job.notes:
                info += f"\n📝 Notes: {job.notes}"

            self._show_error(info)

    def _on_job_status_update(self, job: Job):
        """Handle job status updates"""
        self.after(0, lambda: self._update_job_list())
        self.after(0, lambda: self._log_status(f"Job {job.topic}: {job.status.value} - {job.progress}"))

        # Show errors in error box
        if job.error:
            error_msg = f"❌ Job Failed: {job.topic}\n{job.error}\n\nURL: {job.url}\nPlatform: {job.platform.value}"
            self.after(0, lambda: self._show_error(error_msg))

    def _show_error(self, message: str):
        """Show message in error box"""
        self.error_text.delete("1.0", "end")
        self.error_text.insert("1.0", message)
        self.error_text.see("end")

    def _log_status(self, message: str):
        """Log status message"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_text.insert("end", f"[{timestamp}] {message}\n")
        self.status_text.see("end")

    def _process_jobs_loop(self):
        """Background job processing loop"""
        while True:
            try:
                # Get next job from queue
                job = self.job_queue.get(timeout=1)
                self.current_job = job

                # Process job
                asyncio.run(self.job_processor.process_job(job))

                self.job_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                self._log_status(f"Error processing job: {e}")
                continue

    def _show_settings(self):
        """Show settings dialog (only one at a time)"""
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus()
            return

        settings_window = tk.Toplevel(self)
        settings_window.title("Settings")
        settings_window.geometry("550x700")
        settings_window.resizable(False, False)
        settings_window.configure(bg='#FFE4E1')
        self.settings_window = settings_window

        # Handle window close
        def on_close():
            self.settings_window = None
            settings_window.destroy()

        settings_window.protocol("WM_DELETE_WINDOW", on_close)

        # Create settings variables
        whisper_var = tk.StringVar(value=self.settings.get("whisper_model", "base"))
        images_per_concept_var = tk.IntVar(value=self.settings.get("images_per_concept", 3))
        max_concepts_var = tk.IntVar(value=self.settings.get("max_concepts_per_srt", 15))
        max_total_images_var = tk.IntVar(value=self.settings.get("max_total_images", 50))
        max_scrolls_var = tk.IntVar(value=self.settings.get("max_scrolls_per_keyword", 6))
        chrome_profile_var = tk.StringVar(value=self.settings.get("chrome_profile_dir", ""))
        youtube_srt_var = tk.BooleanVar(value=self.settings.get("srt_youtube_enabled", False))
        other_srt_var = tk.BooleanVar(value=self.settings.get("srt_other_enabled", False))

        # Model status variable
        model_status_var = tk.StringVar(value="Checking...")
        self._check_whisper_model_status(model_status_var)

        # Layout
        main_frame = ttk.Frame(settings_window, padding=20)
        main_frame.pack(fill="both", expand=True)

        row = 0

        # Whisper Model with management
        ttk.Label(main_frame, text="Whisper Model:").grid(row=row, column=0, sticky="w", pady=5)
        model_frame = ttk.Frame(main_frame)
        model_frame.grid(row=row, column=1, sticky="we", pady=5)

        whisper_combo = ttk.Combobox(model_frame, textvariable=whisper_var,
                                   values=["tiny", "base", "small", "medium", "large"], state="readonly", width=10)
        whisper_combo.pack(side="left")

        def load_model():
            """Download/load the selected whisper model"""
            model = whisper_var.get()
            try:
                import whisper
                self._show_error(f"Loading Whisper model '{model}'...")
                settings_window.update()
                whisper.load_model(model)  # This will download if needed
                self._show_error(f"✅ Whisper model '{model}' loaded successfully!")
                messagebox.showinfo("Model Loaded", f"Whisper model '{model}' is ready to use!")
            except Exception as e:
                self._show_error(f"❌ Failed to load model '{model}': {str(e)}")
                messagebox.showerror("Load Failed", f"Could not load model '{model}': {str(e)}")

        def auto_detect_models():
            """Auto-detect available whisper models on system"""
            import os
            import whisper

            # Check cache directory for downloaded models
            cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "whisper")
            available_models = []

            if os.path.exists(cache_dir):
                for model in ["tiny", "base", "small", "medium", "large"]:
                    model_files = [f for f in os.listdir(cache_dir) if model in f and f.endswith(('.pt', '.bin'))]
                    if model_files:
                        available_models.append(model)

            if available_models:
                # Use the largest available model
                best_model = max(available_models, key=lambda x: ["tiny", "base", "small", "medium", "large"].index(x))
                whisper_var.set(best_model)
                self._show_error(f"✅ Auto-detected model: '{best_model}'")
            else:
                self._show_error("❌ No cached models found. Use 'Load' to download one.")
                messagebox.showinfo("No Models", "No Whisper models found. Click 'Load' to download the selected model.")

        ttk.Button(model_frame, text="Load", command=load_model).pack(side="left", padx=(5,0))
        ttk.Button(model_frame, text="Auto", command=auto_detect_models).pack(side="left", padx=(5,0))

        # Model status
        ttk.Label(model_frame, textvariable=model_status_var, font=("Arial", 8)).pack(side="left", padx=(10,0))
        row += 1

        # Images per concept
        ttk.Label(main_frame, text="Images per Concept:").grid(row=row, column=0, sticky="w", pady=5)
        ttk.Spinbox(main_frame, from_=1, to=10, textvariable=images_per_concept_var, width=15).grid(row=row, column=1, sticky="w", pady=5)
        row += 1

        # Max concepts per SRT
        ttk.Label(main_frame, text="Max Concepts per SRT:").grid(row=row, column=0, sticky="w", pady=5)
        ttk.Spinbox(main_frame, from_=5, to=30, textvariable=max_concepts_var, width=15).grid(row=row, column=1, sticky="w", pady=5)
        row += 1

        # Max total images (with proportional scaling)
        ttk.Label(main_frame, text="Max Total Images:").grid(row=row, column=0, sticky="w", pady=5)
        max_total_spinbox = ttk.Spinbox(main_frame, from_=10, to=200, textvariable=max_total_images_var, width=15)
        max_total_spinbox.grid(row=row, column=1, sticky="w", pady=5)

        def update_scaling():
            """Smart scaling when any value changes"""
            try:
                images_per = int(images_per_concept_var.get())
                max_concepts = int(max_concepts_var.get())
                max_scrolls = int(max_scrolls_var.get())

                # Calculate logical total: images_per * max_concepts * reasonable_multiplier
                # We assume each concept might need 1-3 images, so scale max_total accordingly
                calculated_total = images_per * max_concepts * 2  # *2 for some buffer

                # Only update if it's significantly different (avoid infinite loops)
                current_total = int(max_total_images_var.get())
                if abs(calculated_total - current_total) > 5:
                    max_total_images_var.set(max(10, min(200, calculated_total)))

            except (ValueError, TypeError):
                pass

        def on_any_change(*args):
            """Update scaling when any spinbox changes"""
            settings_window.after(300, update_scaling)  # Debounce

        # Connect all spinboxes to scaling logic
        images_per_concept_var.trace_add("write", on_any_change)
        max_concepts_var.trace_add("write", on_any_change)
        max_scrolls_var.trace_add("write", on_any_change)
        max_total_images_var.trace_add("write", on_any_change)
        row += 1

        # Max scrolls per keyword
        ttk.Label(main_frame, text="Max Scrolls per Keyword:").grid(row=row, column=0, sticky="w", pady=5)
        ttk.Spinbox(main_frame, from_=1, to=20, textvariable=max_scrolls_var, width=15).grid(row=row, column=1, sticky="w", pady=5)
        row += 1

        # Browser visibility (note: always background for image search)
        ttk.Label(main_frame, text="Browser Visibility:").grid(row=row, column=0, sticky="w", pady=5)
        ttk.Label(main_frame, text="Background (recommended)", font=("Arial", 8)).grid(row=row, column=1, sticky="w", pady=5)
        row += 1

        # Chrome profile directory with auto-detection
        ttk.Label(main_frame, text="Browser Profile:").grid(row=row, column=0, sticky="w", pady=5)
        profile_frame = ttk.Frame(main_frame)
        profile_frame.grid(row=row, column=1, sticky="we", pady=5)

        profile_entry = ttk.Entry(profile_frame, textvariable=chrome_profile_var, width=15)
        profile_entry.pack(side="left", fill="x", expand=True)

        def auto_detect_profile():
            """Auto-detect browser profile directories"""
            import os
            import platform

            system = platform.system()
            home = os.path.expanduser("~")

            possible_paths = []

            if system == "Linux":
                possible_paths = [
                    f"{home}/.config/google-chrome",
                    f"{home}/.config/chromium",
                    f"{home}/.mozilla/firefox",
                ]
            elif system == "Darwin":  # macOS
                possible_paths = [
                    f"{home}/Library/Application Support/Google/Chrome",
                    f"{home}/Library/Application Support/Chromium",
                    f"{home}/Library/Application Support/Firefox/Profiles",
                ]
            elif system == "Windows":
                possible_paths = [
                    f"{home}\\AppData\\Local\\Google\\Chrome\\User Data",
                    f"{home}\\AppData\\Local\\Chromium\\User Data",
                    f"{home}\\AppData\\Roaming\\Mozilla\\Firefox\\Profiles",
                ]

            # Check which paths exist
            existing_paths = [path for path in possible_paths if os.path.exists(path)]

            if existing_paths:
                # Use the first available path
                detected_path = existing_paths[0]
                chrome_profile_var.set(detected_path)
                # Save it to settings immediately
                self.settings["chrome_profile_dir"] = detected_path
                self._save_app_settings(self.settings)
                messagebox.showinfo("Auto-Detect", f"Found and saved profile: {detected_path}")
            else:
                messagebox.showwarning("Auto-Detect", "No browser profiles found automatically")

        ttk.Button(profile_frame, text="Auto", command=auto_detect_profile).pack(side="left", padx=(2,0))
        ttk.Button(profile_frame, text="Browse", command=lambda: self._browse_chrome_profile(chrome_profile_var)).pack(side="right")
        row += 1

        # SRT generation options
        ttk.Label(main_frame, text="SRT Generation:", font=("Arial", 10, "bold")).grid(row=row, column=0, columnspan=2, sticky="w", pady=(10,5))
        row += 1

        ttk.Checkbutton(main_frame, text="YouTube SRT Generation", variable=youtube_srt_var).grid(row=row, column=0, columnspan=2, sticky="w", pady=2)
        row += 1

        ttk.Checkbutton(main_frame, text="Other Platforms SRT Generation", variable=other_srt_var).grid(row=row, column=0, columnspan=2, sticky="w", pady=2)
        row += 1

        # Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=(20,0))

        def reset_settings():
            """Reset all settings to defaults"""
            # Reset variables to defaults
            whisper_var.set("base")
            images_per_concept_var.set(3)
            max_concepts_var.set(15)
            max_total_images_var.set(50)
            max_scrolls_var.set(6)
            chrome_profile_var.set("")
            youtube_srt_var.set(False)
            other_srt_var.set(False)

            # Update model status
            self._check_whisper_model_status(model_status_var)

        def save_settings():
            old_model = self.settings.get("whisper_model", "base")
            new_model = whisper_var.get()

            new_settings = {
                "whisper_model": new_model,
                "images_per_concept": images_per_concept_var.get(),
                "max_concepts_per_srt": max_concepts_var.get(),
                "max_total_images": max_total_images_var.get(),
                "max_scrolls_per_keyword": max_scrolls_var.get(),
                "use_visible_browser": False,  # Always background for image search
                "chrome_profile_dir": chrome_profile_var.get(),
                "srt_youtube_enabled": youtube_srt_var.get(),
                "srt_other_enabled": other_srt_var.get(),
            }
            self.settings.update(new_settings)
            self._save_app_settings(new_settings)

            self.settings_window = None
            settings_window.destroy()

            # Show message about model change
            if old_model != new_model:
                messagebox.showinfo("Settings", f"Settings saved! Whisper model changed from {old_model} to {new_model}.\nModel will be used for new SRT generations.")
            else:
                messagebox.showinfo("Settings", "Settings saved successfully!")

        ttk.Button(btn_frame, text="Save", command=save_settings).pack(side="left", padx=(0, 10))
        ttk.Button(btn_frame, text="Reset", command=reset_settings).pack(side="left", padx=(0, 10))
        ttk.Button(btn_frame, text="Cancel", command=lambda: (setattr(self, 'settings_window', None), settings_window.destroy())).pack(side="left")

    def _check_whisper_model_status(self, status_var):
        """Check if the current whisper model is available"""
        try:
            import os
            model = self.settings.get("whisper_model", "base")
            cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "whisper")

            if os.path.exists(cache_dir):
                model_files = [f for f in os.listdir(cache_dir) if model in f and f.endswith(('.pt', '.bin'))]
                if model_files:
                    status_var.set("✅ Available")
                    return

            status_var.set("⚠️  Not downloaded")
        except:
            status_var.set("❓ Unknown")

    def _browse_chrome_profile(self, var):
        """Browse for Chrome profile directory"""
        dir_path = filedialog.askdirectory(title="Select Chrome Profile Directory")
        if dir_path:
            var.set(dir_path)

    def _open_output_dir(self):
        """Open output directory - opens the most recent job folder"""
        base_output_dir = self.output_dir_var.get()

        if not os.path.exists(base_output_dir):
            messagebox.showerror("Error", f"Directory does not exist: {base_output_dir}")
            return

        # Find the most recent job folder
        try:
            subdirs = [d for d in os.listdir(base_output_dir)
                      if os.path.isdir(os.path.join(base_output_dir, d))]
            if subdirs:
                # Sort by modification time (most recent first)
                subdirs.sort(key=lambda x: os.path.getmtime(os.path.join(base_output_dir, x)), reverse=True)
                most_recent_job = os.path.join(base_output_dir, subdirs[0])
                os.system(f'xdg-open "{most_recent_job}"')
            else:
                # No job folders, open base directory
                os.system(f'xdg-open "{base_output_dir}"')
        except Exception as e:
            # Fallback to base directory
            os.system(f'xdg-open "{base_output_dir}"')


if __name__ == "__main__":
    app = UnifiedApp()
    app.mainloop()
