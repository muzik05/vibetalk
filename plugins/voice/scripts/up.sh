#!/bin/bash
# VibeTalk helper. Modes: (default) prep — echo-cancel, unmute, process statuses; wait — wait for listener readiness; off — stop listener and panel.
VOICE_HOME="${VOICE_HOME:-$HOME/.voice-assistant}"
mkdir -p "$VOICE_HOME"

alive() {
    local pid
    pid="$(cat "$VOICE_HOME/$1" 2>/dev/null)" || return 1
    [ -n "$pid" ] || return 1
    [ "$(ps -p "$pid" -o comm= 2>/dev/null)" = "python3" ] && \
        ps -p "$pid" -o args= 2>/dev/null | grep -q "$2"
}

case "${1:-prep}" in
  prep)
    if command -v pactl >/dev/null; then
        pactl list short sources | grep -q ec_mic || \
            pactl load-module module-echo-cancel "aec_method=webrtc source_name=ec_mic sink_name=ec_out" >/dev/null || true
    fi
    rm -f "$VOICE_HOME/muted"
    alive listener.pid listener.py && echo "listener=alive" || echo "listener=dead"
    alive panel.pid panel.py && echo "panel=alive" || echo "panel=dead"
    ;;
  wait)
    for _ in $(seq 1 50); do
      if alive listener.pid listener.py && \
         tail -30 "$VOICE_HOME/listener.log" 2>/dev/null | grep -q "слушаю"; then
        echo ready
        exit 0
      fi
      sleep 0.5
    done
    echo "timeout"
    exit 1
    ;;
  off)
    for p in listener panel; do
      pid="$(cat "$VOICE_HOME/$p.pid" 2>/dev/null)" || continue
      if [ -n "$pid" ] && [ "$(ps -p "$pid" -o comm= 2>/dev/null)" = "python3" ]; then
        kill "$pid" 2>/dev/null
      fi
    done
    echo "off"
    ;;
esac
