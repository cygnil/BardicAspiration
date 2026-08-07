#!/usr/bin/env python3

import time
import argparse
import json
import os
import sys
import threading
import re

from utils import get_api_client, animate_spinner

def get_transcript_path(campaign, session_str):
    return os.path.join("campaigns", campaign, "sessions", session_str, "transcript.json")

def load_transcript(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def merge_intervals(intervals, threshold=0):
    if not intervals:
        return []

    # Sort intervals by start time
    intervals.sort(key=lambda x: x[0])

    merged = [intervals[0]]
    for current_start, current_end in intervals[1:]:
        last_start, last_end = merged[-1]

        # If the current interval overlaps with or is exactly adjacent to the previous one
        if current_start <= last_end + threshold:
            # Merge them
            merged[-1] = (last_start, max(last_end, current_end))
        else:
            # They don't overlap, so add the current one to the list
            merged.append((current_start, current_end))

    return merged

def get_text_for_interval(transcript, start, end):
    text_blocks = []
    
    # We might have metrics and segments depending on what kind of pipeline ran this
    # Adjust according to how your transcript.json is formatted
    segments = transcript.get("transcript", transcript) # fallback if transcript is just a list
    
    for segment in segments:
        if isinstance(segment, dict):
            seg_start = segment.get("start", 0)
            seg_end = segment.get("end", 0)
            
            # If segment overlaps with interval
            if seg_end >= start and seg_start <= end:
                text_blocks.append(segment.get("text", "").strip())
            
    return " ".join(text_blocks)

def add_to_wiki(campaign, term, window=30, force=False, model_name="qwen2.5", api_url=None, api_key=None):
    start_time = time.time()
    
    target_dir = os.path.join("campaigns", campaign, "sessions")
    if not os.path.exists(target_dir):
        print(f"❌ Error: Campaign '{campaign}' not found.")
        sys.exit(1)
        
    print(f"🔍 Scanning transcripts in '{campaign}' for '{term}'...")
    
    all_sessions = sorted([d for d in os.listdir(target_dir) if d.isdigit()])
    
    if not all_sessions:
        print("No sessions found to scan.")
        sys.exit(0)
        
    term_pattern = re.compile(re.escape(term), re.IGNORECASE)
    
    total_occurrences = 0
    merged_contexts_by_session = {}
    
    for session_str in all_sessions:
        t_path = get_transcript_path(campaign, session_str)
        if not os.path.exists(t_path):
            continue
            
        transcript = load_transcript(t_path)
        segments = transcript.get("transcript", transcript)
        
        intervals = []
        
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            text = segment.get("text", "")
            if term_pattern.search(text):
                total_occurrences += 1
                seg_start = segment.get("start", 0)
                seg_end = segment.get("end", 0)
                
                # Create window around this occurrence
                intervals.append((max(0, seg_start - window), seg_end + window))
                
        if intervals:
            # Merge overlapping time windows for this session
            merged = merge_intervals(intervals)
            
            contexts = []
            for start, end in merged:
                ctx = get_text_for_interval(transcript, start, end)
                if ctx:
                    contexts.append(f"[{start:.1f}s - {end:.1f}s]: {ctx}")
                    
            if contexts:
                merged_contexts_by_session[session_str] = contexts
                
    print(f"Found {total_occurrences} total occurrences of '{term}'.")
    
    if total_occurrences == 0:
        print(f"'{term}' was not found in any transcripts. Exiting.")
        sys.exit(0)
    elif total_occurrences > 500 and not force:
        print(f"⚠️ '{term}' is extremely common ({total_occurrences} occurrences).")
        print("Feeding this into the agent would be too massive/costly.")
        print("Be more specific, or run with --force if you intentionally want to process this many.")
        sys.exit(0)
        
    # Build complete chronological prompt block
    full_context_text = f"Occurrences of '{term}' chronologically by session:\n\n"
    
    for session_str, contexts in merged_contexts_by_session.items():
        full_context_text += f"### SESSION {session_str}\n"
        for ctx in contexts:
            full_context_text += f"{ctx}\n"
        full_context_text += "\n"
        
    print(f"Compaction resulting in context size of approx {len(full_context_text.split())} words.")
    
    # Load researcher prompt, or fall back to system prompt
    try:
        with open("prompts/researcher.txt", "r", encoding="utf-8") as f:
            system_prompt = f.read()
    except FileNotFoundError:
        print("prompts/researcher.txt not found. Using generic system prompt.")
        system_prompt = f"""You are a dedicated lore archivist for a tabletop roleplaying campaign. 
Your task is to create a well-structured wiki entry for a specific entity, concept, or location.

You will be provided with chronological transcript snippets where this term was discussed. 
Analyze the snippets, ignore random out-of-character banter unless it specifically defines the term, and synthesize all facts into a clean markdown document.

Format the output strictly as Markdown. Do not include introductory conversational filler.
Include these sections if relevant: 
- Description
- History/Chronology 
- Relationships/Affiliations."""

    prompt = f"Term to document: {term}\n\n{full_context_text}"
    
    # Init client
    client = get_api_client(api_url, api_key)
    
    print(f"🧠 Asking the agent to build a wiki entry for '{term}'...")
    
    stop_event = threading.Event()
    spinner_thread = threading.Thread(target=animate_spinner, args=(stop_event, "Generating Wiki Entry"))
    spinner_thread.start()
    
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )
        wiki_entry = response.choices[0].message.content
        stop_event.set()
        spinner_thread.join()
    except Exception as e:
        stop_event.set()
        spinner_thread.join()
        print(f"\n❌ API Error: {e}")
        sys.exit(1)
        
    print("\n✅ Entry generated successfully.")
    
    # Decide where to put it. 
    # For now, put it in 'other' unless we do category detection.
    wiki_dir = os.path.join("campaigns", campaign, "wiki")
    out_dir = os.path.join(wiki_dir, "other")
    os.makedirs(out_dir, exist_ok=True)
    
    safe_term = "".join(c for c in term if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_").lower()
    if not safe_term:
        safe_term = "unknown_term"
        
    out_path = os.path.join(out_dir, f"{safe_term}.md")
    
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(wiki_entry)
        
    print(f"📖 Saved wiki entry to {out_path}")
    
    # Update index so it's linked in the future
    index_path = os.path.join(wiki_dir, "index.json")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            wiki_index = json.load(f)
    else:
        wiki_index = {"entities": {}}
        
    if "entities" not in wiki_index:
        wiki_index["entities"] = {}
        
    # Check if term already exists in index
    # We want the index keys to be fully lowercased and stripped of punctuation just like safe_term but preserve actual value
    entity_key = "".join(c for c in term if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_").lower()
    if not entity_key:
        entity_key = "unknown_term"
        
    if entity_key not in wiki_index["entities"]:
        wiki_index["entities"][entity_key] = f"other/{safe_term}.md"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(wiki_index, f, indent=4)
        print(f"Updated wiki index.json with new entry.")
    else:
        print(f"Term '{entity_key}' already exists in index.json (overwriting file content only).")
            
    print(f"Done in {time.time() - start_time:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scan transcripts and add a targeted wiki entry.")
    parser.add_argument("campaign", help="Target campaign name (e.g. netherdeep)")
    parser.add_argument("term", help="Term to search for and document")
    parser.add_argument("--window", "-w", type=float, default=30, help="Seconds of context before and after the term mention (default 30)")
    parser.add_argument("--force", action="store_true", help="Force processing even if term mentions > 500")
    
    parser.add_argument("--model", "-m", type=str, default="qwen2.5", help="Model to use (default qwen2.5)")
    parser.add_argument("--url", "-u", type=str, help="Override API base URL")
    parser.add_argument("--key", "-k", type=str, help="Override API key")
    parser.add_argument("--local", action="store_true", help="Force local inference usage and ignore defaults.json API URLs.")

    from utils import apply_defaults
    apply_defaults(parser, 'add_to_wiki.py')
    args = parser.parse_args()
    
    if getattr(args, "local", False):
        args.url = None
        args.key = None

    add_to_wiki(
        campaign=args.campaign,
        term=args.term,
        window=args.window,
        force=args.force,
        model_name=args.model,
        api_url=args.url,
        api_key=args.key
    )
