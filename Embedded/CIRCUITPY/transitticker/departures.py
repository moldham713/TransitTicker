"""Turns the backend's /device/<token> payload into what the screen shows.

The payload's minutes_away values are correct at the moment the backend
answered. The device polls every ~25s but redraws every second, so each
redraw subtracts the time elapsed since that response: the countdown keeps
ticking between polls, and keeps ticking honestly through a short network
outage. Departures that have counted past zero are dropped.
"""

MAX_BOARDS = 3
MAX_DEPARTURES = 3


def build_rows(boards, elapsed_ms):
    """
    Args:
        boards: the "boards" list from the API response.
        elapsed_ms: milliseconds since that response arrived.

    Returns:
        A list (at most 3) of {"route": str or None, "departures":
        [(minutes, is_realtime), ...]} dicts, one per board, in the order
        the backend sent them. Malformed entries are skipped, never fatal:
        a display that shows two of three boards is more useful than one
        that crashes on the third.
    """
    elapsed_minutes = max(0, elapsed_ms) // 60000
    rows = []
    for board in boards[:MAX_BOARDS]:
        if not isinstance(board, dict):
            continue
        departures = []
        raw_departures = board.get("departures")
        if not isinstance(raw_departures, list):
            raw_departures = []
        for departure in raw_departures:
            if not isinstance(departure, dict):
                continue
            minutes = departure.get("minutes_away")
            if not isinstance(minutes, int) or isinstance(minutes, bool):
                continue
            minutes -= elapsed_minutes
            if minutes < 0:
                continue
            departures.append((minutes, departure.get("is_realtime") is True))
            if len(departures) == MAX_DEPARTURES:
                break
        # Each board carries its saved "route", which the row marker shows
        # as that route's bullet. A board without one falls back to a
        # numbered marker in saved order.
        route = board.get("route")
        rows.append({
            "route": route if isinstance(route, str) and route else None,
            "departures": departures,
        })
    return rows
