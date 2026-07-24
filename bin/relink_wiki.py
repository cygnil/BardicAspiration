import argparse
import json
import os
import re
import sys

def relink_wiki(campaign):
    wiki_dir = os.path.join('campaigns', campaign, 'wiki')
    if not os.path.exists(wiki_dir):
        print(f'❌ Wiki directory not found for {campaign}.')
        sys.exit(1)
        
    index_path = os.path.join(wiki_dir, 'index.json')
    if not os.path.exists(index_path):
        print(f'❌ index.json not found in {wiki_dir}.')
        sys.exit(1)
        
    with open(index_path, 'r', encoding='utf-8') as f:
        wiki_index = json.load(f)
        
    entities = wiki_index.get('entities', {})
    
    # We create a list of tuples: (name_lower, target_relative_path)
    sorted_entities = []
    for name, path in entities.items():
        sorted_entities.append((name.replace('_', ' ').lower(), path))

    # Sort entities by length of name to avoid sub-word overlap
    sorted_entities = sorted(sorted_entities, key=lambda x: len(x[0]), reverse=True)
    
    # Gather all valid files we can link to and relink
    valid_files = set(entities.values())
    valid_wiki_files = set(entities.values())
    
    # Add session summaries to the list of files to process and link
    sessions_dir = os.path.join('campaigns', campaign, 'sessions')
    if os.path.exists(sessions_dir):
        for root, dirs, files in os.walk(sessions_dir):
            for file in files:
                if file == 'summary.md':
                    # Path relative to wiki_dir so it plays nice with relinking math
                    rel_summary_path = os.path.relpath(os.path.join(root, file), wiki_dir).replace('\\\\\\\\', '/')
                    valid_files.add(rel_summary_path)

    broken_links_fixed = 0
    new_links_added = 0
    
    print(f'Scanning {len(valid_files)} wiki entries and session summaries...')

    for current_file in list(valid_files):
        file_path = os.path.join(wiki_dir, current_file)
        if not os.path.exists(file_path):
            continue
            
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        original_content = content
        
        # Step 1: Remove broken markdown links
        def fix_broken_links(match):
            nonlocal broken_links_fixed
            text = match.group(1)
            link = match.group(2)
            
            # Resolve relative links
            import posixpath
            base = 'dummy/wiki/'
            current_abs = posixpath.normpath(posixpath.join(base, current_file))
            current_dir_abs = posixpath.dirname(current_abs)
            target_abs = posixpath.normpath(posixpath.join(current_dir_abs, link))
            target = posixpath.relpath(target_abs, base)
            if target not in valid_wiki_files:
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
                
                # Calculate relative path from current_file to target_file
                import posixpath
                base = 'dummy/wiki/'
                current_abs = posixpath.normpath(posixpath.join(base, current_file))
                target_abs = posixpath.normpath(posixpath.join(base, target_file))
                current_dir_abs = posixpath.dirname(current_abs)
                rel_target = posixpath.relpath(target_abs, current_dir_abs)
                
                def add_link(match, rel_target=rel_target):
                    nonlocal new_links_added, p_counter
                    new_links_added += 1
                    pid = f"@@@LINK{p_counter}@@@"
                    placeholders[pid] = f"[{match.group(1)}]({rel_target})"
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
    from utils import apply_defaults
    apply_defaults(parser, 'relink_wiki.py')
    args = parser.parse_args()
    relink_wiki(args.campaign)
