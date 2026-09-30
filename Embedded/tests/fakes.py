"""Desktop stand-ins for the displayio and adafruit_requests objects the
pure-logic firmware modules touch."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "CIRCUITPY"))


class FakeBitmap:
    """Same indexing interface as displayio.Bitmap, and like it, raises on
    out-of-range pixels - so any layout that draws off-canvas fails loudly."""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.pixels = [[0] * width for _ in range(height)]

    def fill(self, value):
        for row in self.pixels:
            for x in range(self.width):
                row[x] = value

    def __setitem__(self, key, value):
        x, y = key
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError("pixel (%d, %d) out of range" % (x, y))
        self.pixels[y][x] = value

    def __getitem__(self, key):
        x, y = key
        return self.pixels[y][x]

    def ascii(self):
        chars = " #@%*+o=~abc"
        return "\n".join("|" + "".join(chars[v] if v < len(chars) else "?" for v in row) + "|" for row in self.pixels)


def make_canvas(brightness=100):
    from transitticker import render

    return render.Canvas(FakeBitmap(render.WIDTH, render.HEIGHT), [0] * render.PALETTE_SIZE, brightness)


class FakeResponse:
    def __init__(self, status_code=200, body=None, json_error=None):
        self.status_code = status_code
        self._body = body
        self._json_error = json_error
        self.closed = False

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._body

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, method, url, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "timeout": timeout})
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
