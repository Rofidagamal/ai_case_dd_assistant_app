#!/bin/bash
# Double-click (or run: bash setup_mac_linux.sh) ONCE to prepare the app.
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
echo
echo "Setup finished. Now run ./run_mac_linux.sh to start the app."
