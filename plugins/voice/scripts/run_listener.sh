#!/bin/bash
# Listener launcher (call via run_in_background so the wrapper stays alive with the session).
VOICE_HOME="${VOICE_HOME:-$HOME/.voice-assistant}"
mkdir -p "$VOICE_HOME"
cd "$(dirname "$0")" && exec python3 listener.py >> "$VOICE_HOME/listener.log" 2>&1
