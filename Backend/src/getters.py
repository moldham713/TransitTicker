# Provides several getter functions for accessing transit data from the python dictionary.

import datetime

def get_next_departure_time(route_id: str, stop_id: str, direction: int, data: dict) -> dict:
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
                    departure_time_temp = datetime.datetime.strptime(departure_time_str, '%H:%M:%S') if departure_time_str else None
                    departure_time = datetime.datetime(current_time.year, current_time.month, current_time.day, departure_time_temp.hour, departure_time_temp.minute, departure_time_temp.second) if departure_time_temp else None
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