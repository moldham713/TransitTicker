"""TransitTicker firmware for the Adafruit MatrixPortal S3 (CircuitPython).

Modules split into two groups:

- Pure logic with no hardware imports (config, util, storage, font, render,
  departures, api, web), so they can be unit-tested on a desktop Python -
  see Embedded/tests/.
- Hardware glue (display, network, portal, reset, app), which import
  CircuitPython-only modules like board, wifi and rgbmatrix.
"""

__version__ = "0.1.0"
