import argparse
import json
import os
import subprocess
import sys
import threading
import time
from openai import OpenAI

# --- 🚀 NETWORK RESILIENCE: WINDOWS HOST LOOKUP ---
def get_wsl_host_ip():
    """Dynamically parses the Linux routing table to bridge to Windows Ollama."""
    try:
        cmd = "ip route | grep default | awk '{print $3}'"
        host_ip = subprocess.check_output(cmd, shell=True).decode().strip()
        return host_ip if host_ip else "127.0.0.1"
    except Exception:
        return "127.0.0.1"

WINDOWS_HOST_IP = get_wsl_host_ip()

def load_secrets():
    try:
        with open("secrets.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def get_api_client(api_url=None, api_key=None):
    from urllib.parse import urlparse
    if api_url:
        print(f"🔗 Connected to Remote API Host at: {api_url}")
        if not api_key:
            secrets = load_secrets()
            domain = urlparse(api_url).hostname
            # If standard OpenAI URL, sometimes hostname might be api.openai.com
            # Let's fallback gracefully if hostname is None
            if domain:
                api_key = secrets.get("API_KEYS", {}).get(domain)
        return OpenAI(base_url=api_url, api_key=api_key if api_key else "dummy_key")
    else:
        print(f"🔗 Connected to Windows Ollama Host at: http://{WINDOWS_HOST_IP}:11434")
        return OpenAI(base_url=f"http://{WINDOWS_HOST_IP}:11434/v1", api_key="ollama")

# --- 🛠️ ANIMATION SPINNER HELPERS ---
def animate_spinner(stop_event, message):
    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    idx = 0
    while not stop_event.is_set():
        sys.stdout.write(f"\r{spinner[idx % len(spinner)]} {message}")
        sys.stdout.flush()
        idx += 1
        time.sleep(0.1)
    sys.stdout.write("\r") # Clean up terminal row

# --- 🛠️ DATA PARSERS ---
def load_session_package(path):
    if not os.path.exists(path):
        print(f"❌ Error: Input session file '{path}' not found.")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def run_analysis_agent(session_data, client, model_name="qwen2.5"):
    transcript = session_data["transcript"]
    
    # We provide the FULL lexicon down to the LLM agent for plot alignment
    # (NPCs, Locations, Items, etc.) so it can accurately recognize lore!
    registry_info = json.dumps(session_data.get("campaign_metadata", {}).get("reference_lexicon", []), indent=2)

    # Note: Diarization and Speaker Identity mapping has been moved to transcribe.py

    # If an API URL is specified, we assume it's a large model capable of one-shotting the transcript
    is_remote = getattr(args, 'api_url', getattr(client, 'base_url', None) and "11434" not in str(getattr(client, 'base_url', '')))
    
    if is_remote:
        # --- PHASE 1/2: ONE-SHOT FULL TRANSCRIPT SUMMARY (REMOTE) ---
        print(f"\n🗺️  [Phase 1] Sending full transcript for one-shot synthesis...")
        full_transcript_lines = []
        for seg in transcript:
            # Check for metadata metrics
            metadata = []
            if "emotions" in seg and seg["emotions"]:
                # Sort emotions by weight descending and get top 2
                sorted_emotions = sorted(seg["emotions"].items(), key=lambda x: x[1], reverse=True)
                top_emotions = ", ".join([e[0] for e in sorted_emotions[:2]])
                metadata.append(f"Emotions: {top_emotions}")
            if "drama" in seg:
                metadata.append(f"Drama: {seg['drama']}")
            if "humor" in seg:
                metadata.append(f"Humor: {seg['humor']}")
            if "in_character" in seg:
                metadata.append(f"In-Character: {seg['in_character']}")
            if "surprisal" in seg:
                metadata.append(f"Surprisal: {seg['surprisal']}")
                
            meta_str = f" ({' | '.join(metadata)})" if metadata else ""
            full_transcript_lines.append(f"[{seg['start']}s] {seg['speaker']}{meta_str}: {seg['text']}")
        transcript_text = "\n".join(full_transcript_lines)
        
        with open("prompts/chronicler.txt", "r", encoding="utf-8") as f:
            master_reduce_prompt_template = f.read()

        master_payload = f"Campaign Context:\n{registry_info}\n\nTranscript:\n{transcript_text}"

        stop_reduce = threading.Event()
        reduce_spinner = threading.Thread(target=animate_spinner, args=(stop_reduce, "Compiling and structuring master markdown matrix in one shot..."))
        reduce_spinner.start()

        final_response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": master_reduce_prompt_template},
                {"role": "user", "content": master_payload}
            ]
        )

        stop_reduce.set()
        reduce_spinner.join()
        print("✅ Full pipeline synthesis complete!")

        return final_response.choices[0].message.content

    # --- PHASE 1: LOSSLESS CHUNKING (MAP - LOCAL ONLY) ---
    print(f"\n🗺️  [Phase 1] Breaking long session into manageable chronological chapters...")
    # 900 seconds = 15-minute block increments
    chunk_duration = 900 
    chunks = []
    current_chunk = []
    chunk_start_time = transcript[0]["start"] if transcript else 0

    for seg in transcript:
        # Build metadata string
        metadata = []
        if "emotions" in seg and seg["emotions"]:
            # Sort emotions by weight descending and get top 2
            sorted_emotions = sorted(seg["emotions"].items(), key=lambda x: x[1], reverse=True)
            top_emotions = ", ".join([e[0] for e in sorted_emotions[:2]])
            metadata.append(f"Emotions: {top_emotions}")
        if "drama" in seg:
            metadata.append(f"Drama: {seg['drama']}")
        if "humor" in seg:
            metadata.append(f"Humor: {seg['humor']}")
        if "in_character" in seg:
            metadata.append(f"In-Character: {seg['in_character']}")
        if "surprisal" in seg:
            metadata.append(f"Surprisal: {seg['surprisal']}")
            
        meta_str = f" ({' | '.join(metadata)})" if metadata else ""
        current_chunk.append(f"[{seg['start']}s] {seg['speaker']}{meta_str}: {seg['text']}")
        
        if seg['end'] - chunk_start_time >= chunk_duration:
            chunks.append("\n".join(current_chunk))
            current_chunk = []
            chunk_start_time = seg['end']
    if current_chunk:
        chunks.append("\n".join(current_chunk))

    print(f"📂 Fragmented session into {len(chunks)} chronological segments.")

    with open("prompts/archivist.txt", "r", encoding="utf-8") as f:
        archivist_prompt_template = f.read()

    partial_summaries = []
    
    for i, chunk_text in enumerate(chunks):
        chapter_num = i + 1
        print(f"   🎬 Processing Segment {chapter_num}/{len(chunks)}...")
        
        chunk_payload = f"Campaign Context:\n{registry_info}\n\nTranscript Section (Segment {chapter_num}):\n{chunk_text}\n"

        stop_chunk = threading.Event()
        chunk_spinner = threading.Thread(target=animate_spinner, args=(stop_chunk, f"Model processing segment {chapter_num}..."))
        chunk_spinner.start()

        chunk_response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": archivist_prompt_template},
                {"role": "user", "content": chunk_payload}
            ],
            temperature=0.1 # Low temperature for factual extraction
        )
        
        stop_chunk.set()
        chunk_spinner.join()
        
        partial_summaries.append(chunk_response.choices[0].message.content)
        print(f"   ✅ Segment {chapter_num} processed successfully.")

    # --- PHASE 2: MASTER FORMATTING (REDUCE) ---
    print(f"\n📉 [Phase 2] Formatting final master campaign log...")
    
    with open("prompts/chronicler.txt", "r", encoding="utf-8") as f:
        master_reduce_prompt_template = f.read()

    # Concatenate the lossless bullet points natively in Python
    master_text = "\n\n--- NEXT SEGMENT ---\n\n".join(partial_summaries)
    master_payload = f"Master Bullet Points:\n{master_text}"

    stop_reduce = threading.Event()
    reduce_spinner = threading.Thread(target=animate_spinner, args=(stop_reduce, "Compiling and structuring master markdown matrix..."))
    reduce_spinner.start()

    final_response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": master_reduce_prompt_template},
            {"role": "user", "content": master_payload}
        ]
    )

    stop_reduce.set()
    reduce_spinner.join()
    print("✅ Full pipeline synthesis complete!")

    return final_response.choices[0].message.content

# --- 🎮 ARGUMENT PARSING INTERFACE ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Map-Reduce Contextual Post-Session Analyzer (Local/Remote API).")
    parser.add_argument("campaign", help="Name of the campaign (e.g. 'netherdeep')")
    parser.add_argument("session", type=int, help="Session number (e.g. 1)")
    parser.add_argument("-m", "--model", default="qwen2.5", help="Target model name (default: qwen2.5).")
    parser.add_argument("-u", "--api-url", help="Optional remote API base URL (e.g. OpenAI, Anthropic via LiteLLM, Groq). If not specified, uses local Ollama.")
    parser.add_argument("-k", "--api-key", help="Optional API key for the remote endpoint.")
    
    args = parser.parse_args()
    
    # Establish directory structures
    session_str = f"{str(args.session).zfill(3)}"
    target_dir = os.path.join("campaigns", args.campaign, "sessions", session_str)
    
    # Check for annotated first, fallback to standard transcript
    annotated_path = os.path.join(target_dir, "transcript_annotated.json")
    standard_path = os.path.join(target_dir, "transcript.json")
    
    if os.path.exists(annotated_path):
        input_path = annotated_path
    elif os.path.exists(standard_path):
        input_path = standard_path
    else:
        print(f"❌ Error: Found neither annotated nor core transcript in '{target_dir}'.")
        sys.exit(1)

    output_path = os.path.join(target_dir, "summary.md")
        
    print(f"📥 Loading session artifact: {input_path}")
    data = load_session_package(input_path)
    
    client = get_api_client(api_url=args.api_url, api_key=args.api_key)
    
    markdown_report = run_analysis_agent(data, client, model_name=args.model)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(markdown_report)
        
    print(f"\n🎉 Process Complete! Final log written to: {output_path}")
