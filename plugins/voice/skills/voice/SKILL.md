---
name: voice
description: Start voice mode — background microphone listener (local STT), floating control panel, spoken replies (RU/UK/EN), wake-up monitor. Invoke via /voice or when the user asks to "start voice mode" / «подними голосовой режим».
---

# Voice mode

**Session rotation (performance)**: the laptop load while voice mode runs is the processing and rendering of a GROWN session on every phrase. When the current session gets large (dozens of wake-ups) — suggest by voice moving to a fresh session ("open a new chat and type /voice"); when the new session picks up, the old one releases its monitor. Quality is unaffected: the rules live in this skill and project memory.

**Idempotency (foolproof)**: calling /voice twice must NOT duplicate anything. Start listener/panel only after the pid-file aliveness checks below; if THIS session already has the voice monitor armed — do not arm a second one, just confirm readiness by voice.

Plugin scripts: `${CLAUDE_PLUGIN_ROOT}/scripts/` (listener.py, speak.sh, panel.py, setup.sh, toggle.sh, mic_toggle.sh). Runtime state (transcript, flags, voices, logs): `~/.voice-assistant/` (below: `$VH`).

## Startup steps

1. First-time setup: if `$VH/voices` with `*.onnx` files is missing — run `bash ${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh` (installs pip deps, downloads voices, prepares echo cancellation). The recognition model downloads itself on the listener's first start.
2. `bash ${CLAUDE_PLUGIN_ROOT}/scripts/up.sh` — loads echo cancellation (Linux), clears mute, prints `listener=alive|dead`, `panel=alive|dead` (pid-file based; never trust `pgrep -f`, it matches bash wrappers).
3. If `listener=dead` — start in background (run_in_background): `bash ${CLAUDE_PLUGIN_ROOT}/scripts/run_listener.sh` (a plain script call — compound cd+redirect commands always trigger a manual permission prompt).
4. If `panel=dead` (Linux only) — background (run_in_background): `bash ${CLAUDE_PLUGIN_ROOT}/scripts/run_panel.sh`.
5. Arm a persistent Monitor: `tail -F -n 0 ~/.voice-assistant/transcript.jsonl` — every line is a user utterance (JSON: ts, lang, text) that wakes the session. Name it "voice input (transcript.jsonl)" — all background task names/descriptions in English, short and clear.
6. `bash ${CLAUDE_PLUGIN_ROOT}/scripts/up.sh wait` — prints `ready` when the listener is up.
7. Confirm readiness by voice: `${CLAUDE_PLUGIN_ROOT}/scripts/speak.sh "VibeTalk on." en`

## Shutdown (/voice off)

1. Announce first: `${CLAUDE_PLUGIN_ROOT}/scripts/speak.sh "VibeTalk off." en`.
2. `bash ${CLAUDE_PLUGIN_ROOT}/scripts/up.sh off` — stops listener and panel via pid files (never `pkill -f`: it kills your own bash wrapper whose cmdline contains the same words).
3. TaskStop your voice monitor AND the "voice listener"/"voice panel" background tasks (by their task ids from this session) so they disappear from the task list. Do not restart anything.

## Behavior rules on each wake-up

- For every utterance decide a boolean: work question / directly addressed → answer; small talk, noise, fragments → stay silent, no commentary.
- Reply in the utterance's language (`lang` field: ru/uk/en): `speak.sh "text" uk` / `en`; default is ru.
- Spoken replies are 1–2 short sentences. Details go to chat as text.
- Exactly one session owns the voice. Handoff: TaskStop your monitor → send_message to the target session asking it to start voice mode.
- Actions that change production or external systems — only after the user's explicit spoken confirmation.
- "Quiet" / "speak" (addressed to the assistant) — create/remove `~/.voice-assistant/voice_off`.
- Ignore your own phrases if they leak into the transcript (they match text you just spoke).
- Barge-in is built in: the user's loud speech kills the current playback — that's normal, keep listening.
