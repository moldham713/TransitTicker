"""Small helpers shared across the firmware: timekeeping, logging, retry
backoff, and the hardware watchdog."""

import random
import time


def now_ms():
    """Milliseconds since boot, as an int.

    time.monotonic() returns a single-precision float on CircuitPython, whose
    resolution coarsens as uptime grows (to whole seconds after a few months).
    This device is meant to run indefinitely, so every timer in the firmware
    uses integer milliseconds from monotonic_ns().
    """
    return time.monotonic_ns() // 1000000


def log(message):
    print("[%9.1f] %s" % (now_ms() / 1000, message))


def mask(token):
    """Enough of a device token to tell tokens apart in the serial log,
    without writing the whole credential to it."""
    if not token:
        return "<none>"
    return token[:4] + "..."


def backoff_ms(failures, base_ms=5000, cap_ms=120000):
    """Exponential retry delay for the nth consecutive failure (n >= 1),
    with +/-20% jitter so a fleet of devices knocked offline by the same
    outage doesn't retry in lockstep when it ends."""
    exponent = min(max(failures, 1) - 1, 10)
    delay = min(cap_ms, base_ms << exponent)
    jitter = delay // 5
    return delay - jitter + random.randint(0, 2 * jitter)


class Watchdog:
    """Hardware watchdog that hard-resets the board if the main loop stops
    feeding it - the recovery path for a network call that hangs past its
    own timeout (DNS lookups, for one, aren't covered by the HTTP timeout).

    Disabled via TRANSITTICKER_WATCHDOG = 0, which is useful while working
    at the REPL, and silently inert on boards whose port lacks a watchdog.
    """

    TIMEOUT_S = 60

    def __init__(self, enabled):
        self._wdt = None
        if not enabled:
            log("watchdog disabled by settings")
            return
        try:
            import microcontroller
            from watchdog import WatchDogMode

            wdt = microcontroller.watchdog
            wdt.timeout = self.TIMEOUT_S
            wdt.mode = WatchDogMode.RESET
            wdt.feed()
            self._wdt = wdt
            log("watchdog armed (%ds)" % self.TIMEOUT_S)
        except (ImportError, AttributeError, NotImplementedError, RuntimeError, ValueError) as exc:
            log("watchdog unavailable: %r" % exc)

    def feed(self):
        if self._wdt is not None:
            self._wdt.feed()

    def disarm(self):
        """Best-effort stop, called when the firmware is interrupted from the
        serial console so the board doesn't reset under someone at the REPL."""
        if self._wdt is None:
            return
        try:
            self._wdt.deinit()
        except (RuntimeError, NotImplementedError, ValueError):
            pass
        self._wdt = None
