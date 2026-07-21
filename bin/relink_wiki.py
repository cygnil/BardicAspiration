import argparse
import json
import os
import re
import sys

def relink_wiki(campaign):
    wiki_dir = os.path.join("campaigns", campaign, "wiki")
    if not os.path.exists(wiki_dir):
        print(f"❌ Error: Wiki directory not found for campaign '{campaign}'.")
        sys.exit(1)

    index_path = os.path.join(wiki_dir, "index.json")
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            wiki_index = json.load(f)
    except Exception:
        wiki_index = {"entities": {}}

    valid_files = set(f for f in os.listdir(wiki_dir) if f.endswith(".md"))

    # Build mapping of entity names to markdown files
    entity_map = {}
    for entity_key, file_name in wiki_index.get("entities", {}).items():
        if file_name in valid_files:
            name_str = entity_key.replace("_", " ")
            entity_map[name_str.lower()] = file_name
    
    # Pull any extra keywords from registry
    registry_path = os.path.join("campaigns", campaign, "campaign_registry.json")
    if os.path.exists(registry_path):
        try:
            with open(registry_path, "r", encoding="utf-8") as f:
                reg_data = json.load(f)
                for ent in reg_data.get("entities", []):
                    # Attempt to correlate the registry entity with a real wiki file
                    for test_key in ["character_full_name", "character_short_name", "name"]:
                        val = ent.get(test_key, "")
                        if not val: continue
                        
                        likely_file = val.replace(" ", "_").lower() + ".md"
                        if likely_file in valid_files:
                            # We found the associated file! Bind all its aliases.
                            aliases = []
                            aliases.append(ent.get("character_full_name"))
                            aliases.append(ent.get("character_short_name"))
                            aliases.append(ent.get("name"))
                            aliases.extend(ent.get("keywords", []))
                            
                            for a in aliases:
                                if a and a.lower() not in entity_map:
                                    entity_map[a.lower()] = likely_file
                            break # Move to next entity
        except Exception:
            pass

    # Sort entities by length descending to match "Ifolon River" before "Ifolon", preventing partial-match bugs
    sorted_entities = sorted(entity_map.items(), key=lambda x: len(x[0]), reverse=True)

    broken_links_fixed = 0
    new_links_added = 0

    print(f"🔍 Scanning {len(valid_files)} wiki entries...")

    for current_file in valid_files:
        file_path = os.path.join(wiki_dir, current_file)
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        original_content = content
        
        # Step 1: Remove broken markdown links
        def fix_broken_links(match):
            nonlocal broken_links_fixed
            text = match.group(1)
            link = match.group(2)
            if link not in valid_files:
                broken_links_fixed += 1
                return text
            return match.group(0)

        content = re.sub(r'\[([^\]]+)\]\(([^)]+\.md)\)', fix_broken_links, content)

        # Step 2: Add missing links
        # Protect frontmatter, existing links, and headings by splitting them out
        pattern = re.compile(r'(\A---[\s\S]*?^---|\[[^\]]+\]\([^)]+\)|^#+ .*$)', re.MULTILINE)
        blocks = pattern.split(content)
        
        for i in range(0, len(blocks)):
            if not blocks[i]: continue
            
            # Check if this block is protected
            if blocks[i].startswith('---') or blocks[i].startswith('[') or blocks[i].startswith('#'):
                continue
            
            text_part = blocks[i]
            placeholders = {}
            p_counter = 0

            # Loop over every known entity and search the remaining unlinked text
            for name_lower, target_file in sorted_entities:
                if target_file == current_file:
                    continue 
                    
                # Find occurrences (whole words) matching the entity name
                find_pattern = re.compile(r'\b(' + re.escape(name_lower) + r')\b', re.IGNORECASE)
                
                # Protect newly added links by using a temporary token during the replacement loop
                # This prevents "Steve" from overwriting the inside of "[Disco Steve](...)"
                def add_link(match):
                    nonlocal new_links_added, p_counter
                    new_links_added += 1
                    pid = f"@@@LINK{p_counter}@@@"
                    placeholders[pid] = f"[{match.group(1)}]({target_file})"
                    p_counter += 1
                    return pid
                    
                text_part = find_pattern.sub(add_link, text_part)
            
            # Restore all protected tokens created in this block
            for pid, actual_link in placeholders.items():
                text_part = text_part.replace(pid, actual_link)

            blocks[i] = text_part
        
        new_content = "".join(blocks)
        
        if new_content != original_content:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"  🔗 Updated connections in {current_file}")
            
    print(f"\n✅ Relinking complete!")
    print(f"   - Removed {broken_links_fixed} broken/stale links.")
    print(f"   - Pushed {new_links_added} retroactive cross-references into the text.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scan and repair/add markdown cross-links in the wiki.")
    parser.add_argument("campaign", help="Name of the campaign")
    args = parser.parse_args()
    relink_wiki(args.campaign)
