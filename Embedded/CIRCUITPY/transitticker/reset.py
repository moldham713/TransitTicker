"""Physical reset: hold the DOWN button while the unit powers up.

This works regardless of server state or network, which is what makes a
unit resellable without the previous owner's involvement:

- Hold 3s, release: unpair (forget the device token, keep WiFi) - for
  moving the unit to a different account on the same network.
- Hold 10s, release: full reset (forget the token and WiFi) - for handing
  the unit to someone else.
- Release sooner: nothing happens.

DOWN (board.BUTTON_DOWN) is used because BOOT held at reset enters the
ESP32-S3 ROM bootloader, and RESET restarts the board. UP and DOWN have no
external pull-ups and pull low when pressed, so the internal pull-up is
enabled here.
"""

import time

import board
import digitalio

from . import render
from .util import log, now_ms

UNPAIR_HOLD_MS = 3000
FULL_RESET_HOLD_MS = 10000
DEBOUNCE_MS = 100


def check_boot_hold(show, store, feed):
    """If DOWN is held right now, run the hold/release interaction.

    Args:
        show: callable(draw_fn, *args) that renders a screen and refreshes.
        store: storage.DeviceStore.
        feed: watchdog feed callable.
    """
    button = digitalio.DigitalInOut(board.BUTTON_DOWN)
    button.switch_to_input(pull=digitalio.Pull.UP)
    try:
        if button.value:
            return
        time.sleep(0.03)
        if button.value:
            return  # contact bounce, not a hold

        log("reset: DOWN held at boot")
        start = last_pressed = now_ms()
        # The hold ends once the button has read released continuously
        # for DEBOUNCE_MS, so contact chatter mid-hold doesn't end it early.
        while now_ms() - last_pressed < DEBOUNCE_MS:
            if not button.value:
                last_pressed = now_ms()
            show(render.reset_hold, last_pressed - start, UNPAIR_HOLD_MS, FULL_RESET_HOLD_MS)
            feed()
            time.sleep(0.05)

        held = last_pressed - start
        if held >= FULL_RESET_HOLD_MS:
            store.factory_reset()
            log("reset: full reset, token and WiFi erased")
            show(render.message, [("RESET DONE", render.GREEN), ("WIFI AND", render.DIM), ("PAIRING ERASED", render.DIM)])
        elif held >= UNPAIR_HOLD_MS:
            store.clear_token()
            log("reset: unpaired")
            show(render.message, [("UNPAIRED", render.GREEN)])
        else:
            show(render.message, [("CANCELLED", render.DIM)])
        _pause(2, feed)
    finally:
        button.deinit()


def _pause(seconds, feed):
    deadline = now_ms() + seconds * 1000
    while now_ms() < deadline:
        feed()
        time.sleep(0.1)
