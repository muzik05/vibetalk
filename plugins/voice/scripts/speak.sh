#!/bin/bash
# Speak text: ./speak.sh "text" [ru|uk|en] (default ru).
# Per-language voice comes from $VOICE_HOME/voices.conf (lang=model.onnx[:speaker_id]).
# Writes $TMPDIR/speak.pid so the listener can barge-in; voice_off flag silences.
# Playback order: paplay (Linux) -> afplay (macOS) -> aplay (ALSA) -> python
# fallback, which is the only one that also works on Windows.
VOICE_HOME="${VOICE_HOME:-$HOME/.voice-assistant}"
TMP="${TMPDIR:-/tmp}"
[ -f "$VOICE_HOME/voice_off" ] && { echo "(voice off)"; exit 0; }
L="${2:-ru}"
LINE="$(grep "^$L=" "$VOICE_HOME/voices.conf" 2>/dev/null | head -1 | cut -d= -f2)"
case "$L" in
    uk) DEF="uk_UA-ukrainian_tts-medium.onnx:1" ;;
    en) DEF="en_US-lessac-medium.onnx" ;;
    *)  DEF="ru_RU-irina-medium.onnx" ;;
esac
LINE="${LINE:-$DEF}"
MODEL="${LINE%%:*}"
SPKID="${LINE#*:}"; [ "$SPKID" = "$LINE" ] && SPKID=""
SPK=""; [ -n "$SPKID" ] && SPK="-s $SPKID"
PIPER="$(command -v piper || echo "$HOME/.local/bin/piper")"
WAV="$(mktemp "$TMP/speak.XXXXXX")"
trap 'rm -f "$WAV"' EXIT
echo "$1" | OMP_NUM_THREADS=2 "$PIPER" -m "$VOICE_HOME/voices/$MODEL" $SPK -f "$WAV" 2>/dev/null || exit 1
# a newer phrase interrupts the one still playing instead of talking over it
[ -f "$TMP/speak.pid" ] && kill "$(cat "$TMP/speak.pid")" 2>/dev/null
if command -v paplay >/dev/null; then
    SINK=ec_out
    pactl list short sinks 2>/dev/null | grep -qw ec_out || SINK=@DEFAULT_SINK@
    paplay --device="$SINK" "$WAV" &
elif command -v afplay >/dev/null; then
    afplay "$WAV" &
elif command -v aplay >/dev/null; then
    aplay -q "$WAV" &
else
    # no system player — PortAudio via python works on Windows too
    python3 -c "import sys,soundfile as sf,sounddevice as sd; d,r=sf.read(sys.argv[1],dtype='float32'); sd.play(d,r); sd.wait()" "$WAV" &
fi
PID=$!
echo "$PID" > "$TMP/speak.pid"
wait "$PID"
[ "$(cat "$TMP/speak.pid" 2>/dev/null)" = "$PID" ] && rm -f "$TMP/speak.pid"
