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


def get_next_departure_time(route_id: str, stop_id: str, direction: int, data: dict) -> dict:
    """
    Get the next departure time for a transit vehicle at a specific stop.
    Args:
        route_id (str): The ID of the transit route.
        stop_id (str): The ID of the transit stop.
        direction (int): The direction of travel (0 uptown, 1 downtown).
        data (dict): A dictionary containing transit data populated in refresh.py.
        dict: A dictionary containing:
            - 'next_departure_time' (str or None): The next departure time in 'HH:MM:SS' format, 
              or None if no upcoming departure is found.
            - 'minutes_away' (int or None): The number of minutes until the next departure, 
              or None if no upcoming departure is found.
    """
    print("Getting next arrival time for route:", route_id, "stop:", stop_id, "direction:", direction)

    current_time = datetime.datetime.now()

    print("Current time is:", current_time)

    next_departure = None

    for trip_id, trip_info in data["trips"].items():
        if trip_info['route_id'] == route_id and trip_info['direction_id'] == str(direction):
            service_id = trip_info['service_id']
            # Check if the service is active today
            if service_id in data.get("running_services", set()):
                stop_time_info = data["stop_times"].get(trip_id, {})
                if stop_id in stop_time_info:
                    print("found matching stop ", stop_id, " in trip ", trip_id)
                    departure_time_str = stop_time_info.get(stop_id, {}).get('departure_time')
                    departure_time = _parse_gtfs_time(departure_time_str, current_time.date()) if departure_time_str else None
                    if departure_time and departure_time > current_time:
                        print("valid arrival time found:", departure_time)
                        if next_departure is None or departure_time < next_departure:
                            print("New next arrival time set")
                            next_departure = departure_time
    
    diff = next_departure - current_time if next_departure else None
    diff = diff.total_seconds() / 60 if diff else None
    print("Next departure time is:", next_departure, "which is in", diff, "minutes")

    return {"next_departure_time": next_departure.strftime('%H:%M:%S') if next_departure else None,
            "minutes_away": int(diff) if diff is not None else None}


def get_routes(data: dict) -> list:
    """
    List every route ID the currently loaded feed knows about, so a client
    (e.g. a route dropdown) can offer only valid choices instead of guessing.

    Args:
        data (dict): A dictionary containing transit data populated in refresh.py.

    Returns:
        list[str]: Sorted, de-duplicated route IDs.
    """
    return sorted(set(data.get("routes", [])))


def get_stops_for_route(route_id: str, data: dict) -> list:
    """
    List the stops actually served by a given route, so a client can populate
    a stop dropdown that's scoped to the route already chosen instead of
    showing every stop in the system (NYC subway + bus has thousands).

    Args:
        route_id (str): The ID of the transit route.
        data (dict): A dictionary containing transit data populated in refresh.py.

    Returns:
        list[dict]: One entry per stop, each {'stop_id': str, 'stop_name': str},
        sorted by stop name. Empty if the route ID is unknown.
    """
    trips = data.get("trips", {})
    stop_times = data.get("stop_times", {})
    stops = data.get("stops", {})

    stop_ids = set()
    for trip_id, trip_info in trips.items():
        if trip_info['route_id'] == route_id:
            stop_ids.update(stop_times.get(trip_id, {}).keys())

    return sorted(
        (
            {"stop_id": stop_id, "stop_name": stops.get(stop_id, {}).get('stop_name', stop_id)}
            for stop_id in stop_ids
        ),
        key=lambda s: s["stop_name"]
    )