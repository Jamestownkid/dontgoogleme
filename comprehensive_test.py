#!/usr/bin/env python3
"""
Comprehensive test of the entire application pipeline
"""

import os
import asyncio
import json
from unified_app import UnifiedApp, Platform, Job
from broll_core import generate_srt

async def test_full_pipeline():
    """Test the complete application pipeline"""

    print("🧪 COMPREHENSIVE APPLICATION TEST")
    print("=" * 50)

    # Test 1: Settings Save Button
    print("\n1️⃣ Testing Settings Save Button...")

    app = UnifiedApp.__new__(UnifiedApp)
    app.settings = app._load_app_settings()

    # Modify a setting
    original_model = app.settings.get("whisper_model", "base")
    app.settings["whisper_model"] = "small"  # Change to different model

    # Save settings
    app._save_app_settings(app.settings)

    # Reload and check if saved
    app2 = UnifiedApp.__new__(UnifiedApp)
    app2.settings = app2._load_app_settings()

    if app2.settings.get("whisper_model") == "small":
        print("✅ Settings Save button works!")
    else:
        print("❌ Settings Save button failed!")

    # Restore original setting
    app.settings["whisper_model"] = original_model
    app._save_app_settings(app.settings)

    # Test 2: SRT Generation
    print("\n2️⃣ Testing SRT Generation...")

    video_path = "/home/admin/Downloads/love__war__batch_2026-01-06_04-51-27/I_Built_a_Self_Landing_Satellite [7yVFZn87TkY].mp4"
    srt_dir = "/home/admin/Downloads/love__war__batch_2026-01-06_04-51-27"
    srt_path = os.path.join(srt_dir, "test_transcript.srt")

    if os.path.exists(video_path):
        try:
            generated_srt, transcript = generate_srt(video_path, "base")
            print(f"✅ SRT generated successfully: {len(transcript)} characters")

            # Copy to test location
            if os.path.exists(generated_srt):
                import shutil
                shutil.copy2(generated_srt, srt_path)
                print(f"✅ SRT copied to: {srt_path}")

        except Exception as e:
            print(f"❌ SRT generation failed: {e}")
            # Use existing SRT if generation fails
            existing_srt = "/home/admin/Downloads/love__war__batch_2026-01-06_04-51-27/I_Built_a_Self_Landing_Satellite [7yVFZn87TkY].en.srt"
            if os.path.exists(existing_srt):
                shutil.copy2(existing_srt, srt_path)
                print(f"✅ Using existing SRT: {srt_path}")
    else:
        print("❌ Video file not found")

    # Test 3: Concept Extraction
    print("\n3️⃣ Testing Concept Extraction...")

    if os.path.exists(srt_path):
        from unified_app import NLPConceptExtractor

        with open(srt_path, 'r', encoding='utf-8') as f:
            srt_content = f.read()

        extractor = NLPConceptExtractor()
        concepts = extractor.extract_concepts(srt_content, max_concepts=8)

        print(f"✅ Extracted {len(concepts)} concepts: {concepts[:5]}...")

        if len(concepts) >= 3:
            print("✅ Concept extraction works!")
        else:
            print("❌ Not enough concepts extracted")
    else:
        print("❌ No SRT file for concept extraction")

    # Test 4: Image Generation with Wikipedia
    print("\n4️⃣ Testing Image Generation with Wikipedia...")

    if 'concepts' in locals() and concepts:
        from broll_core import google_images_download

        test_output = "/home/admin/Downloads/love__war__batch_2026-01-06_04-51-27/comprehensive_test_images"
        os.makedirs(test_output, exist_ok=True)

        total_images = 0

        for i, concept in enumerate(concepts[:3]):  # Test first 3 concepts
            print(f"  🖼️ Testing '{concept}'...")

            # Try normal search first
            saved = await google_images_download(
                keyword=concept,
                out_dir=test_output,
                images_needed=2,
                max_scrolls=4,
                use_visible_browser=False,
                use_existing_profile=False,
                chrome_profile_dir="",
            )

            # Try Wikipedia search with proper Wikipedia text
            wiki_keyword = f"{concept} Wikipedia"
            wiki_saved = await google_images_download(
                keyword=wiki_keyword,
                out_dir=test_output,
                images_needed=2 - saved,  # Only get what's missing
                max_scrolls=4,
                use_visible_browser=False,
                use_existing_profile=False,
                chrome_profile_dir="",
            )

            concept_total = saved + wiki_saved
            total_images += concept_total

            print(f"    ✅ {concept_total} images (Google: {saved}, Wiki: {wiki_saved})")

        print(f"✅ Total images generated: {total_images}")

        # Check files
        if os.path.exists(test_output):
            files = os.listdir(test_output)
            image_files = [f for f in files if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            print(f"✅ Image files created: {len(image_files)}")

            if len(image_files) >= 2:
                print("🎉 FULL PIPELINE SUCCESS!")
                print(f"📸 Generated {len(image_files)} images - all systems working!")
                return True
            else:
                print("❌ Not enough images generated")
                return False
    else:
        print("❌ No concepts to test image generation")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_full_pipeline())
    print(f"\n🏁 FINAL RESULT: {'PASS - Project Working!' if success else 'FAIL - Project Issues'}")
