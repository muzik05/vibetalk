# generect-tools — voice

Voice mode for Claude Code: talk to your session hands-free. The assistant listens in the background, decides on its own when a phrase is work-related, and replies with voice and text. Speech recognition (faster-whisper) and synthesis (piper) run fully locally — the only cost is your session's regular messages.

## Install

```bash
# 1. Add the marketplace (git URL or local path)
/plugin marketplace add muzik05/claude-voice-plugin

# 2. Install the plugin
/plugin install voice@generect-tools
```

Then, in any session: **`/voice`** (or just say "start voice mode"). The first run installs pip dependencies and downloads the voices (~200 MB) plus the recognition model (~250 MB).

## Requirements

- Python 3.10+, a microphone
- Linux (PipeWire/Pulse): full feature set — echo cancellation, barge-in, floating control panel
- macOS: basic mode, use headphones (no echo cancellation), no panel
- iOS/Android: not supported

## Controls

- Floating panel: 🎤 listening, 🔊 voice, language (auto/RU/UK/EN)
- Hotkeys: `scripts/toggle.sh` (voice), `scripts/mic_toggle.sh` (mic)
- By voice: "quiet" / "speak"; barge-in — just start talking over the assistant
- Languages: auto-detect ru/uk/en, replies in the language of the question

## How it works

```
mic → VAD → faster-whisper → ~/.voice-assistant/transcript.jsonl
                                   ↓ (Monitor wakes the session)
                          Claude Code (boolean: work-related?)
                                   ↓
                        speak.sh (piper) + text in chat
```
