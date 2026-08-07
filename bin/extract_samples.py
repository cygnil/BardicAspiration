#!/usr/bin/env python3

import argparse
import json
import os
import sys
import pydub

def extract_samples(campaign_name, session_num, min_sample_length=10000, min_confidence=0.85):
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
        
        confidence = seg.get("transcription_metrics", {}).get("confidence", 1.0)
        if confidence < min_confidence:
            continue
            
        start_ms = int(seg.get("transcription_metrics", {}).get("start", 0.0) * 1000)
        end_ms = int(seg.get("transcription_metrics", {}).get("end", 0.0) * 1000)
        
        if spk not in speaker_segments:
            speaker_segments[spk] = []
        speaker_segments[spk].append(seg)
            
    if not speaker_segments:
        print("⚠️ No valid segments found for any speaker.")
        return
        
    samples_dir = os.path.join(target_dir, "samples")
    os.makedirs(samples_dir, exist_ok=True)
    
    for spk, segs in speaker_segments.items():
        # Score each segment based on clarity/ambient noise difference
        def score_segment(s):
            clarity = s.get("transcription_metrics", {}).get("clarity", 0.0)
            ambient = s.get("transcription_metrics", {}).get("ambient", 0.0)
            
            # calculate difference
            diff = clarity - ambient
            return diff

        segs.sort(key=score_segment, reverse=True)
        
        selected_segs = []
        total_duration = 0
        
        for s in segs:
            start_ms = int(s.get("transcription_metrics", {}).get("start", 0.0) * 1000)
            end_ms = int(s.get("transcription_metrics", {}).get("end", 0.0) * 1000)
            dur = end_ms - start_ms
            
            selected_segs.append((start_ms, end_ms, score_segment(s), len(s.get("text", "").split())))
            total_duration += dur
            
            if total_duration >= min_sample_length:
                break
                
        out_clip_path = os.path.join(samples_dir, f"{spk}.mp3")
        
        print(f"   => Exporting {spk} combined sample (Target: >= {min_sample_length}ms, Actual: {total_duration}ms)")
        
        combined_clip = pydub.AudioSegment.empty()
        for i, (start_ms, end_ms, score, words) in enumerate(selected_segs):
            clarity_diff = score
            print(f"      Part {i+1}: {start_ms}ms to {end_ms}ms | Clarity Diff: {clarity_diff:.2f} | Words: {words}")
            combined_clip += master_audio[start_ms:end_ms]
            
        combined_clip.export(out_clip_path, format="mp3", bitrate="128k")
        
    print("🎉 Extraction complete!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract optimal audio samples per speaker using clarity scores.")
    parser.add_argument("campaign", help="Name of the campaign")
    parser.add_argument("session", type=int, help="Session number")
    parser.add_argument("-l", "--length", type=int, default=10000, help="Minimum sample length in milliseconds (default: 10000)")
    parser.add_argument("-c", "--confidence", type=float, default=0.85, help="Minimum speech confidence score (0-1.0)")
    from utils import apply_defaults
    apply_defaults(parser, 'extract_samples.py')
    args = parser.parse_args()
    
    extract_samples(args.campaign, args.session, args.length, args.confidence)