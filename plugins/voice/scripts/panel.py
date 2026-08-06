#!/usr/bin/env python3
"""Мини-панель поверх всех окон: «слух», «голос» и язык (авто/РУ/УКР/EN).

Работает через флаг-файлы в $VOICE_HOME — синхронно с хоткеями и голосовыми
командами, кто бы состояние ни менял. Только Linux (GTK3).
"""
import os
import signal
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

VOICE_HOME = os.environ.get("VOICE_HOME", os.path.expanduser("~/.voice-assistant"))
MUTED = os.path.join(VOICE_HOME, "muted")
VOICE_OFF = os.path.join(VOICE_HOME, "voice_off")
HEADPHONES = os.path.join(VOICE_HOME, "headphones")
AEC_ARGS = ('aec_method=webrtc aec_args="analog_gain_control=0 digital_gain_control=0 '
            'noise_suppression=0 voice_detection=0" source_name=ec_mic sink_name=ec_out')
LANG_FILE = os.path.join(VOICE_HOME, "lang")
LANGS = [("auto", "🌐 auto"), ("en", "EN"), ("uk", "UK"), ("ru", "RU")]
VOICES = {
    "en": [("lessac", "en_US-lessac-medium.onnx", ""),
           ("amy", "en_US-amy-medium.onnx", ""),
           ("ryan", "en_US-ryan-medium.onnx", "")],
    "uk": [("mykyta", "uk_UA-ukrainian_tts-medium.onnx", "1"),
           ("lada", "uk_UA-ukrainian_tts-medium.onnx", "0"),
           ("tetiana", "uk_UA-ukrainian_tts-medium.onnx", "2")],
    "ru": [("irina", "ru_RU-irina-medium.onnx", ""),
           ("denis", "ru_RU-denis-medium.onnx", ""),
           ("dmitri", "ru_RU-dmitri-medium.onnx", ""),
           ("ruslan", "ru_RU-ruslan-medium.onnx", "")],
}
VOICES_CONF = os.path.join(VOICE_HOME, "voices.conf")
STT_CONF = os.path.join(VOICE_HOME, "stt.conf")
ENGINES = [("local", "🖥 local"), ("openai", "☁ openai"), ("groq", "☁ groq")]
KEY_URLS = {
    "openai": "https://platform.openai.com/api-keys",
    "groq": "https://console.groq.com/keys",
}
ENV_VARS = {"openai": "OPENAI_API_KEY", "groq": "GROQ_API_KEY"}
ENV_FILES = (os.path.join(VOICE_HOME, ".env"), "~/.env", "~/.bashrc", "~/.profile")


def have_env_key(engine):
    name = ENV_VARS[engine]
    if os.environ.get(name, "").strip():
        return True
    for path in ENV_FILES:
        try:
            for line in open(os.path.expanduser(path)):
                line = line.strip()
                if line.startswith("export "):
                    line = line[len("export "):]
                if line.startswith(name + "=") and line.split("=", 1)[1].strip().strip("'\""):
                    return True
        except OSError:
            continue
    return False
PIDFILE = "/tmp/speak.pid"


def read_stt():
    d = {"engine": "local"}
    try:
        for line in open(STT_CONF):
            if "=" in line:
                k, v = line.strip().split("=", 1)
                d[k] = v
    except OSError:
        pass
    return d


def write_engine(engine):
    d = read_stt()
    d["engine"] = engine
    with open(STT_CONF, "w") as f:
        for k, v in d.items():
            f.write(f"{k}={v}\n")


def set_headphones(on):
    if on:
        open(HEADPHONES, "w").close()
        out = subprocess.run(["pactl", "list", "short", "modules"],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            if "module-echo-cancel" in line:
                subprocess.run(["pactl", "unload-module", line.split()[0]])
    else:
        subprocess.run(["pactl", "load-module", "module-echo-cancel", AEC_ARGS])
        try:
            os.remove(HEADPHONES)
        except OSError:
            pass


def read_voices():
    d = {}
    try:
        for line in open(VOICES_CONF):
            if "=" in line:
                k, v = line.strip().split("=", 1)
                d[k] = v
    except OSError:
        pass
    return d


def write_voice(lang, model, spk):
    d = read_voices()
    d[lang] = f"{model}:{spk}" if spk else model
    with open(VOICES_CONF, "w") as f:
        for k, v in d.items():
            f.write(f"{k}={v}\n")


class Panel(Gtk.Window):
    def __init__(self):
        super().__init__(title="Claude — voice")
        self.set_keep_above(True)
        self.set_resizable(False)
        self.set_border_width(6)
        box = Gtk.Grid(row_spacing=6, column_spacing=6)
        self.add(box)
        self.mic = Gtk.ToggleButton()
        self.voice = Gtk.ToggleButton()
        self.mic.connect("toggled", self.on_mic)
        self.voice.connect("toggled", self.on_voice)
        self.mic.set_hexpand(True)
        box.attach(self.mic, 0, 0, 1, 1)
        self.voice.set_hexpand(True)
        box.attach(self.voice, 1, 0, 1, 1)
        self.lang = Gtk.ComboBoxText()
        for code, label in LANGS:
            self.lang.append(code, label)
        self.lang.connect("changed", self.on_lang)
        self.lang.set_hexpand(True)
        box.attach(self.lang, 0, 1, 1, 1)
        self.voices_btn = Gtk.ToggleButton(label="🗣 voices")
        self.voices_btn.connect("toggled", self.on_voices_btn)
        box.attach(self.voices_btn, 1, 1, 1, 1)
        self.revealer = Gtk.Revealer()
        grid = Gtk.Grid(row_spacing=6, column_spacing=10)
        grid.set_border_width(4)
        self.spk_combos = {}
        for i, (lang_code, options) in enumerate(VOICES.items()):
            grid.attach(Gtk.Label(label=lang_code.upper(), xalign=0), 0, i, 1, 1)
            cb = Gtk.ComboBoxText()
            for name, _, _ in options:
                cb.append(name, name)
            cb.connect("changed", self.on_spk_changed, lang_code)
            self.spk_combos[lang_code] = cb
            grid.attach(cb, 1, i, 1, 1)
        self.revealer.add(grid)
        box.attach(self.revealer, 0, 2, 2, 1)
        self.stt = Gtk.ComboBoxText()
        for code, label in ENGINES:
            self.stt.append(code, label)
        self.stt.connect("changed", self.on_stt)
        self.stt.set_hexpand(True)
        box.attach(self.stt, 0, 3, 1, 1)
        self.hp = Gtk.ToggleButton()
        self.hp.connect("toggled", self.on_hp)
        box.attach(self.hp, 1, 3, 1, 1)
        self.power = Gtk.Button(label="⏻ off")
        self.power.connect("clicked", self.on_power)
        box.attach(self.power, 0, 4, 2, 1)
        self.syncing = False
        self.sync()
        GLib.timeout_add(2000, self.sync)

    def sync(self):
        self.syncing = True
        mic_on = not os.path.exists(MUTED)
        voice_on = not os.path.exists(VOICE_OFF)
        mic_label = "🎤 listening" if mic_on else "🎤 off"
        voice_label = "🔊 speaking" if voice_on else "🔊 off"
        if self.mic.get_active() != mic_on:
            self.mic.set_active(mic_on)
        if self.mic.get_label() != mic_label:
            self.mic.set_label(mic_label)
        if self.voice.get_active() != voice_on:
            self.voice.set_active(voice_on)
        if self.voice.get_label() != voice_label:
            self.voice.set_label(voice_label)
        try:
            cur = open(LANG_FILE).read().strip() or "auto"
        except OSError:
            cur = "auto"
        if self.lang.get_active_id() != cur:
            self.lang.set_active_id(cur)
        conf = read_voices()
        for lang_code, cb in self.spk_combos.items():
            cur_v = conf.get(lang_code, "")
            cur_name = next(
                (n for n, m, s in VOICES[lang_code] if (f"{m}:{s}" if s else m) == cur_v),
                VOICES[lang_code][0][0],
            )
            if cb.get_active_id() != cur_name:
                cb.set_active_id(cur_name)
        cur_engine = read_stt().get("engine", "local")
        if self.stt.get_active_id() != cur_engine:
            self.stt.set_active_id(cur_engine)
        hp_on = os.path.exists(HEADPHONES)
        hp_label = "🎧 headphones" if hp_on else "📢 speakers"
        if self.hp.get_active() != hp_on:
            self.hp.set_active(hp_on)
        if self.hp.get_label() != hp_label:
            self.hp.set_label(hp_label)
        self.syncing = False
        return True

    def ask_key(self, engine):
        dlg = Gtk.Dialog(title=f"{engine} API key", transient_for=self)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        area = dlg.get_content_area()
        area.set_spacing(6)
        area.set_border_width(10)
        area.add(Gtk.Label(label=f"Paste your {engine} API key — recognition switches instantly."))
        area.add(Gtk.LinkButton.new_with_label(KEY_URLS[engine], f"Get a key: {KEY_URLS[engine]}"))
        entry = Gtk.Entry()
        entry.set_width_chars(44)
        entry.set_placeholder_text("sk-...")
        area.add(entry)
        dlg.show_all()
        resp = dlg.run()
        key = entry.get_text().strip()
        dlg.destroy()
        return key if resp == Gtk.ResponseType.OK and key else None

    def on_stt(self, combo):
        if self.syncing:
            return
        code = combo.get_active_id()
        if not code:
            return
        if code in KEY_URLS and not read_stt().get(f"{code}_key", "").strip() and not have_env_key(code):
            key = self.ask_key(code)
            if key:
                d = read_stt()
                d[f"{code}_key"] = key
                d["engine"] = code
                with open(STT_CONF, "w") as f:
                    for k, v in d.items():
                        f.write(f"{k}={v}\n")
            else:
                combo.set_active_id("local")
            return
        write_engine(code)

    def on_hp(self, btn):
        if self.syncing:
            return
        set_headphones(btn.get_active())

    def on_power(self, btn):
        try:
            pid = int(open(os.path.join(VOICE_HOME, "listener.pid")).read().strip())
            os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError):
            pass
        Gtk.main_quit()

    def on_voices_btn(self, btn):
        self.revealer.set_reveal_child(btn.get_active())

    def on_spk_changed(self, combo, lang_code):
        if self.syncing:
            return
        name = combo.get_active_id()
        if name:
            for n, m, s in VOICES[lang_code]:
                if n == name:
                    write_voice(lang_code, m, s)
                    break

    def on_lang(self, combo):
        if self.syncing:
            return
        code = combo.get_active_id()
        if code:
            with open(LANG_FILE, "w") as f:
                f.write(code)

    def on_mic(self, btn):
        if self.syncing:
            return
        if btn.get_active():
            if os.path.exists(MUTED):
                os.remove(MUTED)
        else:
            open(MUTED, "w").close()

    def on_voice(self, btn):
        if self.syncing:
            return
        if btn.get_active():
            if os.path.exists(VOICE_OFF):
                os.remove(VOICE_OFF)
        else:
            open(VOICE_OFF, "w").close()
            try:
                with open(PIDFILE) as f:
                    os.kill(int(f.read().strip()), signal.SIGTERM)
            except (OSError, ValueError):
                pass


def _parent_check(initial_ppid):
    if os.getppid() != initial_ppid:
        Gtk.main_quit()
        return False
    return True


os.makedirs(VOICE_HOME, exist_ok=True)
with open(os.path.join(VOICE_HOME, "panel.pid"), "w") as f:
    f.write(str(os.getpid()))
win = Panel()
win.connect("destroy", Gtk.main_quit)
win.show_all()
GLib.timeout_add(5000, _parent_check, os.getppid())
Gtk.main()
