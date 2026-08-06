#!/bin/bash
# SessionStart-хук: тихо поднимает «уши» (слушатель) и панель, если плагин настроен.
# Владение голосом (Monitor) сессия берёт только по /voice — чтобы не отвечали все сразу.
VOICE_HOME="${VOICE_HOME:-$HOME/.voice-assistant}"
DIR="$(dirname "$0")"

if [ ! -d "$VOICE_HOME/voices" ]; then
    echo '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"Голосовой плагин установлен, но ещё не настроен. Если пользователь попросит голосовой режим — выполни скилл voice (он запустит setup)."}}'
    exit 0
fi

if command -v pactl >/dev/null; then
    pactl list short sources | grep -q ec_mic || \
        pactl load-module module-echo-cancel 'aec_method=webrtc aec_args="analog_gain_control=0 digital_gain_control=0 noise_suppression=0 voice_detection=0" source_name=ec_mic sink_name=ec_out' >/dev/null 2>&1 || true
fi

# Проверка живости по pid-файлу: pgrep -f ловит мёртвые bash-обёртки, pid-файл — нет.
alive() {
    local pid
    pid="$(cat "$VOICE_HOME/$1" 2>/dev/null)" || return 1
    [ -n "$pid" ] || return 1
    [ "$(ps -p "$pid" -o comm= 2>/dev/null)" = "python3" ] && \
        ps -p "$pid" -o args= 2>/dev/null | grep -q "$2"
}

if ! alive listener.pid listener.py; then
    python3 "$DIR/listener.py" >> "$VOICE_HOME/listener.log" 2>&1 &
fi

if [ -n "$DISPLAY$WAYLAND_DISPLAY" ] && ! alive panel.pid panel.py; then
    python3 "$DIR/panel.py" >/dev/null 2>> "$VOICE_HOME/panel.log" &
fi

echo '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"Голосовой режим: слушатель и панель подняты автоматически. Голосом владеет ровно одна сессия; если пользователь просит голос здесь (/voice или «подними голосовой режим») — повесь persistent Monitor на ~/.voice-assistant/transcript.jsonl и следуй правилам скилла voice."}}'
