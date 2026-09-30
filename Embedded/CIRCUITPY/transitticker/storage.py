"""Per-unit state that must survive power cycles: the device token and the
WiFi credentials entered through the setup portal.

Stored in microcontroller.nvm, a small non-volatile byte array that code.py
can write while the CIRCUITPY drive stays writable over USB. (The CIRCUITPY
filesystem itself is read-only to code whenever it is writable from a
computer.) It also lives outside the filesystem, so reinstalling firmware
files onto CIRCUITPY leaves a unit's pairing intact.

Record layout: b"TTK1" magic, 2-byte big-endian length, then that many
bytes of UTF-8 JSON. Anything else in nvm - a fresh board, or a board that
ran other firmware - reads as empty state.
"""

import json

MAGIC = b"TTK1"
HEADER_SIZE = len(MAGIC) + 2


class DeviceStore:
    def __init__(self, nvm):
        if nvm is None:
            raise RuntimeError("this board has no microcontroller.nvm to store pairing in")
        self._nvm = nvm
        self._data = self._load()

    # -- device token --------------------------------------------------

    @property
    def token(self):
        token = self._data.get("token")
        return token if isinstance(token, str) and token else None

    def set_token(self, token):
        self._update(token=token)

    def clear_token(self):
        self._update(token=None)

    # -- WiFi ----------------------------------------------------------

    @property
    def wifi(self):
        """(ssid, password, verified) or None. `verified` records whether
        the unit has ever joined with these credentials: an unverified
        network that fails is most likely a typo, so the firmware reopens
        the setup portal, while a verified one that fails is most likely a
        router outage, so it keeps retrying."""
        ssid = self._data.get("ssid")
        if not isinstance(ssid, str) or not ssid:
            return None
        password = self._data.get("psk")
        if not isinstance(password, str):
            password = ""
        return ssid, password, bool(self._data.get("wifi_ok"))

    def set_wifi(self, ssid, password):
        self._update(ssid=ssid, psk=password, wifi_ok=False)

    def mark_wifi_verified(self):
        self._update(wifi_ok=True)

    # -- reset ---------------------------------------------------------

    def factory_reset(self):
        """Forget everything: token and WiFi. Overwriting the header is
        enough, since a record without the magic bytes reads as empty."""
        self._nvm[0:HEADER_SIZE] = bytes(HEADER_SIZE)
        self._data = {}

    # -- internals -----------------------------------------------------

    def _load(self):
        nvm = self._nvm
        if len(nvm) < HEADER_SIZE or bytes(nvm[0:len(MAGIC)]) != MAGIC:
            return {}
        length = (nvm[4] << 8) | nvm[5]
        if length > len(nvm) - HEADER_SIZE:
            return {}
        try:
            data = json.loads(bytes(nvm[HEADER_SIZE:HEADER_SIZE + length]).decode("utf-8"))
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def _update(self, **changes):
        data = dict(self._data)
        for key, value in changes.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        if data == self._data:
            # Nothing changed, so skip the flash write.
            return
        self._write(data)
        self._data = data

    def _write(self, data):
        payload = json.dumps(data).encode("utf-8")
        if HEADER_SIZE + len(payload) > len(self._nvm) or len(payload) > 0xFFFF:
            raise ValueError("device state (%d bytes) does not fit in nvm" % len(payload))
        record = MAGIC + bytes((len(payload) >> 8, len(payload) & 0xFF)) + payload
        # One slice assignment for the whole record: on the ESP32-S3 port,
        # each nvm assignment is committed to flash as a single atomic
        # write, so a power cut mid-save leaves the old record intact and
        # never a new header over a half-written payload.
        self._nvm[0:len(record)] = record
