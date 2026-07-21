import time
import argparse
import json
import dirtyjson
import os
import sys
import threading

from utils import get_api_client, animate_spinner

def update_wiki(campaign, session_num, force=False, model_name="qwen2.5", api_url=None, api_key=None):
    start_time = time.time()
    session_str = f"{str(session_num).zfill(3)}"
    target_dir = os.path.join("campaigns", campaign, "sessions", session_str)
    
    summary_path = os.path.join(target_dir, "summary.md")
    if not os.path.exists(summary_path):
        print(f"❌ Error: Required session summary not found at '{summary_path}'. Run summarize.py first.")
        sys.exit(1)
        
    print(f"📖 The Librarian is reviewing Session {session_num}...")
    
    with open(summary_path, "r", encoding="utf-8") as f:
        summary_text = f.read()

    # Load Librarian prompt
    try:
        with open("prompts/librarian.txt", "r", encoding="utf-8") as f:
            librarian_prompt = f.read()
    except FileNotFoundError:
        print("❌ Error: You need to create `prompts/librarian.txt`.")
        sys.exit(1)

    wiki_dir = os.path.join("campaigns", campaign, "wiki")
    index_path = os.path.join(wiki_dir, "index.json")

    # Load index to map entity names to markdown files
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            wiki_index = json.load(f)
    else:
        wiki_index = {"entities": {}}

    # Load campaign registry to give the LLM hints about names, factions, and spellings
    registry_path = os.path.join("campaigns", campaign, "campaign_registry.json")
    registry_hints = ""
    if os.path.exists(registry_path):
        with open(registry_path, "r", encoding="utf-8") as f:
            registry_data = json.load(f)
            registry_hints = f"Campaign Entity Registry (for name spelling and lore hints):\n{json.dumps(registry_data.get('entities', []), indent=2)}\n\n"

    # Pre-fetch existing wiki files for entities mentioned in the summary
    current_knowledge = ""
    filename_mapping_hints = "Available Entity Markdown Links (Use these exact paths when cross-linking):\n"
    
    if wiki_index and "entities" in wiki_index:
        wiki_snippets = []
        for entity_key, entity_file in wiki_index["entities"].items():
            match_name = entity_key.replace("_", " ")
            filename_mapping_hints += f"- [{match_name}]({entity_file})\n"
            
            # Very basic string match to see if the entity might be in the summary
            if match_name.lower() in summary_text.lower():
                try:
                    with open(os.path.join(wiki_dir, entity_file), "r", encoding="utf-8") as wf:
                        wiki_snippets.append(f"--- File: {entity_file} ---\n{wf.read()}\n")
                except Exception:
                    pass
        if wiki_snippets:
            current_knowledge = "Current Existing Wiki Knowledge for Relevant Entities:\n" + "".join(wiki_snippets) + "\n\n"

    # We will enforce JSON output format
    librarian_system_prompt = librarian_prompt + """
    
Important Output Constraints:
You must output a raw JSON array of objects, and absolutely NO OTHER text formatting or markdown wrappers. Example output:
[
  {
    "file_name": "steve.md",
    "player_knowledge_append": "- Session 1: Steve found a magical sword.\n"
  }
]
"""
    
    client = get_api_client(api_url, api_key)
    
    stop_event = threading.Event()
    spinner_thread = threading.Thread(target=animate_spinner, args=(stop_event, "The Librarian is transcribing notes into the wiki..."))
    spinner_thread.start()

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": librarian_system_prompt},
            {"role": "user", "content": f"{registry_hints}\n{filename_mapping_hints}\n{current_knowledge}Please analyze the summary for session {session_num} and generate updates:\n\n### SESSION SUMMARY\n{summary_text}"}
        ]
    )

    stop_event.set()
    spinner_thread.join()
    
    try:
        raw_json_str = response.choices[0].message.content.strip()
        # Clean up if markdown codeblocks were returned despite instructions
        if raw_json_str.startswith("```json"):
            raw_json_str = raw_json_str[7:]
        elif raw_json_str.startswith("```"):
            raw_json_str = raw_json_str[3:]
        if raw_json_str.endswith("```"):
            raw_json_str = raw_json_str[:-3]
            
        raw_json_str = raw_json_str.strip()
        
        # Use dirtyjson to robustly handle missing commas, unescaped quotes, trailing commas, etc.
        updates = dirtyjson.loads(raw_json_str)
    except Exception as e:
        print(f"\n❌ Error parsing output from LLM. It returned invalid JSON: {e}")
        print("Raw response:")
        print(response.choices[0].message.content)
        sys.exit(1)
        
    if not isinstance(updates, list):
        print(f"\n❌ Error: Output must be a list of objects. Received: {type(updates)}")
        sys.exit(1)
        
    print("\n✅ New knowledge categorized! Writing to archives...")
    
    for update in updates:
        file_name = update.get("file_name")
        if not file_name:
            continue
            
        # Ensure proper file formatting
        if not file_name.endswith(".md"):
            file_name += ".md"
            
        file_path = os.path.join(wiki_dir, file_name)
        
        # Prepare content to append
        pk_append = update.get("player_knowledge_append", "")
        
        if not pk_append:
            continue

        # Prevent duplicate session logging
        session_marker = f"Session {session_num}:"
        safe_to_write_pk = session_marker not in pk_append

        # Handle updating an existing file safely
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Prevent writing if run previously, unless forced
            if session_marker in content and not force:
                print(f"⚠️  Skipping {file_name} because updates for {session_marker} already exist. Use --force to overwrite.")
                continue
                
            # If forced, filter out previous session entries before appending the new ones
            if force and session_marker in content:
                lines = content.split('\n')
                content = '\n'.join([line for line in lines if not line.strip().startswith(f"- {session_marker}")])

            # Split logic by header
            if "## Player Knowledge" in content and pk_append:
                content = content.replace("## Player Knowledge", f"## Player Knowledge\n{pk_append}")
                safe_to_write_pk = False

            # If headers are missing somehow, append them
            if pk_append and safe_to_write_pk:
                content += f"\n## Player Knowledge\n{pk_append}"

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
                
            print(f"  📝 Updated existing entity: {file_name}")

        else:
            # Handle creating a new file
            new_content = f"""---
name: {file_name.replace('.md', '').replace('_', ' ').title()}
---
## Player Knowledge
{pk_append}
"""
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
                
            # Immediately add to master index to avoid orphaned ghost files
            entity_key = file_name.replace(".md", "")
            wiki_index["entities"][entity_key] = file_name
            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(wiki_index, f, indent=4)
                
            print(f"  ✨ Created new entity: {file_name}")

    elapsed_time = time.time() - start_time
    print("========================================================")
    print(f"📚 ARCHIVAL COMPLETE FOR THIS SESSION ({elapsed_time:.2f}s)")
    print("========================================================")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read session summary and update Wiki.")
    parser.add_argument("campaign", help="Name of the campaign")
    parser.add_argument("session", type=int, help="Session number")
    parser.add_argument("-f", "--force", action="store_true", help="Force overwrite existing session entries in the wiki")
    parser.add_argument("-m", "--model", default="qwen2.5", help="Target Ollama model engine.")
    parser.add_argument("-u", "--url", help="API URL for remote inference.")
    parser.add_argument("-k", "--key", help="API Key for remote inference.")
    
    args = parser.parse_args()
    update_wiki(args.campaign, args.session, args.force, args.model, args.url, args.key)