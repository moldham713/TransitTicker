from flask import Flask, jsonify, request, session
from flask_cors import CORS
from botocore.exceptions import BotoCoreError
from waitress import serve
import schedule
import threading
import time
import os
import traceback
from refresh import refresh_transit_data
from realtime import refresh_realtime_data
from getters import get_next_departures, get_routes, get_stops_for_route
from users import (
    ensure_table_exists, get_or_create_user, get_user_by_id, save_preferences,
    generate_device_token, set_device_token, clear_device_token, get_user_by_device_token,
)
from auth import verify_google_id_token, login_required
from pairing import (
    ensure_table_exists as ensure_pairing_table_exists,
    start_pairing, get_pairing_status, claim_pairing_code,
)


app = Flask(__name__)

# Signs session cookies - see infra/ecs.tf's random_password.session_secret
# for how this is generated in production. The default here is only ever
# used locally, where real security doesn't matter for a throwaway session.
app.secret_key = os.environ.get('SESSION_SECRET_KEY', 'local-dev-secret-not-for-production')

# The React frontend runs in the browser as its own origin (a separate
# container/port), so it needs CORS enabled here to be allowed to call this
# API directly with fetch(). supports_credentials + explicit origins
# (rather than "*") is required for the session cookie /auth/* sets to be
# sent on cross-origin requests at all - browsers reject the combination of
# a wildcard origin with credentialed requests outright.
#
# A comma-separated list, not a single value: "localhost" and "127.0.0.1"
# are different origins as far as both CORS and Google OAuth are concerned,
# even though they reach the same machine - Docker Desktop's own UI
# commonly links to 127.0.0.1 rather than localhost, so local dev needs
# both accepted rather than whichever one happens to be typed. Production
# only ever needs the one real ALB origin, so this still works fine there
# as a single-item list.
FRONTEND_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('FRONTEND_ORIGIN', 'http://localhost:5001').split(',')
    if origin.strip()
]
CORS(app, supports_credentials=True, origins=FRONTEND_ORIGINS)


@app.after_request
def log_request(response):
    """One access-log line per request (Waitress doesn't write these
    itself). Logs the matched route pattern, e.g. /device/<device_token>,
    so the device token in that URL never ends up in the logs."""
    route = request.url_rule.rule if request.url_rule else request.path
    print(f"{request.method} {route} {response.status_code}")
    return response


@app.errorhandler(BotoCoreError)
def handle_dynamodb_connection_error(exc):
    """
    Covers connection-level DynamoDB failures (EndpointConnectionError and
    the like - BotoCoreError is the base for botocore's own client-side/
    transport errors, distinct from ClientError, which is a response an
    AWS service actually returned). Applies globally to every route that
    touches DynamoDB, rather than wrapping each one individually.

    Without this, a transient DynamoDB outage (real AWS having a bad
    moment, or DynamoDB Local's container becoming unreachable mid-session
    in local dev) surfaces as a bare 500 with a raw traceback - useful in
    the backend's own logs, but the caller only ever sees "backend
    returned 500", with nothing to say the database specifically is the
    problem rather than the application itself.
    """
    print(f"ERROR: DynamoDB request failed: {exc}")
    return jsonify({"error": "temporarily unable to reach the database - please try again shortly"}), 503

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


def _user_response(user: dict) -> dict:
    """The subset of a user record that's safe and useful to hand back to
    the frontend - never the raw oauth_subject, and never the raw
    device_token either. The web UI only ever needs to know *whether* a
    device is paired, not its value: the token flows device -> backend ->
    device during pairing and is never displayed to a human at all, so a
    browser has no legitimate need to see it, and no way to leak what it
    never received."""
    return {
        "user_id": user['user_id'],
        "device_paired": 'device_token' in user,
        "preferences": user.get('preferences', []),
    }


@app.route('/auth/google', methods=['POST'])
def auth_google():
    """
    Exchange a Google ID token (from the frontend's Sign-In button) for a
    logged-in session, creating the user's record on first login.
    """
    id_token_str = (request.get_json(silent=True) or {}).get('id_token')
    if not id_token_str:
        return jsonify({"error": "id_token is required"}), 400

    try:
        subject = verify_google_id_token(id_token_str)
    except Exception as exc:
        # Covers google-auth's own errors (expired token, bad signature,
        # wrong audience) and network errors fetching Google's public keys -
        # all of these mean this particular login attempt failed, not that
        # the server itself is broken, hence 401 rather than 500.
        return jsonify({"error": f"invalid Google ID token: {exc}"}), 401

    user = get_or_create_user('google', subject)
    session['user_id'] = user['user_id']
    session.permanent = True

    return jsonify(_user_response(user))


@app.route('/auth/me', methods=['GET'])
@login_required
def auth_me():
    """Current session's user info, so the frontend can restore login state
    on page load without repeating the Google sign-in flow."""
    user = get_user_by_id(session['user_id'])
    if not user:
        # The DB record is gone (e.g. manually deleted) even though the
        # session cookie still names it - treat that as logged out rather
        # than crashing on the missing record.
        session.clear()
        return jsonify({"error": "login required"}), 401
    return jsonify(_user_response(user))


@app.route('/auth/logout', methods=['POST'])
def auth_logout():
    session.clear()
    return jsonify({"status": "logged out"})


def _validate_preferences(preferences):
    """
    Check that a preferences payload is well-formed: at most 3 entries,
    each a {route, stop, direction} object with a non-empty route/stop and
    direction 0 or 1. Doesn't check that the route/stop combination
    corresponds to any real, currently-known station - that would mean
    cross-referencing transit_data at save time for fairly little benefit,
    since a bad combination just means "no departures found" later, the
    same as it would for the / endpoint's own route/stop/direction params.

    Returns:
        (True, cleaned_list) if valid, (False, error_message) otherwise.
    """
    if not isinstance(preferences, list):
        return False, "preferences must be a list"
    if len(preferences) > 3:
        return False, "at most 3 saved stations are allowed"

    cleaned = []
    for i, pref in enumerate(preferences):
        if not isinstance(pref, dict):
            return False, f"preferences[{i}] must be an object"
        route = pref.get('route')
        stop = pref.get('stop')
        direction = pref.get('direction')
        if not isinstance(route, str) or not route:
            return False, f"preferences[{i}].route is required"
        if not isinstance(stop, str) or not stop:
            return False, f"preferences[{i}].stop is required"
        if direction not in (0, 1):
            return False, f"preferences[{i}].direction must be 0 or 1"
        cleaned.append({"route": route, "stop": stop, "direction": direction})
    return True, cleaned


@app.route('/preferences', methods=['GET'])
@login_required
def get_preferences():
    """The logged-in user's saved stations - identified entirely from the
    session, never a request parameter, so one user can never read
    another's by guessing an id."""
    user = get_user_by_id(session['user_id'])
    if not user:
        session.clear()
        return jsonify({"error": "login required"}), 401
    return jsonify({"preferences": user.get('preferences', [])})


@app.route('/preferences', methods=['POST'])
@login_required
def update_preferences():
    """Overwrite the logged-in user's saved stations with the full list
    provided - not a partial merge, matching users.save_preferences."""
    body = request.get_json(silent=True) or {}
    valid, result = _validate_preferences(body.get('preferences'))
    if not valid:
        return jsonify({"error": result}), 400
    save_preferences(session['user_id'], result)
    return jsonify({"preferences": result})


@app.route('/device/pair/start', methods=['POST'])
def device_pair_start():
    """
    Called by a device with no stored token, to begin pairing. No auth -
    the device isn't signed in as anyone yet, it's establishing a brand
    new pairing session that a human will complete from the web UI.
    """
    return jsonify(start_pairing())


@app.route('/device/pair/status/<pairing_code>', methods=['GET'])
def device_pair_status(pairing_code):
    """Polled by the device while its screen shows the pairing code,
    waiting to learn whether a human has claimed it yet."""
    return jsonify(get_pairing_status(pairing_code))


@app.route('/device/pair/claim', methods=['POST'])
@login_required
def device_pair_claim():
    """
    Called from the web UI once a signed-in human reads the pairing code
    off their device's screen and enters it here. Success binds a freshly
    generated device_token to their account and to that pairing code, for
    the device to pick up on its next status poll.
    """
    body = request.get_json(silent=True) or {}
    pairing_code = (body.get('pairing_code') or '').strip().upper()
    if not pairing_code:
        return jsonify({"error": "pairing_code is required"}), 400

    candidate_token = generate_device_token()
    if not claim_pairing_code(pairing_code, candidate_token):
        return jsonify({"error": "invalid, already-claimed, or expired pairing code"}), 400

    # Only reaches the user's account once the pairing_codes table has
    # confirmed the code was valid, pending, and unexpired - a failed claim
    # attempt above must never have any side effect on the account.
    set_device_token(session['user_id'], candidate_token)
    return jsonify({"status": "paired"})


@app.route('/device/unlink', methods=['POST'])
@login_required
def device_unlink():
    """Self-service revoke: the account's current device token stops
    working immediately. Saved preferences are untouched - pairing a
    replacement device later picks them right back up."""
    clear_device_token(session['user_id'])
    return jsonify({"status": "unlinked"})


@app.route('/device/<device_token>', methods=['GET'])
def device_departures(device_token):
    """
    What a paired device actually polls in normal operation: send the
    token it received during pairing, get back up to 3 departure boards
    for whichever stations are currently saved on the account it's bound
    to - no route/stop/direction parameters needed, unlike the / endpoint.
    """
    user = get_user_by_device_token(device_token)
    if not user:
        # Wrong, unlinked, or never-claimed token. The device's own logic
        # should treat this as "not paired" and fall back to
        # POST /device/pair/start for a fresh code, rather than retrying
        # this same token indefinitely.
        return jsonify({"error": "unknown device token"}), 401

    boards = []
    with transit_data_lock, realtime_data_lock:
        for pref in user.get('preferences', []):
            boards.append(get_next_departures(
                pref['route'], pref['stop'], pref['direction'],
                transit_data, realtime_data, count=3,
            ))
    return jsonify({"boards": boards})


def _wait_for_dynamodb_local(timeout_seconds: int = 30) -> None:
    """
    Local dev only: DynamoDB Local is a JVM process that takes a few
    seconds to finish starting and bind its port after its container
    starts, and Compose's `depends_on` on its own only guarantees this
    container was told to start first - not that it's actually ready to
    accept connections by the time the backend's own startup code runs.
    Retries table creation until it succeeds or this timeout elapses,
    rather than letting one early, transient connection failure crash the
    whole backend on startup.

    A no-op in production: DYNAMODB_ENDPOINT_URL is unset there, so this
    returns immediately without retrying anything, and boto3 talks to the
    real, already-running AWS service instead.
    """
    if not os.environ.get('DYNAMODB_ENDPOINT_URL'):
        ensure_table_exists()
        ensure_pairing_table_exists()
        return

    deadline = time.time() + timeout_seconds
    while True:
        try:
            ensure_table_exists()
            ensure_pairing_table_exists()
            return
        except Exception as exc:
            if time.time() >= deadline:
                print(f"WARNING: DynamoDB Local still unreachable after {timeout_seconds}s, continuing anyway: {exc}")
                return
            print("Waiting for DynamoDB Local to finish starting...")
            time.sleep(1)


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
    # In production this runs once and returns immediately (no-op tables -
    # see users.py's docstring). In local dev, retries against DynamoDB
    # Local until it's actually up - see _wait_for_dynamodb_local.
    _wait_for_dynamodb_local()

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

    # Waitress serves the app: one process with a thread pool. A single
    # process matters here - all transit data lives in this process's memory
    # and is refreshed by the scheduler thread started above, so a
    # multi-process server would hold one copy of the schedule per worker
    # and never run this startup block in any of them.
    #
    # FLASK_DEBUG=1 switches to Flask's own development server with the
    # Werkzeug debugger, for local debugging only: the debugger allows
    # arbitrary code execution, so it must never run where the port is
    # reachable by anyone else. The reloader stays off either way, since it
    # would start a second process that repeats the startup refresh and
    # scheduler.
    if os.environ.get('FLASK_DEBUG', '0') == '1':
        app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
    else:
        serve(app, host='0.0.0.0', port=5000, threads=8)