from flask import Flask, jsonify, request
import schedule
import json
from refresh import refresh_transit_data
from getters import get_next_departure_time


app = Flask(__name__)

transit_data = {}

@app.route('/', methods=['GET'])
def home():
    # username = request.args.get('line')

    # return jsonify({'data': 'hello world'})
    return json.dumps(get_next_departure_time("Q", "Q05S", 1, transit_data))

if __name__ == '__main__':
    refresh_transit_data(data=transit_data)


    # Every hour, run the repository refresh script to update transit data.
    schedule.every().hour.do(refresh_transit_data, data=transit_data)

    # Run the Flask app
    app.run(host='0.0.0.0', debug=True)