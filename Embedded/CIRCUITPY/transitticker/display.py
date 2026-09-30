"""HUB75 matrix setup for the MatrixPortal S3, driven directly through
CircuitPython's rgbmatrix + framebufferio modules."""

import board
import displayio
import framebufferio
import rgbmatrix

from . import render

# 5 bits per channel keeps the dim palette colors (and the low end of the
# brightness setting) distinguishable from off; the S3's PSRAM has room
# for the larger frame buffers.
BIT_DEPTH = 5


class Screen:
    def __init__(self, display, canvas):
        self._display = display
        self.canvas = canvas

    def refresh(self):
        self._display.refresh(minimum_frames_per_second=0)


def create_screen(width, height, brightness):
    displayio.release_displays()

    addr_pins = [board.MTX_ADDRA, board.MTX_ADDRB, board.MTX_ADDRC, board.MTX_ADDRD]
    if height > 32:
        # 64-row panels need the fifth address line, which the board only
        # connects once its "Address E" solder jumper is closed.
        addr_pins.append(board.MTX_ADDRE)

    matrix = rgbmatrix.RGBMatrix(
        width=width,
        height=height,
        bit_depth=BIT_DEPTH,
        rgb_pins=[board.MTX_R1, board.MTX_G1, board.MTX_B1, board.MTX_R2, board.MTX_G2, board.MTX_B2],
        addr_pins=addr_pins,
        clock_pin=board.MTX_CLK,
        latch_pin=board.MTX_LAT,
        output_enable_pin=board.MTX_OE,
        doublebuffer=True,
    )
    # Manual refresh: every screen is drawn in full and then pushed at
    # once, so the panel never shows a partially drawn frame.
    display = framebufferio.FramebufferDisplay(matrix, auto_refresh=False)

    bitmap = displayio.Bitmap(render.WIDTH, render.HEIGHT, 16)
    palette = displayio.Palette(render.PALETTE_SIZE)
    canvas = render.Canvas(bitmap, palette, brightness)

    group = displayio.Group()
    group.append(displayio.TileGrid(
        bitmap,
        pixel_shader=palette,
        x=(width - render.WIDTH) // 2,
        y=(height - render.HEIGHT) // 2,
    ))
    display.root_group = group
    return Screen(display, canvas)
