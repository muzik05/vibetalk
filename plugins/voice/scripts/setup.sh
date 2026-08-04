#!/bin/bash
# Установка зависимостей голосового режима. Идемпотентен — можно запускать повторно.
set -e
VOICE_HOME="${VOICE_HOME:-$HOME/.voice-assistant}"
VOICES="$VOICE_HOME/voices"
mkdir -p "$VOICES"

echo "== python-зависимости =="
python3 -m pip install --user -q faster-whisper piper-tts numpy

echo "== голоса piper (ru/uk/en, ~200 МБ суммарно) =="
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"
declare -A URLS=(
  ["ru_RU-irina-medium.onnx"]="$BASE/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx"
  ["ru_RU-irina-medium.onnx.json"]="$BASE/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx.json"
  ["uk_UA-ukrainian_tts-medium.onnx"]="$BASE/uk/uk_UA/ukrainian_tts/medium/uk_UA-ukrainian_tts-medium.onnx"
  ["uk_UA-ukrainian_tts-medium.onnx.json"]="$BASE/uk/uk_UA/ukrainian_tts/medium/uk_UA-ukrainian_tts-medium.onnx.json"
  ["en_US-lessac-medium.onnx"]="$BASE/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
  ["en_US-lessac-medium.onnx.json"]="$BASE/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
  ["ru_RU-denis-medium.onnx"]="$BASE/ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx"
  ["ru_RU-denis-medium.onnx.json"]="$BASE/ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx.json"
  ["ru_RU-dmitri-medium.onnx"]="$BASE/ru/ru_RU/dmitri/medium/ru_RU-dmitri-medium.onnx"
  ["ru_RU-dmitri-medium.onnx.json"]="$BASE/ru/ru_RU/dmitri/medium/ru_RU-dmitri-medium.onnx.json"
)
for f in "${!URLS[@]}"; do
  [ -s "$VOICES/$f" ] || curl -sL -o "$VOICES/$f" "${URLS[$f]}"
done

[ -s "$VOICE_HOME/lang" ] || echo auto > "$VOICE_HOME/lang"
[ -s "$VOICE_HOME/voices.conf" ] || printf 'ru=ru_RU-irina-medium.onnx\nuk=uk_UA-ukrainian_tts-medium.onnx:1\nen=en_US-lessac-medium.onnx\n' > "$VOICE_HOME/voices.conf"
touch "$VOICE_HOME/transcript.jsonl"

echo "== проверка звука =="
if command -v pactl >/dev/null; then
  pactl list short sources | grep -q ec_mic || \
    pactl load-module module-echo-cancel "aec_method=webrtc source_name=ec_mic sink_name=ec_out" >/dev/null || true
  echo "ok: pipewire/pulse найден"
else
  echo "ВНИМАНИЕ: pactl не найден (не Linux?) — эхоподавление и перебивание недоступны, работайте в наушниках"
fi

echo "== готово: модель распознавания докачается при первом запуске =="
