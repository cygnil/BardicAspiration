import argparse
import os
import subprocess
import sys

# --- 🛠️ CONFIGURATION ---
ENV_PYTHON = "./dnd_env/bin/python"

if not os.path.exists(ENV_PYTHON):
    print(f"❌ Error: Cannot find virtual environment python at '{ENV_PYTHON}'.")
    sys.exit(1)

def run_command(command_args, step_name):
    print(f"\n========================================================")
    print(f"🎬 STARTING STEP: {step_name}")
    print(f"========================================================")
    
    process = subprocess.Popen(command_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    
    # Read binary character by character and decode to faithfully pass \r without Python's automatic universal newline (\n) conversion translation
    while True:
        char = process.stdout.read(1)
        if not char and process.poll() is not None:
            break
        if char:
            sys.stdout.write(char.decode('utf-8', errors='replace'))
            sys.stdout.flush()
            
    rc = process.poll()
    if rc != 0:
        print(f"\n❌ Step '{step_name}' failed with exit code {rc}. Halting pipeline.")
        sys.exit(rc)
    print(f"✅ STEP COMPLETE: {step_name}\n")

# --- 🎮 RUNTIME CLI ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="D&D Post-Session Master Orchestration Pipeline.")
    parser.add_argument("input", help="Path to raw session audio file (or tracks folder).")
    parser.add_argument("campaign", help="Name of the campaign (e.g. 'netherdeep')")
    parser.add_argument("session", type=int, help="Session number (e.g. 1)")
    parser.add_argument("-l", "--length", type=int, default=90, help="Target audio recap length in seconds (default: 90).")
    parser.add_argument("-m", "--model", default="qwen2.5", help="Target Ollama model engine (default: qwen2.5).")
    parser.add_argument("-u", "--url", help="API URL for remote inference (e.g., https://api.openai.com/v1).")
    parser.add_argument("-k", "--key", help="API Key for remote inference.")
    parser.add_argument("-n", "--next", action="store_true", help="Peek at session_num + 1 recap summary to target foreshadowing.")
    parser.add_argument("--info", type=str, help="Optional raw JSON string of extra session metadata to inject.")
    args = parser.parse_args()

    campaign = args.campaign
    session_num = args.session
    session_str = f"{str(session_num).zfill(3)}"
    target_dir = os.path.join("campaigns", campaign, "sessions", session_str)

    print("⚔️ Starting Full Post-Session Processing Core... ⚔️")
    print(f"📦 Target Directory: {target_dir}")

    # --- STEP 1: TRANSCRIBE ---
    transcribe_cmd = [ENV_PYTHON, "bin/transcribe.py", args.input, campaign, str(session_num), "-f"]
    if args.info:
        transcribe_cmd.extend(["--details", args.info])
    run_command(transcribe_cmd, "WhisperX Audio Transcription")

    # --- STEP 2: DIARIZE ---
    diarize_cmd = [ENV_PYTHON, "bin/diarize.py", campaign, str(session_num)]
    run_command(diarize_cmd, "Scribe Identity Resolution")
    
    # --- STEP 3: ANNOTATE ---
    annotate_cmd = [ENV_PYTHON, "bin/annotate.py", campaign, str(session_num)]
    run_command(annotate_cmd, "Zero-Shot Emotional & Contextual Inference")

    # --- STEP 4: VISUALIZE ---
    visualize_cmd = [ENV_PYTHON, "bin/visualize.py", campaign, str(session_num)]
    run_command(visualize_cmd, "Visual Summary Generation")

    # --- STEP 5: ANALYZE / SUMMARIZE ---
    summarize_cmd = [ENV_PYTHON, "bin/summarize.py", campaign, str(session_num), "-m", args.model]
    if args.url: summarize_cmd.extend(["-u", args.url])
    if args.key: summarize_cmd.extend(["-k", args.key])
    run_command(summarize_cmd, "LLM Context Mapping & Session Summary Synthesis")
    
    # --- STEP 6: UPDATE WIKI ---
    wiki_cmd = [ENV_PYTHON, "bin/update_wiki.py", campaign, str(session_num), "-m", args.model]
    if args.url: wiki_cmd.extend(["-u", args.url])
    if args.key: wiki_cmd.extend(["-k", args.key])
    run_command(wiki_cmd, "Librarian Automated Entity Tracking")

    # --- STEP 7: WIKI CROSS-REFERENCE RELINKING ---
    relink_cmd = [ENV_PYTHON, "bin/relink_wiki.py", campaign]
    run_command(relink_cmd, "Wiki Markdown Retroactive Entity Linker")

    # --- STEP 8: AUDIO RECAP COMPILATION ---
    recap_cmd = [
        ENV_PYTHON, "bin/recap.py", campaign, str(session_num),
        "-l", str(args.length), 
        "-m", args.model
    ]
    if args.url: recap_cmd.extend(["-u", args.url])
    if args.key: recap_cmd.extend(["-k", args.key])
    if args.next: recap_cmd.append("--next")
    
    run_command(recap_cmd, "Pydub Cinematic Audio Recap Splicing")

    print("========================================================")
    print("🎉 ALL PIPELINE TASKS COMPLETE SUCCESSFULY!")
    print(f"¼️ Workspace Folder: {os.path.abspath(target_dir)}")
    print("========================================================")