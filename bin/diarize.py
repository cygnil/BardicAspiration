import argparse
import json
import os
import sys
import time

print("🔄 Diarize Script initializing...")

from utils import get_api_client

def load_campaign_registry(campaign_dir):
    registry_path = os.path.join(campaign_dir, "campaign_registry.json")
    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"⚠️ Notice: 'campaign_registry.json' not found in {campaign_dir}. Running with clean defaults.")
    return {"campaign_name": "Unknown Campaign", "entities": []}

def run_diarization(campaign_name, session_num, force_overwrite=False, api_url=None, api_key=None, model_name="qwen2.5"):
    diarization_start_time = time.time()
    
    campaign_dir = os.path.join("campaigns", campaign_name)
    session_str = f"{str(session_num).zfill(3)}"
    target_dir = os.path.join(campaign_dir, "sessions", session_str)
    
    if not os.path.exists(target_dir):
        print(f"❌ Error: Session directory '{target_dir}' does not exist.")
        sys.exit(1)
        
    output_json_path = os.path.join(target_dir, "transcript.json")
    
    if not os.path.exists(output_json_path):
         print(f"❌ Error: Cannot run Diarization Scribe. No existing 'transcript.json' at {output_json_path}")
         sys.exit(1)
         
    with open(output_json_path, "r", encoding="utf-8") as f:
         manifest = json.load(f)
         processed_transcript = manifest.get("transcript", [])
         input_path = manifest.get("session_file", "Unknown Route")

    REGISTRY = load_campaign_registry(campaign_dir)
    
    print("\n🧠 [Agent: Scribe] Connecting for Identity Resolution Phase...")
    client = get_api_client(api_url=api_url, api_key=api_key) 
    
    snippet_lines = []
    
    total_lines = len(processed_transcript)
    if total_lines > 150:
        chunk_size = 50
        indices = list(range(0, chunk_size)) + \
                  list(range(total_lines // 2 - chunk_size // 2, total_lines // 2 + chunk_size // 2)) + \
                  list(range(total_lines - chunk_size, total_lines))
        indices = sorted(list(set(i for i in indices if 0 <= i < total_lines)))
        sample_segments = [processed_transcript[i] for i in indices]
    else:
        sample_segments = processed_transcript

    for seg in sample_segments:
        snippet_lines.append(f"{seg['speaker']}: {seg['text']}")
    transcript_snippet = "\n".join(snippet_lines)[:10000]




    try:
        registry_info = json.dumps(REGISTRY.get("entities", []), indent=2)
    except Exception as e:
        registry_info = "[]"

    try:
        with open("prompts/scribe.txt", "r", encoding="utf-8") as f:
            identity_prompt_template = f.read()
    except FileNotFoundError:
         print("⚠️ Warning: 'prompts/scribe.txt' missing. Skipping AI Diarization alignment.")
         identity_prompt_template = None
         
    if identity_prompt_template:
        json_example = "{\n  \"SPEAKER_00\": \"Player Name\",\n  \"...\": \"...\"\n}"
        identity_payload = f"Cross-reference with Campaign Registry:\n{registry_info}\n\nTranscript Snippet:\n{transcript_snippet}\n\nREQUIREMENTS:\n1. Map every SPEAKER_tag found in the transcript to a character.\n2. If you don't know who is speaking, use \"Unknown\".\n3. ONLY RETURN THIS EXACT JSON FORMAT:\n{json_example}"

        print("Scribe aligning actor identities...")
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": identity_prompt_template},
                    {"role": "user", "content": identity_payload}
                ],
                
            )
            
            raw_json = response.choices[0].message.content
            # print(f"[Debug] raw AI identity output:\n{raw_json}")
            
            import re
            json_match = re.search(r'\{[\s\S]*\}', raw_json)
            if json_match:
                clean_json = json_match.group(0)
            else:
                clean_json = raw_json.strip()

            loaded_json = json.loads(clean_json)
            
            valid_map = {}
            for key, val in loaded_json.items():
                if str(key).startswith("SPEAKER_"):
                     if isinstance(val, dict):
                         val = str(val.get('name', list(val.values())[0] if val else 'Unknown'))
                     elif isinstance(val, list):
                         val = str(val[0]) if val else 'Unknown'
                     valid_map[key] = str(val)
                     
            speaker_map = valid_map
            
            print(f"👥 AI Resolved Speaker Map:\n{json.dumps(speaker_map, indent=4)}")
                
        except Exception as e:
            speaker_map = {}
            print(f"⚠️ Warning: AI Identity mapping failed. Defaulting to raw/heuristic tags. Details: {e}")
    else:
        speaker_map = {}
    
    print(f"✅ Diarization and Identity Resolution complete. ({time.time() - diarization_start_time:.2f}s)")

    session_manifest = {
        "session_file": os.path.abspath(input_path),
        "speaker_identities": speaker_map,
        "campaign_metadata": {
            "campaign_name": REGISTRY.get("campaign_name", "Unknown Campaign"),
            "reference_lexicon": REGISTRY.get("entities", [])
        },
        "transcript": processed_transcript
    }

    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(session_manifest, f, indent=4, ensure_ascii=False)
        
    print(f"🎉 Success! Identity mapping updated in: {output_json_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Linux Optimized DnD Identity Mapper.")
    parser.add_argument("campaign", help="Name of the campaign (e.g. 'netherdeep')")
    parser.add_argument("session", type=int, help="Session number (e.g. 1)")
    parser.add_argument("-f", "--force", action="store_true", help="Force overwrite if the session directory already exists.")
    parser.add_argument("-u", "--api-url", default=None, help="Optional OpenAI-compatible API endpoint (e.g., https://api.openai.com/v1)")
    parser.add_argument("-k", "--api-key", default=None, help="API Key for remote endpoint. Overrides local secrets.json")
    parser.add_argument("-m", "--model", default="qwen2.5", help="Model to use for summarization. Default: qwen2.5. Good remote choice: gpt-4o")
    from utils import apply_defaults
    apply_defaults(parser, 'diarize.py')
    args = parser.parse_args()
    
    run_diarization(args.campaign, args.session, force_overwrite=args.force, api_url=args.api_url, api_key=args.api_key, model_name=args.model)
