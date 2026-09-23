#!/usr/bin/env python3
"""Фоновый слушатель голосового режима Claude Code.

Микрофон -> VAD по энергии -> faster-whisper -> $VOICE_HOME/transcript.jsonl.
Сегменты режутся по паузе ~1 с, реплика уходит в файл одной строкой после
FLUSH_AFTER_S тишины, с меткой языка (auto-детект или фиксированный из файла lang).
Если доступен источник ec_mic (module-echo-cancel) — слушаем через него и умеем
перебивание: пока играет TTS (есть /tmp/speak.pid), громкая речь глушит озвучку.
Файл $VOICE_HOME/muted — ручное отключение слуха.
"""
import json
import os
import queue
import signal
import platform
import shutil
import subprocess
import tempfile
import sys
import threading
import time

import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.vad import VadOptions, get_speech_timestamps

import audio
import commands

VAD_OPTS = VadOptions(min_speech_duration_ms=250)

VOICE_HOME = os.environ.get("VOICE_HOME", os.path.expanduser("~/.voice-assistant"))
RATE = 16000
FRAME_MS = 60
FRAME_SAMPLES = RATE * FRAME_MS // 1000
FRAME_BYTES = FRAME_SAMPLES * 2
SILENCE_CLOSE_S = 1.0
FLUSH_AFTER_S = 2.5
PRE_ROLL_S = 0.4
MIN_UTT_S = 0.5
MAX_UTT_S = 30.0
BARGE_IN_S = 0.7
BARGE_FLOOR = 1000.0
THRESH_MULT = 3.5
ABS_FLOOR = 550.0
SPEECH_PEAK = 900.0     # real speech peaks above this RMS
SPEECH_CV = 0.35        # speech is dynamic (std/mean over frames), fan noise is flat
OUT = os.path.join(VOICE_HOME, "transcript.jsonl")
MUTE = os.path.join(VOICE_HOME, "muted")
HEADPHONES = os.path.join(VOICE_HOME, "headphones")  # echo cancelling off: capture straight from the device mic
LANG_FILE = os.path.join(VOICE_HOME, "lang")  # auto | ru | uk | en
STT_CONF = os.path.join(VOICE_HOME, "stt.conf")  # engine=local|openai|groq + *_key
PIDFILE = os.path.join(tempfile.gettempdir(), "speak.pid")

CLOUD = {
    "openai": ("https://api.openai.com/v1/audio/transcriptions", "whisper-1", "openai_key", "OPENAI_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1/audio/transcriptions", "whisper-large-v3-turbo", "groq_key", "GROQ_API_KEY"),
}
ENV_KEYS = {"OPENAI_API_KEY", "GROQ_API_KEY"}
ENV_FILES = (os.path.join(VOICE_HOME, ".env"), "~/.env", "~/.bashrc", "~/.profile")
CLOUD_LANG = {"russian": "ru", "ukrainian": "uk", "english": "en"}

state_lock = threading.Lock()
pending: list[str] = []
last_speech = [time.time()]
stt_busy = [False]
cur_lang = ["ru"]
q: "queue.Queue[list[bytes]]" = queue.Queue()


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def rms(frame: bytes) -> float:
    # audioop is a C implementation — ~20x cheaper than numpy on 30ms frames
    import audioop
    return float(audioop.rms(frame, 2)) + 1e-9


def has_ec_mic() -> bool:
    try:
        out = subprocess.run(
            ["pactl", "list", "short", "sources"], capture_output=True, text=True, timeout=5
        ).stdout
        return "ec_mic" in out
    except (OSError, subprocess.TimeoutExpired):
        return False


def capture_cmd(headphones: bool) -> list[str] | None:
    """Command that writes raw s16le mono to stdout, or None to use PortAudio.

    Order of preference: `parecord` on `ec_mic` (only Linux gives echo
    cancellation for free), then whatever native recorder the platform ships,
    then None — which sends the caller to sounddevice, the one backend that
    needs no system binary at all and is the only option on Windows.
    """
    if not headphones and has_ec_mic():
        log("capture: ec_mic (echo cancellation active)")
        return ["parecord", "-d", "ec_mic", "--rate", str(RATE), "--channels", "1",
                "--format", "s16le", "--raw"]
    system = platform.system()
    if system == "Linux" and shutil.which("parecord"):
        src = audio.route()[2] or audio.laptop()[2]
        log(f"capture: {src or 'default device'} (no echo cancellation)")
        return ["parecord", *(["-d", src] if src else []), "--rate", str(RATE), "--channels", "1",
                "--format", "s16le", "--raw"]
    log("capture: default device (no echo cancellation — headphones mode)")
    if system in ("Linux", "Darwin") and shutil.which("sox"):
        return ["sox", "-d", "-t", "raw", "-r", str(RATE), "-c", "1", "-b", "16", "-e", "signed", "-"]
    return None


def open_recorder(headphones: bool):
    """Recorder for this machine — a real process where one exists, else PortAudio."""
    cmd = capture_cmd(headphones)
    if cmd is not None:
        return subprocess.Popen(cmd, stdout=subprocess.PIPE)
    from portaudio_stream import PortAudioRecorder  # noqa: PLC0415

    log("capture: portaudio (no system recorder found)")
    return PortAudioRecorder(RATE)


def speechlike(utt: list[bytes]) -> bool:
    """Pre-STT gate: rejects steady noise (fans), passes dynamic speech."""
    a = np.frombuffer(b"".join(utt), dtype=np.int16).astype(np.float32)
    n = len(a) // FRAME_SAMPLES * FRAME_SAMPLES
    if n == 0:
        return False
    fr = a[:n].reshape(-1, FRAME_SAMPLES)
    r = np.sqrt(np.mean(fr * fr, axis=1))
    return float(r.max()) > SPEECH_PEAK and float(r.std() / (r.mean() + 1e-9)) > SPEECH_CV


_model = [None]


def get_model() -> WhisperModel:
    if _model[0] is None:
        threads = int(read_stt_conf().get("threads", "2"))
        log(f"loading STT model (small, int8, threads: {threads})…")
        _model[0] = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=threads)
        log("local model ready")
    return _model[0]


def load_home_env():
    """Pick up ONLY the cloud API keys (KEY=VALUE / export KEY=VALUE) from user env files."""
    for path in ENV_FILES:
        try:
            for line in open(os.path.expanduser(path)):
                line = line.strip()
                if line.startswith("export "):
                    line = line[len("export "):]
                if "=" not in line or line.startswith("#"):
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip("'\"")
                if k in ENV_KEYS and v and k not in os.environ:
                    os.environ[k] = v
        except OSError:
            continue


def read_stt_conf() -> dict:
    conf = {"engine": "local"}
    try:
        for line in open(STT_CONF):
            if "=" in line:
                k, v = line.strip().split("=", 1)
                conf[k] = v
    except OSError:
        pass
    return conf


def transcribe_cloud(engine: str, key: str, utt: list[bytes]):
    import io
    import wave as wavemod

    import requests

    url, model_name, _, _ = CLOUD[engine]
    buf = io.BytesIO()
    w = wavemod.open(buf, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(RATE)
    w.writeframes(b"".join(utt))
    w.close()
    buf.seek(0)
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}"},
        files={"file": ("audio.wav", buf, "audio/wav")},
        data={"model": model_name, "response_format": "verbose_json"},
        timeout=20,
    )
    r.raise_for_status()
    j = r.json()
    lang = CLOUD_LANG.get(str(j.get("language", "")).lower(), "en")
    return j.get("text", "").strip(), lang


def barge_in():
    try:
        with open(PIDFILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGTERM)
        log("перебивание: озвучка заглушена")
    except (OSError, ValueError):
        pass


def transcriber():
    while True:
        utt = q.get()
        stt_busy[0] = True
        try:
            audio = np.frombuffer(b"".join(utt), dtype=np.int16).astype(np.float32) / 32768.0
            dur = len(audio) / RATE
            if not get_speech_timestamps(audio, VAD_OPTS):
                log(f"({dur:.1f}s) VAD: no speech, STT skipped")
                continue
            try:
                lang_cfg = open(LANG_FILE).read().strip() or "auto"
            except OSError:
                lang_cfg = "auto"
            conf = read_stt_conf()
            engine = conf.get("engine", "local")
            t0 = time.time()
            text = None
            det = None
            src = "local"
            if engine in CLOUD:
                key = conf.get(CLOUD[engine][2], "").strip() or os.environ.get(CLOUD[engine][3], "").strip()
                if key:
                    try:
                        text, det = transcribe_cloud(engine, key, utt)
                        src = engine
                    except Exception as e:
                        log(f"cloud {engine}: {e} — falling back to local")
                        text = None
                else:
                    log(f"engine {engine}: no key in stt.conf — falling back to local")
            if text is None:
                segments, info = get_model().transcribe(
                    audio,
                    language=None if lang_cfg == "auto" else lang_cfg,
                    beam_size=1,
                    vad_filter=True,
                )
                parts = [
                    s.text.strip()
                    for s in segments
                    if s.no_speech_prob < 0.6 and s.avg_logprob > -1.2
                ]
                text = " ".join(p for p in parts if p).strip()
                det = info.language if lang_cfg == "auto" else lang_cfg
                src = "local"
            if lang_cfg != "auto":
                det = lang_cfg
            if text:
                with state_lock:
                    pending.append(text)
                    cur_lang[0] = det or "en"
                log(f"[{cur_lang[0]}/{src}] » {text}  ({dur:.1f}s, {time.time()-t0:.1f}s)")
            else:
                log(f"({dur:.1f}s) noise/empty")
        except Exception as e:
            log(f"transcription error: {e}")
        finally:
            stt_busy[0] = False


def flusher():
    while True:
        time.sleep(0.3)
        with state_lock:
            quiet = time.time() - last_speech[0] >= FLUSH_AFTER_S
            ready = pending and quiet and q.empty() and not stt_busy[0]
            if not ready:
                continue
            text = " ".join(pending)
            lang = cur_lang[0]
            pending.clear()
        cmd = commands.match(text)
        if cmd:
            try:
                log(f"⌘ {text} → {commands.run(*cmd)}")
            except Exception as e:
                log(f"⌘ {text} → error: {e}")
            continue
        line = {"ts": round(time.time(), 1), "lang": lang, "text": text}
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        log(f"⇒ в transcript: {text[:60]}…" if len(text) > 60 else f"⇒ в transcript: {text}")


def parent_watchdog():
    """The app that spawned us has closed (we were re-parented) — exit with it."""
    initial = os.getppid()
    while True:
        time.sleep(5)
        if os.getppid() != initial:
            with state_lock:
                text = " ".join(pending)
                lang = cur_lang[0]
                pending.clear()
            if text:
                line = {"ts": round(time.time(), 1), "lang": lang, "text": text}
                with open(OUT, "a", encoding="utf-8") as f:
                    f.write(json.dumps(line, ensure_ascii=False) + "\n")
            log("parent process closed — exiting")
            os._exit(0)


def already_running() -> bool:
    try:
        pid = int(open(os.path.join(VOICE_HOME, "listener.pid")).read().strip())
    except (OSError, ValueError):
        return False
    if pid == os.getpid():
        return False
    try:
        with open(f"/proc/{pid}/comm") as f:
            if f.read().strip() != "python3":
                return False
        with open(f"/proc/{pid}/cmdline") as f:
            return "listener.py" in f.read()
    except OSError:
        return False


def main():
    os.makedirs(VOICE_HOME, exist_ok=True)
    load_home_env()
    if already_running():
        log("listener already running — refusing to start a second instance")
        return
    with open(os.path.join(VOICE_HOME, "listener.pid"), "w") as f:
        f.write(str(os.getpid()))
    threading.Thread(target=parent_watchdog, daemon=True).start()
    if read_stt_conf().get("engine", "local") == "local":
        get_model()
    log("готово, слушаю микрофон")

    threading.Thread(target=transcriber, daemon=True).start()
    threading.Thread(target=flusher, daemon=True).start()

    def mic_mode() -> tuple[bool, int]:
        # route is rewritten on every device switch and ec_mic reload
        try:
            mtime = os.stat(audio.ROUTE).st_mtime_ns
        except OSError:
            mtime = 0
        return os.path.exists(HEADPHONES), mtime

    mode = mic_mode()
    rec = open_recorder(mode[0])
    fails = 0

    noise = 200.0
    pre: list[bytes] = []
    utt: list[bytes] = []
    silence_frames = 0
    speaking = False
    barged = False
    barge_frames = 0
    pre_max = int(PRE_ROLL_S * 1000 / FRAME_MS)

    while True:
        new_mode = mic_mode()
        if new_mode != mode:
            mode = new_mode
            rec.kill()
            rec = open_recorder(mode[0])
            speaking = False
            utt = []
            pre = []
            silence_frames = 0
            continue
        frame = rec.stdout.read(FRAME_BYTES)
        if not frame or len(frame) < FRAME_BYTES:
            fails += 1
            if fails > 30:
                log("mic stream will not come up — exiting")
                sys.exit(1)
            log("mic stream broke — restarting capture")
            time.sleep(1)
            rec.kill()
            mode = mic_mode()
            rec = open_recorder(mode[0])
            speaking = False
            utt = []
            pre = []
            continue
        fails = 0
        if os.path.exists(MUTE):
            speaking = False
            utt = []
            pre = []
            silence_frames = 0
            last_speech[0] = time.time()
            continue
        level = rms(frame)
        # while TTS plays through speakers, residual echo must not open an utterance; headphones have no echo
        floor = BARGE_FLOOR if (os.path.exists(PIDFILE) and not mode[0]) else ABS_FLOOR
        loud = level > noise * THRESH_MULT and level > floor
        if loud:
            last_speech[0] = time.time()
        if not speaking:
            noise = 0.95 * noise + 0.05 * level
            pre.append(frame)
            if len(pre) > pre_max:
                pre.pop(0)
            if loud:
                speaking = True
                barged = False
                barge_frames = 0
                utt = pre[:]
                utt.append(frame)
                pre = []
                silence_frames = 0
        else:
            utt.append(frame)
            silence_frames = 0 if loud else silence_frames + 1
            utt_s = len(utt) * FRAME_MS / 1000.0
            speech_s = utt_s - silence_frames * FRAME_MS / 1000.0
            if loud and level > BARGE_FLOOR:
                barge_frames += 1
            elif not loud:
                barge_frames = 0
            if not barged and barge_frames * FRAME_MS / 1000.0 >= BARGE_IN_S and os.path.exists(PIDFILE):
                barge_in()
                barged = True
            if silence_frames * FRAME_MS / 1000.0 >= SILENCE_CLOSE_S or utt_s > MAX_UTT_S:
                speaking = False
                if speech_s >= MIN_UTT_S:
                    if speechlike(utt):
                        q.put(utt)
                    else:
                        log(f"({utt_s:.1f}s) steady noise, STT skipped")
                utt = []


if __name__ == "__main__":
    main()
