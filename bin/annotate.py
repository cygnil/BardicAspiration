from utils import load_secrets
import argparse
import json
import os
import sys
import time
import torch
import warnings
from transformers import pipeline, AutoModelForCausalLM, AutoTokenizer, logging as hf_logging

# Suppress harmless config warnings from older models like distilgpt2
hf_logging.set_verbosity_error()
warnings.filterwarnings('ignore', category=UserWarning)

secrets = load_secrets()
HF_TOKEN = secrets.get("HF_TOKEN")

def append_surprisal_metric(segments, device):
    print("📈 Analyzing dialogue surprisal (weirdness/uniqueness)...")
    start_time = time.time()
    
    # We use a very tiny causal LM to quickly calculate perplexity/loss
    model_id = "distilgpt2"
    tokenizer = AutoTokenizer.from_pretrained(model_id, token=HF_TOKEN)
    model = AutoModelForCausalLM.from_pretrained(model_id, token=HF_TOKEN)
    
    # Move model to device
    if device == "cuda":
        model = model.to("cuda")
    
    model.eval()
    
    # Process each segment
    # It must be sequential to cleanly calculate the precise loss of each specific string
    with torch.no_grad():
        for seg in segments:
            text = seg.get("text", "").strip()
            if not text:
                seg["surprisal"] = 0.0
                continue
                
            inputs = tokenizer(text, return_tensors="pt")
            
            # If the sentence is incredibly short or somehow tokenizes to nothing
            if inputs["input_ids"].shape[1] < 2:
                seg["surprisal"] = 0.0
                continue
                
            if device == "cuda":
                inputs = {k: v.to("cuda") for k, v in inputs.items()}
                
            # By passing labels=input_ids, huggingface automatically computes the Cross Entropy Loss (surprisal)
            outputs = model(inputs["input_ids"], labels=inputs["input_ids"])
            loss = outputs.loss.item()
            
            # Record it (higher loss = higher surprisal)
            seg["surprisal"] = round(loss, 2)
            
    print(f"✅ Surprisal analysis complete. ({time.time() - start_time:.2f}s)")
    return segments

def append_emotional_valence(segments, device, emotion_threshold=0.35):
    print("🎭 Analyzing dialogue emotional valence...")
    start_time = time.time()
    # Load a highly accurate conversational emotion classifier
    classifier = pipeline("text-classification", model="j-hartmann/emotion-english-distilroberta-base", device=0 if device == "cuda" else -1, top_k=None, token=HF_TOKEN)
    
    # Process text in batches (the classifier handles list inputs efficiently)
    texts_to_classify = [seg.get("text", "") for seg in segments]
    
    emotion_results = classifier(texts_to_classify, batch_size=16)
    
    for i, seg in enumerate(segments):
        valid_emotions = {}
        # Result[i] is a list of dicts: [{'label': 'joy', 'score': 0.8}, {'label': 'neutral', 'score': 0.1}, ...]
        for emotion in emotion_results[i]:
            if emotion['score'] >= emotion_threshold and emotion['label'] != 'neutral':
                valid_emotions[emotion['label']] = round(emotion['score'], 4)
                
        # We only assign top emotions if they cross the confidence threshold
        if valid_emotions:
            seg["emotions"] = valid_emotions

    print(f"✅ Emotion analysis complete. ({time.time() - start_time:.2f}s)")
    return segments

def calculate_wps(segments):
    for seg in segments:
        text = seg.get("text", "")
        start = seg.get("start", 0.0)
        end = seg.get("end", 0.0)
        duration = end - start
        
        # Avoid division by zero
        if duration > 0:
            word_count = len(text.split())
            seg["wps"] = round(word_count / duration, 2)
        else:
            seg["wps"] = 0.0
            
    return segments

def append_zero_shot_metrics(segments, device, threshold):
    print("🎲 Analyzing dialogue for in-character probability, dramatic tension, and humor...")
    start_time = time.time()
    
    # Using a stronger zero-shot classifier
    classifier = pipeline("zero-shot-classification", model="cross-encoder/nli-deberta-v3-large", device=0 if device == "cuda" else -1, token=HF_TOKEN)
    texts_to_classify = [seg.get("text", "") for seg in segments]
    
    # Analyze in-character vs out-of-character
    print("   ↳ Pass 1/3: Character Alignment...")
    candidate_labels_ic = ["in-character acting and fantasy roleplay", "out-of-character table talk and game rules"]
    results_ic = classifier(
        texts_to_classify, 
        candidate_labels_ic, 
        hypothesis_template="In a Dungeons and Dragons game, this spoken dialogue is {}.",
        batch_size=8
    )
    
    # Analyze drama vs calm
    print("   ↳ Pass 2/3: Dramatic Tension...")
    candidate_labels_drama = ["high stakes and dramatic tension", "calm and relaxed"]
    results_drama = classifier(
        texts_to_classify, 
        candidate_labels_drama, 
        hypothesis_template="This spoken dialogue is {}.",
        batch_size=8
    )

    # Analyze humor vs serious
    print("   ↳ Pass 3/3: Humor and Comedy...")
    candidate_labels_humor = ["an intentional joke and extremely funny comedy", "a normal conversation, mundane, or entirely serious"]
    results_humor = classifier(
        texts_to_classify, 
        candidate_labels_humor, 
        hypothesis_template="This spoken dialogue is {}.",
        batch_size=8
    )
    
    for i, seg in enumerate(segments):
        # Process IC scores
        res_ic = results_ic[i]
        scores_ic = dict(zip(res_ic['labels'], res_ic['scores']))
        ic_score = scores_ic.get("in-character acting and fantasy roleplay", 0)
        ooc_score = scores_ic.get("out-of-character table talk and game rules", 0)
        seg["in_character"] = round(ic_score - ooc_score, 2)
        
        # Process Drama scores
        res_drama = results_drama[i]
        scores_drama = dict(zip(res_drama['labels'], res_drama['scores']))
        drama_score = scores_drama.get("high stakes and dramatic tension", 0)
        calm_score = scores_drama.get("calm and relaxed", 0)
        drama_diff = round(drama_score - calm_score, 2)
        if drama_diff >= threshold:
            seg["drama"] = drama_diff
        
        # Process Humor scores
        res_humor = results_humor[i]
        scores_humor = dict(zip(res_humor['labels'], res_humor['scores']))
        humor_score = scores_humor.get("an intentional joke and extremely funny comedy", 0)
        serious_score = scores_humor.get("a normal conversation, mundane, or entirely serious", 0)
        humor_diff = round(humor_score - serious_score, 2)
        if humor_diff >= threshold:
            seg["humor"] = humor_diff

    print(f"✅ Context analysis complete. ({time.time() - start_time:.2f}s)")
    return segments

def process_annotation(campaign_name, session_num, emotion_threshold):
    # Establish directory structures
    session_str = f"{str(session_num).zfill(3)}"
    target_dir = os.path.join("campaigns", campaign_name, "sessions", session_str)
    input_path = os.path.join(target_dir, "transcript.json")
    output_json_path = os.path.join(target_dir, "transcript_annotated.json")
    
    if not os.path.exists(input_path):
         print(f"❌ Error: Target reference path '{input_path}' not found. You must run transcribe.py first.")
         sys.exit(1)
         
    with open(input_path, "r", encoding="utf-8") as f:
        session_manifest = json.load(f)
        
    device = "cuda" if torch.cuda.is_available() else "cpu"
    processed_transcript = session_manifest.get("transcript", [])
    
    # Calculate WPS sequentially (extremely fast CPU-bound)
    processed_transcript = calculate_wps(processed_transcript)
    
    processed_transcript = append_surprisal_metric(processed_transcript, device)
    processed_transcript = append_zero_shot_metrics(processed_transcript, device, emotion_threshold)
    processed_transcript = append_emotional_valence(processed_transcript, device, emotion_threshold)
        
    session_manifest["transcript"] = processed_transcript

    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(session_manifest, f, indent=4, ensure_ascii=False)
        
    print(f"🎉 Success! Annotated data saved to: {output_json_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Annotate D&D Transcript with Emotion.")
    parser.add_argument("campaign", help="Name of the campaign (e.g. 'netherdeep')")
    parser.add_argument("session", type=int, help="Session number (e.g. 1)")
    parser.add_argument("-e", "--emotion-threshold", type=float, default=0.35, help="Minimum probability (0-1) to preserve an emotion tag (default 0.35)")
    args = parser.parse_args()
        
    process_annotation(args.campaign, args.session, args.emotion_threshold)
