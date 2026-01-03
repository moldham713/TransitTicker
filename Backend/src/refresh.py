import requests
import zipfile
import csv

# Every hour, this script fetches the latest transit data from MTA's APIs and updates the local working directory.
MTA_SUPP_GTFS_API_URL = 'https://rrgtfsfeeds.s3.amazonaws.com/gtfs_supplemented.zip'


def refresh_transit_data(data : dict) -> None:
    import requests
    import os

    # Directory to store the fetched data
    data_directory = os.path.join(os.path.dirname(__file__), 'data')

    if not os.path.exists(data_directory):
        os.makedirs(data_directory)

    # Download the GTFS supplemented zip file
    response = requests.get(MTA_SUPP_GTFS_API_URL, stream=True)
    response.raise_for_status()

    if response.status_code == 200:
        file_path = os.path.join(data_directory, 'gtfs_supplemented.zip')
        with open(file_path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192): # Iterate over chunks
                file.write(chunk)
        print(f"Successfully downloaded '{file_path}'")
    else:
        print(f'Failed to fetch GTFS data. Status code: {response.status_code}')

    # Unzip the downloaded file
    with zipfile.ZipFile(file_path, 'r') as zip_ref:
        zip_ref.extractall(data_directory)
        print(f"Extracted GTFS data to '{data_directory}'")

    # Load data into the provided dictionary
    data["calendar_dates"] = {}
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
                data["calendar"][key] = {}
            data["calendar"][key]['monday'] = line['monday']
            data["calendar"][key]['tuesday'] = line['tuesday']
            data["calendar"][key]['wednesday'] = line['wednesday']
            data["calendar"][key]['thursday'] = line['thursday']
            data["calendar"][key]['friday'] = line['friday']
            data["calendar"][key]['saturday'] = line['saturday']
            data["calendar"][key]['sunday'] = line['sunday']
            data["calendar"][key]['start_date'] = line['start_date']
            data["calendar"][key]['end_date'] = line['end_date']
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
            data["stop_times"][key]['stop_id'] = line['stop_id']
            data["stop_times"][key]['arrival_time'] = line['arrival_time']
            data["stop_times"][key]['departure_time'] = line['departure_time']
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