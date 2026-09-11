from flask import Flask, jsonify, request
from flask_cors import CORS
import schedule
import threading
import time
import os
import traceback
from refresh import refresh_transit_data
from realtime import refresh_realtime_data
from getters import get_next_departures, get_routes, get_stops_for_route


app = Flask(__name__)
# The React frontend runs in the browser as its own origin (a separate
# container/port), so it needs CORS enabled here to be allowed to call this
# API directly with fetch().
CORS(app)

transit_data = {}
# Guards transit_data during the brief swap in refresh_transit_data, and during
# reads here, so a request never sees a partially-rebuilt dataset.
transit_data_lock = threading.Lock()

realtime_data = {}
# Separate dict and lock from transit_data/transit_data_lock: the two refresh
# on very different cadences (hourly for the static schedule, every 30
# seconds for live predictions - see refresh_realtime_data), and sharing one
# dict would mean the hourly refresh's data.clear()/update() wipes out
# whatever the much-more-frequent real-time refresh had just published.
realtime_data_lock = threading.Lock()

@app.route('/', methods=['GET'])
def home():
    route = request.args.get('route', 'Q')
    # "Q05" is a parent station id, matching what get_stops_for_route returns
    # for a dropdown - the shape getters.py's
    # _station_key/_platform_belongs_to_station expect, and what the frontend
    # actually sends. A bare platform id (e.g. "Q05S") also works via exact
    # match.
    stop = request.args.get('stop', 'Q05')
    try:
        direction = int(request.args.get('direction', 1))
    except ValueError:
        return jsonify({"error": "direction must be an integer (0 or 1)"}), 400

    try:
        count = int(request.args.get('count', 3))
    except ValueError:
        return jsonify({"error": "count must be an integer"}), 400
    # Range clamping (not just "is this parseable") is get_next_departures'
    # own responsibility, not this route's - see its docstring.

    # Consistent lock order (transit_data_lock, then realtime_data_lock)
    # everywhere both are held, as a defensive habit against deadlock even
    # though nothing currently acquires them in the opposite order.
    with transit_data_lock, realtime_data_lock:
        result = get_next_departures(route, stop, direction, transit_data, realtime_data, count=count)
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

    Each tick is wrapped in its own try/except: `schedule.run_pending()`
    propagates any exception a due job raises, and an uncaught exception on
    a background thread doesn't crash the process - Python just silently
    ends that thread. Without this, one bad tick would permanently stop
    every future scheduled job (both the hourly static refresh and the
    30-second real-time refresh) with no error anywhere in the logs to
    explain why.
    """
    while True:
        try:
            schedule.run_pending()
        except Exception as exc:
            print(f"ERROR: scheduler tick failed, will retry next tick: {exc}")
            traceback.print_exc()
        time.sleep(1)


if __name__ == '__main__':
    if not refresh_transit_data(data=transit_data, lock=transit_data_lock):
        print("WARNING: initial transit data load failed; serving no data until the next scheduled refresh succeeds.")

    if not refresh_realtime_data(data=realtime_data, lock=realtime_data_lock):
        print("WARNING: initial real-time data load failed; departures will use the static schedule only until the next refresh succeeds.")

    # Static schedule data changes rarely, so an hourly refresh is enough.
    # Live predictions are only useful if kept current with how often MTA
    # actually updates them, roughly every 30 seconds.
    schedule.every().hour.do(refresh_transit_data, data=transit_data, lock=transit_data_lock)
    schedule.every(30).seconds.do(refresh_realtime_data, data=realtime_data, lock=realtime_data_lock)

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