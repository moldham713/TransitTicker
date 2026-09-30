"""WiFi station connection and the shared HTTP session."""

import adafruit_connection_manager
import adafruit_requests
import wifi

from .util import log

CONNECT_TIMEOUT_S = 15
MAX_SCAN_RESULTS = 20


class Network:
    def __init__(self):
        self.pool = adafruit_connection_manager.get_radio_socketpool(wifi.radio)
        ssl_context = adafruit_connection_manager.get_radio_ssl_context(wifi.radio)
        # The SSL context is unused while the backend is plain HTTP, and
        # makes https:// API URLs work unchanged once TLS is in place.
        self.session = adafruit_requests.Session(self.pool, ssl_context)

    @property
    def connected(self):
        return wifi.radio.connected

    def connect(self, ssid, password):
        """Join `ssid`. Returns True on success; failures are logged, not raised."""
        log("wifi: connecting to %r" % ssid)
        try:
            wifi.radio.connect(ssid, password, timeout=CONNECT_TIMEOUT_S)
        except (ConnectionError, OSError, ValueError, RuntimeError) as exc:
            log("wifi: connect failed: %r" % exc)
            return False
        log("wifi: connected, ip %s" % wifi.radio.ipv4_address)
        return True

    def scan(self):
        """Nearby network names, strongest first, for the setup portal."""
        strongest = {}
        try:
            for network in wifi.radio.start_scanning_networks():
                name = network.ssid
                if name and (name not in strongest or network.rssi > strongest[name]):
                    strongest[name] = network.rssi
        except (OSError, RuntimeError) as exc:
            log("wifi: scan failed: %r" % exc)
        try:
            wifi.radio.stop_scanning_networks()
        except (OSError, RuntimeError):
            pass
        names = sorted(strongest, key=lambda name: -strongest[name])
        return names[:MAX_SCAN_RESULTS]


def mac_suffix():
    """Last two bytes of this unit's MAC address as 4 hex digits: a short
    per-unit identifier derived from hardware, so identical firmware still
    gives every unit a distinct setup hotspot name."""
    mac = wifi.radio.mac_address
    return "%02X%02X" % (mac[-2], mac[-1])
