#!/bin/bash
# Кнопка «голос вкл/выкл». Повесь на хоткей: Настройки -> Клавиатура -> Свои сочетания.
VOICE_HOME="${VOICE_HOME:-$HOME/.voice-assistant}"
if [ -f "$VOICE_HOME/voice_off" ]; then
    rm -f "$VOICE_HOME/voice_off"
    command -v notify-send >/dev/null && notify-send -t 2000 "Клод" "Голос включён"
else
    touch "$VOICE_HOME/voice_off"
    [ -f /tmp/speak.pid ] && kill "$(cat /tmp/speak.pid)" 2>/dev/null
    command -v notify-send >/dev/null && notify-send -t 2000 "Клод" "Голос выключен"
fi
