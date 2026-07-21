import argparse
import json
import os
import sys
from pydub import AudioSegment

CROSSFADE_DURATION = 150

from utils import get_api_client, get_wsl_host_ip

# --- DATA LOADING ---
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# --- THE DIRECTOR: LLM SCORING ---
def rank_audio_segments(client, transcript_data, registry, model_name, summary_text, next_session_text, target_length):
    print(f"🤖 [Agent: Director] Reviewing transcript with '{model_name}' to find cinematic highlights...")
    
    # Compress transcript for payload
    condensed_segments = []
    for idx, s in enumerate(transcript_data["transcript"]):
        # Discard clips shorter than 1.5 seconds (likely random laughs/crosstalk)
        duration = s["end"] - s["start"]
        if duration >= 1.5:
             condensed_segments.append({
                 "id": idx, 
                 "duration": round(duration, 1), 
                 "speaker": s["speaker"], 
                 "text": s["text"],
                 # Include annotations if present
                 "drama": s.get("drama"),
                 "surprisal": s.get("surprisal"),
                 "humor": s.get("humor")
             })
             
    total_len = len(condensed_segments)
    safe_condensed = condensed_segments
    
    # If the transcript is massive, take a spread avoiding the early game (table chatter)
    if total_len > 300:
        safe_condensed = condensed_segments[int(total_len * 0.15):]
        # Only pass a max of 1000 items to the LLM to save token limits
        if len(safe_condensed) > 1000:
             step = len(safe_condensed) // 1000
             safe_condensed = safe_condensed[::step]
    
    registry_info = json.dumps(registry.get("reference_lexicon", []), indent=2)

    with open(os.path.join("prompts", "director.txt"), "r", encoding="utf-8") as prompt_file:
        prompt_text = prompt_file.read()

    # We inject the specific target_length math directly at runtime
    prompt = prompt_text.replace(
        "your Target Length.", 
        f"~{target_length} seconds!"
    )

    payload = f"Campaign Registry:\n{registry_info}\n\n"
    if summary_text:
        payload += f"Key Session Beats:\n{summary_text}\n\n"
    if next_session_text:
         payload += f"Next Session Preview (Crucial Context):\n{next_session_text}\n\n"
         
    payload += f"Transcript Dataset:\n{json.dumps(safe_condensed)}"

    try:
        # Check if we're using Ollama JSON mode or standard provider output
        is_local = False
        if client.base_url:
            base_url_str = str(client.base_url)
            windows_ip = get_wsl_host_ip()
            if windows_ip in base_url_str or "localhost" in base_url_str or "127.0.0.1" in base_url_str:
                is_local = True

        if is_local:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": payload}
                ],
                response_format={"type": "json_object"},
            )
        else:
            # External providers (OpenAI, Anthropic, Groq, etc) may not uniformly support response_format={"type": "json_object"}
            prompt += "\nIMPORTANT: Provide ONLY the raw JSON object. Do not include markdown codeblocks like ```json."
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": payload}
                ]
            )

        content = response.choices[0].message.content
        print(f"   [Debug] RAW LLM OUTPUT:\n{content}\n")
        
        # Clean markdown code blocks if the remote LLM ignored our instruction
        if content.startswith("```json"):
            content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
        elif content.startswith("```"):
            content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
        content = content.strip()
        
        result = json.loads(content)
        ids = result.get("selected_ids", result.get("ids", result.get("id", [])))
        
        # If the LLM returned a single integer instead of an array, wrap it in a list
        if isinstance(ids, int):
            ids = [ids]
            
        if not ids or not isinstance(ids, list):
             for key, value in result.items():
                  if isinstance(value, list) and len(value) > 0 and isinstance(value[0], int):
                       ids = value
                       break
                       
        if not isinstance(ids, list):
            ids = []
            
        return ids
    except Exception as e:
        print(f"❌ Error parsing director's choices: {e}")
        sys.exit(1)

# --- RUNTIME ENGINE ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="D&D Cinematic Post-Session Audio Compiler.")
    parser.add_argument("campaign", help="Name of the campaign (e.g. 'netherdeep')")
    parser.add_argument("session", type=int, help="Session number (e.g. 1)")
    parser.add_argument("-a", "--audio", help="Path to the original master audio file (.mp3/.wav). If not provided, will attempt to read from the transcript.")
    parser.add_argument("-n", "--next", action="store_true", help="Peek at session_num + 1 recap summary to target foreshadowing.")
    parser.add_argument("-l", "--length", type=int, default=90, help="Target recap duration in seconds (default: 90).")
    parser.add_argument("-m", "--model", default="qwen2.5", help="Target LLM model (default: qwen2.5).")
    parser.add_argument("-u", "--api-url", help="Optional remote API base URL.")
    parser.add_argument("-k", "--api-key", help="Optional API key for the remote endpoint.")
    from utils import apply_defaults
    apply_defaults(parser)
    args = parser.parse_args()

    # Directory structures
    session_str = f"{str(args.session).zfill(3)}"
    target_dir = os.path.join("campaigns", args.campaign, "sessions", session_str)
    
    transcript_path = os.path.join(target_dir, "transcript_annotated.json")
    if not os.path.exists(transcript_path):
        transcript_path = os.path.join(target_dir, "transcript.json")
        if not os.path.exists(transcript_path):
            print(f"❌ Error: Could not find transcript in {target_dir}")
            sys.exit(1)

    summary_path = os.path.join(target_dir, "summary.md")
    output_path = os.path.join(target_dir, "recap.mp3")

    session_package = load_json(transcript_path)

    audio_path = args.audio
    if not audio_path:
        audio_path = session_package.get("session_file")
        if not audio_path:
            print(f"❌ Error: Master audio file not provided (-a) and not found in transcript.")
            sys.exit(1)
            
    if not os.path.exists(audio_path):
        # Fallback to local execution directory if it's a relative path from transcription
        audio_fallback = os.path.join(os.getcwd(), os.path.basename(audio_path))
        if os.path.exists(audio_fallback):
            audio_path = audio_fallback
        else:
            print(f"❌ Error: Master audio file '{audio_path}' not found on disk.")
            sys.exit(1)

    registry = session_package.get("campaign_metadata", {})
            
    summary_text = ""
    if os.path.exists(summary_path):
        with open(summary_path, "r", encoding="utf-8") as f:
            summary_text = f.read()

    next_session_text = ""
    if args.next:
        next_session_num = args.session + 1
        next_session_str = f"{str(next_session_num).zfill(3)}"
        next_dir = os.path.join("campaigns", args.campaign, "sessions", next_session_str)
        # Just grab the summary itself so it knows what actually happened!
        next_summary_path = os.path.join(next_dir, "summary.md")
        
        if os.path.exists(next_summary_path):
            with open(next_summary_path, "r", encoding="utf-8") as f:
                next_session_text = f.read()
            print(f"👁️ Foreshadowing enabled: Loaded future knowledge from Session {next_session_num}.")
        else:
            print(f"⚠️ Warning: --next requested, but session '{next_session_str}' summary not found. Proceeding without foreshadowing context.")

    client = get_api_client(api_url=args.api_url, api_key=args.api_key)

    chosen_ids = rank_audio_segments(client, session_package, registry, args.model, summary_text, next_session_text, args.length)
    
    if not chosen_ids:
        print("❌ LLM director failed to return valid segment IDs.")
        sys.exit(1)

    print(f"📂 Loading master audio asset into memory: {audio_path}")
    full_audio = AudioSegment.from_file(audio_path)
    recap_mix = AudioSegment.empty()

    print(f"✂️ Splicing {len(chosen_ids)} key clips together with dynamic crossfades...")
    for idx in sorted(chosen_ids):
        # Gracefully handle IDs that might be out of bounds if the LLM hallucinates
        if idx < 0 or idx >= len(session_package["transcript"]):
            continue
            
        segment_meta = session_package["transcript"][idx]
        start_ms = int(segment_meta["start"] * 1000)
        end_ms = int(segment_meta["end"] * 1000)
        clip_duration_ms = end_ms - start_ms
        
        clip = full_audio[start_ms:end_ms]
        print(f"   ↳ Cut Added [{segment_meta['start']}s -> {segment_meta['end']}s] {segment_meta['speaker']}: '{segment_meta['text'][:50]}...' ({clip_duration_ms}ms)")
        
        if len(recap_mix) > 0:
            current_crossfade = min(CROSSFADE_DURATION, int(clip_duration_ms / 3))
            recap_mix = recap_mix.append(clip, crossfade=current_crossfade)
        else:
            recap_mix = clip

    print(f"💾 Exporting finalized compilation mix track out...")
    recap_mix.export(output_path, format="mp3", bitrate="192k")
    
    runtime_seconds = round(len(recap_mix) / 1000, 2)
    print(f"\n🎉 Success! Audio recap constructed: {output_path} ({runtime_seconds}s long)")