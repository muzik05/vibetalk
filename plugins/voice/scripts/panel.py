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
LANGS = [("auto", "🌐 авто"), ("ru", "РУ"), ("uk", "УКР"), ("en", "EN")]
PIDFILE = "/tmp/speak.pid"


class Panel(Gtk.Window):
    def __init__(self):
        super().__init__(title="Клод — голос")
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
        self.syncing = False
        self.sync()
        GLib.timeout_add(500, self.sync)

    def sync(self):
        self.syncing = True
        mic_on = not os.path.exists(MUTED)
        voice_on = not os.path.exists(VOICE_OFF)
        self.mic.set_active(mic_on)
        self.mic.set_label("🎤 слушаю" if mic_on else "🎤 выкл")
        self.voice.set_active(voice_on)
        self.voice.set_label("🔊 говорю" if voice_on else "🔊 выкл")
        try:
            cur = open(LANG_FILE).read().strip() or "auto"
        except OSError:
            cur = "auto"
        if self.lang.get_active_id() != cur:
            self.lang.set_active_id(cur)
        self.syncing = False
        return True

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


os.makedirs(VOICE_HOME, exist_ok=True)
win = Panel()
win.connect("destroy", Gtk.main_quit)
win.show_all()
Gtk.main()
