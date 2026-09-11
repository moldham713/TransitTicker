# Fetches and parses MTA's GTFS-Realtime feeds, producing live departure
# predictions that getters.py layers on top of the static schedule.

import requests
import threading
from google.transit import gtfs_realtime_pb2

# MTA splits real-time data across these feeds by line group. No API key is
# required for any of them. trip_id values are unique across the whole
# system regardless of which feed reports them, so every feed is fetched and
# merged into one flat trip_id-keyed structure below - there's no need to
# track which route maps to which feed for that merge.
FEED_URLS = [
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",       # 1,2,3,4,5,6,7,S
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace",   # A,C,E,H,FS
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm",  # B,D,F,M
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-g",     # G
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-jz",    # J,Z
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw",  # N,Q,R,W
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l",     # L
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-si",    # SIR
]


def refresh_realtime_data(data: dict, lock: threading.Lock = None) -> bool:
    """
    Fetch every MTA GTFS-Realtime feed and publish live departure predictions
    into `data`, structured as data[trip_id][stop_id] = predicted_departure_epoch
    (a Unix timestamp in UTC seconds - getters.py converts this to the
    container's local time the same way it parses static schedule times, so
    the two stay directly comparable).

    Builds a private dict first and swaps it into the caller's `data` under
    `lock` only for that final assignment, the same pattern
    refresh_transit_data in refresh.py uses for the static schedule. This
    runs far more often than that hourly static refresh - MTA updates these
    feeds roughly every 30 seconds - so keeping failures non-fatal matters
    just as much here.

    Each feed is fetched independently: one feed failing (a transient
    network error, MTA serving a bad response for one line group) doesn't
    discard predictions successfully fetched from the other feeds. Only a
    total failure across every feed leaves `data` untouched.

    Returns:
        bool: True if at least one feed was fetched and parsed successfully
        and `data` was updated. False if every feed failed and `data` was
        left as-is.
    """
    new_data = {}
    any_succeeded = False

    for feed_url in FEED_URLS:
        try:
            response = requests.get(feed_url, timeout=15)
            response.raise_for_status()

            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(response.content)

            for entity in feed.entity:
                if not entity.HasField('trip_update'):
                    continue
                trip_id = entity.trip_update.trip.trip_id
                for stop_time_update in entity.trip_update.stop_time_update:
                    stop_id = stop_time_update.stop_id
                    # Prefer departure time; a stop_time_update that's the
                    # last stop on a trip typically only has arrival set.
                    if stop_time_update.HasField('departure') and stop_time_update.departure.time:
                        predicted_epoch = stop_time_update.departure.time
                    elif stop_time_update.HasField('arrival') and stop_time_update.arrival.time:
                        predicted_epoch = stop_time_update.arrival.time
                    else:
                        continue
                    new_data.setdefault(trip_id, {})[stop_id] = predicted_epoch

            any_succeeded = True
        except Exception as exc:
            print(f"WARNING: GTFS-Realtime feed '{feed_url}' failed: {exc}")

    if not any_succeeded:
        print("ERROR: every GTFS-Realtime feed failed this cycle, keeping previous real-time data in place.")
        return False

    if lock:
        with lock:
            data.clear()
            data.update(new_data)
    else:
        data.clear()
        data.update(new_data)
    print(f"Swapped in refreshed real-time data ({len(new_data)} trips with live predictions).")
    return True
