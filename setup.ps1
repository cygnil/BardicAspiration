# setup.ps1
# Requires PowerShell
# Creates Python environment on Windows and ensures setup

echo "🔨 Setting up BardicAspiration Windows Environment..."

# 1. Check Python
if (!(Get-Command python -ErrorAction SilentlyContinue)) {
    echo "❌ Error: Python not found. Please install Python 3.x"
    exit 1
}

# 2. Check ffmpeg
if (!(Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
     echo "⚠️ Warning: ffmpeg not found. Required for Pyannote audio processing."
     echo "Please install ffmpeg (e.g. via winget install ffmpeg or Scoop) and ensure it's in your PATH."
}

# 3. Create venv
if (!(Test-Path -Path ./dnd_env)) {
    echo "📦 Creating python virtual environment in dnd_env..."
    python -m venv dnd_env
} else {
    echo "✅ dnd_env already exists."
}

# 4. Activate and Install
echo "⬇️ Installing basic wrappers..."
& .\dnd_env\Scripts\python.exe -m pip install --upgrade pip
& .\dnd_env\Scripts\python.exe -m pip install pydub openai tqdm transformers matplotlib yt-dlp deno questionary

echo "🔥 Installing PyTorch with Windows CUDA 12.1 GPU acceleration..."
& .\dnd_env\Scripts\python.exe -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

echo "🎙️ Installing WhisperX speech-to-text alignment matrix from source..."
& .\dnd_env\Scripts\python.exe -m pip install git+https://github.com/m-bain/whisperX.git

# 5. Handle Templates
if (!(Test-Path -Path ./secrets.json)) {
    echo "📝 Creating 'secrets.json' from template..."
    if (Test-Path -Path ./secrets.template.json) {
        Copy-Item -Path ./secrets.template.json -Destination ./secrets.json
    } elseif (Test-Path -Path "secrets template.json") {
         Copy-Item -Path "secrets template.json" -Destination ./secrets.json
    } else {
        '{"HF_TOKEN": "PASTE_YOUR_HUGGINGFACE_TOKEN_HERE"}' | Out-File -FilePath ./secrets.json -Encoding utf8
    }
}

if (!(Test-Path -Path ./plugins.json)) {
    echo "📝 Creating 'plugins.json' from template..."
    if (Test-Path -Path ./plugins.template.json) {
        Copy-Item -Path ./plugins.template.json -Destination ./plugins.json
    }
}

# 6. Done
echo "✨ DONE! You can now activate your environment using:"
echo "./dnd_env/Scripts/Activate.ps1"
echo "Or just run the interactive terminal wizard:"
echo "python bin/wizard_pipeline.py"