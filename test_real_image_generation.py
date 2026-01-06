#!/usr/bin/env python3
"""
Test real image generation from the user's SRT file
"""

import os
import asyncio
from unified_app import NLPConceptExtractor
from broll_core import google_images_download

async def test_real_image_generation():
    """Test the complete image generation pipeline"""

    print("🚀 Testing COMPLETE image generation pipeline...")

    # Use the user's SRT file
    srt_path = '/home/admin/Downloads/love__war__batch_2026-01-06_04-51-27/I_Built_a_Self_Landing_Satellite [7yVFZn87TkY].en.srt'
    output_dir = '/home/admin/Downloads/love__war__batch_2026-01-06_04-51-27'

    if not os.path.exists(srt_path):
        print(f"❌ SRT file not found: {srt_path}")
        return False

    # Read SRT
    with open(srt_path, 'r', encoding='utf-8') as f:
        srt_content = f.read()

    print(f"📄 Loaded SRT: {len(srt_content)} characters")

    # Extract concepts
    extractor = NLPConceptExtractor()
    concepts = extractor.extract_concepts(srt_content, max_concepts=5)  # Test with fewer concepts

    print(f"🧠 Extracted {len(concepts)} concepts: {concepts}")

    if not concepts:
        print("❌ No concepts extracted - pipeline would fail")
        return False

    # Create test output directory
    test_output = os.path.join(output_dir, "test_images")
    os.makedirs(test_output, exist_ok=True)

    print(f"📁 Test output directory: {test_output}")

    total_images = 0

    # Test image generation for first 2 concepts
    for i, concept in enumerate(concepts[:2]):
        print(f"🖼️  Testing concept {i+1}/2: '{concept}'")

        try:
            # Test Google search (background mode)
            saved = await google_images_download(
                keyword=concept,
                out_dir=test_output,
                images_needed=2,  # Just 2 images for testing
                max_scrolls=3,  # Fewer scrolls for testing
                use_visible_browser=False,
                use_existing_profile=False,
                chrome_profile_dir="",
                status_cb=lambda msg: print(f"    {msg}")
            )

            # If Google didn't get enough, try Wikipedia
            wiki_saved = 0
            if saved < 2:
                wiki_keyword = f"{concept} Wikipedia"
                print(f"    Trying Wikipedia: '{wiki_keyword}'")
                wiki_saved = await google_images_download(
                    keyword=wiki_keyword,
                    out_dir=test_output,
                    images_needed=2 - saved,
                    max_scrolls=3,
                    use_visible_browser=False,
                    use_existing_profile=False,
                    chrome_profile_dir="",
                    status_cb=lambda msg: print(f"      {msg}")
                )

            total_saved = saved + wiki_saved
            print(f"    ✅ Downloaded {total_saved} images for '{concept}' (Google: {saved}, Wiki: {wiki_saved})")
            total_images += total_saved

        except Exception as e:
            print(f"    ❌ Failed for '{concept}': {e}")

    # Check results
    print("\n📊 Results:")
    print(f"Total images downloaded: {total_images}")

    # List downloaded files
    if os.path.exists(test_output):
        files = os.listdir(test_output)
        image_files = [f for f in files if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
        print(f"Image files found: {len(image_files)}")

        if image_files:
            print("Sample files:")
            for img in image_files[:3]:
                print(f"  ✅ {img}")

        if len(image_files) >= 1:
            print("🎉 SUCCESS: Image generation pipeline works!")
            print(f"📸 Generated {len(image_files)} images - the system is functional!")
            return True
        else:
            print("❌ FAILURE: No images generated")
            return False
    else:
        print("❌ FAILURE: No output directory created")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_real_image_generation())
    print(f"\n🏁 Final Result: {'PASS' if success else 'FAIL'}")
    if not success:
        print("💀 Project status: Faded (failed)")
    else:
        print("🚀 Project status: Working!")
