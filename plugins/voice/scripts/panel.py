#!/usr/bin/env python3
"""Мини-панель поверх всех окон: «слух», «голос», эхоподавление, язык, распознавание, устройство.

Работает через флаг-файлы в $VOICE_HOME — синхронно с хоткеями и голосовыми
командами, кто бы состояние ни менял. Только Linux (GTK3).
"""
import os
import signal
import tempfile
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

import audio

VOICE_HOME = os.environ.get("VOICE_HOME", os.path.expanduser("~/.voice-assistant"))
MUTED = os.path.join(VOICE_HOME, "muted")
VOICE_OFF = os.path.join(VOICE_HOME, "voice_off")
LANG_FILE = os.path.join(VOICE_HOME, "lang")
POS_FILE = os.path.join(VOICE_HOME, "panel_pos")
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
PIDFILE = os.path.join(tempfile.gettempdir(), "speak.pid")


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


def write_stt(d):
    # holds API keys: owner-only
    fd = os.open(STT_CONF, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        for k, v in d.items():
            f.write(f"{k}={v}\n")
    os.chmod(STT_CONF, 0o600)


def write_engine(engine):
    d = read_stt()
    d["engine"] = engine
    write_stt(d)


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


CSS = b"""
window.vt { background: transparent; }
.card { background: #15171c; border-radius: 16px; border: 1px solid #262a33; padding: 10px 12px 12px; }
.card * { color: #e6e8ee; text-shadow: none; -gtk-icon-shadow: none; }
.title { font-weight: 700; font-size: 11px; letter-spacing: 2px; color: #8a93a6; }
.status { font-size: 11px; color: #8a93a6; }
.dot { font-size: 10px; color: #4a5160; }
.dot.on { color: #3ecf8e; }
.lbl { font-size: 11px; color: #8a93a6; }
.card button { background: #1f222a; background-image: none; border: none; border-radius: 10px;
               box-shadow: none; padding: 4px 10px; min-height: 0; min-width: 0; outline: none; }
.card button:hover { background: #292d37; }
.card button:checked { background: #3a6df0; }
.big { padding: 8px 4px 6px; border-radius: 12px; }
.big label { font-size: 11px; }
.card button.big:not(:checked) image, .card button.big:not(:checked) label { color: #8a93a6; }
.icon { padding: 4px; border-radius: 8px; background: transparent; }
.card button.danger:hover { background: #5a2323; }
.seg button { border-radius: 0; font-size: 12px; padding: 3px 9px; margin: 0; }
.seg button:first-child { border-radius: 8px 0 0 8px; }
.seg button:last-child { border-radius: 0 8px 8px 0; }
.seg button:only-child { border-radius: 8px; }
"""


def seg(options, on_change, *extra):
    """Сегментированный переключатель из радио-кнопок: {id: button}."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
    box.get_style_context().add_class("seg")
    buttons, group = {}, None
    for code, label in options:
        b = Gtk.RadioButton.new_with_label_from_widget(group, label)
        b.set_mode(False)
        b.connect("toggled", lambda btn, c=code: btn.get_active() and on_change(c, *extra))
        box.pack_start(b, False, False, 0)
        buttons[code] = b
        group = group or b
    return box, buttons


def big_toggle(caption):
    btn = Gtk.ToggleButton()
    btn.get_style_context().add_class("big")
    inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
    img = Gtk.Image()
    lbl = Gtk.Label(label=caption)
    inner.pack_start(img, False, False, 0)
    inner.pack_start(lbl, False, False, 0)
    btn.add(inner)
    btn.set_hexpand(True)
    return btn, img, lbl


class Panel(Gtk.Window):
    def __init__(self):
        super().__init__(title="Claude — voice")
        self.set_keep_above(True)
        self.set_resizable(False)
        self.set_decorated(False)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.get_style_context().add_class("vt")
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        # безрамочное окно таскается за любое пустое место карточки
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("button-press-event", self.on_drag)
        self.connect("configure-event", self.on_configure)
        try:
            self.move(*map(int, open(POS_FILE).read().split()))
        except (OSError, ValueError, TypeError):
            pass
        self.syncing = False

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.get_style_context().add_class("card")
        self.add(card)

        head = Gtk.Box(spacing=6)
        self.dot = Gtk.Label(label="●")
        self.dot.get_style_context().add_class("dot")
        title = Gtk.Label(label="VIBETALK")
        title.get_style_context().add_class("title")
        self.status = Gtk.Label()
        self.status.get_style_context().add_class("status")
        self.power = Gtk.Button()
        self.power.add(Gtk.Image.new_from_icon_name("system-shutdown-symbolic", Gtk.IconSize.MENU))
        self.power.set_tooltip_text("Stop voice mode")
        for c in ("icon", "danger"):
            self.power.get_style_context().add_class(c)
        self.power.connect("clicked", self.on_power)
        self.hide_btn = Gtk.Button()
        self.hide_btn.add(Gtk.Image.new_from_icon_name("window-minimize-symbolic", Gtk.IconSize.MENU))
        self.hide_btn.set_tooltip_text("Minimize")
        self.hide_btn.get_style_context().add_class("icon")
        self.hide_btn.connect("clicked", lambda _b: self.iconify())
        head.pack_start(self.dot, False, False, 0)
        head.pack_start(title, False, False, 0)
        head.pack_end(self.power, False, False, 0)
        head.pack_end(self.hide_btn, False, False, 0)
        head.pack_end(self.status, False, False, 4)
        card.pack_start(head, False, False, 0)

        row = Gtk.Box(spacing=6, homogeneous=True)
        self.mic, self.mic_img, _ = big_toggle("listen")
        self.voice, self.voice_img, _ = big_toggle("speak")
        self.aec, self.aec_img, _ = big_toggle("echo cancel")
        self.mic.connect("toggled", self.on_mic)
        self.voice.connect("toggled", self.on_voice)
        self.aec.connect("toggled", self.on_aec)
        self.aec.set_tooltip_text("Echo cancelling: needed when replies play through speakers next to the mic.\n"
                                  "Set automatically when you pick a device.")
        for b in (self.mic, self.voice, self.aec):
            row.pack_start(b, True, True, 0)
        card.pack_start(row, False, False, 0)

        grid = Gtk.Grid(row_spacing=8, column_spacing=10)
        card.pack_start(grid, False, False, 0)

        def add_row(i, name, widget):
            lbl = Gtk.Label(label=name, xalign=0)
            lbl.get_style_context().add_class("lbl")
            grid.attach(lbl, 0, i, 1, 1)
            grid.attach(widget, 1, i, 1, 1)
            return lbl

        box, self.lang_btns = seg([(c, l.replace("🌐 ", "")) for c, l in LANGS], self.on_lang)
        add_row(0, "language", box)
        box, self.stt_btns = seg([(c, l.split(" ", 1)[1]) for c, l in ENGINES], self.on_stt)
        add_row(1, "recognition", box)
        self.dev_holder = Gtk.Box(spacing=8)
        self.dev_mic = Gtk.Label()
        self.dev_mic.get_style_context().add_class("lbl")
        self.dev_mic.set_tooltip_text("This device's mic gives no audio, listening through the laptop mic")
        self.dev_holder.pack_end(self.dev_mic, False, False, 0)
        self.dev_list, self.dev_btns, self.dev_combo = None, {}, None
        self.dev_lbl = add_row(2, "device", self.dev_holder)
        # строка видна, только когда устройств больше одного; show_all её не трогает
        self.dev_mic.show()
        for w in (self.dev_holder, self.dev_lbl):
            w.set_no_show_all(True)

        self.voices_btn = Gtk.ToggleButton()
        self.voices_img = Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.MENU)
        self.voices_btn.add(self.voices_img)
        self.voices_btn.get_style_context().add_class("icon")
        self.voices_btn.set_halign(Gtk.Align.START)
        self.voices_btn.connect("toggled", self.on_voices_btn)
        add_row(3, "voices", self.voices_btn)

        self.revealer = Gtk.Revealer()
        vgrid = Gtk.Grid(row_spacing=8, column_spacing=10)
        self.spk_btns = {}
        for i, (lang_code, options) in enumerate(VOICES.items()):
            lbl = Gtk.Label(label=lang_code.upper(), xalign=0)
            lbl.get_style_context().add_class("lbl")
            vgrid.attach(lbl, 0, i, 1, 1)
            box, self.spk_btns[lang_code] = seg([(n, n) for n, _, _ in options], self.on_spk_changed, lang_code)
            vgrid.attach(box, 1, i, 1, 1)
        self.revealer.add(vgrid)
        card.pack_start(self.revealer, False, False, 0)

        self.sync()
        GLib.timeout_add(2000, self.sync)

    @staticmethod
    def _pick(buttons, code):
        b = buttons.get(code)
        if b and not b.get_active():
            b.set_active(True)

    def sync(self):
        self.syncing = True
        mic_on = not os.path.exists(MUTED)
        voice_on = not os.path.exists(VOICE_OFF)
        aec_on = audio.aec_on()
        for btn, img, on, icons in (
            (self.mic, self.mic_img, mic_on, ("audio-input-microphone-symbolic", "microphone-sensitivity-muted-symbolic")),
            (self.voice, self.voice_img, voice_on, ("audio-volume-high-symbolic", "audio-volume-muted-symbolic")),
            (self.aec, self.aec_img, aec_on, ("media-playlist-repeat-symbolic",) * 2),
        ):
            if btn.get_active() != on:
                btn.set_active(on)
            img.set_from_icon_name(icons[0] if on else icons[1], Gtk.IconSize.LARGE_TOOLBAR)
        ctx = self.dot.get_style_context()
        (ctx.add_class if mic_on else ctx.remove_class)("on")
        speaking = os.path.exists(PIDFILE)
        self.status.set_label("speaking" if speaking else ("listening" if mic_on else "muted"))
        try:
            cur = open(LANG_FILE).read().strip() or "auto"
        except OSError:
            cur = "auto"
        self._pick(self.lang_btns, cur)
        conf = read_voices()
        for lang_code, btns in self.spk_btns.items():
            cur_v = conf.get(lang_code, "")
            cur_name = next(
                (n for n, m, s in VOICES[lang_code] if (f"{m}:{s}" if s else m) == cur_v),
                VOICES[lang_code][0][0],
            )
            self._pick(btns, cur_name)
        self._pick(self.stt_btns, read_stt().get("engine", "local"))
        self.sync_devices()
        self.syncing = False
        return True

    def sync_devices(self):
        devs = audio.devices()
        if devs != self.dev_list:
            self.dev_list = devs
            self.build_devices(devs)
        many = len(devs) > 1
        for w in (self.dev_holder, self.dev_lbl):
            if w.get_visible() != many:
                w.set_visible(many)
        card, snk, src = audio.route()
        cards = [c for c, _ in devs]
        if os.path.exists(audio.ROUTE) and (snk is None or card not in cards):
            # выбранное устройство отключили — звук и микрофон обратно на ноутбук
            laptop_card = audio.laptop()[0]
            if laptop_card:
                audio.select(laptop_card)
                card, snk, src = audio.route()
        if self.dev_combo:
            if self.dev_combo.get_active_id() != card:
                self.dev_combo.set_active_id(card)
        else:
            self._pick(self.dev_btns, card)
        own_mic = bool(src) and card is not None and card.split(".", 1)[1] in src
        self.dev_mic.set_label("" if own_mic or not src else "mic: laptop")

    def build_devices(self, devs):
        for child in self.dev_holder.get_children():
            if child is not self.dev_mic:
                child.destroy()
        short = [(c, l if len(l) <= 14 else l[:13] + "…") for c, l in devs]
        if len(devs) <= 3:
            widget, self.dev_btns = seg(short, self.on_device)
            self.dev_combo = None
        else:
            self.dev_btns = {}
            self.dev_combo = widget = Gtk.ComboBoxText()
            for c, l in short:
                widget.append(c, l)
            widget.connect("changed", lambda cb: cb.get_active_id() and self.on_device(cb.get_active_id()))
        self.dev_holder.pack_start(widget, False, False, 0)
        widget.show_all()

    def on_drag(self, _win, event):
        if event.button == 1:
            self.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
        return False

    def on_configure(self, _win, _event):
        x, y = self.get_position()
        try:
            with open(POS_FILE, "w") as f:
                f.write(f"{x} {y}")
        except OSError:
            pass
        return False

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

    def on_stt(self, code):
        if self.syncing:
            return
        if code in KEY_URLS and not read_stt().get(f"{code}_key", "").strip() and not have_env_key(code):
            key = self.ask_key(code)
            if key:
                d = read_stt()
                d[f"{code}_key"] = key
                d["engine"] = code
                write_stt(d)
            else:
                self._pick(self.stt_btns, read_stt().get("engine", "local"))
            return
        write_engine(code)

    def on_device(self, card):
        if self.syncing:
            return
        audio.select(card)
        self.sync()

    def on_aec(self, btn):
        if self.syncing:
            return
        audio.set_aec(btn.get_active())
        self.sync()

    def on_power(self, btn):
        try:
            pid = int(open(os.path.join(VOICE_HOME, "listener.pid")).read().strip())
            os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError):
            pass
        Gtk.main_quit()

    def on_voices_btn(self, btn):
        on = btn.get_active()
        self.revealer.set_reveal_child(on)
        self.voices_img.set_from_icon_name("pan-up-symbolic" if on else "pan-down-symbolic", Gtk.IconSize.MENU)
        if not on:
            # окно не сжимается само после сворачивания revealer
            GLib.timeout_add(300, lambda: self.resize(1, 1) and False)

    def on_spk_changed(self, name, lang_code):
        if self.syncing:
            return
        for n, m, s in VOICES[lang_code]:
            if n == name:
                write_voice(lang_code, m, s)
                break

    def on_lang(self, code):
        if self.syncing:
            return
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
        self.sync()

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
        self.sync()


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
