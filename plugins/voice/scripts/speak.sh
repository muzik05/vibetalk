#!/bin/bash
# Озвучить текст: ./speak.sh "текст" [ru|uk|en]  (по умолчанию ru)
# Пишет PID в /tmp/speak.pid — слушатель может перебить озвучку.
# Файл $VOICE_HOME/voice_off — голос выключен, выходим молча.
VOICE_HOME="${VOICE_HOME:-$HOME/.voice-assistant}"
[ -f "$VOICE_HOME/voice_off" ] && { echo "(голос выключен)"; exit 0; }
SPK=""
case "${2:-ru}" in
    uk) MODEL="uk_UA-ukrainian_tts-medium.onnx"; SPK="-s 1" ;;  # mykyta (male)
    en) MODEL="en_US-lessac-medium.onnx" ;;
    *)  MODEL="ru_RU-irina-medium.onnx" ;;
esac
PIPER="$(command -v piper || echo "$HOME/.local/bin/piper")"
echo "$1" | "$PIPER" -m "$VOICE_HOME/voices/$MODEL" $SPK -f /tmp/speak.wav 2>/dev/null || exit 1
if command -v paplay >/dev/null; then
    SINK=ec_out
    pactl list short sinks 2>/dev/null | grep -qw ec_out || SINK=@DEFAULT_SINK@
    paplay --device="$SINK" /tmp/speak.wav &
elif command -v afplay >/dev/null; then
    afplay /tmp/speak.wav &
else
    aplay -q /tmp/speak.wav &
fi
PID=$!
echo "$PID" > /tmp/speak.pid
wait "$PID"
rm -f /tmp/speak.pid
