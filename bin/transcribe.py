#!/usr/bin/env python3

from utils import animate_spinner
import argparse
import difflib
import gc
import hashlib
import json
import math
import os
import sys
import time
import threading
import torch
import numpy as np
import whisperx
import yt_dlp
from whisperx.diarize import DiarizationPipeline
from transformers import pipeline
from tqdm import tqdm
from openai import OpenAI
import subprocess

SAMPLE_LENGTH = 3000  # Minimum sample length in milliseconds

print("⚡ Script initializing...")

# --- NETWORK RESILIENCE: HOST LOOKUP ---
def get_wsl_host_ip():
    try:
        cmd = "ip route | grep default | awk '{print $3}'"
        host_ip = subprocess.check_output(cmd, shell=True).decode().strip()
        return host_ip if host_ip else "127.0.0.1"
    except Exception:
        return "127.0.0.1"

LOCAL_HOST_IP = get_wsl_host_ip()

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
        print(f"⚡ Connected to Local Host at: http://{LOCAL_HOST_IP}:11434")
        return OpenAI(base_url=f"http://{LOCAL_HOST_IP}:11434/v1", api_key=api_key if api_key else "local")

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

def clear_gpu_memory():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def is_out_of_memory(error):
    message = str(error).lower()
    return isinstance(error, torch.cuda.OutOfMemoryError) or (
        "out of memory" in message or "cuda_error_out_of_memory" in message
    )


def transcribe_with_retry(model, audio, batch_size):
    while True:
        try:
            return model.transcribe(audio, batch_size=batch_size, language="en")
        except RuntimeError as error:
            if not is_out_of_memory(error):
                raise
            if batch_size == 1:
                raise RuntimeError(
                    "Transcription ran out of memory at batch size 1. "
                    "Resume with --resume --device cpu, or use a smaller --model."
                ) from error
        batch_size = max(1, batch_size // 2)
        clear_gpu_memory()
        print(f"GPU memory exhausted; retrying window with batch size {batch_size}.")


def load_transcription_model(model_name, device, compute_type, initial_prompt):
    options = {"initial_prompt": initial_prompt, "beam_size": 5, "best_of": 5}
    try:
        model = whisperx.load_model(
            model_name, device, compute_type=compute_type, language="en", asr_options=options,
        )
        return model, device, compute_type
    except RuntimeError as error:
        if device != "cuda" or not is_out_of_memory(error):
            raise
    clear_gpu_memory()
    print("Whisper model exhausted GPU memory while loading; falling back to CPU.")
    model = whisperx.load_model(
        model_name, "cpu", compute_type="int8", language="en", asr_options=options,
    )
    return model, "cpu", "int8"


def load_audio_window(audio_path, start, duration, db_threshold):
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(start), "-i", audio_path,
         "-t", str(duration), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
        capture_output=True, check=True,
    )
    audio = np.frombuffer(result.stdout, dtype="<f4").copy()
    db = 20 * np.log10(np.maximum(np.abs(audio), 1e-10))
    if db_threshold is not None:
        audio[db < db_threshold] = 0.0
    return audio, db


def save_checkpoint(path, data):
    temporary_path = path + ".tmp"
    with open(temporary_path, "w", encoding="utf-8") as checkpoint:
        json.dump(data, checkpoint, ensure_ascii=False)
    os.replace(temporary_path, path)


def merge_window_segments(segments, offset, core_start, core_end, db):
    merged = []
    for segment in segments:
        segment = dict(segment)
        words = [dict(word) for word in segment.get("words", [])]
        retained_words = []
        for word in words:
            midpoint = (word.get("start", segment["start"]) + word.get("end", segment["end"])) / 2
            if core_start <= offset + midpoint < core_end:
                for key in ("start", "end"):
                    if key in word:
                        word[key] = round(word[key] + offset, 3)
                retained_words.append(word)
        if words:
            if not retained_words:
                continue
            if len(retained_words) != len(words):
                segment["text"] = " ".join(word["word"] for word in retained_words)
            segment["start"] = retained_words[0].get("start", offset + segment["start"])
            segment["end"] = retained_words[-1].get("end", offset + segment["end"])
            segment["words"] = retained_words
        else:
            midpoint = offset + (segment["start"] + segment["end"]) / 2
            if not core_start <= midpoint < core_end:
                continue
            segment["start"] += offset
            segment["end"] += offset
        start_sample = max(0, int((segment["start"] - offset) * 16000))
        end_sample = min(len(db), int((segment["end"] - offset) * 16000))
        values = db[start_sample:end_sample]
        peak_db = float(np.percentile(values, 95)) if len(values) else -100.0
        clarity = peak_db - float(np.median(values)) if len(values) else 0.0
        segment["db"] = round(peak_db, 2)
        segment["clarity"] = round(clarity, 2)
        merged.append(segment)
    return merged


def transcribe_and_align(audio_path, device, compute_type, checkpoint_dir,
                         db_threshold=-45.0, initial_prompt=None, batch_size=1,
                         model_name="large-v3", window_seconds=300, resume=False):
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", audio_path],
        capture_output=True, check=True, text=True,
    )
    duration = float(json.loads(probe.stdout)["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"Invalid audio duration for {audio_path}: {duration}")
    source = os.stat(audio_path)
    identity = [1, os.path.abspath(audio_path), source.st_size, source.st_mtime_ns,
                db_threshold, initial_prompt, model_name, window_seconds]
    cache_key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    track_dir = os.path.join(checkpoint_dir, cache_key)
    os.makedirs(track_dir, exist_ok=True)
    windows = []
    for index in range(math.ceil(duration / window_seconds)):
        core_start = index * window_seconds
        core_end = min(duration, core_start + window_seconds)
        start = max(0, core_start - 2)
        end = min(duration, core_end + 2)
        windows.append((index, start, end - start, core_start, core_end))
        if not resume:
            for stage in ("asr", "aligned"):
                previous = os.path.join(track_dir, f"{index:05d}.{stage}.json")
                if os.path.exists(previous):
                    os.remove(previous)

    def cache_path(index, stage):
        return os.path.join(track_dir, f"{index:05d}.{stage}.json")

    def cached(index, stage):
        path = cache_path(index, stage)
        if not resume or not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as checkpoint:
                return json.load(checkpoint)
        except (OSError, ValueError):
            return None

    model = None
    try:
        for index, start, length, core_start, core_end in windows:
            if cached(index, "aligned") is not None or cached(index, "asr") is not None:
                continue
            if model is None:
                print(f"Loading {model_name} on {device} ({compute_type}).")
                model, device, compute_type = load_transcription_model(
                    model_name, device, compute_type, initial_prompt,
                )
            print(f"Transcribing window {index + 1}/{len(windows)}: {audio_path}")
            audio, db = load_audio_window(audio_path, start, length, db_threshold)
            try:
                result = transcribe_with_retry(model, audio, batch_size)
            except RuntimeError as error:
                if device != "cuda" or not is_out_of_memory(error):
                    raise
                result = None
            if result is None:
                print("Transcription exhausted GPU memory at batch size 1; retrying on CPU.")
                model = None
                clear_gpu_memory()
                device, compute_type = "cpu", "int8"
                model, device, compute_type = load_transcription_model(
                    model_name, device, compute_type, initial_prompt,
                )
                result = transcribe_with_retry(model, audio, 1)
            save_checkpoint(cache_path(index, "asr"), result["segments"])
            del audio, db, result
    finally:
        del model
        clear_gpu_memory()

    alignment_model = None
    segments = []
    try:
        for index, start, length, core_start, core_end in windows:
            aligned = cached(index, "aligned")
            if aligned is not None:
                print(f"Resuming aligned window {index + 1}/{len(windows)}.")
                segments.extend(aligned)
                continue
            with open(cache_path(index, "asr"), "r", encoding="utf-8") as checkpoint:
                transcript = json.load(checkpoint)
            if not transcript:
                save_checkpoint(cache_path(index, "aligned"), [])
                continue
            if alignment_model is None:
                try:
                    alignment_model, metadata = whisperx.load_align_model(language_code="en", device=device)
                except RuntimeError as error:
                    if device != "cuda" or not is_out_of_memory(error):
                        raise
                if alignment_model is None:
                    print("Alignment model exhausted GPU memory while loading; falling back to CPU.")
                    clear_gpu_memory()
                    device = "cpu"
                    alignment_model, metadata = whisperx.load_align_model(language_code="en", device=device)
            print(f"Aligning window {index + 1}/{len(windows)}: {audio_path}")
            audio, db = load_audio_window(audio_path, start, length, db_threshold)
            try:
                result = whisperx.align(
                    transcript, alignment_model, metadata, audio, device, return_char_alignments=False,
                )
            except RuntimeError as error:
                if device != "cuda" or not is_out_of_memory(error):
                    raise
                result = None
            if result is None:
                print("Alignment exhausted GPU memory; retrying on CPU.")
                alignment_model = alignment_model.to("cpu")
                device = "cpu"
                clear_gpu_memory()
                result = whisperx.align(
                    transcript, alignment_model, metadata, audio, device, return_char_alignments=False,
                )
            aligned = merge_window_segments(result["segments"], start, core_start, core_end, db)
            save_checkpoint(cache_path(index, "aligned"), aligned)
            segments.extend(aligned)
            del audio, db, result
    finally:
        del alignment_model
        clear_gpu_memory()
    return segments, duration


def process_pipeline(input_path, campaign_name, session_num, db_threshold=-45.0, force_overwrite=False, extra_info=None, dedup=False,
                     batch_size=1, compute_type=None, model_name="large-v3", window_seconds=300, resume=False, device=None):
    if batch_size < 1 or not math.isfinite(window_seconds) or window_seconds <= 4:
        raise ValueError("batch_size must be positive and window_seconds must be greater than 4.")
    total_start_time = time.time()
    
    # Establish directory structures (Validation already handled at script entry)
    campaign_dir = os.path.join("campaigns", campaign_name)
    session_str = f"{str(session_num).zfill(3)}"
    target_dir = os.path.join(campaign_dir, "sessions", session_str)
    
    if os.path.exists(target_dir):
        if force_overwrite:
            print(f"⚡ Warning: Target session directory '{target_dir}' exists. Overwriting...")
    
    os.makedirs(target_dir, exist_ok=True)
    output_json_path = os.path.join(target_dir, "transcript.json")
    
    session_info_path = os.path.join(target_dir, "session_info.json")
    
    session_info = {}
    if os.path.exists(session_info_path):
        try:
            with open(session_info_path, "r", encoding="utf-8") as f:
                session_info = json.load(f)
        except Exception:
            pass
            
    session_info["session_num"] = str(session_num)
    session_info["original_audio_path"] = input_path

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

    # Ensure the input files are accessible and valid before spending time loading whisper
    def is_valid_audio(file_path):
        """Attempts to load audio to determine if it's a valid media file."""
        if not os.path.isfile(file_path): return False
        try:
            # First, check extensions to avoid ffmpeg overhead/issues for known bad/good extensions
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ['.wav', '.mp3', '.m4a', '.flac', '.ogg', '.opus', '.webm', '.aac']:
                return True
                
            # We use a fast try-catch, ffmpeg will complain if it can't read the header
            # rather than using whisperx.load_audio to load the entire array into memory just to check.
            import ffmpeg
            ffmpeg.probe(file_path)
            return True
        except Exception:
            return False

    audio_files = []
    if os.path.isdir(input_path):
        print(f"⚡ Scanning directory for valid media tracks...")
        for f in os.listdir(input_path):
            full_path = os.path.join(input_path, f)
            if is_valid_audio(full_path):
                audio_files.append(full_path)
        
        if not audio_files:
            print(f"❌ Error: No readable media files found in directory '{input_path}'.")
            sys.exit(1)
    elif os.path.isfile(input_path):
        if not is_valid_audio(input_path):
            print(f"❌ Error: Input file '{input_path}' is not a valid audio file.")
            sys.exit(1)
    else:
        print(f"❌ Error: Input path '{input_path}' does not exist.")
        sys.exit(1)

    import ctranslate2
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    supported_types = ctranslate2.get_supported_compute_types(device)
    if compute_type is None:
        preferences = ("int8_float16", "float16", "int8", "float32") if device == "cuda" else ("int8", "float32")
        compute_type = next(precision for precision in preferences if precision in supported_types)
    elif compute_type not in supported_types:
        raise ValueError(f"{compute_type} is not supported on {device}; choose from {sorted(supported_types)}.")
    raw_segments = []

    print(f"⚡ Engine active on [{device.upper()}] using {compute_type} precision.")

    transcription_options = {
        "device": device, "compute_type": compute_type,
        "checkpoint_dir": os.path.join(target_dir, ".transcription_checkpoints"),
        "db_threshold": db_threshold, "initial_prompt": HOTWORDS,
        "batch_size": batch_size, "model_name": model_name,
        "window_seconds": window_seconds, "resume": resume,
    }

    if os.path.isdir(input_path):
        print(f"⚡ Processing multi-track directory ({len(audio_files)} tracks)...")
        multi_track_start_time = time.time()
        for file_path in tqdm(audio_files, desc="Overall Transcription Progress", unit="track"):
            speaker_identity = os.path.splitext(os.path.basename(file_path))[0].upper()
            segments, audio_dur = transcribe_and_align(file_path, **transcription_options)
            
            # Record maximum duration across tracks
            session_info["length_seconds"] = max(session_info.get("length_seconds", 0), audio_dur)
            
            for seg in segments:
                words = seg.get("words", [])
                avg_confidence = 0.0
                if words:
                    confidences = [w.get("score", 0.0) for w in words if "score" in w]
                    if confidences:
                        avg_confidence = sum(confidences) / len(confidences)
                        
                raw_segments.append({
                    "speaker": speaker_identity,
                    "text": seg.get("text", ""),
                    "transcription_metrics": {
                        "start": seg.get("start", 0.0),
                        "end": seg.get("end", 0.0),
                        "confidence": round(avg_confidence, 3),
                        "db": seg.get("db", -100.0),
                        "clarity": seg.get("clarity", 0.0)
                    }
                })
        print(f"⚠️ Multi-track transcription complete. ({time.time() - multi_track_start_time:.2f}s)")
        raw_segments.sort(key=lambda x: x.get("transcription_metrics", {}).get("start", 0.0))
        
        processed_transcript = []
        if dedup:
            print("⚡ Deduplicating overlapping multi-track segments based on dB...")
            for seg in raw_segments:
                found_duplicate = False
                for i in range(max(0, len(processed_transcript) - 10), len(processed_transcript)):
                    kept_seg = processed_transcript[i]
                    seg_start = seg.get('transcription_metrics', {}).get('start', 0.0)
                    kept_start = kept_seg.get('transcription_metrics', {}).get('start', 0.0)
                    if abs(seg_start - kept_start) < 2.0:
                        similarity = difflib.SequenceMatcher(None, seg.get('text', ''), kept_seg.get('text', '')).ratio()
                        if similarity > 0.6:
                            found_duplicate = True
                            seg_db = seg.get('transcription_metrics', {}).get('db', -100.0)
                            kept_db = kept_seg.get('transcription_metrics', {}).get('db', -100.0)
                            if seg_db > kept_db:
                                processed_transcript[i] = seg
                            break
                if not found_duplicate:
                    processed_transcript.append(seg)
        else:
            processed_transcript = raw_segments
            
    # ⚡ MODE B:
    elif os.path.isfile(input_path):
        transcribe_start_time = time.time()
        segments, audio_dur = transcribe_and_align(input_path, **transcription_options)
        session_info["length_seconds"] = audio_dur
        print(f"⚠️ Core transcription complete. ({time.time() - transcribe_start_time:.2f}s)                                     ")
            
        stop_diarize = threading.Event()
        diarize_model_start_time = time.time()
        spinner_thread = threading.Thread(target=animate_spinner, args=(stop_diarize, "Running PyAnnote speaker diarization (Voice tracking)..."))
        spinner_thread.start()
            
        diarize_model = None
        try:
            audio_data = whisperx.load_audio(input_path)
            try:
                diarize_model = DiarizationPipeline(token=HF_TOKEN, device=device)
                diarize_segments = diarize_model(audio_data)
            except RuntimeError as error:
                if device != "cuda" or not is_out_of_memory(error):
                    raise
                diarize_segments = None
            if diarize_segments is None:
                print("Diarization exhausted GPU memory; retrying on CPU.")
                diarize_model = None
                clear_gpu_memory()
                diarize_model = DiarizationPipeline(token=HF_TOKEN, device="cpu")
                diarize_segments = diarize_model(audio_data)
        finally:
            stop_diarize.set()
            spinner_thread.join()
            del diarize_model
            clear_gpu_memory()
        del audio_data
        print(f"⚠️ Diarization complete. ({time.time() - diarize_model_start_time:.2f}s)")
            
        print("⚡ Correlating vocal tracks to script layers...")
        dummy_result = {"segments": segments}
        final_result = whisperx.assign_word_speakers(diarize_segments, dummy_result)
            
        processed_transcript = []
        for seg in final_result["segments"]:
            words = seg.get("words", [])
            avg_confidence = 0.0
            if words:
                confidences = [w.get("score", 0.0) for w in words if "score" in w]
                if confidences:
                    avg_confidence = sum(confidences) / len(confidences)

            processed_transcript.append({
                "speaker": seg.get("speaker", "UNKNOWN_SPEAKER"),
                "text": seg.get("text", "").strip(),
                "transcription_metrics": {
                    "start": round(seg.get("start", 0.0), 2),
                    "end": round(seg.get("end", 0.0), 2),
                    "db": seg.get("db", -100.0),
                    "clarity": seg.get("clarity", 0.0),
                    "confidence": round(avg_confidence, 3)
                }
            })

    # Check misspellings before writing
    import re
    corrections = {}
    
    # Combine entities and players for misspelling checks
    all_entries = REGISTRY.get("entities", []) + REGISTRY.get("players", [])
    
    for entry in all_entries:
        if "common_misspellings" in entry and isinstance(entry["common_misspellings"], dict):
            for correct_name, misspellings_list in entry["common_misspellings"].items():
                for misspelling in misspellings_list:
                    corrections[misspelling.lower()] = correct_name

    if corrections:
        sorted_misspellings = sorted(corrections.keys(), key=len, reverse=True)
        escaped_terms = [re.escape(m) for m in sorted_misspellings]
        pattern = re.compile(r'\b(' + '|'.join(escaped_terms) + r')\b', re.IGNORECASE)

        def replace_match(match):
            return corrections[match.group(1).lower()]

        for seg in processed_transcript:
            seg["text"] = pattern.sub(replace_match, seg["text"])

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
    parser.add_argument("input_path", help="Target .mp3 file, directory of stems, or URL to a video/audio.")
    parser.add_argument("campaign_name", help="Name of the campaign this sequence belongs to.")
    parser.add_argument("session_num", type=int, help="Chronological sequence ID of the session.")
    parser.add_argument("--db-threshold", type=float, default=-45.0, help="VAD noise floor threshold (default: -45.0).")
    parser.add_argument("--dedup", "-d", action="store_true", help="Deduplicate microphone bleed across multi-track processing based on peak dB comparison.")
    parser.add_argument("--force", "-f", action="store_true", help="Bypass cached files and force execution.")
    parser.add_argument("--details", type=str)
    parser.add_argument("--batch-size", type=int, default=1, help="Whisper batch size; reduced automatically on GPU OOM (default: 1).")
    parser.add_argument("--compute-type", choices=["int8_float16", "float16", "int8", "float32"], help="Whisper precision; defaults to int8_float16 on supported GPUs, int8 on CPU.")
    parser.add_argument("--model", default="large-v3", help="Whisper model name (default: large-v3).")
    parser.add_argument("--window-seconds", type=float, default=300, help="Checkpoint window duration, greater than 4 seconds (default: 300).")
    parser.add_argument("--resume", action="store_true", help="Reuse compatible transcription/alignment checkpoints in an existing session.")
    parser.add_argument("--device", choices=["cuda", "cpu"], help="Inference device (default: CUDA when available).")
    from utils import apply_defaults
    apply_defaults(parser, 'transcribe.py')
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")
    if not math.isfinite(args.window_seconds) or args.window_seconds <= 4:
        parser.error("--window-seconds must be finite and greater than 4")
    
    input_path = args.input_path
    
    # Define session directory so we can validate it before doing a massive network pull
    campaign_dir = os.path.join("campaigns", args.campaign_name)
    session_str = f"{str(args.session_num).zfill(3)}"
    target_dir = os.path.join(campaign_dir, "sessions", session_str)
    
    if os.path.exists(target_dir):
        if not args.force and not args.resume:
            print(f"⚠️ Error: Target session directory '{target_dir}' already exists.")
            print("To overwrite, supply --force. To continue checkpointed work, supply --resume.")
            sys.exit(1)
            
    # Check if input path is a URL and grab it using yt-dlp first if it is
    if input_path.startswith("http://") or input_path.startswith("https://"):
        print(f"🎬 Detected remote URL: {input_path}")
        print(f"⬇️ Downloading highest quality audio layer to a temporary local file...")
        
        # Download locally to campaigns/{campaign}/sessions/{session}/source_audio.mp3
        session_str = f"{str(args.session_num).zfill(3)}"
        target_dir = os.path.join("campaigns", args.campaign_name, "sessions", session_str)
        os.makedirs(target_dir, exist_ok=True)
        
        # yt-dlp will automatically append the extension (e.g. .mp3) when the FFmpegExtractAudio processor runs,
        # so we just provide the base name here.
        download_target_base = os.path.join(target_dir, "source_audio") 
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': download_target_base,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': False,
            'verbose': False,
            'nocheckcertificate': True,
            'ignoreerrors': False,
            'remote_components': ['ejs:github'],
            'js_runtimes': {
                'deno': {
                    'path': os.path.join(os.environ.get("VIRTUAL_ENV", ""), "bin", "deno")
                }
            }
        }
        
        if not (args.resume and os.path.isfile(f"{download_target_base}.mp3")):
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([input_path])
            
        download_target_final = f"{download_target_base}.mp3"
        print(f"✅ Finished downloading to: {download_target_final}")
        
        # Override the input parameter so the rest of the script triggers standard single-file execution Mode B
        input_path = download_target_final
    
    if args.db_threshold is not None and args.db_threshold > 0:
        args.db_threshold = -args.db_threshold
        
    process_pipeline(input_path, args.campaign_name, args.session_num, args.db_threshold, args.force,
                     getattr(args, "details", None), args.dedup, batch_size=args.batch_size,
                     compute_type=args.compute_type, model_name=args.model, window_seconds=args.window_seconds,
                     resume=args.resume, device=args.device)