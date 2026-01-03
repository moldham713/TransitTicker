from flask import Flask, jsonify, request
from refresh import refresh_transit_data
import schedule

app = Flask(__name__)

@app.route('/', methods=['GET'])
def home():
    username = request.args.get('line')

    return jsonify({'data': 'hello world'})

if __name__ == '__main__':
    refresh_transit_data()

    # Every hour, run the repository refresh script to update transit data.
    schedule.every().hour.do(refresh_transit_data)

    # Run the Flask app
    app.run(debug=True)

    

