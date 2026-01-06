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
        """Extract visual concepts from SRT text using NLP pipeline"""
        self._load_model()

        # Clean SRT text (remove timestamps and indices)
        clean_text = self._clean_srt_text(srt_text)

        # Split into sentences
        sentences = [s.strip() for s in clean_text.split('.') if s.strip()]

        concepts = []
        seen_concepts = set()

        for sentence in sentences:
            if not sentence:
                continue

            # Score sentence for visual importance
            score = self._score_sentence_visual_importance(sentence)
            if score < 0.3:  # Skip low-importance sentences
                continue

            # Extract concepts from high-importance sentences
            sentence_concepts = self._extract_concepts_from_sentence(sentence)

            for concept in sentence_concepts:
                if concept not in seen_concepts and len(concept) > 2:
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
        from downloader import download_all

        job.progress = "Downloading video..."
        self._update_status(job)

        success, failed = download_all([job.url], job_dir, os.path.join(job_dir, "download.log"))
        if failed > 0:
            raise Exception(f"Failed to download video: {job.url}")

        # Find the downloaded video file
        for file in os.listdir(job_dir):
            if file.endswith(('.mp4', '.mkv', '.webm', '.mov')):
                return os.path.join(job_dir, file)

        raise Exception("No video file found after download")

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
        """Download images for concepts"""
        images_dir = os.path.join(job_dir, "images")
        ensure_dir(images_dir)

        total_images = 0
        for i, concept in enumerate(concepts):
            job.progress = f"Images: {concept} ({i+1}/{len(concepts)})"
            self._update_status(job)

            concept_dir = os.path.join(images_dir, safe_folder_name(concept))

            # Calculate images needed for this concept
            images_per_concept = max(1, self.settings["images_per_concept"])
            if total_images + images_per_concept > self.settings["max_total_images"]:
                images_per_concept = max(1, self.settings["max_total_images"] - total_images)

            if images_per_concept <= 0:
                break

            saved = await google_images_download(
                keyword=concept,
                out_dir=concept_dir,
                images_needed=images_per_concept,
                max_scrolls=self.settings["max_scrolls_per_keyword"],
                use_visible_browser=self.settings["use_visible_browser"],
                use_existing_profile=self.settings["use_existing_chrome_profile"],
                chrome_profile_dir=self.settings["chrome_profile_dir"],
                status_cb=None
            )

            total_images += saved

            if total_images >= self.settings["max_total_images"]:
                break


class UnifiedApp(tk.Tk):
    """Main application with job queue"""

    def __init__(self):
        super().__init__()
        self.title("Research & B-Roll Harvester")
        self.geometry("1200x800")

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

        # Bind Enter key
        self.bind("<Return>", lambda e: self._on_enter())

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
            with open("settings.json", "r") as f:
                loaded = json.load(f)
                defaults.update(loaded)
        except FileNotFoundError:
            pass

        return defaults

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

        # Job details panel (bottom of left)
        details_frame = ttk.LabelFrame(left_panel, text="Job Details", height=200)
        details_frame.pack(fill="x", pady=(10, 0))
        details_frame.pack_propagate(False)

        self.job_details_text = scrolledtext.ScrolledText(details_frame, height=8, wrap="word")
        self.job_details_text.pack(fill="both", expand=True)

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

        # URL input
        ttk.Label(input_frame, text="Video URL:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        self.url_var = tk.StringVar()
        ttk.Entry(input_frame, textvariable=self.url_var, width=60).grid(row=0, column=1, columnspan=2, padx=5, pady=2, sticky="we")

        # Platform selection
        ttk.Label(input_frame, text="Platform:").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        self.platform_var = tk.StringVar(value="tiktok")
        platform_combo = ttk.Combobox(input_frame, textvariable=self.platform_var,
                                    values=["tiktok", "youtube", "instagram", "other"], state="readonly")
        platform_combo.grid(row=1, column=1, padx=5, pady=2, sticky="w")

        # Topic input
        ttk.Label(input_frame, text="Topic:").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        self.topic_var = tk.StringVar()
        ttk.Entry(input_frame, textvariable=self.topic_var, width=40).grid(row=2, column=1, columnspan=2, padx=5, pady=2, sticky="we")

        # Notes
        ttk.Label(input_frame, text="Notes:").grid(row=3, column=0, sticky="nw", padx=5, pady=2)
        self.notes_text = tk.Text(input_frame, height=4, width=50)
        self.notes_text.grid(row=3, column=1, columnspan=2, padx=5, pady=2, sticky="we")

        # Buttons
        btn_frame = ttk.Frame(input_frame)
        btn_frame.grid(row=4, column=0, columnspan=3, pady=10)

        ttk.Button(btn_frame, text="Add Job (Enter)", command=self._add_job).pack(side="left", padx=(0, 10))
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

    def _on_enter(self):
        """Handle Enter key press"""
        self._add_job()

    def _add_job(self):
        """Add a new job to the queue"""
        url = self.url_var.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a video URL")
            return

        platform_str = self.platform_var.get()
        try:
            platform = Platform(platform_str)
        except ValueError:
            messagebox.showerror("Error", f"Invalid platform: {platform_str}")
            return

        topic = self.topic_var.get().strip()
        if not topic:
            # Auto-generate topic from URL
            topic = self._extract_topic_from_url(url)

        output_dir = self.output_dir_var.get().strip()
        if not output_dir:
            messagebox.showerror("Error", "Please select an output directory")
            return

        notes = self.notes_text.get("1.0", "end").strip()

        # Create job
        job = Job(
            id="",
            url=url,
            platform=platform,
            output_dir=output_dir,
            topic=topic,
            notes=notes
        )

        # Add to jobs dict and queue
        self.jobs[job.id] = job
        self.job_queue.put(job)

        # Update UI
        self._update_job_list()
        self._log_status(f"Added job: {job.topic} ({job.url})")

        # Clear input fields
        self.url_var.set("")
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
        """Handle job selection"""
        selection = self.job_listbox.curselection()
        if selection:
            index = selection[0]
            job_id = list(self.jobs.keys())[index]
            job = self.jobs[job_id]

            # Display job details
            details = f"""ID: {job.id}
URL: {job.url}
Platform: {job.platform.value}
Topic: {job.topic}
Status: {job.status.value}
Created: {job.created_at.strftime('%Y-%m-%d %H:%M:%S')}

Notes:
{job.notes}

Progress: {job.progress}
"""

            if job.error:
                details += f"\nError: {job.error}"

            self.job_details_text.delete("1.0", "end")
            self.job_details_text.insert("1.0", details)

    def _on_job_status_update(self, job: Job):
        """Handle job status updates"""
        self.after(0, lambda: self._update_job_list())
        self.after(0, lambda: self._log_status(f"Job {job.topic}: {job.status.value} - {job.progress}"))

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
        """Show settings dialog"""
        # This would open a settings window - simplified for now
        messagebox.showinfo("Settings", "Settings panel not implemented yet. Edit settings.json manually.")

    def _open_output_dir(self):
        """Open output directory"""
        output_dir = self.output_dir_var.get()
        if os.path.exists(output_dir):
            os.system(f'xdg-open "{output_dir}"')
        else:
            messagebox.showerror("Error", f"Directory does not exist: {output_dir}")


if __name__ == "__main__":
    app = UnifiedApp()
    app.mainloop()
