import requests
import zipfile
import csv
import os
import threading
import traceback
from datetime import datetime

# Every hour, this script fetches the latest transit data from MTA's APIs and updates the local working directory.
MTA_SUPP_GTFS_API_URL = 'https://rrgtfsfeeds.s3.amazonaws.com/gtfs_supplemented.zip'


def refresh_transit_data(data: dict, lock: threading.Lock = None) -> bool:
    """
    Download and parse the latest GTFS feed, then publish it into `data`.

    The download and parse happen against a fresh, private dict (`new_data`) so
    that requests being served concurrently keep reading the old, complete
    dataset for the entire (potentially slow) download/parse. Only the final
    swap into the caller's `data` dict is guarded by `lock` (if provided), so
    readers never observe a half-populated dataset, and the exclusive window
    is just the swap itself rather than the whole refresh.

    The whole attempt is wrapped in a try/except: a bad download, a corrupt
    zip, or a malformed CSV should not crash the caller. That matters most
    for the hourly background refresh, which runs on its own daemon thread
    with nothing else watching it - an uncaught exception there would kill
    the scheduler thread silently, and every future hourly refresh would
    just stop happening with no visible error. On failure, `data` is left
    untouched (since the swap never runs), so the app keeps serving whatever
    it already had.

    Returns:
        bool: True if the refresh succeeded and `data` was updated, False if
        it failed and `data` was left as-is.
    """
    try:
        # Directory to store the fetched data
        data_directory = os.path.join(os.path.dirname(__file__), 'data')

        if not os.path.exists(data_directory):
            os.makedirs(data_directory)

        # Download the GTFS supplemented zip file
        response = requests.get(MTA_SUPP_GTFS_API_URL, stream=True)
        response.raise_for_status()

        file_path = os.path.join(data_directory, 'gtfs_supplemented.zip')
        with open(file_path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192): # Iterate over chunks
                file.write(chunk)
        print(f"Successfully downloaded '{file_path}'")

        # Unzip the downloaded file
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            zip_ref.extractall(data_directory)
            print(f"Extracted GTFS data to '{data_directory}'")

        # Load and process the new data into a private dict first, so in-flight
        # requests keep seeing the old (complete) `data` until the swap below.
        new_data = {}
        load(new_data, data_directory)
        optimize_transit_data(new_data)

        if lock:
            with lock:
                data.clear()
                data.update(new_data)
        else:
            data.clear()
            data.update(new_data)
        print("Swapped in refreshed transit data.")
        return True
    except Exception as exc:
        print(f"ERROR: transit data refresh failed, keeping previous data in place: {exc}")
        traceback.print_exc()
        return False

def load(data: dict, data_directory : str) -> None:
    # Load data into the provided dictionary
    data["calendar_dates"] = {} # TODO: only load if matches today's date
    with open(os.path.join(data_directory, 'calendar_dates.txt'), 'r') as file:
        for line in csv.DictReader(file):
            key = line['service_id']
            if key not in data["calendar_dates"]:
                data["calendar_dates"][key] = {}
            data["calendar_dates"][key][line['date']] = line['exception_type']
    print("Loaded 'calendar_dates' data into memory.")

    data["calendar"] = {}
    with open(os.path.join(data_directory, 'calendar.txt'), 'r') as file:
        for line in csv.DictReader(file):
            key = line['service_id']
            if key not in data["calendar"]:
                data["calendar"][key] = [] # TODO: only load if matches today's weekday
            data['calendar'][key].append('monday') if line['monday'] == '1' else None
            data['calendar'][key].append('tuesday') if line['tuesday'] == '1' else None
            data['calendar'][key].append('wednesday') if line['wednesday'] == '1' else None
            data['calendar'][key].append('thursday') if line['thursday'] == '1' else None
            data['calendar'][key].append('friday') if line['friday'] == '1' else None
            data['calendar'][key].append('saturday') if line['saturday'] == '1' else None
            data['calendar'][key].append('sunday') if line['sunday'] == '1' else None
    print("Loaded 'calendar' data into memory.")

    data["routes"] = []
    with open(os.path.join(data_directory, 'routes.txt'), 'r') as file:
        for line in csv.DictReader(file):
            data["routes"].append(line['route_id'])
    print("Loaded 'routes' data into memory.")

    data["stops"] = {}
    with open(os.path.join(data_directory, 'stops.txt'), 'r') as file:
        for line in csv.DictReader(file):
            key = line['stop_id']
            data["stops"][key] = {
                'stop_code': line.get('stop_code', ''),
                'stop_name': line['stop_name'],
            }
    print("Loaded 'stops' data into memory.")

    data["stop_times"] = {}
    with open(os.path.join(data_directory, 'stop_times.txt'), 'r') as file:
        for line in csv.DictReader(file):
            key = line['trip_id']
            if key not in data["stop_times"]:
                data["stop_times"][key] = {}
            data["stop_times"][key][line['stop_id']] = {'arrival_time' : line['arrival_time'], 'departure_time' : line['departure_time']}
    print("Loaded 'stop_times' data into memory.")

    data["trips"] = {}
    with open(os.path.join(data_directory, 'trips.txt'), 'r') as file:
        for line in csv.DictReader(file):
            key = line['trip_id']
            data["trips"][key] = {
                'route_id': line['route_id'],
                'service_id': line['service_id'],
                'trip_headsign': line['trip_headsign'],
                'direction_id': line['direction_id'],
            }
    print("Loaded 'trips' data into memory.")



def optimize_transit_data(data: dict) -> None:
    # Identify services that are currently running
    date = datetime.today().strftime('%Y%m%d')
    weekday = datetime.today().strftime('%A').lower()

    running_services = []
    for service_id in data["calendar_dates"]:
        if weekday in data["calendar_dates"][service_id]:
            running_services.append(service_id)

    for service_id in data["calendar_dates"]:
        if date in data["calendar_dates"][service_id]:
            if data["calendar_dates"][service_id][date] == '1':  # Added service
                running_services.append(service_id)
            elif data["calendar_dates"][service_id][date] == '2':  # Removed service
                if service_id in running_services:
                    running_services.remove(service_id)
    
    data['running_services'] = running_services