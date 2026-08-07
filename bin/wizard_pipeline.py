#!/usr/bin/env python3

import argparse
import json
import os
import sys
import subprocess
import time
from pathlib import Path

# Try strictly importing questionary for terminal menus
try:
    import questionary
except ImportError:
    print("❌ Error: Missing optional dependency 'questionary'.")
    print("Please install it to use interactive mode: pip install questionary")
    sys.exit(1)

def run_command(cmd_list, description):
    print(f"\n🚀 === {description} ===")
    print(f"Executing: {' '.join(cmd_list)}")
    start = time.time()
    try:
        subprocess.run(cmd_list, check=True)
        print(f"✅ {description} Complete. ({time.time() - start:.2f}s)")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error during {description}: Process exited with code {e.returncode}")
        print("Pipeline aborted.")
        sys.exit(e.returncode)
    except KeyboardInterrupt:
        print(f"\n✋ Execution interrupted by user during {description}.")
        sys.exit(1)

def get_env_python():
    # Resolve the python executable based on the environment (cross-platform compatible)
    if "VIRTUAL_ENV" in os.environ:
        if os.name == 'nt':
            return os.path.join(os.environ["VIRTUAL_ENV"], "Scripts", "python.exe")
        return os.path.join(os.environ["VIRTUAL_ENV"], "bin", "python3")
    return sys.executable

ENV_PYTHON = get_env_python()

def play_audio(filepath):
    """Attempt cross-platform native audio playing for sample reviewing"""
    if os.name == 'nt':  # Windows
        os.startfile(filepath)
    elif sys.platform == "darwin":  # macOS
        subprocess.Popen(["afplay", filepath])
    else:  # Linux (WSL/Ubuntu)
        # Try a few common linux players
        players = ["ffplay", "aplay", "paplay", "xdg-open", "vlc"]
        for p in players:
            import shutil
            if shutil.which(p):
                # We use popen instead of run so it doesn't hard-block the CLI while playing 
                subprocess.Popen([p, filepath], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break

def get_session_info(target_dir):
    session_info_path = os.path.join(target_dir, "session_info.json")
    if os.path.exists(session_info_path):
        with open(session_info_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_session_info(target_dir, info_dict):
    session_info_path = os.path.join(target_dir, "session_info.json")
    with open(session_info_path, "w", encoding="utf-8") as f:
        json.dump(info_dict, f, indent=4)

BASE_DIR = Path(__file__).resolve().parent.parent

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
        
        # Split command
        import shlex
        cmd_args = shlex.split(formatted_cmd)
        
        print(f"🔌 Triggering Hook '{hook_name}' -> {cmd_args[0]}")
        run_command(cmd_args, f"Plugin Event: {hook_name}")

if __name__ == "__main__":
    print("========================================================")
    print("🧙‍♂️ BARDIC ASPIRATION - INTERACTIVE WORKFLOW SUITE 🧙‍♂️")
    print("========================================================")
    
    # 1. Gather initial targets via CLI prompts
    action = questionary.select(
        "What would you like to process today?",
        choices=[
            "Process a new session completely from scratch",
            "Resume a partially finished session (Manual Speaker Tagging & Analytics)",
            "Exit"
        ]).ask()
        
    if action == "Exit" or not action:
        sys.exit(0)

    # Gather campaign
    campaigns_dir = Path("campaigns")
    existing_campaigns = [d.name for d in campaigns_dir.iterdir() if d.is_dir()] if campaigns_dir.exists() else []
    
    if existing_campaigns:
        campaign = questionary.autocomplete(
            "Enter Campaign Name:",
            choices=existing_campaigns,
            validate=lambda text: len(text) > 0 or "Campaign name cannot be empty."
        ).ask()
    else:
        campaign = questionary.text(
            "Enter Campaign Name (No existing campaigns found):",
            validate=lambda text: len(text) > 0 or "Campaign name cannot be empty."
        ).ask()
    
    session = int(questionary.text(
        "Enter Session Number:",
        validate=lambda text: text.isdigit() or "Please enter a valid number."
    ).ask())
    
    session_str = f"{str(session).zfill(3)}"
    target_dir = os.path.join("campaigns", campaign, "sessions", session_str)
    
    # Pre-configure CLI flags tracking dictionary
    shared_cli = []
    
    use_local = questionary.confirm("Force all inference out to your Local Engine (Ollama/LMStudio) bypassing defaults.json?", default=False).ask()
    if use_local:
        shared_cli.append("--local")
        model_name = questionary.text("Enter local model name (or hit enter for 'qwen2.5'):", default="qwen2.5").ask()
        shared_cli.extend(["-m", model_name])

    if action == "Process a new session completely from scratch":
        # 1A. Start from zero 
        media_input = questionary.text("Provide path to raw media file or URL (e.g. YouTube):").ask()
        
        # Build session info right away
        title = questionary.text("Session Title:").ask()
        date_played = questionary.text("Date Played (YYYY-MM-DD) [Optional]:").ask()
        media_url = questionary.text("Archived URL link back to original stream (for front-end linking) [Optional]:").ask()
        
        # Fire transcription 
        transcribe_cmd = [ENV_PYTHON, "bin/transcribe.py", media_input, campaign, str(session)]
        run_command(transcribe_cmd, "WhisperX Transcription Processing")
        fire_hook("post_transcribe", campaign, session)
        
        # Now save the accumulated metadata 
        os.makedirs(target_dir, exist_ok=True)
        session_info = get_session_info(target_dir)
        if title: session_info["title"] = title
        if date_played: session_info["date_played"] = date_played
        if media_url: session_info["media_url"] = media_url
        save_session_info(target_dir, session_info)
        
        # Fire extraction
        extract_cmd = [ENV_PYTHON, "bin/extract_samples.py", campaign, str(session)]
        run_command(extract_cmd, "Vocal Profile Referencing Extraction")
        fire_hook("post_extract_samples", campaign, session)
        
        # Fire automated match logic right before asking the user! (It silently succeeds/fails and alters identities if possible)
        match_cmd = [ENV_PYTHON, "bin/match_speakers.py", campaign, str(session)]
        run_command(match_cmd, "Pre-Diarization Voice Biometric Mapping")

    # Interactive Identity Binding 
    assign_speakers = questionary.confirm("Do you want to manually assign Speaker IDs now by listening to samples? (If 'No', the AI Diarizer will try clustering them blindly instead)", default=False).ask()
    
    if assign_speakers:
        samples_dir = os.path.join(target_dir, "samples")
        if not os.path.exists(samples_dir):
            print("❌ Samples directory not found. Please run the extraction step first.")
            sys.exit(1)
            
        transcript_path = os.path.join(target_dir, "transcript.json")
        if not os.path.exists(transcript_path):
             print("❌ Main transcript.json not found for mapping.")
             sys.exit(1)
             
        with open(transcript_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
            
        speaker_identities = manifest.get("speaker_identities", {})
        
        # Pull campaign registry to get known player names as autocomplete targets!
        registry_path = os.path.join("campaigns", campaign, "campaign_registry.json")
        known_players = []
        if os.path.exists(registry_path):
            try:
                with open(registry_path, "r", encoding="utf-8") as f:
                    reg = json.load(f)
                    known_players = [p.get("player_name") for p in reg.get("players", []) if p.get("player_name")]
            except Exception:
                pass
                
        if not known_players:
            print(f"❌ Error: No players mapped in '{registry_path}'.")
            print("Please populate the players array in your campaign registry before assigning speakers interactively!")
            sys.exit(1)
                
        print("\n🎧 Launching Audio Assignment Loop...")
        for speaker_file in os.listdir(samples_dir):
            if speaker_file.endswith(".mp3"):
                speaker_id = speaker_file.replace(".mp3", "")
                
                # Check if it was already assigned
                if speaker_identities.get(speaker_id) and speaker_identities.get(speaker_id) != speaker_id:
                    print(f"Skipping {speaker_id}, already mapped to '{speaker_identities.get(speaker_id)}'")
                    continue
                    
                sample_path = os.path.join(samples_dir, speaker_file)
                play_audio(sample_path)
                
                print(f"\n🔊 Playing sample for: {speaker_id}")
                map_name = questionary.autocomplete(
                    f"Who is speaking in {speaker_file}? (Or press Enter to skip/leave unknown)",
                    choices=known_players,
                    ignore_case=True
                ).ask()
                
                if map_name and map_name.strip():
                    speaker_identities[speaker_id] = map_name.strip()
                    print(f"   => Mapped {speaker_id} to {map_name.strip()}")
                
        # Save mappings back primarily into transcript.json (so downstream compute respects it)
        # And also into annotated in case it already exists somehow
        manifest["speaker_identities"] = speaker_identities
        with open(transcript_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=4, ensure_ascii=False)
            
        annotated_path = os.path.join(target_dir, "transcript_annotated.json")
        with open(annotated_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=4, ensure_ascii=False)
            
        print("\n✅ Identity Map successfully baked into transcript.json (and transcript_annotated)!")
        
        # If they manually annotated, we should probably skip the AI Diarizer step.
        skip_diarize = True
    else:
        skip_diarize = False

    # Execute remaining pipeline
    print("\n⏳ Triggering downstream computational stages...")
    
    if not skip_diarize:
        cmd = [ENV_PYTHON, "bin/diarize.py", campaign, str(session)] + shared_cli
        run_command(cmd, "AI Identity Diarization")
    fire_hook("post_diarize", campaign, session)
        
    cmd = [ENV_PYTHON, "bin/annotate.py", campaign, str(session)] + shared_cli
    run_command(cmd, "Context & Emotional Analysis")
    fire_hook("post_annotate", campaign, session)
    
    cmd = [ENV_PYTHON, "bin/visualize.py", campaign, str(session)]
    run_command(cmd, "Visualization Export")
    fire_hook("post_visualize", campaign, session)
    
    cmd = [ENV_PYTHON, "bin/summarize.py", campaign, str(session)] + shared_cli
    run_command(cmd, "Session Summarization")
    fire_hook("post_summarize", campaign, session)
    
    cmd = [ENV_PYTHON, "bin/update_wiki.py", campaign, str(session)] + shared_cli
    run_command(cmd, "Librarian Entity Extraction")
    fire_hook("post_update_wiki", campaign, session)
    
    cmd = [ENV_PYTHON, "bin/relink_wiki.py", campaign]
    run_command(cmd, "Markdown Retro-Linker")
    fire_hook("post_relink_wiki", campaign, session)
    
    cmd = [ENV_PYTHON, "bin/recap.py", campaign, str(session)] + shared_cli
    run_command(cmd, "Cinematic Recap Engine")
    fire_hook("post_recap", campaign, session)
    
    fire_hook("pipeline_complete", campaign, session)
    
    print("\n🎉========================================================")
    print("🎉 FULL INTERACTIVE WORKFLOW COMPLETED SUCCESSFULLY!")
    print(f"📂 Check the folder: {target_dir}")
    print("🎉========================================================")