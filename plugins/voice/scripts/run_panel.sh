#!/bin/bash
# Panel launcher (call via run_in_background).
VOICE_HOME="${VOICE_HOME:-$HOME/.voice-assistant}"
mkdir -p "$VOICE_HOME"
cd "$(dirname "$0")" && exec python3 panel.py 2>> "$VOICE_HOME/panel.log"
