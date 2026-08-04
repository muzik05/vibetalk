---
name: voice
description: Start voice mode — background microphone listener (local STT), floating control panel, spoken replies (RU/UK/EN), wake-up monitor. Invoke via /voice or when the user asks to "start voice mode" / «подними голосовой режим».
---

# Voice mode

Plugin scripts: `${CLAUDE_PLUGIN_ROOT}/scripts/` (listener.py, speak.sh, panel.py, setup.sh, toggle.sh, mic_toggle.sh). Runtime state (transcript, flags, voices, logs): `~/.voice-assistant/` (below: `$VH`).

## Startup steps

1. First-time setup: if `$VH/voices` with `*.onnx` files is missing — run `bash ${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh` (installs pip deps, downloads ~200 MB of voices, prepares echo cancellation). The recognition model downloads itself on the listener's first start.
2. Echo cancellation (Linux): `pactl list short sources | grep -q ec_mic || pactl load-module module-echo-cancel "aec_method=webrtc source_name=ec_mic sink_name=ec_out"`. If pactl is absent (macOS) — skip and warn the user to work with headphones.
3. Listener, if not running (`pgrep -f "scripts/listener.py"`): start in background (run_in_background): `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/listener.py >> ~/.voice-assistant/listener.log 2>&1`. Ready when `$VH/listener.log` mentions listening started.
4. Panel (Linux only), if not running: background `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/panel.py 2>> ~/.voice-assistant/panel.log`.
5. Clear manual mute: `rm -f ~/.voice-assistant/muted`.
6. Arm a persistent Monitor: `tail -F -n 0 ~/.voice-assistant/transcript.jsonl` — every line is a user utterance (JSON: ts, lang, text) that wakes the session.
7. Confirm readiness by voice: `${CLAUDE_PLUGIN_ROOT}/scripts/speak.sh "Voice mode is up, I'm listening." <lang>` — in the user's language.

## Behavior rules on each wake-up

- For every utterance decide a boolean: work question / directly addressed → answer; small talk, noise, fragments → stay silent, no commentary.
- Reply in the utterance's language (`lang` field: ru/uk/en): `speak.sh "text" uk` / `en`; default is ru.
- Spoken replies are 1–2 short sentences. Details go to chat as text.
- Exactly one session owns the voice. Handoff: TaskStop your monitor → send_message to the target session asking it to start voice mode.
- Actions that change production or external systems — only after the user's explicit spoken confirmation.
- "Quiet" / "speak" (addressed to the assistant) — create/remove `~/.voice-assistant/voice_off`.
- Ignore your own phrases if they leak into the transcript (they match text you just spoke).
- Barge-in is built in: the user's loud speech kills the current playback — that's normal, keep listening.
