import argparse
import os
import sys
import json
import re

def create_markdown_link(text_match, entity_type, entity_id):
    """Generates a Markdown link string given the matched text and entity details."""
    # Assuming the relative path from a session directory up to the wiki
    # We are in campaigns/<campaign>/sessions/<session_num>/summary.md
    # So we need to go up two directories (sessions, <campaign>) to reach wiki
    path = f"../../wiki/{entity_type}/{entity_id}.md"
    return f"[{text_match}]({path})"

def update_summary_links(campaign, session_num):
    session_str = f"{str(session_num).zfill(3)}"
    campaign_dir = os.path.join("campaigns", campaign)
    session_dir = os.path.join(campaign_dir, "sessions", session_str)
    summary_path = os.path.join(session_dir, "summary.md")
    wiki_index_path = os.path.join(campaign_dir, "wiki", "index.json")

    # 1. Verify necessary files exist
    if not os.path.exists(summary_path):
        print(f"❌ View error - No summary found at {summary_path}")
        return
        
    if not os.path.exists(wiki_index_path):
        print(f"❌ Index error - No wiki index found at {wiki_index_path}")
        return

    # 2. Load the Wiki Index
    print(f"📂 Loading Wiki Index from {wiki_index_path}...")
    try:
        with open(wiki_index_path, 'r', encoding='utf-8') as f:
            wiki_index = json.load(f)
    except Exception as e:
        print(f"❌ Failed to parse wiki index: {e}")
        return

    # 3. Compile regex patterns for entity aliases
    # Map entity_id -> (type, regex_pattern)
    entity_patterns = {}
    
    # We iterate over all entities in the index
    for category, entities in wiki_index.items():
        if not isinstance(entities, dict): continue # skip non-entity groups like metadata if they exist
        for entity_id, entity_path in entities.items():
            # load the actual markdown file to get the frontmatter name/aliases
            entity_full_path = os.path.join(campaign_dir, "wiki", entity_path)
            if not os.path.exists(entity_full_path): continue
            
            name = ""
            aliases = []
            
            try:
                with open(entity_full_path, 'r', encoding='utf-8') as ef:
                    content = ef.read()
                    
                    # Extract frontmatter bounded by ---
                    fm_match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL)
                    if fm_match:
                        fm_text = fm_match.group(1)
                        # primitive yaml parsing for our specific fields
                        name_match = re.search(r'^name:\s*(.+)$', fm_text, re.MULTILINE)
                        if name_match:
                            name = name_match.group(1).strip().strip('"\'')
                            
                        aliases_match = re.search(r'^aliases:\s*\[(.*?)\]', fm_text, re.MULTILINE)
                        if aliases_match:
                            # split by comma, strip quotes and spaces
                            alias_str = aliases_match.group(1)
                            for a in alias_str.split(','):
                                clean_a = a.strip().strip('"\'')
                                if clean_a: aliases.append(clean_a)
            except Exception as e:
                print(f"Failed to read frontmatter from {entity_path}: {e}")
                continue

            
            if not name: continue
            
            # The type is actually the first part of the generated entity_path
            entity_type = entity_path.split('/')[0]
            
            # Combine name and aliases, sort by length descending to match longest phrases first
            all_names = [name] + [a for a in aliases if a]
            # Escape regex characters in names just in case
            escaped_names = [re.escape(n) for n in all_names]
            
            # Create a regex that will match any of these names as whole words
            # The (?i) makes it case-insensitive. 
            # \b ensures word boundaries so "Bob" doesn't match inside "Bobcat"
            pattern_str = r'(?i)\b(' + '|'.join(escaped_names) + r')\b'
            
            try:
                pattern = re.compile(pattern_str)
                entity_patterns[entity_id] = {
                    'type': entity_type,
                    'pattern': pattern,
                    'name': name
                }
            except Exception as e:
                print(f"⚠️ Warning: Could not compile regex for {name} ({e})")
                
    if not entity_patterns:
        print("ℹ️ No entities found in wiki index to link.")
        return

    # 4. Load the summary
    print(f"📖 Loading Summary from {summary_path}...")
    with open(summary_path, 'r', encoding='utf-8') as f:
        summary_content = f.read()

    # 5. Iteratively replace entity names with links
    # Be careful not to replace names inside existing Markdown links!
    # A simple but rugged approach: Temporarily obfuscate existing links, do replacements, then restore them.
    
    # regex for markdown links: [text](link)
    link_pattern = re.compile(r'\[([^\]]+)\]\([^\)]+\)')
    existing_links = []
    
    def stash_link(match):
        existing_links.append(match.group(0))
        return f"__STASHED_LINK_{len(existing_links) - 1}__"
        
    summary_content = link_pattern.sub(stash_link, summary_content)
    
    # Now that links are stashed, we can do our entity replacements safely.
    # To avoid double-linking (e.g. if one alias is a substring of another), we process by length of primary name descending
    # But since we already sort aliases inside the regex, we just need to ensure we don't match the newly inserted markdown text.
    # We will do replacement entity by entity. 
    
    print(f"🔗 Relinking entities in summary...")
    links_added = 0
    
    for entity_id, data in sorted(entity_patterns.items(), key=lambda x: len(x[1]['name']), reverse=True):
        pattern = data['pattern']
        entity_type = data['type']
        
        # We need a custom replacement function to use the exact matched text
        def replace_with_link(match):
            nonlocal links_added
            links_added += 1
            matched_text = match.group(1)
            return create_markdown_link(matched_text, entity_type, entity_id)
            
        summary_content = pattern.sub(replace_with_link, summary_content)

    # 6. Restore stashed links
    for i, original_link in enumerate(existing_links):
        summary_content = summary_content.replace(f"__STASHED_LINK_{i}__", original_link)

    # 7. Write back
    print(f"💾 Saving updated summary (added ~{links_added} links)...")
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(summary_content)
        
    print(f"✅ Success! Summary cross-referenced with wiki.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cross-references a session summary against the wiki index, adding Markdown links.")
    parser.add_argument("campaign", help="Target campaign name (e.g., netherdeep)")
    parser.add_argument("session", type=int, help="Target session number (e.g., 1)")
    args = parser.parse_args()

    update_summary_links(args.campaign, args.session)