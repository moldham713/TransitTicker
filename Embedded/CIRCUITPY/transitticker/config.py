"""Runtime settings, read from settings.toml on the CIRCUITPY drive.

Everything here is per-environment (local dev vs. production), never
per-unit: every device built for an environment ships the same
settings.toml. Per-unit identity - which WiFi network a unit joins and the
device token it was paired with - lives in non-volatile memory, written at
runtime by the WiFi setup portal and the pairing flow (see storage.py).
"""

import os

from .util import log

DEFAULT_POLL_SECONDS = 25


def _get_str(name):
    value = os.getenv(name)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _get_int(name, default, minimum, maximum):
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        log("settings: %s=%r is not an integer, using %d" % (name, raw, default))
        return default
    return max(minimum, min(maximum, value))


class Config:
    def __init__(self):
        # Base URL of the Flask backend, e.g. "http://192.168.1.50:5000" in
        # local dev or the load balancer's address in production. No
        # default: a device pointed at the wrong backend silently pairs
        # against the wrong user database, so a missing value halts with an
        # on-screen error (see api_url_problem).
        self.api_url = _get_str("TRANSITTICKER_API_URL")

        # The backend refreshes live predictions every ~30s, so polling
        # much faster than that returns the same data.
        self.poll_seconds = _get_int("TRANSITTICKER_POLL_SECONDS", DEFAULT_POLL_SECONDS, 10, 300)

        # Short text shown under the pairing code telling the user where to
        # enter it, e.g. the web app's domain. Must fit ~15 characters of
        # the small font; longer values are cut off at the screen edge.
        self.pair_hint = _get_str("TRANSITTICKER_PAIR_HINT") or "ON THE WEB APP"

        self.brightness = _get_int("TRANSITTICKER_BRIGHTNESS", 60, 1, 100)

        # All screens are laid out for a 64x32 panel; larger panels (chained
        # 64-wide panels, or a 64x64 with the address E jumper soldered)
        # show that 64x32 picture centered.
        self.matrix_width = _get_int("TRANSITTICKER_MATRIX_WIDTH", 64, 64, 256)
        self.matrix_height = 64 if _get_int("TRANSITTICKER_MATRIX_HEIGHT", 32, 32, 64) > 32 else 32

        self.watchdog = _get_int("TRANSITTICKER_WATCHDOG", 1, 0, 1) == 1

        # Development shortcut: CircuitPython's own WiFi settings. When
        # present they take priority over credentials saved through the
        # setup portal. Production images leave them out so end users
        # provision WiFi from the device itself.
        self.dev_wifi_ssid = _get_str("CIRCUITPY_WIFI_SSID")
        self.dev_wifi_password = _get_str("CIRCUITPY_WIFI_PASSWORD") or ""

    def api_url_problem(self):
        """A short on-screen explanation if the API URL can't be used, else None."""
        if not self.api_url:
            return "NO API URL SET"
        if not (self.api_url.startswith("http://") or self.api_url.startswith("https://")):
            return "BAD API URL"
        return None
