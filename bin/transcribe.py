from utils import animate_spinner
import argparse
import json
import os
import sys
import time
import threading
import torch
import numpy as np
import whisperx
from whisperx.diarize import DiarizationPipeline
from transformers import pipeline
from tqdm import tqdm
from openai import OpenAI
import subprocess

SAMPLE_LENGTH = 3000  # Minimum sample length in milliseconds

print("⚡ Script initializing...")

# --- NETWORK RESILIENCE: WINDOWS HOST LOOKUP ---
def get_wsl_host_ip():
    try:
        cmd = "ip route | grep default | awk '{print $3}'"
        host_ip = subprocess.check_output(cmd, shell=True).decode().strip()
        return host_ip if host_ip else "127.0.0.1"
    except Exception:
        return "127.0.0.1"

WINDOWS_HOST_IP = get_wsl_host_ip()

def get_api_client(api_url=None, api_key=None):
    from urllib.parse import urlparse
    if api_url:
        print(f"⚡ Connected to Remote API Host at: {api_url}")
        if not api_key:
            secrets = load_secrets()
            domain = urlparse(api_url).hostname
            if domain:
                api_key = secrets.get("API_KEYS", {}).get(domain)
        return OpenAI(base_url=api_url, api_key=api_key if api_key else "dummy_key")
    else:
        print(f"⚡ Connected to Windows Ollama Host at: http://{WINDOWS_HOST_IP}:11434")
        return OpenAI(base_url=f"http://{WINDOWS_HOST_IP}:11434/v1", api_key=api_key if api_key else "ollama")

# --- CONFIGURATION & SECRET EXTRACTOR ---
def load_secrets():
    try:
        with open("secrets.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print("⚠️ Error: 'secrets.json' missing. Please create it with your HF_TOKEN.")
        sys.exit(1)

def load_campaign_registry(campaign_dir):
    registry_path=os.path.join(campaign_dir, "campaign_registry.json")
    if os.path.exists(registry_path):
        with open(registry_path, "r", encoding="utf-8") as f:
            return json.load(f)
    print(f"⚡ Notice: 'campaign_registry.json' not found in {campaign_dir}. Running with clean defaults.")
    return {"campaign_name": "Unknown Campaign", "entities": []}

print("⚡ Loading local configuration assets...")
secrets = load_secrets()
HF_TOKEN = secrets.get("HF_TOKEN")
HOTWORDS = "[laughing], (laughing), [laughter], hahaha, hehehe"
# Attempt to identify cheering
HOTWORDS += ", [cheers], (cheering), [applause], woohoo, yay"
# Attempt to identify yelling
HOTWORDS += ", [yells], (yelling), [shouts], hey!"

def get_audio_duration(audio_array):
    """Calculates the duration of the whisperx audio array (sampled at 16000Hz)."""
    # whisperx.load_audio resamples to 16000Hz by default, shape is (samples,)
    # duration in seconds = number of samples / sample rate
    return len(audio_array) / 16000.0

def transcribe_and_align(audio_path, device, compute_type, model, alignment_model, metadata, db_threshold=-45.0):
    print(f"⚡ Audio engine reading track target: {audio_path}")
    audio = whisperx.load_audio(audio_path)
    audio_duration_sec = get_audio_duration(audio)
    
    if db_threshold is not None:
        print(f"⚡ Applying noise gating (Silence detection below {db_threshold} dB)...")
        # Calculate RMS amplitude
        rms = np.abs(audio)
        # Avoid log10(0)
        rms = np.maximum(rms, 1e-10)
        # Convert to dB relative to max possible amplitude (assuming float32 audio [-1.0, 1.0])
        db = 20 * np.log10(rms)
        # Zero out audio below threshold
        audio[db < db_threshold] = 0.0
    
    print("⚠️ Step 1/2: Processing deep voice transcription arrays...")
    result = model.transcribe(audio, batch_size=4, language="en")
    
    print("⚡ Step 2/2: Aligning phonemes for sub-second precision...")
    aligned_result = whisperx.align(
        result["segments"], alignment_model, metadata, audio, device, return_char_alignments=False
    )
    return aligned_result["segments"], audio_duration_sec


def process_pipeline(input_path, campaign_name, session_num, db_threshold=-45.0, force_overwrite=False, extra_info=None):
    total_start_time = time.time()
    
    # Establish directory structures
    campaign_dir = os.path.join("campaigns", campaign_name)
    session_str = f"{str(session_num).zfill(3)}"
    target_dir = os.path.join(campaign_dir, "sessions", session_str)
    
    if os.path.exists(target_dir):
        if not force_overwrite:
            print(f"⚠️ Error: Target session directory '{target_dir}' already exists.")
            print("To overwrite, supply the --force flag.")
            sys.exit(1)
        else:
            print(f"⚡ Warning: Target session directory '{target_dir}' exists. Overwriting...")
    
    os.makedirs(target_dir, exist_ok=True)
    output_json_path = os.path.join(target_dir, "transcript.json")
    
    session_info_path = os.path.join(target_dir, "session_info.json")
    session_info = {
        "session_num": str(session_num),
        "original_audio_path": input_path
    }
    if extra_info:
        try:
            extra_data = json.loads(extra_info)
            session_info.update(extra_data)
        except Exception as e:
            pass
            
    with open(session_info_path, "w", encoding="utf-8") as f:
        json.dump(session_info, f, indent=4)
        
    # Load Campaign Registry
    REGISTRY = load_campaign_registry(campaign_dir)
    HOTWORDS = ", ".join([k for e in REGISTRY.get("entities", []) for k in e.get("keywords", [])])
    HOTWORDS += ", [laughs], (laughing), [laughter], hahaha, hehehe, [cheering], [yelling], [applause]"

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "int8_float16"
    raw_segments = []

    print(f"⚡ Engine active on [{device.upper()}] using {compute_type} precision.")

    
    # Needs whisper loaded FIRST!
    stop_model = threading.Event()
    spinner_thread = threading.Thread(target=animate_spinner, args=(stop_model, f"Loading WhisperX (large-v3) into {device.upper()} VRAM..."))
    spinner_thread.start()

    model = whisperx.load_model("large-v3", device, compute_type=compute_type, language="en")
    alignment_model, metadata = whisperx.load_align_model(language_code="en", device=device)

    stop_model.set()
    spinner_thread.join()
    print(f"⚠️ Models loaded.                                                          ")

    def is_valid_audio(file_path):
        """Attempts to load audio to determine if it's a valid media file."""
        if not os.path.isfile(file_path): return False
        try:
            # We use a fast try-catch, ffmpeg will complain if it can't read the header
            # rather than using whisperx.load_audio to load the entire array into memory just to check.
            import ffmpeg
            ffmpeg.probe(file_path)
            return True
        except Exception:
            return False

    if os.path.isdir(input_path):
        print(f"⚡ Scanning directory for valid media tracks...")
        audio_files = []
        for f in os.listdir(input_path):
            full_path = os.path.join(input_path, f)
            if is_valid_audio(full_path):
                audio_files.append(full_path)
        
        if not audio_files:
            print(f"❌ Error: No readable media files found in directory '{input_path}'.")
            sys.exit(1)
            
        print(f"⚡ Processing multi-track directory ({len(audio_files)} tracks)...")
        multi_track_start_time = time.time()
        for file_path in tqdm(audio_files, desc="Overall Transcription Progress", unit="track"):
            speaker_identity = os.path.splitext(os.path.basename(file_path))[0].upper()
            segments, audio_dur = transcribe_and_align(file_path, device, compute_type, model, alignment_model, metadata, db_threshold)
            
            # Record maximum duration across tracks
            session_info["length_seconds"] = max(session_info.get("length_seconds", 0), audio_dur)
            
            for seg in segments:
                raw_segments.append({
                    "start": seg.get("start", 0.0),
                    "end": seg.get("end", 0.0),
                    "speaker": speaker_identity,
                    "text": seg.get("text", "")
                })
        print(f"⚠️ Multi-track transcription complete. ({time.time() - multi_track_start_time:.2f}s)")
        raw_segments.sort(key=lambda x: x["start"])
        processed_transcript = raw_segments
    # ⚡ MODE B:
    elif os.path.isfile(input_path):
        import datetime
        from pydub import AudioSegment
        
        try:
            audio = whisperx.load_audio(input_path)
        except Exception as e:
            print(f"❌ Error: Failed to open media file '{input_path}'. It may be corrupted or an unsupported format.")
            print(f"   Details: {e}")
            sys.exit(1)
            
        audio_duration = len(audio) / 16000 # Sample rate is 16kHz
        formatted_duration = str(datetime.timedelta(seconds=int(audio_duration)))
        print(f"⚡ Audio loaded. Sequence duration: {formatted_duration}")
        print(f"⚡ Loading PyDub Master Audio Segment...")
        master_audio = AudioSegment.from_file(input_path)
        
        stop_transcribe = threading.Event()
        transcribe_start_time = time.time()
            
        spinner_thread = threading.Thread(target=animate_spinner, args=(stop_transcribe, "WhisperX transcribing and aligning master audio file..."))
        spinner_thread.start()
            
        segments, audio_dur = transcribe_and_align(input_path, device, compute_type, model, alignment_model, metadata, db_threshold)
        session_info["length_seconds"] = audio_dur
            
        stop_transcribe.set()
        spinner_thread.join()
        print(f"⚠️ Core transcription complete. ({time.time() - transcribe_start_time:.2f}s)                                     ")
            
        print("⚠️ Clearing transcription VRAM layers...")
        del model, alignment_model
        torch.cuda.empty_cache()
            
        stop_diarize = threading.Event()
        diarize_model_start_time = time.time()
        spinner_thread = threading.Thread(target=animate_spinner, args=(stop_diarize, "Running PyAnnote speaker diarization (Voice tracking)..."))
        spinner_thread.start()
            
        diarize_model = DiarizationPipeline(token=HF_TOKEN, device=device)
        audio_data = whisperx.load_audio(input_path)
        diarize_segments = diarize_model(audio_data)
            
        stop_diarize.set()
        spinner_thread.join()
        print(f"⚠️ Diarization complete. ({time.time() - diarize_model_start_time:.2f}s)")
            
        print("⚡ Correlating vocal tracks to script layers...")
        dummy_result = {"segments": segments}
        final_result = whisperx.assign_word_speakers(diarize_segments, dummy_result)
            
        processed_transcript = []
        for seg in final_result["segments"]:
            processed_transcript.append({
                "start": round(seg.get("start", 0.0), 2),
                "end": round(seg.get("end", 0.0), 2),
                "speaker": seg.get("speaker", "UNKNOWN_SPEAKER"),
                "text": seg.get("text", "").strip()
            })


        found_speakers=set()
        for seg in processed_transcript:
            spk=seg.get("speaker", "UNKNOWN_SPEAKER")
            if spk in found_speakers or spk == "UNKNOWN_SPEAKER":
                continue

            start_ms=int(seg.get("start", 0.0) * 1000)
            end_ms=int(seg.get("end", 0.0) * 1000)

            # We want at least a ~2.0 second clip to make it identifiable
            if (end_ms - start_ms) > SAMPLE_LENGTH:
                samples_dir = os.path.join(target_dir, "samples")
                os.makedirs(samples_dir, exist_ok=True)
                out_clip_path = os.path.join(samples_dir, f"{spk}.mp3")
                print(f"   => Exporting {spk} sample ({start_ms}ms to {end_ms}ms)")
                clip = master_audio[start_ms:end_ms]
                clip.export(out_clip_path, format="mp3", bitrate="128k")
                found_speakers.add(spk)


    session_manifest={
        "session_file": os.path.abspath(input_path),
        "session_number": session_num,
        "speaker_identities": {},
        "campaign_metadata": {
            "campaign_name": REGISTRY.get("campaign_name", "Unknown Campaign"),
            "players": REGISTRY.get("players", []),
            "reference_lexicon": REGISTRY.get("entities", [])
        },
        "transcript": processed_transcript
    }

    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(session_manifest, f, indent=4, ensure_ascii=False)

    # Finally, write the updated session_info to preserve length
    with open(session_info_path, "w", encoding="utf-8") as f:
        json.dump(session_info, f, indent=4)

    total_runtime=time.time() - total_start_time
    print(f"⚡ Success! Data compiled natively into local path: {output_json_path}")
    print(f"⚡ Total script runtime: {total_runtime:.2f}s ({total_runtime / 60:.2f}m)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WhisperX Multi-track engine + Audio Slicer")
    parser.add_argument("input_path", help="Target .mp3 file or directory of stems.")
    parser.add_argument("campaign_name", help="Name of the campaign this sequence belongs to.")
    parser.add_argument("session_num", type=int, help="Chronological sequence ID of the session.")
    parser.add_argument("--db-threshold", type=float, default=-45.0, help="VAD noise floor threshold (default: -45.0).")
    parser.add_argument("--force", "-f", action="store_true", help="Bypass cached files and force execution.")
    parser.add_argument("--details", type=str)
    from utils import apply_defaults
    apply_defaults(parser, 'transcribe.py')
    args = parser.parse_args()
    process_pipeline(args.input_path, args.campaign_name, args.session_num, args.db_threshold, args.force, getattr(args, "details", None))