# TransitTicker firmware entry point. CircuitPython runs this file at boot
# (and again whenever a file on the CIRCUITPY drive is saved).
# See Embedded/README.md for setup, and transitticker/app.py for behavior.

from transitticker import app

app.main()
