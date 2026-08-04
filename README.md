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

## Controls

A small always-on-top panel appears automatically and is the single control surface:

| Control | What it does |
|---|---|
| 🎤 **listening** | toggles whether the assistant hears you |
| 🔊 **voice** | toggles spoken replies; switching off also cuts the current playback |
| 🌐 **language** | auto-detect or pin RU / UK / EN |

You can also control everything by voice: say "quiet" / "speak", and to interrupt the assistant — just start talking over it (barge-in).

## How it works

<p align="center">
  <img src="assets/how-it-works.svg" alt="How voice mode works: local speech recognition feeds your Claude Code session, which decides when to act and replies with voice and text" width="880"/>
</p>

Nothing leaves your machine except the recognized text of work-related phrases, which goes into your Claude Code session like a typed message. Replies come back in the language you spoke — the assistant answers Ukrainian in Ukrainian (voice: mykyta), Russian in Russian (irina), English in English (lessac).

## Requirements

- Python 3.10+, a microphone
- Linux (PipeWire/Pulse): full feature set — echo cancellation, barge-in, control panel
- macOS: basic mode, use headphones (no echo cancellation), no panel
- iOS/Android: not supported
