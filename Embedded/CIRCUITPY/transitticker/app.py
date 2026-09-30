"""The device's top-level behavior.

    boot -> [DOWN held? reset flow] -> WiFi -> paired? --no--> pairing ----+
                                                 |                         |
                                                yes                        |
                                                 v                         |
                                   departures loop <---- token saved ------+
                                                 |
                                   401 from backend: forget token, back to pairing

WiFi is re-checked before every network call, so losing the network at any
point drops into the reconnect screen and resumes where it left off.
"""

import time

import microcontroller

from . import config, departures, display, network, portal, render, reset
from .api import ApiClient, ApiError, Unauthorized
from .storage import DeviceStore
from .util import Watchdog, backoff_ms, log, mask, now_ms

UI_TICK_S = 0.25
STATUS_POLL_MS = 4000
# The device requests a fresh code slightly before the server-side expiry,
# so it never displays a code the backend is about to reject.
PAIRING_EXPIRY_MARGIN_MS = 3000
# Beyond this age, cached departures are too old to count down from, and
# the screen says so.
MAX_DATA_AGE_MS = 10 * 60 * 1000
# Unverified WiFi credentials get this many tries before the setup portal
# reopens, which covers a network that is slow to accept the first join.
UNVERIFIED_WIFI_ATTEMPTS = 2


class Device:
    def __init__(self, cfg, screen, store, watchdog):
        self.cfg = cfg
        self.screen = screen
        self.store = store
        self.dog = watchdog
        self.net = network.Network()
        self.api = ApiClient(self.net.session, cfg.api_url)

    # -- helpers -------------------------------------------------------

    def show(self, draw, *args):
        draw(self.screen.canvas, *args)
        self.screen.refresh()

    def pause(self, seconds):
        deadline = now_ms() + int(seconds * 1000)
        while now_ms() < deadline:
            self.dog.feed()
            time.sleep(UI_TICK_S)

    def countdown(self, lines, delay_ms):
        """Show `lines` plus a live "RETRY IN Ns" until `delay_ms` passes."""
        deadline = now_ms() + delay_ms
        while True:
            remaining = deadline - now_ms()
            if remaining <= 0:
                return
            self.show(render.countdown_message, lines, (remaining + 999) // 1000)
            self.dog.feed()
            time.sleep(UI_TICK_S)

    # -- main loop -----------------------------------------------------

    def run(self):
        while True:
            self.ensure_wifi()
            token = self.store.token
            if token is None:
                self.pair()
            else:
                self.show_departures(token)

    # -- WiFi ----------------------------------------------------------

    def _wifi_credentials(self):
        if self.cfg.dev_wifi_ssid:
            return self.cfg.dev_wifi_ssid, self.cfg.dev_wifi_password, True
        return self.store.wifi

    def ensure_wifi(self):
        if self.net.connected:
            return
        failures = 0
        while True:
            credentials = self._wifi_credentials()
            if credentials is None:
                self._run_setup_portal(None)
                continue
            ssid, password, verified = credentials
            self.show(render.message, [("CONNECTING TO", render.ACCENT), ssid])
            self.dog.feed()
            if self.net.connect(ssid, password):
                if not verified:
                    self.store.mark_wifi_verified()
                return
            failures += 1
            if not verified and failures >= UNVERIFIED_WIFI_ATTEMPTS:
                self._run_setup_portal("Couldn't join \"%s\". Check the network name and password." % ssid)
                failures = 0
                continue
            self.countdown([("WIFI UNAVAILABLE", render.WHITE), (ssid, render.DIM)], backoff_ms(failures))

    def _run_setup_portal(self, error):
        self.show(render.message, [("SCANNING FOR", render.WHITE), ("NETWORKS", render.WHITE)])
        networks = self.net.scan()
        self.dog.feed()
        portal.run(
            pool=self.net.pool,
            store=self.store,
            networks=networks,
            draw_instructions=lambda ssid, password, ip: self.show(render.wifi_setup, ssid, password, ip),
            feed=self.dog.feed,
            error=error,
        )

    # -- pairing -------------------------------------------------------

    def pair(self):
        """Show pairing codes until one is claimed; returns once a token is saved."""
        failures = 0
        while True:
            self.ensure_wifi()
            self.show(render.message, [("GETTING", render.WHITE), ("PAIRING CODE", render.WHITE)])
            self.dog.feed()
            try:
                code, expires_in = self.api.pair_start()
            except (ApiError, Unauthorized) as exc:
                failures += 1
                log("pairing: start failed: %s" % exc)
                self.countdown([("CAN'T REACH", render.WHITE), ("SERVER", render.WHITE)], backoff_ms(failures))
                continue
            failures = 0
            log("pairing: showing code %s (expires in %ds)" % (code, expires_in))
            if self._wait_for_claim(code, expires_in):
                return
            log("pairing: code %s expired, requesting a new one" % code)

    def _wait_for_claim(self, code, expires_in):
        deadline = now_ms() + expires_in * 1000 - PAIRING_EXPIRY_MARGIN_MS
        next_poll = now_ms() + STATUS_POLL_MS
        alert = False
        while True:
            now = now_ms()
            if now >= deadline:
                return False
            if now >= next_poll:
                self.ensure_wifi()
                try:
                    status, token = self.api.pair_status(code)
                except (ApiError, Unauthorized) as exc:
                    # The code stays valid server-side until it expires, so
                    # keep showing it and keep polling.
                    log("pairing: status check failed: %s" % exc)
                    alert = True
                else:
                    alert = False
                    if status == "claimed":
                        self.store.set_token(token)
                        log("pairing: claimed, token %s saved" % mask(token))
                        self.show(render.message, [("PAIRED!", render.GREEN)])
                        self.pause(2)
                        return True
                    if status == "not_found":
                        return False
                next_poll = now_ms() + STATUS_POLL_MS
            self.show(render.pairing, code, (deadline - now_ms() + 999) // 1000, self.cfg.pair_hint, alert)
            self.dog.feed()
            time.sleep(UI_TICK_S)

    # -- departures ----------------------------------------------------

    def show_departures(self, token):
        """Poll and display departures; returns only if the token is rejected."""
        poll_ms = self.cfg.poll_seconds * 1000
        stale_after_ms = poll_ms * 2 + 15000
        boards = None
        fetched_at = 0
        failures = 0
        next_poll = now_ms()
        log("departures: polling every %ds with token %s" % (self.cfg.poll_seconds, mask(token)))
        while True:
            if now_ms() >= next_poll:
                self.ensure_wifi()
                try:
                    boards = self.api.departures(token)
                except Unauthorized:
                    log("departures: token rejected (401), returning to pairing")
                    self.store.clear_token()
                    self.show(render.message, [("DEVICE UNLINKED", render.WHITE), ("PAIRING AGAIN", render.DIM)])
                    self.pause(3)
                    return
                except ApiError as exc:
                    failures += 1
                    log("departures: fetch failed (%d in a row): %s" % (failures, exc))
                    # Retry quickly after a blip, backing off to the normal
                    # poll interval during a longer outage.
                    next_poll = now_ms() + min(backoff_ms(failures), poll_ms)
                else:
                    fetched_at = now_ms()
                    failures = 0
                    next_poll = fetched_at + poll_ms
            self._draw_departures(boards, fetched_at, failures, stale_after_ms)
            self.dog.feed()
            time.sleep(1)

    def _draw_departures(self, boards, fetched_at, failures, stale_after_ms):
        if boards is None:
            if failures:
                self.show(render.message, [("CAN'T REACH", render.WHITE), ("SERVER", render.WHITE), ("RETRYING", render.DIM)], True)
            else:
                self.show(render.message, [("LOADING", render.WHITE)])
            return
        age = now_ms() - fetched_at
        if age > MAX_DATA_AGE_MS:
            self.show(render.message, [("NO LIVE DATA", render.WHITE), ("CAN'T REACH", render.DIM), ("SERVER", render.DIM)], True)
            return
        self.show(render.boards, departures.build_rows(boards, age), age > stale_after_ms)


def main():
    cfg = config.Config()
    screen = None
    dog = None
    try:
        screen = display.create_screen(cfg.matrix_width, cfg.matrix_height, cfg.brightness)
        render.splash(screen.canvas)
        screen.refresh()

        dog = Watchdog(cfg.watchdog)
        store = DeviceStore(microcontroller.nvm)
        log("boot: paired=%s wifi_saved=%s" % (store.token is not None, store.wifi is not None))

        def show(draw, *args):
            draw(screen.canvas, *args)
            screen.refresh()

        reset.check_boot_hold(show, store, dog.feed)

        problem = cfg.api_url_problem()
        if problem:
            # A build/configuration mistake, not something the end user
            # can fix; halt with the reason on screen. Saving a corrected
            # settings.toml restarts code.py automatically.
            log("config: %s (TRANSITTICKER_API_URL=%r)" % (problem, cfg.api_url))
            show(render.message, [(problem, render.RED), ("CHECK", render.DIM), ("SETTINGS.TOML", render.DIM)])
            while True:
                dog.feed()
                time.sleep(1)

        log("boot: backend %s" % cfg.api_url)
        Device(cfg, screen, store, dog).run()
    except KeyboardInterrupt:
        # Ctrl-C at the serial console: hand control to the REPL.
        if dog is not None:
            dog.disarm()
        raise
    except Exception as exc:  # noqa: BLE001 - last-resort recovery for an unattended appliance
        _report_crash(exc, screen)
        microcontroller.reset()


def _report_crash(exc, screen):
    try:
        import traceback

        traceback.print_exception(exc, exc, exc.__traceback__)
    except Exception:  # noqa: BLE001
        print("fatal:", repr(exc))
    if screen is not None:
        try:
            render.message(screen.canvas, [("ERROR", render.RED), (type(exc).__name__, render.DIM), ("RESTARTING", render.DIM)])
            screen.refresh()
        except Exception:  # noqa: BLE001
            pass
    # Long enough to read the screen and serial output; short enough that
    # the unit recovers on its own. The watchdog timeout is longer than this.
    time.sleep(10)
