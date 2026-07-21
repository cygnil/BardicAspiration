import argparse
import json
import os
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import datetime

def format_time(x, pos):
    """Formatter to convert seconds into HH:MM:SS format."""
    return str(datetime.timedelta(seconds=int(x)))

def generate_graph(campaign_name, session_num):
    # Establish directory structures
    session_str = f"{str(session_num).zfill(3)}"
    target_dir = os.path.join("campaigns", campaign_name, "sessions", session_str)
    
    # Check for annotated first, fallback to standard transcript
    annotated_path = os.path.join(target_dir, "transcript_annotated.json")
    standard_path = os.path.join(target_dir, "transcript.json")
    
    if os.path.exists(annotated_path):
        input_path = annotated_path
    elif os.path.exists(standard_path):
        input_path = standard_path
    else:
        print(f"❌ Error: Found neither annotated nor core transcript in '{target_dir}'.")
        return

    graphs_dir = os.path.join(target_dir, "graphs")
    os.makedirs(graphs_dir, exist_ok=True)
    output_image_path_analytics = os.path.join(graphs_dir, "analytics_graph.png")
    output_image_path_speakers = os.path.join(graphs_dir, "speaker_time_graph.png")

    with open(input_path, "r", encoding="utf-8") as f:
        session_manifest = json.load(f)

    title = session_manifest.get("recap_title", "Session Graph")
    transcript = session_manifest.get("transcript", [])
    
    if not transcript:
        print("❌ Error: Transcript is empty, nothing to graph.")
        return
        
    times = []
    
    # Store tuples of (time, value) to filter out missing/zero inputs
    humor_data = []
    drama_data = []
    emotion_data = []
    
    pos_ic_data = []
    neg_ic_data = []

    for seg in transcript:
        # Use segment start time (in seconds) or index if time not available
        t = seg.get("start", len(times))
        times.append(t)
        
        if "humor" in seg and seg["humor"] > 0:
            humor_data.append((t, seg["humor"]))
            
        if "drama" in seg and seg["drama"] > 0:
            drama_data.append((t, seg["drama"]))
        
        # Determine raw cumulative emotion sum for the segment, clipped at 1.0
        emo_dict = seg.get("emotions", {})
        if emo_dict:
            emo_weight = sum(emo_dict.values())
            emo_weight = min(emo_weight, 1.0)
            if emo_weight > 0:
                emotion_data.append((t, emo_weight))
        
        ic = seg.get("in_character", 0.0)
        if ic > 0:
            pos_ic_data.append((t, ic))
        elif ic < 0:
            neg_ic_data.append((t, ic))

    # Unpack tuples to (times, values) for plotting. Use empty lists if no valid data.
    humor_t, humor_v = zip(*humor_data) if humor_data else ([], [])
    drama_t, drama_v = zip(*drama_data) if drama_data else ([], [])
    emo_t, emo_v = zip(*emotion_data) if emotion_data else ([], [])
    pos_ic_t, pos_ic_v = zip(*pos_ic_data) if pos_ic_data else ([], [])
    neg_ic_t, neg_ic_v = zip(*neg_ic_data) if neg_ic_data else ([], [])

    # Create the analytics plot
    fig1, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True)
    fig1.suptitle(f"{title} - Session Analytics", fontsize=16)
    
    # Create the pie chart plot
    fig2 = plt.figure(figsize=(10, 10))
    ax3 = fig2.add_subplot(111)
    fig2.suptitle(f"{title} - Speaking Time", fontsize=16)

    # Process speaking time per speaker
    speaker_durations = {}
    total_talk_time = 0.0
    for seg in transcript:
        speaker = seg.get("speaker", "UNKNOWN")
        speaker_identities = session_manifest.get("speaker_identities", {})
        # Map speaker key to actual name if available
        if speaker in speaker_identities:
            speaker = speaker_identities[speaker]
            
        # Ignore UNKNOWN or unresolved entries to keep the chart clean
        if speaker == "UNKNOWN" or "UNKNOWN_SPEAKER" in speaker or "Unknown" in speaker:
            continue
            
        duration = seg.get("end", 0) - seg.get("start", 0)
        if duration > 0:
            speaker_durations[speaker] = speaker_durations.get(speaker, 0) + duration
            total_talk_time += duration
            
    # Sort speakers by duration
    sorted_speakers = sorted(speaker_durations.items(), key=lambda x: x[1], reverse=True)
    speakers, durations = zip(*sorted_speakers) if sorted_speakers else ([], [])
    
    # Plot Speaker Time (Pie Chart)
    if sorted_speakers:
        def autopct_format(pct, allvals):
            absolute = int(pct/100.*sum(allvals))
            return f"{pct:.1f}%\n({format_time(absolute, None)})"
            
        ax3.pie(durations, labels=speakers, autopct=lambda pct: autopct_format(pct, durations),
                startangle=140, colors=plt.cm.Paired.colors, radius=0.7)
        ax3.set_title("Speaking Time by Player")
        ax3.axis('equal') # Equal aspect ratio ensures that pie is drawn as a circle.

    # Plot metrics from 0 to 1 on the top graph
    if emotion_data: ax1.plot(emo_t, emo_v, label="Emotion", color="red", alpha=0.7)
    if humor_data: ax1.plot(humor_t, humor_v, label="Humor", color="orange", alpha=0.7)
    if drama_data: ax1.plot(drama_t, drama_v, label="Drama", color="purple", alpha=0.7)
    ax1.set_ylabel("Intensity (0.0 to 1.0)")
    ax1.set_ylim(0, 1.1)
    ax1.legend(loc="upper right")
    ax1.grid(True, linestyle="--", alpha=0.5)

    # Plot in-character vs out-of-character from -1 to 1 on the bottom graph
    if pos_ic_data: ax2.plot(pos_ic_t, pos_ic_v, label="In-Character", color="green", alpha=0.8)
    if neg_ic_data: ax2.plot(neg_ic_t, neg_ic_v, label="Table-Talk", color="red", alpha=0.8)
    ax2.axhline(0, color="black", linestyle="-", linewidth=1.5)
    ax2.set_xlabel("Time (H:MM:SS)")
    ax2.set_ylabel("In-Character (1.0) vs Table-Talk (-1.0)")
    ax2.set_ylim(-1.1, 1.1)
    ax2.legend(loc="upper right")
    ax2.grid(True, linestyle="--", alpha=0.5)

    # Format the x-axis to show HH:MM:SS
    formatter = ticker.FuncFormatter(format_time)
    ax2.xaxis.set_major_formatter(formatter)

    # Fill areas to make it look nicer
    if pos_ic_data: ax2.fill_between(pos_ic_t, 0, pos_ic_v, facecolor='green', alpha=0.3, interpolate=True)
    if neg_ic_data: ax2.fill_between(neg_ic_t, 0, neg_ic_v, facecolor='red', alpha=0.3, interpolate=True)

    fig1.tight_layout()
    fig1.savefig(output_image_path_analytics, dpi=300)
    fig2.tight_layout()
    fig2.savefig(output_image_path_speakers, dpi=300)
    print(f"🎉 Success! Graphs saved to: {graphs_dir}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a graph of D&D session analytics.")
    parser.add_argument("campaign", help="Name of the campaign (e.g. 'netherdeep')")
    parser.add_argument("session", type=int, help="Session number (e.g. 1)")
    
    args = parser.parse_args()
    generate_graph(args.campaign, args.session)
