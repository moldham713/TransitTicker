# TransitTicker — Embedded Display

CircuitPython firmware for the **Adafruit MatrixPortal S3** (ESP32-S3) driving
a 64×32 HUB75 RGB LED matrix. It shows live NYC subway departures from the
TransitTicker backend.

Every unit runs identical firmware. A unit gets its identity at runtime:

1. **WiFi**: from an on-device setup hotspot (no computer needed).
2. **Account**: from a pairing code shown on the matrix and entered in the web app.

Both are stored in the board's non-volatile memory (`microcontroller.nvm`),
outside the CIRCUITPY filesystem. Reinstalling firmware files leaves a unit's
pairing intact, and only the physical reset erases it.

## What's on the drive

```
Embedded/
├── CIRCUITPY/                 Copy the contents of this folder to the CIRCUITPY drive
│   ├── code.py                Entry point (CircuitPython runs this at boot)
│   ├── settings.toml.example  Copy to settings.toml and set the backend URL
│   ├── requirements.txt       Adafruit libraries, installed with circup
│   └── transitticker/
│       ├── app.py             State machine: WiFi → pairing → departures
│       ├── api.py             Backend client (/device/... endpoints)
│       ├── departures.py      Counts minutes down between polls
│       ├── render.py          Every screen layout
│       ├── font.py            3×5 and 5×7 bitmap fonts
│       ├── display.py         rgbmatrix/framebufferio setup (MatrixPortal S3 pins)
│       ├── network.py         WiFi station + HTTP session
│       ├── portal.py          WiFi setup hotspot + web form
│       ├── web.py             Portal HTML and form parsing
│       ├── reset.py           Hold-DOWN-at-boot reset
│       ├── storage.py         Token + WiFi in microcontroller.nvm
│       ├── config.py          settings.toml values
│       └── util.py            Timekeeping, backoff, watchdog
└── tests/                     Desktop tests and an ASCII screen previewer
```

## Installing onto a board

Requires **CircuitPython 9.x or later** (the MatrixPortal S3 needs at least
8.2.1; this firmware targets 9+).

1. Install CircuitPython: download the MatrixPortal S3 `.uf2` from
   [circuitpython.org](https://circuitpython.org/board/adafruit_matrixportal_s3/).
   Then click RESET, and click it again while the NeoPixel is purple, to get the
   `MATRXS3BOOT` drive. Drag the `.uf2` onto it. (Some early boards shipped
   without the UF2 bootloader. See the "Factory Reset" page of Adafruit's
   MatrixPortal S3 guide to install it.)
2. Copy everything inside `Embedded/CIRCUITPY/` to the root of the `CIRCUITPY` drive.
3. Install the libraries with [circup](https://github.com/adafruit/circup):
   ```
   pip install circup
   circup install -r Embedded/CIRCUITPY/requirements.txt
   ```
   (Or copy `adafruit_requests`, `adafruit_connection_manager` and
   `adafruit_httpserver` from the Adafruit CircuitPython Bundle into `CIRCUITPY/lib/`.)
4. Copy `settings.toml.example` to `CIRCUITPY/settings.toml` and set
   `TRANSITTICKER_API_URL`.

The board restarts `code.py` whenever a file on the drive is saved. To watch
logs, open the USB serial console (e.g. `tio`, PuTTY, or the Mu editor).

## Configuration (`settings.toml`)

These are per-environment settings, identical on every unit built for that
environment:

| Setting | Default | Purpose |
|---|---|---|
| `TRANSITTICKER_API_URL` | *(required)* | Backend base URL, e.g. `http://192.168.1.50:5000`. Plain HTTP today; `https://` also works. |
| `TRANSITTICKER_POLL_SECONDS` | `25` | Departure poll interval (10–300s). |
| `TRANSITTICKER_PAIR_HINT` | `ON THE WEB APP` | Text under the pairing code (about 15 characters max). |
| `TRANSITTICKER_BRIGHTNESS` | `60` | 1–100. |
| `TRANSITTICKER_MATRIX_WIDTH` / `_HEIGHT` | `64` / `32` | Larger panels show the 64×32 layout centered. 64-row panels need the Address E jumper soldered. |
| `TRANSITTICKER_WATCHDOG` | `1` | Hardware watchdog. Set to `0` while working at the REPL. |
| `CIRCUITPY_WIFI_SSID` / `_PASSWORD` | *(unset)* | **Development only.** Joins this network directly, skipping the setup hotspot. Leave these out of production images. |

## Developing against the local backend

1. From the repo root, run `docker compose up --build`. The backend listens on port 5000 of your computer.
2. Find your computer's LAN IP (`ipconfig` on Windows) and set
   `TRANSITTICKER_API_URL = "http://<that-ip>:5000"`. `localhost` from the device
   refers to the device itself.
3. The device and your computer must be on the same network, and Windows
   Firewall must allow inbound TCP 5000 (Docker Desktop usually prompts for this).
4. Set `CIRCUITPY_WIFI_SSID` / `CIRCUITPY_WIFI_PASSWORD` to skip the setup hotspot while iterating.
5. Pair from the frontend at http://localhost:5001. DynamoDB Local runs with
   `-inMemory`, so restarting the backend forgets all pairings. The device then
   gets a 401 on its next poll and shows a new pairing code by itself.

Desktop tests (no board needed, any Python 3):

```
cd Embedded
python -m unittest discover -s tests -v
python tests/preview.py      # every screen as ASCII art
```

## How it behaves

```
boot ─► DOWN held? ─► reset flow
  │
  ▼
WiFi saved? ──no──► setup hotspot ──► join ──fails (new creds)──► hotspot again
  │yes                                  │fails (known-good creds)──► retry with backoff
  ▼
token saved? ──no──► pairing: show code, poll every 4s ──claimed──► save token ─┐
  │yes                      └─ code expires ─► new code                          │
  ▼                                                                              │
departures: poll every 25s, redraw every 1s ◄───────────────────────────────────┘
  └─ 401 ─► forget token ─► pairing
```

### First-time setup (end user)

1. **WiFi.** The matrix shows `JOIN WIFI`, a hotspot name `TICKER-XXXX` (the last
   4 hex digits of the unit's MAC address), an 8-digit password, and `OPEN 192.168.4.1`.
   Join that hotspot from a phone, open the address, and pick the home network.
   The hotspot password is random each time and only ever appears on the
   display. Only someone looking at the device can join, and the home WiFi
   password travels encrypted. The ESP32-S3 supports **2.4 GHz networks only**.
   Some phones warn that the hotspot "has no internet". Stay connected anyway.
2. **Pairing.** The matrix shows `ENTER CODE`, a 6-character code, and a
   countdown. Entering the code in the web app links the unit to that account.
   Codes last 10 minutes, and the unit fetches a new one on its own.

If the unit can't join a newly entered network (usually a typo), it reopens the
setup hotspot with an error message on the form. If a network it has joined
before goes down, it keeps retrying without asking again.

### The departures screen

One row per saved station (up to 3), led by that route's colored bullet, then
up to 3 departures as minutes away:

- **Amber number + green dot**: a live, real-time-tracked train.
- **Dim blue-white number, no dot**: a static-schedule estimate.
- **`NO TRAINS`**: no upcoming service for that station right now.
- **Red block in the top-right corner**: the backend hasn't answered recently,
  so the minutes are counting down from the last good data. After 10 minutes
  without data, the screen says `NO LIVE DATA`.

Minutes keep counting down every second between polls, and departed trains
drop off.

### Reset (hold DOWN while powering on)

The **DOWN** button is the bottom one on the board's edge. Hold it while
plugging in the power or pressing RESET, and follow the on-screen countdown:

| Hold, then release | Result |
|---|---|
| under 3 s | Cancelled, nothing changes |
| 3–10 s | **Unpair**: forgets the device token, keeps WiFi |
| 10 s or more | **Full reset**: forgets the token and WiFi (use this before selling or giving away the unit) |

This works with no network and regardless of server state. The old token stays
valid on the server until the previous owner unlinks it in the web app, but no
device holds it any more.

Don't use the **BOOT** button for this. BOOT held during reset enters the
ESP32-S3 ROM bootloader.

## Known gaps

- **Not yet run on hardware.** The logic modules are unit-tested on a desktop,
  and every module compiles. The hardware glue (`display.py`, `network.py`,
  `portal.py`, `reset.py`, `app.py`) follows Adafruit's documented APIs but still
  needs a first run on a real board.
- Minutes above 99 display as `99`.
- The setup portal has no captive-portal DNS, so users type `192.168.4.1`
  themselves (it's shown on the matrix).
