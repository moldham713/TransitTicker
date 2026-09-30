"""Every screen the device can show, drawn onto a 64x32 palette canvas.

Screens only draw; display.Screen.refresh() pushes the finished frame to
the panel, so a half-drawn frame is never visible.

Visual language, shared by every screen:
- Amber minutes with a green dot: a live, real-time-tracked train - the
  same cue as a platform countdown clock. Dim blue-white minutes with no
  dot: a static-schedule estimate. The dot means the distinction holds up
  for color-blind riders too.
- A red 2x2 block in the top-right corner: the device can't currently
  reach the backend, so what's on screen may be out of date.
"""

from . import font

WIDTH = 64
HEIGHT = 32

# Palette indices.
BLACK = 0
WHITE = 1
DIM = 2
LIVE = 3
SCHEDULED = 4
GREEN = 5
RED = 6
ACCENT = 7
MARKER_BASE = 8  # 8, 9, 10: one marker color per board row
PALETTE_SIZE = 11

_BASE_COLORS = (
    (0, 0, 0),        # BLACK (unlit)
    (200, 200, 200),  # WHITE
    (80, 80, 95),     # DIM
    (255, 150, 0),    # LIVE: amber
    (110, 120, 160),  # SCHEDULED: dim blue-white
    (0, 200, 60),     # GREEN
    (220, 0, 0),      # RED
    (0, 150, 220),    # ACCENT
)

_DEFAULT_MARKER_COLOR = (120, 120, 130)

# Official MTA route bullet colors, used once boards carry a route id.
_ROUTE_COLORS = {}
for _routes, _rgb in (
    (("1", "2", "3"), (238, 53, 46)),
    (("4", "5", "6", "6X"), (0, 147, 60)),
    (("7", "7X"), (185, 51, 173)),
    (("A", "C", "E", "SI"), (0, 57, 166)),
    (("B", "D", "F", "FX", "M"), (255, 99, 25)),
    (("G",), (108, 190, 69)),
    (("J", "Z"), (153, 102, 51)),
    (("L",), (167, 169, 172)),
    (("N", "Q", "R", "W"), (252, 204, 10)),
    (("S", "GS", "FS", "H"), (128, 129, 131)),
):
    for _route in _routes:
        _ROUTE_COLORS[_route] = _rgb

_SHUTTLES = ("GS", "FS", "H")


class Canvas:
    """A 64x32 drawing surface over a displayio Bitmap + Palette (or any
    objects with the same indexing interface, which is how the tests
    render screens on a desktop)."""

    def __init__(self, bitmap, palette, brightness=100):
        self.bitmap = bitmap
        self.palette = palette
        self._brightness = max(1, min(100, brightness))
        for index, rgb in enumerate(_BASE_COLORS):
            self.set_color(index, rgb)
        for row in range(3):
            self.set_color(MARKER_BASE + row, _DEFAULT_MARKER_COLOR)

    def set_color(self, index, rgb):
        # Brightness is applied by scaling palette colors, since the
        # matrix driver itself only offers on/off brightness.
        b = self._brightness
        red, green, blue = rgb
        self.palette[index] = ((red * b // 100) << 16) | ((green * b // 100) << 8) | (blue * b // 100)

    def clear(self):
        self.bitmap.fill(BLACK)

    def pixel(self, x, y, color):
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            self.bitmap[x, y] = color

    def fill_rect(self, x, y, width, height, color):
        for yy in range(y, y + height):
            for xx in range(x, x + width):
                self.pixel(xx, yy, color)

    def text_centered(self, y, text, color, face=font.SMALL):
        text = face.truncate(text, WIDTH)
        return face.draw(self, (WIDTH - face.measure(text)) // 2, y, text, color)


def _alert_corner(canvas):
    canvas.fill_rect(WIDTH - 2, 0, 2, 2, RED)


# -- generic screens ---------------------------------------------------

def splash(canvas):
    canvas.clear()
    canvas.text_centered(8, "TRANSIT", ACCENT, font.LARGE)
    canvas.text_centered(17, "TICKER", WHITE, font.LARGE)


def message(canvas, lines, alert=False):
    """Up to four centered lines of small text. Each line is a string
    (drawn white) or a (text, palette_index) pair."""
    canvas.clear()
    pitch = font.SMALL.height + 2
    lines = lines[:4]
    y = (HEIGHT - (len(lines) * pitch - 2)) // 2
    for line in lines:
        if isinstance(line, str):
            text, color = line, WHITE
        else:
            text, color = line
        canvas.text_centered(y, text, color)
        y += pitch
    if alert:
        _alert_corner(canvas)


def countdown_message(canvas, lines, seconds_left, alert=True):
    message(canvas, list(lines) + [("RETRY IN %dS" % seconds_left, DIM)], alert)


# -- setup and pairing -------------------------------------------------

def wifi_setup(canvas, ap_ssid, password, ip):
    """Instructions for the WiFi setup portal: which hotspot to join, its
    password (large, since it has to be typed), and the address to open."""
    canvas.clear()
    canvas.text_centered(1, "JOIN WIFI", ACCENT)
    canvas.text_centered(8, ap_ssid, WHITE)
    canvas.text_centered(15, password, LIVE, font.LARGE)
    canvas.text_centered(25, "OPEN " + ip, WHITE)


def pairing(canvas, code, seconds_left, hint, alert=False):
    canvas.clear()
    canvas.text_centered(1, "ENTER CODE", ACCENT)
    _draw_code(canvas, 9, code)
    canvas.text_centered(19, hint, DIM)
    minutes, seconds = divmod(max(0, seconds_left), 60)
    canvas.text_centered(26, "EXPIRES %d:%02d" % (minutes, seconds), DIM)
    if alert:
        _alert_corner(canvas)


def _draw_code(canvas, y, code):
    face = font.LARGE
    if len(code) != 6:
        canvas.text_centered(y, code, WHITE, face)
        return
    # Two groups of three, the way humans read a code aloud.
    left, right = code[:3], code[3:]
    gap = 4
    width = face.measure(left) + gap + face.measure(right)
    x = (WIDTH - width) // 2
    face.draw(canvas, x, y, left, WHITE)
    face.draw(canvas, x + face.measure(left) + gap, y, right, WHITE)


def reset_hold(canvas, held_ms, unpair_ms, full_reset_ms):
    """Feedback while the reset button is held at boot, so the outcome of
    letting go is always on screen before it happens."""
    if held_ms < unpair_ms:
        seconds = (unpair_ms - held_ms + 999) // 1000
        lines = [("KEEP HOLDING", WHITE), ("TO UNPAIR", DIM), ("%d" % seconds, ACCENT)]
    elif held_ms < full_reset_ms:
        seconds = (full_reset_ms - held_ms + 999) // 1000
        lines = [("RELEASE TO", WHITE), ("UNPAIR", LIVE), ("HOLD %dS MORE" % seconds, DIM), ("TO ERASE WIFI", DIM)]
    else:
        lines = [("RELEASE TO", WHITE), ("ERASE WIFI", RED), ("AND PAIRING", RED)]
    message(canvas, lines)


# -- departures --------------------------------------------------------

_ROW_HEIGHT = 9
_ROW_PITCH = 11
_SLOT_X = (11, 29, 47)
# Minutes are right-aligned to this offset within a slot, so one- and
# two-digit values line up in columns; the live dot sits just after.
_SLOT_DIGITS_RIGHT = 11
_MAX_MINUTES = 99

_MARKER_ROWS = tuple(int(row, 2) for row in (
    "001111100",
    "011111110",
    "111111111",
    "111111111",
    "111111111",
    "111111111",
    "111111111",
    "011111110",
    "001111100",
))


def boards(canvas, rows, alert=False):
    """One row per saved station: a round marker, then up to three
    departures as minutes-away."""
    if not rows:
        message(canvas, [("NO STATIONS", WHITE), ("SAVED YET", WHITE), ("ADD SOME ON", DIM), ("THE WEB APP", DIM)], alert)
        return

    canvas.clear()
    rows = rows[:3]
    top = (HEIGHT - (len(rows) * _ROW_PITCH - (_ROW_PITCH - _ROW_HEIGHT))) // 2
    for index, row in enumerate(rows):
        y = top + index * _ROW_PITCH
        _draw_marker(canvas, index, y, row.get("route"))
        departures = row["departures"]
        if not departures:
            font.SMALL.draw(canvas, _SLOT_X[0], y + 2, "NO TRAINS", DIM)
            continue
        for slot_x, (minutes, live) in zip(_SLOT_X, departures):
            text = str(min(minutes, _MAX_MINUTES))
            x = slot_x + _SLOT_DIGITS_RIGHT - font.LARGE.measure(text)
            font.LARGE.draw(canvas, x, y + 1, text, LIVE if live else SCHEDULED)
            if live:
                canvas.fill_rect(slot_x + _SLOT_DIGITS_RIGHT + 1, y + 1, 2, 2, GREEN)
    if alert:
        _alert_corner(canvas)


def _draw_marker(canvas, index, y, route):
    color_index = MARKER_BASE + index
    if route:
        canvas.set_color(color_index, _ROUTE_COLORS.get(route.upper(), _DEFAULT_MARKER_COLOR))
        label = "S" if route.upper() in _SHUTTLES else route[0]
    else:
        canvas.set_color(color_index, _DEFAULT_MARKER_COLOR)
        label = str(index + 1)
    for row, mask in enumerate(_MARKER_ROWS):
        for col in range(9):
            if mask & (1 << (8 - col)):
                canvas.pixel(col, y + row, color_index)
    # Label is cut out of the marker (unlit pixels), which reads clearly
    # against every route color.
    label_x = (9 - font.SMALL.measure(label)) // 2
    font.SMALL.draw(canvas, label_x, y + 2, label, BLACK)
