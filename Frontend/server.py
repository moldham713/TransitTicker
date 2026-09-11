from flask import Flask, send_from_directory, Response
import os

app = Flask(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')

# The backend URL the *browser* should call. This can't be a Docker-internal
# service name (e.g. "http://backend:5000") because fetch() runs client-side
# in the user's browser, not inside this container - it needs a host/port the
# browser can actually reach. Configurable via env var so the same image can
# point at a different backend without a rebuild.
BACKEND_API_URL = os.environ.get('BACKEND_API_URL', 'http://localhost:5000')


@app.route('/config.js')
def config_js():
    # Served as JS (not JSON) so index.html can load it with a plain
    # <script src="/config.js"> tag before the app code runs.
    return Response(f'window.BACKEND_API_URL = {BACKEND_API_URL!r};', mimetype='application/javascript')


@app.route('/')
def index():
    return send_from_directory(STATIC_DIR, 'index.html')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
