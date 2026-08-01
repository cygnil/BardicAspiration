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
echo "⬇️ Installing requirements..."
& .\dnd_env\Scripts\python.exe -m pip install -r requirements.txt

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
echo "Or just run the pipeline script:"
echo "python bin/run_pipeline.py"