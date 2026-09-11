from flask import Flask, jsonify, request
from flask_cors import CORS
import schedule
import threading
import time
import os
from refresh import refresh_transit_data
from getters import get_next_departure_time, get_routes, get_stops_for_route


app = Flask(__name__)
# The React frontend runs in the browser as its own origin (a separate
# container/port), so it needs CORS enabled here to be allowed to call this
# API directly with fetch().
CORS(app)

transit_data = {}
# Guards transit_data during the brief swap in refresh_transit_data, and during
# reads here, so a request never sees a partially-rebuilt dataset.
transit_data_lock = threading.Lock()

@app.route('/', methods=['GET'])
def home():
    route = request.args.get('route', 'Q')
    stop = request.args.get('stop', 'Q05S')
    try:
        direction = int(request.args.get('direction', 1))
    except ValueError:
        return jsonify({"error": "direction must be an integer (0 or 1)"}), 400

    with transit_data_lock:
        result = get_next_departure_time(route, stop, direction, transit_data)
    return jsonify(result)


@app.route('/routes', methods=['GET'])
def routes():
    """List every known route ID, e.g. for populating a route dropdown."""
    with transit_data_lock:
        result = get_routes(transit_data)
    return jsonify(result)


@app.route('/routes/<route_id>/stops', methods=['GET'])
def stops_for_route(route_id):
    """List the stops served by `route_id`, e.g. for a stop dropdown scoped to
    whichever route the client already picked."""
    with transit_data_lock:
        result = get_stops_for_route(route_id, transit_data)
    return jsonify(result)


def run_scheduler() -> None:
    """Background loop that actually executes jobs registered with `schedule`.

    `schedule.every().hour.do(...)` only registers a job; something still has
    to call `schedule.run_pending()` periodically to fire it. This runs on a
    daemon thread so it doesn't block Flask from serving requests.
    """
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == '__main__':
    if not refresh_transit_data(data=transit_data, lock=transit_data_lock):
        print("WARNING: initial transit data load failed; serving no data until the next scheduled refresh succeeds.")

    # Every hour, run the repository refresh script to update transit data.
    schedule.every().hour.do(refresh_transit_data, data=transit_data, lock=transit_data_lock)

    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    # Debug mode (Werkzeug debugger + reloader) must stay off in the container:
    # the debugger allows arbitrary code execution if the port is ever exposed,
    # and the reloader would spawn a second process that re-runs the startup
    # refresh and starts a second scheduler thread. Opt in only for local dev
    # via FLASK_DEBUG=1, and keep the reloader off either way since startup
    # refresh/scheduling here isn't reloader-safe.
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', debug=debug_mode, use_reloader=False)