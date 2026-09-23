"""Аудиоустройство голосового режима: откуда слушаем, куда говорим, эхоподавление."""
import os
import subprocess
import time

VOICE_HOME = os.environ.get("VOICE_HOME", os.path.expanduser("~/.voice-assistant"))
ROUTE = os.path.join(VOICE_HOME, "route")  # "<card> <sink> <source>" выбранного устройства
AEC_OFF = os.path.join(VOICE_HOME, "headphones")  # флаг: эхоподавление выключено (имя историческое)
HFP_PROFILES = ("handsfree_head_unit", "headset_head_unit")
A2DP_PROFILE = "a2dp_sink"
AEC_ARGS = ["aec_method=webrtc",
            'aec_args="analog_gain_control=0 digital_gain_control=0 noise_suppression=0 voice_detection=0"',
            "source_name=ec_mic", "sink_name=ec_out"]


def _pactl(*args):
    try:
        return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _short(kind):
    return [ln.split("\t")[1] for ln in _pactl("list", "short", kind).splitlines() if "\t" in ln]


def sinks():
    return [s for s in _short("sinks") if s != "ec_out"]


def sources():
    return [s for s in _short("sources") if s != "ec_mic" and not s.endswith(".monitor")]


def _key(card):
    return card.split(".", 1)[1]


def _find(names, card):
    return next((n for n in names if _key(card) in n), None)


def _wait(fn, tries=20):
    # устройства после смены профиля появляются не сразу
    for _ in range(tries):
        v = fn()
        if v:
            return v
        time.sleep(0.15)
    return None


def _cards():
    cards, cur = [], None
    for line in _pactl("list", "cards").splitlines():
        s = line.strip()
        if s.startswith(("Name:", "Имя:")):
            cur = {"name": s.split(":", 1)[1].strip(), "label": None, "profiles": {}, "active": None}
            cards.append(cur)
        elif cur is None:
            continue
        elif s.startswith("device.description = ") and cur["label"] is None:
            cur["label"] = s.split("=", 1)[1].strip().strip('"')
        elif s.startswith(("Active Profile:", "Активный профиль:")):
            cur["active"] = s.split(":", 1)[1].strip()
        else:
            prof = s.split(":", 1)[0]
            if prof in HFP_PROFILES or prof == A2DP_PROFILE:
                cur["profiles"][prof] = not s.endswith(("no)", "нет)"))
    return cards


def is_laptop(card):
    return card.startswith("alsa_card.pci-")


def devices():
    """[(card, label)] устройств, куда можно вывести звук; ноутбук первым."""
    snks = sinks()
    out = []
    for c in _cards():
        bt = c["name"].startswith("bluez_card.")
        if not bt and not _find(snks, c["name"]):
            continue
        out.append((c["name"], "laptop" if is_laptop(c["name"]) else (c["label"] or _key(c["name"]))))
    out.sort(key=lambda d: not is_laptop(d[0]))
    return out


def laptop():
    card = next((c for c, _ in devices() if is_laptop(c)), None)
    snk = next((s for s in sinks() if s.startswith("alsa_output.pci-")), None)
    src = next((s for s in sources() if s.startswith("alsa_input.pci-")), None)
    return card, snk, src


def route():
    """(card, sink, source) выбранного устройства; исчезнувшее — None."""
    try:
        card, snk, src = open(ROUTE).read().split()
    except (OSError, ValueError):
        return laptop()
    snks, srcs = sinks(), sources()
    return card, (snk if snk in snks else None), (src if src in srcs else None)


def aec_on():
    return not os.path.exists(AEC_OFF)


def _speaker_port(sink):
    cur = None
    for line in _pactl("list", "sinks").splitlines():
        s = line.strip()
        if s.startswith(("Name:", "Имя:")):
            cur = s.split(":", 1)[1].strip()
        elif cur == sink and s.startswith(("Active Port:", "Активный порт:")):
            return "speaker" in s
    return False


def needs_aec(sink):
    """Эхо есть, только когда звук идёт в динамики ноутбука (не в наушники в разъёме)."""
    return bool(sink) and sink.startswith("alsa_output.pci-") and _speaker_port(sink)


def _unload_aec():
    for line in _pactl("list", "short", "modules").splitlines():
        if "module-echo-cancel" in line:
            _pactl("unload-module", line.split()[0])


def _apply_aec(on, snk, src):
    _unload_aec()
    if not on:
        open(AEC_OFF, "w").close()
        return
    masters = [f"{k}={v}" for k, v in (("source_master", src), ("sink_master", snk)) if v]
    _pactl("load-module", "module-echo-cancel", *AEC_ARGS, *masters)
    try:
        os.remove(AEC_OFF)
    except OSError:
        pass


def set_aec(on):
    _, snk, src = route()
    _apply_aec(on, snk, src)


def _delivers_audio(src, seconds=2):
    # HFP-источник может существовать, но молчать (SCO не поднялся): parecord не отдаёт ни байта
    try:
        out = subprocess.run(
            ["timeout", str(seconds), "parecord", "-d", src, "--raw",
             "--rate", "16000", "--channels", "1", "--format", "s16le"],
            capture_output=True,
        ).stdout
    except OSError:
        return False
    return len(out) > 0


def select(card):
    """Звук и микрофон — на устройство card; микрофон без звука заменяется ноутбучным.

    Возвращает (sink, source) или None, если устройства нет.
    """
    cards = {c["name"]: c for c in _cards()}
    c = cards.get(card)
    if c is None:
        return None
    for other in cards.values():
        if other["name"] != card and other["active"] in HFP_PROFILES:
            _pactl("set-card-profile", other["name"], A2DP_PROFILE)
    _, _, laptop_src = laptop()
    snk = src = None
    if card.startswith("bluez_card."):
        hfp = next((p for p in HFP_PROFILES if c["profiles"].get(p)), None)
        if hfp:
            _pactl("set-card-profile", card, hfp)
            src = _wait(lambda: _find(sources(), card))
            if src and _delivers_audio(src):
                snk = _wait(lambda: _find(sinks(), card))
            else:
                src = None
        if not snk:
            _pactl("set-card-profile", card, A2DP_PROFILE)
            snk = _wait(lambda: _find(sinks(), card))
    else:
        snk = _find(sinks(), card)
        src = _find(sources(), card)
    src = src or laptop_src
    _apply_aec(needs_aec(snk), snk, src)
    # route пишется последним: слушатель переоткрывает запись по его mtime, когда ec_mic уже новый
    with open(ROUTE, "w") as f:
        f.write(f"{card} {snk} {src}")
    return snk, src
