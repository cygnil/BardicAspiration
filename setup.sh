#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "⚔️  D&D Post-Session Pipeline: Environment Initializer ⚔️"
echo "=========================================================="

# 1. System check for ffmpeg (required by whisperx and pydub)
if ! command -v ffmpeg &> /dev/null; then
    echo "❌ Error: ffmpeg is not installed on this Linux subsystem."
    echo "Please run: sudo apt update && sudo apt install -y ffmpeg"
    exit 1
fi

# 2. Clean out old broken environments if they exist
if [ -d "dnd_env" ]; then
    echo "🧹 Removing existing environment folder..."
    rm -rf dnd_env
fi

echo "📦 Creating fresh Python virtual environment (dnd_env)..."
python3 -m venv dnd_env

echo "🚀 Activating environment and upgrading core pip architecture..."
source dnd_env/bin/activate
pip install --upgrade pip

echo "🔥 Installing PyTorch with native Linux CUDA 12.1 GPU acceleration..."
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

echo "🎙️ Installing WhisperX speech-to-text alignment matrix from source..."
pip install git+https://github.com/m-bain/whisperX.git

echo "🎵 Installing integration wrappers (OpenAI API compatibility, Pydub & Matplotlib)..."
pip install pydub openai tqdm transformers matplotlib

echo "📂 Verifying project file structure..."
mkdir -p campaigns

# Ensure default JSON config structures exist so the primary scripts don't crash on start
if [ ! -f "secrets.json" ]; then
    echo "📝 Creating 'secrets.json' from template..."
    if [ -f "secrets template.json" ]; then
        cp "secrets template.json" secrets.json
    else
        echo '{"HF_TOKEN": "PASTE_YOUR_HUGGINGFACE_TOKEN_HERE"}' > secrets.json
    fi
fi

# The campaign registry is now managed by create_campaign.py per-campaign
# So we don't automatically drop a blank one in the root anymore.

echo "=========================================================="
echo "🎉 SETUP SUCCESSFUL!"
echo "=========================================================="
echo "Next Steps for your users:"
echo " 1. Update 'secrets.json' with their PyAnnote Hugging Face token."
echo " 2. Populate 'campaigns/<campaign_name>/campaign_registry.json' using 'python create_campaign.py'"
echo " 3. Run the master tools:"
echo "    python transcribe.py <campaign_name> <session_num> -f /path/to/session.mp3"
echo "    python annotate.py <campaign_name> <session_num>"
echo "    python visualize.py <campaign_name> <session_num>"
echo "    python summarize.py <campaign_name> <session_num>"
echo "    python recap.py <campaign_name> <session_num>"
echo "=========================================================="
