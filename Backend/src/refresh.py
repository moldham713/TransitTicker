import requests
import zipfile

# Every hour, this script fetches the latest transit data from MTA's APIs and updates the local working directory.
MTA_SUPP_GTFS_API_URL = 'https://rrgtfsfeeds.s3.amazonaws.com/gtfs_supplemented.zip'


def refresh_transit_data():
    import requests
    import os

    # Directory to store the fetched data
    data_directory = os.path.join(os.path.dirname(__file__), 'data')

    if not os.path.exists(data_directory):
        os.makedirs(data_directory)

    
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