# RPG Post-Session Pipeline

A set of tools for processing and analyzing session audio for tabletop role-playing games. It uses WhisperX for speech-to-text alignment and PyAnnote for speaker diarization.

## Prerequisites

You will need `ffmpeg` installed on your system.
To install `ffmpeg` on Ubuntu/Debian/WSL:
```bash
sudo apt update && sudo apt install -y ffmpeg
```
For Windows Native, install `ffmpeg` via winget or Scoop and ensure it's in your PATH.

You will also need Python 3.

## Installation and Setup

Select the installation script based on your operating system:

### Linux / macOS / WSL
Run the included `setup.sh` bash script:
```bash
bash setup.sh
```

### Windows Native
Run the included PowerShell script (requires PowerShell execution policies to allow local scripts, typically `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`):
```powershell
.\setup.ps1
```

Both scripts will automatically:
1. Check for `ffmpeg` availability.
2. Create a clean Python virtual environment named `dnd_env`.
3. Install PyTorch with CUDA GPU acceleration components.
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

3. **`defaults.json`**: Optional configuration JSON stored securely in the root repository. Defines base default variable mappings applied dynamically against specific tools. Use this to permanently set configuration properties like `--model` or `--api-url` globally instead of manually passing arguments to the CLI every time. 

  Supported arguments vary by script, but commonly include `--model`, `--api-url`, and `--api-key`. CLI arguments provided at runtime will override these defaults. Example structure:
  ```json
  {
      "run_pipeline.py": {
          "--model": "llama3.1:70b"
      },
      "recap.py": {
          "--model": "gpt-4o-mini",
          "--api-url": "https://api.openai.com/v1"
      }
  }
  ```

4. **`campaign_registry.json`**: Populate the newly created `campaigns/Homebrouhaha/campaign_registry.json` file with your party's lore names and keywords used in the campaign.
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
python bin/run_pipeline.py /path/to/session.mp3 my_campaign 1 -l 90 --model qwen2.5
```
- `<input>`: Path to the raw session audio file (or tracks folder)
- `<campaign>`: Name of the campaign (e.g., `netherdeep`)
- `<session>`: Session number (e.g., `1`)
- `-l`, `--length`: Target audio recap length in seconds (optional, default: 90)
- `-m`, `--model`: Target local or remote model engine (optional, default: qwen2.5)
- `-u`, `--api-url`: API URL for remote inference (optional)
- `-k`, `--api-key`: API Key for remote inference (optional)
- `-n`, `--next`: Peek at next session's summary to target foreshadowing (optional)
- `--skip`: List of step numbers to skip (1-9) (optional, e.g. `--skip 1 3`)
- `--info`: Optional raw JSON string of extra session metadata to inject (optional)

### Pipeline Steps (For `--skip`)

The pipeline consists of the following 9 steps. You can pass these numbers to the `--skip` argument to bypass specific stages (e.g., `--skip 1 2 3`):

1. **WhisperX Audio Transcription** (`transcribe.py`): Speech-to-text transcription with alignment.
2. **Speaker Reference Sample Extraction** (`extract_samples.py`): Extracts audio samples for each detected speaker.
3. **Scribe Identity Resolution** (`diarize.py`): Speaker diarization and identity mapping.
4. **Zero-Shot Emotional & Contextual Inference** (`annotate.py`): Adds emotional and contextual annotations to the transcript.
5. **Visual Summary Generation** (`visualize.py`): Generates visual timelines and summaries (e.g., HTML/CSS views).
6. **LLM Context Mapping & Session Summary Synthesis** (`summarize.py`): AI-driven summary of the session.
7. **Librarian Automated Entity Tracking** (`update_wiki.py`): Updates the campaign wiki with new entities.
8. **Wiki Markdown Retroactive Entity Linker** (`relink_wiki.py`): Cross-references and links entities across wiki markdowns.
9. **Pydub Cinematic Audio Recap Splicing** (`recap.py`): Generates the final cinematic audio recap.

## Web Hosting

The generated files and campaign wiki are designed to be easily hosted as a static website. The root `www/` directory contains the core HTML, CSS, and JS components to display and navigate your campaigns.

To host your generated campaigns online:
1. Upload the entire `www/` directory to the root of your web server or static hosting provider (like GitHub Pages, Vercel, or an Apache/Nginx server).
2. Copy the entire `campaigns/` directory generated by the pipeline directly into the `www/` directory on your server (resulting in `www/campaigns/`).
3. The web app uses client-side JavaScript to discover and load the JSON manifests from `www/campaigns/`, allowing it to serve as a fully self-contained wiki, transcription viewer, and audio player without requiring a backend database.
