#!/usr/bin/env python3

import argparse
import json
import os
import sys

def revert_wiki(campaign, session_num, changes_file=None):
    session_str = f"{str(session_num).zfill(3)}"
    target_dir = os.path.join("campaigns", campaign, "sessions", session_str)
    wiki_dir = os.path.join("campaigns", campaign, "wiki")
    index_path = os.path.join(wiki_dir, "index.json")
    
    if not changes_file:
        # Find the latest wiki_changes.json if not specified
        base = os.path.join(target_dir, "wiki_changes")
        candidates = [f"{base}.json"]
        counter = 1
        while os.path.exists(f"{base}.{counter}.json"):
            candidates.append(f"{base}.{counter}.json")
            counter += 1
            
        # The last one added to candidates might not exist if it's just the base one that we haven't checked yet
        # Let's filter to existing ones and pick the last
        existing = [c for c in candidates if os.path.exists(c)]
        if not existing:
            changes_file = None
        else:
            changes_file = existing[-1]
        
    if not changes_file or not os.path.exists(changes_file):
        print(f"❌ Error: No wiki changes file found for session {session_num}")
        sys.exit(1)
        
    print(f"⏪ Reverting changes documented in {os.path.basename(changes_file)}")
    
    with open(changes_file, "r", encoding="utf-8") as f:
        updates = json.load(f)
        
    # Load index to modify if needed
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            wiki_index = json.load(f)
    else:
        wiki_index = {"entities": {}}
        
    index_modified = False
    
    for update in updates:
        file_name = update.get("file_name")
        category = update.get("category", "other").lower().strip()
        action = update.get("action")
        pk_append = update.get("player_knowledge_append", "")
        
        if not file_name or not action or action == "none":
            continue
            
        file_name = os.path.basename(file_name)
        if not file_name.endswith(".md"):
            file_name += ".md"
            
        file_path = os.path.join(wiki_dir, category, file_name)
        entity_key = file_name.replace(".md", "")
        
        if action == "created":
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"  🗑️ Deleted created file: {file_name}")
            if entity_key in wiki_index.get("entities", {}):
                del wiki_index["entities"][entity_key]
                index_modified = True
                print(f"  🗑️ Removed {entity_key} from index.json")
                
        elif action == "appended":
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    
                if pk_append in content:
                    # Cleanly remove the appended text
                    if f"\n{pk_append}" in content:
                        content = content.replace(f"\n{pk_append}", "")
                    else:
                        content = content.replace(pk_append, "")
                        
                    # Write updated content back
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    print(f"  ⏪ Reverted append for: {file_name}")
                else:
                    print(f"  ⚠️ Warning: Could not find exact text to revert in {file_name}")
            else:
                print(f"  ⚠️ Warning: File not found for reverting append: {file_name}")
                
    if index_modified:
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(wiki_index, f, indent=4)
            
    print("✅ Revert complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Revert Wiki updates for a session.")
    parser.add_argument("campaign", help="Name of the campaign")
    parser.add_argument("session", type=int, help="Session number")
    parser.add_argument("--file", help="Specific wiki changes JSON file to revert (defaults to the most recent one)")
    args = parser.parse_args()
    
    revert_wiki(args.campaign, args.session, args.file)
