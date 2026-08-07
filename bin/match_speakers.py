#!/usr/bin/env python3

import argparse
import json
import os
import sys
import time
import torch
import numpy as np

# Try strict importing to ensure environment has what we need
try:
    from pyannote.audio import Model, Inference
except ImportError:
    print("❌ Error: pyannote.audio not found. Check virtual environment.")
    sys.exit(1)

def load_secrets():
    try:
        with open("secrets.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def run_matching(campaign, session_num, threshold=0.55):
    start_time = time.time()
    
    campaign_dir = os.path.join("campaigns", campaign)
    session_str = f"{str(session_num).zfill(3)}"
    target_dir = os.path.join(campaign_dir, "sessions", session_str)
    samples_dir = os.path.join(target_dir, "samples")
    ref_dir = os.path.join(campaign_dir, "reference_audio")
    
    transcript_path = os.path.join(target_dir, "transcript.json")
    annotated_path = os.path.join(target_dir, "transcript_annotated.json")
    
    if not os.path.exists(ref_dir) or not os.listdir(ref_dir):
        print(f"⚠️ Notice: No reference audio found in {ref_dir}. Skipping automated biometric matching.")
        return

    if not os.path.exists(samples_dir) or not os.listdir(samples_dir):
        print(f"⚠️ Notice: No speaker samples found in {samples_dir}. Run extract_samples first.")
        return

    if not os.path.exists(transcript_path):
        print("❌ Error: Main transcript.json not found for mapping.")
        sys.exit(1)

    secrets = load_secrets()
    hf_token = secrets.get("HF_TOKEN")
    if not hf_token or hf_token == "PASTE_YOUR_HUGGINGFACE_TOKEN_HERE":
        print("❌ Error: Valid HF_TOKEN required for PyAnnote embedding model in secrets.json")
        sys.exit(1)

    print("🧠 [Voice Biometrics] Loading PyAnnote Embedding Model...")
    try:
        # Standard voice embedding model that ships with modern PyAnnote (used in diarization)
        model = Model.from_pretrained("pyannote/wespeaker-voxceleb-resnet34-LM", use_auth_token=hf_token)
        if model is None:
            # Fallback
            model = Model.from_pretrained("pyannote/embedding", use_auth_token=hf_token)
        inference = Inference(model, window="whole")
    except Exception as e:
        print(f"❌ Error loading pyannote embedding model: {e}")
        print("Ensure your HF_TOKEN has accepted the user agreements for PyAnnote models on HuggingFace.")
        sys.exit(1)

    # Compute reference embeddings
    ref_embeddings = {}
    print("⚡ Extracting vocal fingerprints from reference audio...")
    for ref_file in os.listdir(ref_dir):
        if ref_file.endswith(".mp3") or ref_file.endswith(".wav") or ref_file.endswith(".m4a"):
            player_name = os.path.splitext(ref_file)[0]
            path = os.path.join(ref_dir, ref_file)
            try:
                emb = inference(path)
                if isinstance(emb, np.ndarray):
                    emb = torch.tensor(emb)
                if emb.ndim > 1:
                     emb = emb.mean(dim=0)
                ref_embeddings[player_name] = emb
            except Exception as e:
                print(f"  ⚠️ Warning: Could not process reference {ref_file} ({e})")

    if not ref_embeddings:
         print("⚠️ Notice: No valid reference embeddings extracted. Skipping.")
         return

    # Open manifest
    with open(transcript_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
        
    speaker_identities = manifest.get("speaker_identities", {})
    
    print("⚡ Correlating unknown session speakers via Cosine Similarity...")
    matched_count = 0
    for sample_file in os.listdir(samples_dir):
        if not sample_file.endswith(".mp3"): continue
        
        speaker_id = os.path.splitext(sample_file)[0]
        if speaker_id in speaker_identities and speaker_identities[speaker_id] != speaker_id:
            # Already mapped
            continue
            
        path = os.path.join(samples_dir, sample_file)
        try:
            emb = inference(path)
            if isinstance(emb, np.ndarray):
                emb = torch.tensor(emb)
            if emb.ndim > 1:
                emb = emb.mean(dim=0)
                
            best_match = None
            best_score = -1.0
            
            for r_name, r_emb in ref_embeddings.items():
                sim = torch.nn.functional.cosine_similarity(emb.unsqueeze(0), r_emb.unsqueeze(0)).item()
                if sim > best_score:
                    best_score = sim
                    best_match = r_name
            
            # Match based on parameterized threshold
            if best_score >= threshold:
                print(f"  ✅ {speaker_id}  ->  {best_match} (Match Confidence: {best_score:.2f})")
                speaker_identities[speaker_id] = best_match
                matched_count += 1
            else:
                print(f"  ❌ {speaker_id}  ->  Unknown (Highest: {best_match} at {best_score:.2f}, failed threshold)")
                
        except Exception as e:
            print(f"  ⚠️ Could not process sample {sample_file} ({e})")

    # Save to disk
    manifest["speaker_identities"] = speaker_identities
    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=4, ensure_ascii=False)
        
    with open(annotated_path, "w", encoding="utf-8") as f:
         json.dump(manifest, f, indent=4, ensure_ascii=False)

    print(f"========================================================")
    print(f"🎙️ BIOMETRIC ASSIGNMENT COMPLETE ({time.time() - start_time:.2f}s)")
    print(f"Mapped {matched_count} identities automatically.")
    print(f"========================================================")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Match extracted samples to reference audio using voice biometrics.")
    parser.add_argument("campaign", help="Campaign name")
    parser.add_argument("session", type=int, help="Session number")
    parser.add_argument("-t", "--threshold", type=float, default=0.55, help="Match confidence threshold (default: 0.55)")
    from utils import apply_defaults
    apply_defaults(parser, 'match_speakers.py')
    args = parser.parse_args()
    
    run_matching(args.campaign, args.session, args.threshold)