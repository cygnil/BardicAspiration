# D&D Post-Session Pipeline

A set of tools for processing and analyzing Dungeons & Dragons session audio. It uses WhisperX for speech-to-text alignment and PyAnnote for speaker diarization.

## Prerequisites

You will need `ffmpeg` installed on your Linux system (or WSL).
To install `ffmpeg` on Ubuntu/Debian:
```bash
sudo apt update && sudo apt install -y ffmpeg
```

You will also need Python 3.

## Installation and Setup

To easily set up your environment, install the necessary dependencies, and create the required configuration templates, run the included `setup.sh` script:

```bash
bash setup.sh
```

This script will:
1. Check for `ffmpeg`.
2. Create a clean Python virtual environment named `dnd_env`.
3. Install PyTorch with CUDA 12.1 GPU acceleration.
4. Install WhisperX and other required dependencies (such as `pydub`, `openai`, `transformers`).
5. Generate template files for `secrets.json` and `campaign_registry.json` if they do not already exist.

## Configuration

After running `setup.sh`, you need to configure a few things before running the pipeline:

1. **`secrets.json`**: Update this file with your Hugging Face token, which is required for PyAnnote. Any API tokens may also be added here based on the API URL, although you can also specify them on the command line.
  ```json
  {
    "HF_TOKEN": "PASTE_YOUR_HUGGINGFACE_TOKEN_HERE",
    "API_KEYS": {
      "api.openai.com": "sk-123456..."
    }
  }
  ```

2. **Create a Campaign**: Run the initialization script to scaffold a new campaign directory (which will hold transcripts, summaries, and recaps).
  ```bash
  source dnd_env/bin/activate
  python create_campaign.py "Homebrouhaha"
  ```
  This creates `campaigns/Homebrouhaha/` containing a default registry and folders for its sessions.

3. **`campaign_registry.json`**: Populate the newly created `campaigns/Homebrouhaha/campaign_registry.json` file with your party's lore names and keywords used in the campaign.
  ```json
  {
    "campaign_name": "Homebrouhaha",
    "players": [
      {
        "player_name": "Gary",
        "type": "Dungeon Master"
      },
      {
        "player_name": "Stu",
        "type": "Player Character",
        "character_full_name": "Disco Steve",
        "character_short_name": "Steve",
        "ipa_pronunciations": ["ˈdɪskoʊ stiːv"],
        "keywords": ["Stevie"]
      }
    ],
    "entities": [
      {
        "character_full_name": "Daisy the Mortician",
        "character_short_name": "Daisy",
        "type": "NPC",
        "factions": ["The Bear Brigade"],
        "ipa_pronunciations": ["ˈdeɪ.zi ðə mɔːrˈtɪʃən"],
        "keywords": []
      },
      {
        "name": "Spira",
        "type": "Location",
        "ipa_pronunciations": ["ˈspaɪrə", "ˈspɪərə"],
        "keywords": ["The Haunted Land"]
      }
    ]
  }
  ```

## Usage

Once configured, you can run the main pipeline. Ensure your virtual environment is active:
```bash
source dnd_env/bin/activate
```

Then, execute the primary script:
```bash
python run_pipeline.py /path/to/session.mp3 my_campaign 1 -l 90 -m qwen2.5
```
- `<input>`: Path to the raw session audio file (or tracks folder)
- `<campaign>`: Name of the campaign (e.g., `netherdeep`)
- `<session>`: Session number (e.g., `1`)
- `-l`, `--length`: Target audio recap length in seconds (optional, default: 90)
- `-m`, `--model`: Target local or remote model engine (optional, default: qwen2.5)
- `-u`, `--url`: API URL for remote inference (optional)
- `-k`, `--key`: API Key for remote inference (optional)
- `-n`, `--next`: Peek at next session's summary to target foreshadowing (optional)
