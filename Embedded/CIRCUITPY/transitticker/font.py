"""Two bitmap fonts drawn directly onto the matrix canvas.

- SMALL: 3x5 (a few glyphs wider), for labels and messages. Fits 16
  characters across a 64-pixel panel and four lines down a 32-pixel one.
- LARGE: 5x7, for the numbers that matter at a glance - minutes until a
  train, and the pairing code a human has to read and type. The pairing
  code alphabet (see Backend/src/pairing.py) excludes look-alike
  characters, and a 5x7 grid keeps the rest unambiguous; at 3x5, letters
  like M and N are hard to tell apart.

Glyphs are written as rows of "X" (lit) and "." (unlit) so they can be
read and edited in place. Lowercase text renders as uppercase; any other
unknown character renders as "?".
"""

_SMALL_GLYPHS = {
    " ": ("..", "..", "..", "..", ".."),
    "!": ("X", "X", "X", ".", "X"),
    "'": ("X", "X", ".", ".", "."),
    "(": (".X", "X.", "X.", "X.", ".X"),
    ")": ("X.", ".X", ".X", ".X", "X."),
    "+": ("...", ".X.", "XXX", ".X.", "..."),
    "-": ("...", "...", "XXX", "...", "..."),
    ".": (".", ".", ".", ".", "X"),
    "/": ("..X", "..X", ".X.", "X..", "X.."),
    ":": (".", "X", ".", "X", "."),
    "?": ("XX.", "..X", ".X.", "...", ".X."),
    "_": ("...", "...", "...", "...", "XXX"),
    "0": ("XXX", "X.X", "X.X", "X.X", "XXX"),
    "1": (".X.", "XX.", ".X.", ".X.", "XXX"),
    "2": ("XX.", "..X", ".X.", "X..", "XXX"),
    "3": ("XX.", "..X", ".X.", "..X", "XX."),
    "4": ("X.X", "X.X", "XXX", "..X", "..X"),
    "5": ("XXX", "X..", "XX.", "..X", "XX."),
    "6": (".XX", "X..", "XXX", "X.X", "XXX"),
    "7": ("XXX", "..X", "..X", ".X.", ".X."),
    "8": ("XXX", "X.X", "XXX", "X.X", "XXX"),
    "9": ("XXX", "X.X", "XXX", "..X", "XX."),
    "A": (".X.", "X.X", "XXX", "X.X", "X.X"),
    "B": ("XX.", "X.X", "XX.", "X.X", "XX."),
    "C": (".XX", "X..", "X..", "X..", ".XX"),
    "D": ("XX.", "X.X", "X.X", "X.X", "XX."),
    "E": ("XXX", "X..", "XX.", "X..", "XXX"),
    "F": ("XXX", "X..", "XX.", "X..", "X.."),
    "G": (".XX", "X..", "X.X", "X.X", ".XX"),
    "H": ("X.X", "X.X", "XXX", "X.X", "X.X"),
    "I": ("XXX", ".X.", ".X.", ".X.", "XXX"),
    "J": ("..X", "..X", "..X", "X.X", ".X."),
    "K": ("X.X", "X.X", "XX.", "X.X", "X.X"),
    "L": ("X..", "X..", "X..", "X..", "XXX"),
    "M": ("X...X", "XX.XX", "X.X.X", "X...X", "X...X"),
    "N": ("X..X", "XX.X", "X.XX", "X..X", "X..X"),
    "O": (".X.", "X.X", "X.X", "X.X", ".X."),
    "P": ("XX.", "X.X", "XX.", "X..", "X.."),
    "Q": (".X.", "X.X", "X.X", "XX.", ".XX"),
    "R": ("XX.", "X.X", "XX.", "X.X", "X.X"),
    "S": (".XX", "X..", ".X.", "..X", "XX."),
    "T": ("XXX", ".X.", ".X.", ".X.", ".X."),
    "U": ("X.X", "X.X", "X.X", "X.X", "XXX"),
    "V": ("X.X", "X.X", "X.X", "X.X", ".X."),
    "W": ("X...X", "X...X", "X.X.X", "XX.XX", "X...X"),
    "X": ("X.X", "X.X", ".X.", "X.X", "X.X"),
    "Y": ("X.X", "X.X", ".X.", ".X.", ".X."),
    "Z": ("XXX", "..X", ".X.", "X..", "XXX"),
}

_LARGE_GLYPHS = {
    " ": ("...", "...", "...", "...", "...", "...", "..."),
    "-": (".....", ".....", ".....", "XXXXX", ".....", ".....", "....."),
    "?": (".XXX.", "X...X", "....X", "...X.", "..X..", ".....", "..X.."),
    "0": (".XXX.", "X...X", "X..XX", "X.X.X", "XX..X", "X...X", ".XXX."),
    "1": ("..X..", ".XX..", "..X..", "..X..", "..X..", "..X..", ".XXX."),
    "2": (".XXX.", "X...X", "....X", "...X.", "..X..", ".X...", "XXXXX"),
    "3": ("XXXXX", "...X.", "..X..", "...X.", "....X", "X...X", ".XXX."),
    "4": ("...X.", "..XX.", ".X.X.", "X..X.", "XXXXX", "...X.", "...X."),
    "5": ("XXXXX", "X....", "XXXX.", "....X", "....X", "X...X", ".XXX."),
    "6": ("..XX.", ".X...", "X....", "XXXX.", "X...X", "X...X", ".XXX."),
    "7": ("XXXXX", "....X", "...X.", "..X..", ".X...", ".X...", ".X..."),
    "8": (".XXX.", "X...X", "X...X", ".XXX.", "X...X", "X...X", ".XXX."),
    "9": (".XXX.", "X...X", "X...X", ".XXXX", "....X", "...X.", ".XX.."),
    "A": (".XXX.", "X...X", "X...X", "XXXXX", "X...X", "X...X", "X...X"),
    "B": ("XXXX.", "X...X", "X...X", "XXXX.", "X...X", "X...X", "XXXX."),
    "C": (".XXX.", "X...X", "X....", "X....", "X....", "X...X", ".XXX."),
    "D": ("XXX..", "X..X.", "X...X", "X...X", "X...X", "X..X.", "XXX.."),
    "E": ("XXXXX", "X....", "X....", "XXXX.", "X....", "X....", "XXXXX"),
    "F": ("XXXXX", "X....", "X....", "XXXX.", "X....", "X....", "X...."),
    "G": (".XXX.", "X...X", "X....", "X.XXX", "X...X", "X...X", ".XXXX"),
    "H": ("X...X", "X...X", "X...X", "XXXXX", "X...X", "X...X", "X...X"),
    "I": (".XXX.", "..X..", "..X..", "..X..", "..X..", "..X..", ".XXX."),
    "J": ("..XXX", "...X.", "...X.", "...X.", "...X.", "X..X.", ".XX.."),
    "K": ("X...X", "X..X.", "X.X..", "XX...", "X.X..", "X..X.", "X...X"),
    "L": ("X....", "X....", "X....", "X....", "X....", "X....", "XXXXX"),
    "M": ("X...X", "XX.XX", "X.X.X", "X.X.X", "X...X", "X...X", "X...X"),
    "N": ("X...X", "X...X", "XX..X", "X.X.X", "X..XX", "X...X", "X...X"),
    "O": (".XXX.", "X...X", "X...X", "X...X", "X...X", "X...X", ".XXX."),
    "P": ("XXXX.", "X...X", "X...X", "XXXX.", "X....", "X....", "X...."),
    "Q": (".XXX.", "X...X", "X...X", "X...X", "X.X.X", "X..X.", ".XX.X"),
    "R": ("XXXX.", "X...X", "X...X", "XXXX.", "X.X..", "X..X.", "X...X"),
    "S": (".XXXX", "X....", "X....", ".XXX.", "....X", "....X", "XXXX."),
    "T": ("XXXXX", "..X..", "..X..", "..X..", "..X..", "..X..", "..X.."),
    "U": ("X...X", "X...X", "X...X", "X...X", "X...X", "X...X", ".XXX."),
    "V": ("X...X", "X...X", "X...X", "X...X", "X...X", ".X.X.", "..X.."),
    "W": ("X...X", "X...X", "X...X", "X.X.X", "X.X.X", "X.X.X", ".X.X."),
    "X": ("X...X", "X...X", ".X.X.", "..X..", ".X.X.", "X...X", "X...X"),
    "Y": ("X...X", "X...X", ".X.X.", "..X..", "..X..", "..X..", "..X.."),
    "Z": ("XXXXX", "....X", "...X.", "..X..", ".X...", "X....", "XXXXX"),
}


class Font:
    SPACING = 1

    def __init__(self, height, glyphs):
        self.height = height
        self._glyphs = {}
        for char, rows in glyphs.items():
            width = len(rows[0])
            masks = tuple(int(row.replace("X", "1").replace(".", "0"), 2) for row in rows)
            self._glyphs[char] = (width, masks)
        self._fallback = self._glyphs["?"]

    def _glyph(self, char):
        glyph = self._glyphs.get(char)
        if glyph is None:
            glyph = self._glyphs.get(char.upper(), self._fallback)
        return glyph

    def measure(self, text):
        """Width in pixels of `text`, excluding trailing spacing."""
        if not text:
            return 0
        return sum(self._glyph(char)[0] for char in text) + self.SPACING * (len(text) - 1)

    def truncate(self, text, max_width):
        while text and self.measure(text) > max_width:
            text = text[:-1]
        return text

    def draw(self, canvas, x, y, text, color):
        """Draw `text` with its top-left corner at (x, y). Returns the x
        where a following glyph would start."""
        for char in text:
            width, masks = self._glyph(char)
            for row, mask in enumerate(masks):
                if not mask:
                    continue
                for col in range(width):
                    if mask & (1 << (width - 1 - col)):
                        canvas.pixel(x + col, y + row, color)
            x += width + self.SPACING
        return x


SMALL = Font(5, _SMALL_GLYPHS)
LARGE = Font(7, _LARGE_GLYPHS)
