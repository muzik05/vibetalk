"""Local voice commands for Claude Desktop: run via xdotool without waking the model (Linux/X11 only)."""
import os
import re
import shutil
import subprocess
import sys
import time

WIN_CLASS = "com.anthropic.claude"
AVAILABLE = sys.platform.startswith("linux") and bool(os.environ.get("DISPLAY")) and shutil.which("xdotool") is not None

# phrase (normalized, optional "claude" prefix) -> action
KEYS = {
    ("новая сессия", "новую сессию", "новый чат", "нова сесія", "new session", "new chat"): "ctrl+n",
    ("открой папку", "открыть папку", "відкрий папку", "open folder"): "ctrl+shift+o",
    ("палитра", "палитру", "открой палитру", "палітра", "command palette", "palette"): "ctrl+k",
    ("сайдбар", "боковая панель", "боковую панель", "бічна панель", "sidebar", "toggle sidebar"): "ctrl+b",
    ("закрой вкладку", "закрыть вкладку", "закрий вкладку", "close tab"): "ctrl+w",
    ("верни вкладку", "вернуть вкладку", "поверни вкладку", "reopen tab"): "ctrl+shift+t",
    ("горячие клавиши", "шорткаты", "shortcuts"): "ctrl+slash",
    ("стоп клод", "останови генерацию", "стоп генерация", "зупини генерацію", "stop claude", "stop generation"): "Escape",
    ("ввод", "энтер", "отправь", "надішли", "enter", "send it"): "Return",
}
SHOW = ("покажи клод", "разверни клод", "открой клод", "покажи клода", "покажи окно", "show claude")
HIDE = ("сверни клод", "сверни клода", "спрячь клод", "сверни окно", "згорни клод", "hide claude", "minimize claude")
TYPE_PREFIX = ("диктовка", "впиши", "dictate")
PALETTE_PREFIX = ("палитра", "палітра", "palette")
WAKE = ("клод", "клоуд", "claude")
MAX_WORDS = 5


def norm(text: str) -> str:
    t = text.lower().replace("ё", "е")
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def strip_wake(t: str) -> str:
    for w in WAKE:
        if t.startswith(w + " "):
            return t[len(w) + 1:]
    return t


def match(text: str):
    """(kind, arg) or None. The whole utterance must be a command, so ordinary speech never fires."""
    if not AVAILABLE:
        return None
    t = norm(text)
    for c in (t, strip_wake(t)):
        if c in SHOW:
            return ("show", None)
        if c in HIDE:
            return ("hide", None)
        for phrases, key in KEYS.items():
            if c in phrases:
                return ("key", key)
    body = strip_wake(t)
    raw = text.strip()
    for p in TYPE_PREFIX:
        if body.startswith(p + " "):
            # keep case and punctuation from the original
            m = re.match(rf"\W*(?:(?:{'|'.join(WAKE)})\W+)?{p}\W+(.*)$", raw, re.I)
            return ("type", m.group(1) if m else body[len(p) + 1:])
    for p in PALETTE_PREFIX:
        if body.startswith(p + " ") and len(body.split()) <= MAX_WORDS + 1:
            return ("palette", body[len(p) + 1:])
    return None


def _xdo(*args) -> str:
    return subprocess.run(["xdotool", *args], capture_output=True, text=True, timeout=5).stdout.strip()


def window() -> str | None:
    ids = _xdo("search", "--onlyvisible", "--class", WIN_CLASS).split() or _xdo("search", "--class", WIN_CLASS).split()
    for wid in ids:
        if _xdo("getwindowname", wid):
            return wid
    return ids[0] if ids else None


def focus() -> bool:
    wid = window()
    if not wid:
        return False
    _xdo("windowactivate", "--sync", wid)
    time.sleep(0.15)
    return True


def run(kind: str, arg) -> str:
    if kind == "hide":
        wid = window()
        if wid:
            _xdo("windowminimize", wid)
        return "свёрнуто" if wid else "окно не найдено"
    if not focus():
        return "окно не найдено"
    if kind == "show":
        return "показано"
    if kind == "key":
        _xdo("key", "--clearmodifiers", arg)
        return f"key {arg}"
    if kind == "type":
        _xdo("type", "--clearmodifiers", "--delay", "8", arg)
        return f"напечатано: {arg}"
    if kind == "palette":
        _xdo("key", "--clearmodifiers", "ctrl+k")
        time.sleep(0.3)
        _xdo("type", "--clearmodifiers", "--delay", "8", arg)
        return f"палитра: {arg}"
    return "неизвестно"


def open_session(title: str) -> str:
    """Open a session by exact title via the palette (sessions rank first on title match)."""
    if not AVAILABLE:
        return "unavailable: needs Linux/X11 with xdotool"
    if not focus():
        return "window not found"
    _xdo("key", "--clearmodifiers", "ctrl+k")
    time.sleep(0.4)
    _xdo("type", "--clearmodifiers", "--delay", "8", title)
    time.sleep(0.8)
    _xdo("key", "--clearmodifiers", "Return")
    return f"opened: {title}"


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "open-session":
        print(open_session(sys.argv[2]))
    else:
        sys.exit('usage: commands.py open-session "<exact session title>"')
