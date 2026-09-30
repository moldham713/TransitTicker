"""WiFi setup portal: how a unit fresh out of the box (or freshly factory
reset) learns which network to join, with no computer or file editing.

The unit starts its own WPA2 hotspot, "TICKER-XXXX", and shows the name,
a random 8-digit password and the portal address on the matrix. The user
joins that hotspot from a phone, opens the address and picks their home
network. The hotspot password is generated fresh each time and exists only
on the screen, so only someone who can see the display can join it - the
home WiFi password then travels over an encrypted link.
"""

import os
import time

import wifi
from adafruit_httpserver import GET, POST, Request, Response, Server

from . import web
from .network import mac_suffix
from .util import log, now_ms

AP_PASSWORD_DIGITS = 8
HTML = "text/html; charset=utf-8"
# After the "saved" page is served, keep serving briefly so the phone
# receives the whole response before the hotspot disappears.
FLUSH_MS = 1500


def _ap_password():
    return "".join(str(byte % 10) for byte in os.urandom(AP_PASSWORD_DIGITS))


def run(pool, store, networks, draw_instructions, feed, error=None):
    """Serve the portal until credentials are submitted and saved to
    `store` (unverified - app.Device.ensure_wifi verifies them by joining).

    Args:
        pool: socket pool for the HTTP server.
        store: storage.DeviceStore.
        networks: nearby SSIDs to suggest (scanned before the hotspot
            starts, since scanning disturbs an active access point).
        draw_instructions: callable(ap_ssid, password, ip) that puts the
            join instructions on the matrix.
        feed: watchdog feed callable.
        error: message shown at the top of the form, e.g. why the last
            attempt to join failed.
    """
    ap_ssid = "TICKER-" + mac_suffix()
    password = _ap_password()
    wifi.radio.start_ap(ap_ssid, password, authmode=[wifi.AuthMode.WPA2, wifi.AuthMode.PSK])
    ip = str(wifi.radio.ipv4_address_ap)
    log("portal: hotspot %s up, serving http://%s/" % (ap_ssid, ip))
    draw_instructions(ap_ssid, password, ip)

    saved = []
    server = Server(pool, debug=False)

    @server.route("/", GET)
    def show_form(request: Request):
        return Response(request, web.setup_page(networks, error), content_type=HTML)

    @server.route("/", POST)
    def save(request: Request):
        try:
            fields = web.parse_form(request.body)
        except ValueError:
            return Response(request, web.setup_page(networks, "That form couldn't be read - please try again."), content_type=HTML)
        ssid, wifi_password, problem = web.validate_wifi(fields)
        if problem:
            return Response(request, web.setup_page(networks, problem, ssid), content_type=HTML)
        store.set_wifi(ssid, wifi_password)
        saved.append(ssid)
        log("portal: saved network %r" % ssid)
        return Response(request, web.saved_page(ssid), content_type=HTML)

    server.start(ip, 80)
    try:
        flush_until = None
        while True:
            feed()
            try:
                server.poll()
            except (OSError, RuntimeError) as exc:
                log("portal: request failed: %r" % exc)
            if saved:
                if flush_until is None:
                    flush_until = now_ms() + FLUSH_MS
                elif now_ms() >= flush_until:
                    return
            time.sleep(0.01)
    finally:
        server.stop()
        wifi.radio.stop_ap()
        log("portal: hotspot stopped")
