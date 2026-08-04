#!/usr/bin/env python3
"""Мини-панель поверх всех окон: «слух», «голос» и язык (авто/РУ/УКР/EN).

Работает через флаг-файлы в $VOICE_HOME — синхронно с хоткеями и голосовыми
командами, кто бы состояние ни менял. Только Linux (GTK3).
"""
import os
import signal

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

VOICE_HOME = os.environ.get("VOICE_HOME", os.path.expanduser("~/.voice-assistant"))
MUTED = os.path.join(VOICE_HOME, "muted")
VOICE_OFF = os.path.join(VOICE_HOME, "voice_off")
LANG_FILE = os.path.join(VOICE_HOME, "lang")
LANGS = [("auto", "🌐 auto"), ("ru", "RU"), ("uk", "UK"), ("en", "EN")]
VOICES = {
    "ru": [("irina", "ru_RU-irina-medium.onnx", ""),
           ("denis", "ru_RU-denis-medium.onnx", ""),
           ("dmitri", "ru_RU-dmitri-medium.onnx", "")],
    "uk": [("mykyta", "uk_UA-ukrainian_tts-medium.onnx", "1"),
           ("lada", "uk_UA-ukrainian_tts-medium.onnx", "0"),
           ("tetiana", "uk_UA-ukrainian_tts-medium.onnx", "2")],
    "en": [("lessac", "en_US-lessac-medium.onnx", "")],
}
VOICES_CONF = os.path.join(VOICE_HOME, "voices.conf")
PIDFILE = "/tmp/speak.pid"


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
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.add(box)
        self.mic = Gtk.ToggleButton()
        self.voice = Gtk.ToggleButton()
        self.mic.connect("toggled", self.on_mic)
        self.voice.connect("toggled", self.on_voice)
        box.pack_start(self.mic, True, True, 0)
        box.pack_start(self.voice, True, True, 0)
        self.lang = Gtk.ComboBoxText()
        for code, label in LANGS:
            self.lang.append(code, label)
        self.lang.connect("changed", self.on_lang)
        box.pack_start(self.lang, False, False, 0)
        self.voices_btn = Gtk.MenuButton(label="🗣 voices")
        pop = Gtk.Popover()
        grid = Gtk.Grid(row_spacing=4, column_spacing=8)
        grid.set_border_width(8)
        self.spk_combos = {}
        for i, (lang_code, options) in enumerate(VOICES.items()):
            grid.attach(Gtk.Label(label=lang_code.upper(), xalign=0), 0, i, 1, 1)
            cb = Gtk.ComboBoxText()
            for name, _, _ in options:
                cb.append(name, name)
            cb.connect("changed", self.on_spk_changed, lang_code)
            self.spk_combos[lang_code] = cb
            grid.attach(cb, 1, i, 1, 1)
        grid.show_all()
        pop.add(grid)
        pop.set_position(Gtk.PositionType.BOTTOM)
        self.voices_btn.set_popover(pop)
        box.pack_start(self.voices_btn, False, False, 0)
        self.syncing = False
        self.sync()
        GLib.timeout_add(1000, self.sync)

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
        self.syncing = False
        return True

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
