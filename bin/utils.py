import sys
import time
import subprocess
import json
from openai import OpenAI

def get_wsl_host_ip():
    """Dynamically parses the Linux routing table to bridge to Windows Ollama."""
    try:
        cmd = "ip route | grep default | awk '{print $3}'"
        host_ip = subprocess.check_output(cmd, shell=True).decode().strip()
        return host_ip if host_ip else "127.0.0.1"
    except Exception:
        return "127.0.0.1"

WINDOWS_HOST_IP = get_wsl_host_ip()

def load_secrets():
    try:
        with open("secrets.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def get_api_client(api_url=None, api_key=None):
    from urllib.parse import urlparse
    if api_url:
        print(f"🔗 Connected to Remote API Host at: {api_url}")
        if not api_key:
            secrets = load_secrets()
            domain = urlparse(api_url).hostname
            if domain:
                api_key = secrets.get("API_KEYS", {}).get(domain)
        return OpenAI(base_url=api_url, api_key=api_key if api_key else "dummy_key")
    else:
        print(f"🔗 Connected to Windows Ollama Host at: http://{WINDOWS_HOST_IP}:11434")
        return OpenAI(base_url=f"http://{WINDOWS_HOST_IP}:11434/v1", api_key="ollama")

def animate_spinner(stop_event, message):
    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    idx = 0
    while not stop_event.is_set():
        sys.stdout.write(f"\r{spinner[idx % len(spinner)]} {message}")
        sys.stdout.flush()
        idx += 1
        time.sleep(0.1)
    sys.stdout.write(f"\r{' ' * (len(message) + 2)}\r")
