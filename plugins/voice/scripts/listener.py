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
import subprocess
import sys
import threading
import time

import numpy as np
from faster_whisper import WhisperModel

VOICE_HOME = os.environ.get("VOICE_HOME", os.path.expanduser("~/.voice-assistant"))
RATE = 16000
FRAME_MS = 30
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
LANG_FILE = os.path.join(VOICE_HOME, "lang")  # auto | ru | uk | en
PIDFILE = "/tmp/speak.pid"

state_lock = threading.Lock()
pending: list[str] = []
last_speech = [time.time()]
stt_busy = [False]
cur_lang = ["ru"]
q: "queue.Queue[list[bytes]]" = queue.Queue()


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def rms(frame: bytes) -> float:
    a = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(a * a)) + 1e-9)


def has_ec_mic() -> bool:
    try:
        out = subprocess.run(
            ["pactl", "list", "short", "sources"], capture_output=True, text=True, timeout=5
        ).stdout
        return "ec_mic" in out
    except (OSError, subprocess.TimeoutExpired):
        return False


def capture_cmd() -> list[str]:
    if has_ec_mic():
        log("захват: ec_mic (эхоподавление активно, перебивание доступно)")
        return ["parecord", "-d", "ec_mic", "--rate", str(RATE), "--channels", "1",
                "--format", "s16le", "--raw"]
    log("захват: устройство по умолчанию (без эхоподавления — работайте в наушниках)")
    if os.uname().sysname == "Linux":
        return ["parecord", "--rate", str(RATE), "--channels", "1",
                "--format", "s16le", "--raw"]
    return ["sox", "-d", "-t", "raw", "-r", str(RATE), "-c", "1", "-b", "16", "-e", "signed", "-"]


def speechlike(utt: list[bytes]) -> bool:
    """Pre-STT gate: rejects steady noise (fans), passes dynamic speech."""
    a = np.frombuffer(b"".join(utt), dtype=np.int16).astype(np.float32)
    n = len(a) // FRAME_SAMPLES * FRAME_SAMPLES
    if n == 0:
        return False
    fr = a[:n].reshape(-1, FRAME_SAMPLES)
    r = np.sqrt(np.mean(fr * fr, axis=1))
    return float(r.max()) > SPEECH_PEAK and float(r.std() / (r.mean() + 1e-9)) > SPEECH_CV


def barge_in():
    try:
        with open(PIDFILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGTERM)
        log("перебивание: озвучка заглушена")
    except (OSError, ValueError):
        pass


def transcriber(model: WhisperModel):
    while True:
        utt = q.get()
        stt_busy[0] = True
        try:
            audio = np.frombuffer(b"".join(utt), dtype=np.int16).astype(np.float32) / 32768.0
            dur = len(audio) / RATE
            t0 = time.time()
            try:
                lang_cfg = open(LANG_FILE).read().strip() or "auto"
            except OSError:
                lang_cfg = "auto"
            segments, info = model.transcribe(
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
            if text:
                with state_lock:
                    pending.append(text)
                    cur_lang[0] = info.language if lang_cfg == "auto" else lang_cfg
                log(f"[{cur_lang[0]}] » {text}  ({dur:.1f}s, распознание {time.time()-t0:.1f}s)")
            else:
                log(f"({dur:.1f}s) шум/пусто")
        except Exception as e:
            log(f"ошибка распознания: {e}")
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
            log("parent process closed — exiting")
            os._exit(0)


def main():
    os.makedirs(VOICE_HOME, exist_ok=True)
    threading.Thread(target=parent_watchdog, daemon=True).start()
    log("загружаю модель STT (small, int8)…")
    model = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=2)
    log("модель готова, слушаю микрофон")

    threading.Thread(target=transcriber, args=(model,), daemon=True).start()
    threading.Thread(target=flusher, daemon=True).start()

    rec = subprocess.Popen(capture_cmd(), stdout=subprocess.PIPE)

    noise = 200.0
    pre: list[bytes] = []
    utt: list[bytes] = []
    silence_frames = 0
    speaking = False
    barged = False
    barge_frames = 0
    pre_max = int(PRE_ROLL_S * 1000 / FRAME_MS)

    while True:
        frame = rec.stdout.read(FRAME_BYTES)
        if not frame or len(frame) < FRAME_BYTES:
            log("поток микрофона оборвался")
            sys.exit(1)
        if os.path.exists(MUTE):
            speaking = False
            utt = []
            pre = []
            silence_frames = 0
            last_speech[0] = time.time()
            continue
        level = rms(frame)
        loud = level > noise * THRESH_MULT and level > ABS_FLOOR
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
