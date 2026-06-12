#!/bin/bash
# Double-click once after cloning to install everything needed.
cd "$(dirname "$0")"

echo "=== Embroidery Opportunity Finder — first-time setup ==="
echo ""

echo "[1/3] Installing Python packages..."
pip3 install -r requirements.txt

echo ""
echo "[2/3] Installing the headless browser for scraping..."
python3 -m playwright install chromium

echo ""
echo "[3/3] Checking Ollama (local AI)..."
if command -v ollama >/dev/null 2>&1; then
  echo "  Ollama found. Make sure a model is pulled, e.g.:"
  echo "    ollama pull gemma4:31b-cloud"
else
  echo "  Ollama NOT found. Install it from https://ollama.com to enable AI scoring."
  echo "  (The dashboard still runs without it; AI features will be limited.)"
fi

echo ""
echo "=== Setup complete! ==="
echo "Now double-click 'Start Dashboard.command' to open the app."
echo ""
read -p "Press Enter to close..."
