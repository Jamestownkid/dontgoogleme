#!/usr/bin/env python3
"""
Test SRT generation with Whisper base model
"""

import os
from broll_core import generate_srt

def test_whisper_base():
    print("🎤 Testing SRT generation with Whisper 'base' model...")

    # Use the existing video file
    video_path = "/home/admin/Downloads/love__war__batch_2026-01-06_04-51-27/I_Built_a_Self_Landing_Satellite [7yVFZn87TkY].mp4"

    if not os.path.exists(video_path):
        print(f"❌ Video file not found: {video_path}")
        return False

    print(f"📹 Found video: {os.path.basename(video_path)}")

    try:
        print("⏳ Generating SRT with Whisper 'base' model...")
        print("   (This may take a minute...)")

        srt_path, transcript = generate_srt(video_path, "base")

        print("✅ SRT generation completed!")
        print(f"📄 Transcript length: {len(transcript)} characters")
        print(f"💾 SRT file saved to: {srt_path}")

        # Check if SRT file exists and has content
        if os.path.exists(srt_path):
            with open(srt_path, 'r', encoding='utf-8') as f:
                srt_content = f.read()

            lines = srt_content.strip().split('\n')
            print(f"📝 SRT file has {len(lines)} lines")

            if len(lines) > 10:  # Should have timestamps and text
                print("✅ SRT file looks valid")
                print("\n📋 Sample SRT content:")
                sample_lines = lines[:10]  # First 10 lines
                for line in sample_lines:
                    print(f"   {line}")
                print("   ...")
                return True
            else:
                print("❌ SRT file seems too short")
                return False
        else:
            print("❌ SRT file was not created")
            return False

    except Exception as e:
        print(f"❌ SRT generation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_whisper_base()
    print(f"\n🏁 Whisper Base Test: {'PASS ✅' if success else 'FAIL ❌'}")

    if success:
        print("\n🎯 SRT generation with Whisper 'base' works perfectly!")
        print("📦 The app can generate SRT from videos using the base model.")
    else:
        print("\n💥 SRT generation with Whisper 'base' is not working.")
