#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys

import platform
from pathlib import Path

# --- 🛠️ CONFIGURATION ---
BASE_DIR = Path(__file__).resolve().parent.parent
if platform.system() == "Windows":
    ENV_PYTHON = str(BASE_DIR / "dnd_env" / "Scripts" / "python")
else:
    ENV_PYTHON = str(BASE_DIR / "dnd_env" / "bin" / "python")

if not os.path.exists(ENV_PYTHON):
    print(f"❌ Error: Cannot find virtual environment python at '{ENV_PYTHON}'.")
    sys.exit(1)

def run_command(command_args: list[str], step_name: str) -> None:
    print(f"\n========================================================")
    print(f"🎬 STARTING STEP: {step_name}")
    print(f"========================================================")
    
    process = subprocess.Popen(command_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    
    # Read binary stream one byte at a time but accumulate until we have a full valid utf-8 character
    buffer = b""
    while True:
        byte = process.stdout.read(1)
        if not byte:
            if process.poll() is not None:
                break
            continue
            
        buffer += byte
        try:
            # Try to decode the accumulated bytes
            char = buffer.decode('utf-8')
            # Write directly to the underlying raw bytes buffer to prevent terminal parsing faults across WSL instances
            sys.stdout.buffer.write(char.encode('utf-8'))
            sys.stdout.flush()
            buffer = b""
        except UnicodeDecodeError:
            # If we get a decode error, it means we're in the middle of a multi-byte character
            # Keep reading bytes into the buffer!
            pass
            
    rc = process.poll()
    if rc != 0:
        print(f"\n❌ Step '{step_name}' failed with exit code {rc}. Halting pipeline.")
        sys.exit(rc)
    print(f"✅ STEP COMPLETE: {step_name}\n")

import json

def fire_hook(hook_name: str, campaign: str, session_num: int) -> None:
    """Reads plugins.json and executes any commands registered to the given lifecycle hook."""
    plugins_file = BASE_DIR / "plugins.json"
    if not plugins_file.exists():
        return
        
    try:
        with open(plugins_file, "r", encoding="utf-8") as f:
            registry = json.load(f)
    except json.JSONDecodeError:
        print(f"⚠️ Warning: plugins.json contains invalid JSON. Disabling hooks.")
        return

    commands = registry.get(hook_name, [])
    for cmd_str in commands:
        if not cmd_str or cmd_str.startswith("//"):
            continue
            
        # Replace variables
        formatted_cmd = cmd_str.replace("{campaign}", campaign).replace("{session}", str(session_num))
        
        # Split command (simple space split, assuming plugins don't have spaces in args for now. For robust parsing, use shlex.split)
        import shlex
        cmd_args = shlex.split(formatted_cmd)
        
        print(f"🔌 Triggering Hook '{hook_name}' -> {cmd_args[0]}")
        run_command(cmd_args, f"Plugin Event: {hook_name}")

# --- 🎮 RUNTIME CLI ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="D&D Post-Session Master Orchestration Pipeline.")
    parser.add_argument("input", help="Path to raw session audio file, remote URL (e.g. YouTube), or tracks folder.")
    parser.add_argument("campaign", help="Name of the campaign (e.g. 'netherdeep')")
    parser.add_argument("session", type=int, help="Session number (e.g. 1)")
    parser.add_argument("-l", "--length", type=int, default=90, help="Target audio recap length in seconds (default: 90).")
    parser.add_argument("-m", "--model", default="qwen2.5", help="Target model engine (default: qwen2.5).")
    parser.add_argument("-u", "--api-url", help="API URL for remote inference (e.g., https://api.openai.com/v1).")
    parser.add_argument("-k", "--api-key", help="API Key for remote inference.")
    parser.add_argument("--local", action="store_true", help="Force local inference (overrides defaults.json remote APIs).")
    parser.add_argument("-n", "--next", action="store_true", help="Peek at session_num + 1 recap summary to target foreshadowing.")
    parser.add_argument("--skip", nargs="+", type=int, default=[], help="List of step numbers to skip (1-10).")
    parser.add_argument("--info", type=str, help="Optional raw JSON string of extra session metadata to inject.")
    from utils import apply_defaults
    apply_defaults(parser, 'run_pipeline.py')
    args = parser.parse_args()

    if args.local:
        args.api_url = None
        args.api_key = None

    campaign = args.campaign
    session_num = args.session
    session_str = f"{str(session_num).zfill(3)}"
    target_dir = BASE_DIR / "campaigns" / campaign / "sessions" / session_str

    print("⚔️ Starting Full Post-Session Processing Core... ⚔️")
    print(f"📦 Target Directory: {target_dir}")

    # --- STEP 1: TRANSCRIBE ---
    if 1 not in args.skip:
        transcribe_cmd = [ENV_PYTHON, "bin/transcribe.py", args.input, campaign, str(session_num), "-f"]
        if args.info:
            transcribe_cmd.extend(["--details", args.info])
        run_command(transcribe_cmd, "WhisperX Audio Transcription")
    fire_hook("post_transcribe", campaign, session_num)

    # --- STEP 2: EXTRACT SAMPLES ---
    if 2 not in args.skip:
        extract_cmd = [ENV_PYTHON, "bin/extract_samples.py", campaign, str(session_num)]
        run_command(extract_cmd, "Speaker Reference Sample Extraction")
    fire_hook("post_extract_samples", campaign, session_num)

    # --- STEP 3: VOICE BIOMETRICS (AUTO-MAPPING) ---
    if 3 not in args.skip:
        match_cmd = [ENV_PYTHON, "bin/match_speakers.py", campaign, str(session_num)]
        run_command(match_cmd, "Pre-Diarization Voice Biometric Mapping")

    # --- STEP 4: DIARIZE ---
    if 4 not in args.skip:
        diarize_cmd = [ENV_PYTHON, "bin/diarize.py", campaign, str(session_num)]
        run_command(diarize_cmd, "Scribe Identity Resolution")
    fire_hook("post_diarize", campaign, session_num)
    
    # --- STEP 5: ANNOTATE ---
    if 5 not in args.skip:
        annotate_cmd = [ENV_PYTHON, "bin/annotate.py", campaign, str(session_num)]
        run_command(annotate_cmd, "Zero-Shot Emotional & Contextual Inference")
    fire_hook("post_annotate", campaign, session_num)

    # --- STEP 6: VISUALIZE ---
    if 6 not in args.skip:
        visualize_cmd = [ENV_PYTHON, "bin/visualize.py", campaign, str(session_num)]
        run_command(visualize_cmd, "Visual Summary Generation")
    fire_hook("post_visualize", campaign, session_num)

    # --- STEP 7: ANALYZE / SUMMARIZE ---
    if 7 not in args.skip:
        summarize_cmd = [ENV_PYTHON, "bin/summarize.py", campaign, str(session_num)]
        if args.api_url: summarize_cmd.extend(["-u", args.api_url])
        if args.api_key: summarize_cmd.extend(["-k", args.api_key])
        if args.model: summarize_cmd.extend(["-m", args.model])
        run_command(summarize_cmd, "LLM Context Mapping & Session Summary Synthesis")
    fire_hook("post_summarize", campaign, session_num)
    
    # --- STEP 8: UPDATE WIKI ---
    if 8 not in args.skip:
        wiki_cmd = [ENV_PYTHON, "bin/update_wiki.py", campaign, str(session_num)]
        if args.api_url: wiki_cmd.extend(["-u", args.api_url])
        if args.api_key: wiki_cmd.extend(["-k", args.api_key])
        if args.model: wiki_cmd.extend(["-m", args.model])
        run_command(wiki_cmd, "Librarian Automated Entity Tracking")
    fire_hook("post_update_wiki", campaign, session_num)

    # --- STEP 9: WIKI CROSS-REFERENCE RELINKING ---
    if 9 not in args.skip:
        relink_cmd = [ENV_PYTHON, "bin/relink_wiki.py", campaign]
        run_command(relink_cmd, "Wiki Markdown Retroactive Entity Linker")
    fire_hook("post_relink_wiki", campaign, session_num)

    # --- STEP 10: AUDIO RECAP COMPILATION ---
    if 10 not in args.skip:
        recap_cmd = [
            ENV_PYTHON, "bin/recap.py", campaign, str(session_num),
            "-l", str(args.length)
        ]
        if args.api_url: recap_cmd.extend(["-u", args.api_url])
        if args.api_key: recap_cmd.extend(["-k", args.api_key])
        if args.model: recap_cmd.extend(["-m", args.model])
        if args.next: recap_cmd.append("--next")
        
        run_command(recap_cmd, "Pydub Cinematic Audio Recap Splicing")
    fire_hook("post_recap", campaign, session_num)

    fire_hook("pipeline_complete", campaign, session_num)

    print("========================================================")
    print("🎉 ALL PIPELINE TASKS COMPLETE SUCCESSFULY!")
    print(f"📂 Workspace Folder: {target_dir.resolve()}")
    print("========================================================")