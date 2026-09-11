# Provides several getter functions for accessing transit data from the python dictionary.

import datetime


def _parse_gtfs_time(time_str: str, service_day: datetime.date) -> datetime.datetime:
    """
    Parse a GTFS HH:MM:SS time string into a full datetime anchored to the given
    service day. GTFS allows hours >= 24 to represent times after midnight that
    still belong to the previous day's service (e.g. a 25:30:00 departure is
    1:30 AM the following calendar day). datetime.strptime can't parse hours
    above 23, so this splits the string manually and rolls the day over via
    timedelta instead.
    """
    hour_str, minute_str, second_str = time_str.split(':')
    return datetime.datetime(service_day.year, service_day.month, service_day.day) + \
        datetime.timedelta(hours=int(hour_str), minutes=int(minute_str), seconds=int(second_str))


def _station_key(platform_stop_id: str, stops: dict) -> str:
    """
    Collapse a platform-level GTFS stop_id to the physical station it belongs
    to. MTA subway data gives every station a separate stop_id per direction
    (e.g. "127N" and "127S", both children of parent station "127"); this
    resolves both back to the single station id "127". Falls back to the
    platform's own stop_id when it has no parent_station (e.g. most bus
    stops, which aren't split by direction the same way), so each such stop
    is simply its own station.
    """
    parent = stops.get(platform_stop_id, {}).get('parent_station')
    return parent if parent else platform_stop_id


def _platform_belongs_to_station(platform_stop_id: str, station_id: str, stops: dict) -> bool:
    """True if `platform_stop_id` is one of the directional platforms that
    make up `station_id` (or *is* station_id itself, for stops with no
    parent/child split)."""
    return platform_stop_id == station_id or _station_key(platform_stop_id, stops) == station_id


def get_next_departures(route_id: str, stop_id: str, direction: int, data: dict,
                         realtime_data: dict = None, count: int = 3) -> dict:
    """
    Get the next several upcoming departures for a transit vehicle at a
    specific station - the kind of small departure board a real platform
    display shows. Each departure uses a live GTFS-Realtime prediction when
    one is available for that trip, falling back to the static schedule
    otherwise; typically only the next few departures per route/direction
    have an active live prediction at all, which lines up well with only
    ever returning a handful of departures in the first place.

    Args:
        route_id (str): The ID of the transit route.
        stop_id (str): The station to check - either a parent station id (as
            returned by get_stops_for_route) or a raw platform-level stop_id.
            Since a station's uptown and downtown platforms are separate GTFS
            stop_ids, resolving which specific platform to check happens here:
            for each candidate trip already filtered to the requested
            direction, whichever of that station's platforms the trip
            actually stops at is - by construction - the one serving that
            direction, so no hardcoded assumption about what a platform
            suffix means is needed.
        direction (int): The direction of travel (0 uptown, 1 downtown).
        data (dict): A dictionary containing static transit data populated in refresh.py.
        realtime_data (dict): Live predictions populated by realtime.py, structured
            as realtime_data[trip_id][stop_id] = predicted_departure_epoch (a Unix
            timestamp). None or {} is fine - every trip then falls back to its
            static scheduled time. datetime.fromtimestamp() converts an epoch
            using the container's local timezone, matching how the static
            schedule's naive local times are already handled here - both rely
            on the container being set to America/New_York (see Backend/Dockerfile).
        count (int): Maximum number of upcoming departures to return. Clamped
            to [1, 10] here (not by the caller) so this function's own "at
            most `count` entries" contract holds regardless of who calls it
            or what value they pass in - an API route is one caller today,
            but nothing about this function should depend on that route
            having already validated the value.

    Returns:
        dict: {
            "departures": [
                {"departure_time": "HH:MM:SS", "minutes_away": int, "is_realtime": bool},
                ...  # soonest first, at most `count` entries, [] if none found
            ]
        }
    """
    count = max(1, min(count, 10))
    realtime_data = realtime_data or {}
    current_time = datetime.datetime.now()
    stops = data.get("stops", {})
    upcoming = []  # list of (departure_time, is_realtime) tuples

    for trip_id, trip_info in data["trips"].items():
        if trip_info['route_id'] == route_id and trip_info['direction_id'] == str(direction):
            service_id = trip_info['service_id']
            # Check if the service is active today
            if service_id in data.get("running_services", set()):
                stop_time_info = data["stop_times"].get(trip_id, {})
                platform_stop_id = next(
                    (sid for sid in stop_time_info if _platform_belongs_to_station(sid, stop_id, stops)),
                    None
                )
                if platform_stop_id:
                    live_epoch = realtime_data.get(trip_id, {}).get(platform_stop_id)
                    if live_epoch:
                        departure_time = datetime.datetime.fromtimestamp(live_epoch)
                        is_realtime = True
                    else:
                        departure_time_str = stop_time_info[platform_stop_id].get('departure_time')
                        departure_time = _parse_gtfs_time(departure_time_str, current_time.date()) if departure_time_str else None
                        is_realtime = False
                    if departure_time and departure_time > current_time:
                        upcoming.append((departure_time, is_realtime))

    upcoming.sort(key=lambda pair: pair[0])
    soonest = upcoming[:count]
    departures = [
        {
            "departure_time": dt.strftime('%H:%M:%S'),
            "minutes_away": int((dt - current_time).total_seconds() / 60),
            "is_realtime": is_realtime,
        }
        for dt, is_realtime in soonest
    ]

    # One summary line per request, listing every returned departure and how
    # many came from a live prediction versus the static schedule.
    live_count = sum(1 for d in departures if d["is_realtime"])
    print(f"[{route_id}/{stop_id} dir={direction}] next {len(departures)} departure(s) "
          f"({live_count} live): {', '.join(d['departure_time'] for d in departures) if departures else 'none'}")

    return {"departures": departures}


def get_routes(data: dict) -> list:
    """
    List every route ID the currently loaded feed knows about, so a client
    (e.g. a route dropdown) can offer only valid choices.

    Args:
        data (dict): A dictionary containing transit data populated in refresh.py.

    Returns:
        list[str]: Sorted, de-duplicated route IDs.
    """
    return sorted(set(data.get("routes", [])))


def get_stops_for_route(route_id: str, data: dict) -> list:
    """
    List the stations actually served by a given route, scoped to that
    route so a stop dropdown only offers stations that route serves (NYC
    subway + bus has thousands of stops system-wide).

    One entry per physical station, not per platform: MTA subway data has a
    separate stop_id for each direction's platform at a station (e.g.
    "127N"/"127S"). Entries are keyed by station (parent_station, or the raw
    stop_id for stops with no such parent, e.g. most bus stops) via
    _station_key - see get_next_departures for how the direction the caller
    actually wants gets resolved back to the right platform.

    Args:
        route_id (str): The ID of the transit route.
        data (dict): A dictionary containing transit data populated in refresh.py.

    Returns:
        list[dict]: One entry per station, each {'stop_id': str, 'stop_name': str},
        sorted by stop name. Empty if the route ID is unknown.
    """
    trips = data.get("trips", {})
    stop_times = data.get("stop_times", {})
    stops = data.get("stops", {})

    stations = {}
    for trip_id, trip_info in trips.items():
        if trip_info['route_id'] == route_id:
            for platform_stop_id in stop_times.get(trip_id, {}):
                station_id = _station_key(platform_stop_id, stops)
                if station_id not in stations:
                    stations[station_id] = {
                        "stop_id": station_id,
                        "stop_name": stops.get(platform_stop_id, {}).get('stop_name', station_id),
                    }

    return sorted(stations.values(), key=lambda s: s["stop_name"])