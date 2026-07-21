import os
import json
import argparse

def create_campaign(name):
    base_dir = os.path.join("campaigns", name)
    sessions_dir = os.path.join(base_dir, "sessions")
    wiki_dir = os.path.join(base_dir, "wiki")
    
    os.makedirs(sessions_dir, exist_ok=True)
    os.makedirs(wiki_dir, exist_ok=True)
    
    registry_path = os.path.join(base_dir, "campaign_registry.json")
    wiki_index_path = os.path.join(wiki_dir, "index.json")

    if not os.path.exists(wiki_index_path):
        wiki_index_data = {
            "entities": {}
        }
        with open(wiki_index_path, "w", encoding="utf-8") as f:
            json.dump(wiki_index_data, f, indent=4)
        print(f"📝 Created default wiki index at: {wiki_index_path}")

    if not os.path.exists(registry_path):
        registry_data = {
            "campaign_name": name,
            "entities": [
                {
                    "true_name": "Dungeon Master", 
                    "type": "Dungeon Master",
                    "keywords": ["DM", "Dungeon Master", "Narrator"]
                },
                {
                    "true_name": "Hero Name", 
                    "type": "Player Character",
                    "keywords": ["character_keyword"]
                }
            ]
        }
        with open(registry_path, "w", encoding="utf-8") as f:
            json.dump(registry_data, f, indent=4)
        print(f"📝 Created default campaign registry at: {registry_path}")
    else:
        print(f"ℹ️ Campaign registry already exists at: {registry_path}")
        
    print(f"🎉 Fully scaffolded campaign directory structure for: {name}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a new D&D campaign structure.")
    parser.add_argument("name", help="Name of the campaign directory")
    args = parser.parse_args()
    create_campaign(args.name)
