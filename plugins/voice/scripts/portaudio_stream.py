"""Microphone through PortAudio, shaped like a `subprocess.Popen`.

The listener talks to its recorder as `rec.stdout.read(n)` / `rec.kill()`,
which is what `parecord` and `sox` give for free. Windows ships neither, and
on macOS `sox` is an extra brew install — but PortAudio arrives with a pip
package on all three systems. Wearing the Popen shape here means the listener
loop stays exactly as it is.
"""

from __future__ import annotations

import threading

RATE = 16_000


class PortAudioRecorder:
    def __init__(self, rate: int = RATE, device=None):
        import sounddevice  # imported late so a Linux box never needs the package

        self._buf = bytearray()
        self._cv = threading.Condition()
        self._closed = False

        def on_block(indata, _frames, _time, _status):
            with self._cv:
                self._buf.extend(bytes(indata))
                self._cv.notify_all()

        self._stream = sounddevice.RawInputStream(
            samplerate=rate, blocksize=0, device=device, dtype="int16", channels=1, callback=on_block
        )
        self._stream.start()

    # -- Popen surface -----------------------------------------------------
    @property
    def stdout(self):
        return self

    def read(self, n: int) -> bytes:
        """Block until n bytes are available, like a pipe would."""
        with self._cv:
            while len(self._buf) < n and not self._closed:
                self._cv.wait(timeout=1.0)
            chunk = bytes(self._buf[:n])
            del self._buf[:n]
            return chunk

    def kill(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify_all()
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:  # noqa: BLE001 — closing twice must never raise
            pass

    def poll(self):
        """None while running, 0 once closed — mirrors Popen.poll()."""
        return None if not self._closed else 0

    def wait(self, timeout=None):  # noqa: ARG002
        return self.poll()
