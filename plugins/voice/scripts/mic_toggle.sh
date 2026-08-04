#!/bin/bash
# Кнопка «слух вкл/выкл» (микрофон).
VOICE_HOME="${VOICE_HOME:-$HOME/.voice-assistant}"
if [ -f "$VOICE_HOME/muted" ]; then
    rm -f "$VOICE_HOME/muted"
    command -v notify-send >/dev/null && notify-send -t 2000 "Клод" "Слух включён"
else
    touch "$VOICE_HOME/muted"
    command -v notify-send >/dev/null && notify-send -t 2000 "Клод" "Слух выключен"
fi
