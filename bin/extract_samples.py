#!/usr/bin/env python3

import argparse
import json
import os
import sys
import pydub

def extract_samples(campaign_name, session_num, min_sample_length=3000, min_confidence=0.85):
    session_str = f"{str(session_num).zfill(3)}"
    target_dir = os.path.join("campaigns", campaign_name, "sessions", session_str)
    transcript_path = os.path.join(target_dir, "transcript.json")
    
    if not os.path.exists(transcript_path):
        print(f"❌ Error: Transcript not found at {transcript_path}")
        sys.exit(1)
        
    with open(transcript_path, "r", encoding="utf-8") as f:
        session_manifest = json.load(f)
        
    processed_transcript = session_manifest.get("transcript", [])
    input_path = session_manifest.get("session_file")
    
    if not input_path or not os.path.exists(input_path):
        print(f"❌ Error: Master audio file not found at {input_path}")
        sys.exit(1)
        
    print(f"⚡ Loading master audio: {input_path}")
    master_audio = pydub.AudioSegment.from_file(input_path)
    
    print("⚡ Extracting optimal speaker reference samples...")
    speaker_segments = {}
    for seg in processed_transcript:
        spk = seg.get("speaker", "UNKNOWN_SPEAKER")
        if spk == "UNKNOWN_SPEAKER": continue
        
        confidence = seg.get("confidence", 1.0)
        if confidence < min_confidence:
            continue
            
        start_ms = int(seg.get("start", 0.0) * 1000)
        end_ms = int(seg.get("end", 0.0) * 1000)
        
        if (end_ms - start_ms) > min_sample_length:
            if spk not in speaker_segments:
                speaker_segments[spk] = []
            speaker_segments[spk].append(seg)
            
    if not speaker_segments:
        print("⚠️ No valid segments found for any speaker.")
        return
        
    samples_dir = os.path.join(target_dir, "samples")
    os.makedirs(samples_dir, exist_ok=True)
    
    for spk, segs in speaker_segments.items():
        # Score each segment based on both clarity and word count
        # Combining them allows us to prioritize high clarity but heavily penalize segments that are mostly silence with one word/laugh
        def score_segment(s):
            text = s.get("text", "").strip()
            word_count = len(text.split())
            clarity = s.get("clarity", 0.0)
            
            # If there's barely any words, heavily penalize. Otherwise, scale clarity by word count loosely
            if word_count < 3:
                return clarity * 0.1
            return clarity * min(word_count, 15) # Cap multiplier so huge rambles don't strictly beat cleaner mid-length clips

        best_seg = max(segs, key=score_segment)
        
        start_ms = int(best_seg.get("start", 0.0) * 1000)
        end_ms = int(best_seg.get("end", 0.0) * 1000)
        clarity = best_seg.get("clarity", 0.0)

        out_clip_path = os.path.join(samples_dir, f"{spk}.mp3")
        score = score_segment(best_seg)
        print(f"   => Exporting {spk} sample ({start_ms}ms to {end_ms}ms) | Clarity: {clarity} | Score: {score:.2f} | Words: {len(best_seg.get('text', '').split())}")
        clip = master_audio[start_ms:end_ms]
        clip.export(out_clip_path, format="mp3", bitrate="128k")
        
    print("🎉 Extraction complete!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract optimal audio samples per speaker using clarity scores.")
    parser.add_argument("campaign", help="Name of the campaign")
    parser.add_argument("session", type=int, help="Session number")
    parser.add_argument("-l", "--length", type=int, default=3000, help="Minimum sample length in milliseconds (default: 3000)")
    parser.add_argument("-c", "--confidence", type=float, default=0.85, help="Minimum speech confidence score (0-1.0)")
    from utils import apply_defaults
    apply_defaults(parser, 'extract_samples.py')
    args = parser.parse_args()
    
    extract_samples(args.campaign, args.session, args.length, args.confidence)