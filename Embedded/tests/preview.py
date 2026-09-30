"""Print every screen as ASCII art, for checking layouts without a panel.

    python tests/preview.py

Each character is one LED; the symbol identifies the palette color
(space = off, # white, @ dim, % amber/live, * scheduled, + green, o red,
= accent, ~ a-c row markers).
"""

from fakes import make_canvas  # noqa: E402 (sets sys.path)

from transitticker import render


def show(title, draw, *args):
    canvas = make_canvas()
    draw(canvas, *args)
    print("== %s ==" % title)
    print("+" + "-" * render.WIDTH + "+")
    print(canvas.bitmap.ascii())
    print("+" + "-" * render.WIDTH + "+\n")


if __name__ == "__main__":
    show("splash", render.splash)
    show("wifi setup", render.wifi_setup, "TICKER-4F2A", "80315562", "192.168.4.1")
    show("pairing", render.pairing, "AB3XQ9", 581, "ON THE WEB APP", False)
    show("pairing (server unreachable)", render.pairing, "KMN7WX", 42, "ON THE WEB APP", True)
    show("three boards", render.boards, [
        {"route": None, "departures": [(2, True), (9, True), (14, False)]},
        {"route": None, "departures": [(0, True), (23, False)]},
        {"route": None, "departures": []},
    ])
    show("one board, route-labelled, stale", render.boards, [
        {"route": "Q", "departures": [(4, True), (11, False), (58, False)]},
    ], True)
    show("no stations", render.boards, [])
    show("reset hold (armed: unpair)", render.reset_hold, 4200, 3000, 10000)
    show("countdown", render.countdown_message, [("WIFI UNAVAILABLE", render.WHITE), ("HomeNet", render.DIM)], 17)
