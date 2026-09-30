"""Client for the backend's device endpoints (Backend/src/app.py):

    POST /device/pair/start            -> {"pairing_code", "expires_in"}
    GET  /device/pair/status/<code>    -> {"status": "pending" | "claimed" | "not_found", ...}
    GET  /device/<device_token>        -> {"boards": [...]}, or 401 if the token is unknown

Every failure surfaces as one of two exceptions, so callers only decide
between "retry later" (ApiError) and "the backend doesn't recognize this
device's token, so it needs pairing" (Unauthorized).
"""

DEFAULT_PAIRING_TTL_S = 600
REQUEST_TIMEOUT_S = 10

# What adafruit_requests and the socket layer raise for DNS failures,
# refused connections, timeouts and truncated responses.
_TRANSPORT_ERRORS = (OSError, RuntimeError, ValueError)


class ApiError(Exception):
    """Network failure, timeout, non-200 response, or a body that doesn't
    match the expected shape. Always worth retrying later."""


class Unauthorized(Exception):
    """HTTP 401: the backend doesn't recognize this device token."""


class ApiClient:
    def __init__(self, session, base_url, timeout=REQUEST_TIMEOUT_S):
        self._session = session
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def pair_start(self):
        """Returns (pairing_code, expires_in_seconds)."""
        body = self._request("POST", "/device/pair/start", "pair/start")
        code = body.get("pairing_code")
        if not isinstance(code, str) or not code.strip():
            raise ApiError("pair/start: response has no pairing_code")
        expires_in = body.get("expires_in")
        if not isinstance(expires_in, int) or isinstance(expires_in, bool) or expires_in <= 0:
            expires_in = DEFAULT_PAIRING_TTL_S
        return code.strip().upper(), expires_in

    def pair_status(self, code):
        """Returns ("pending", None), ("not_found", None) or ("claimed", token)."""
        body = self._request("GET", "/device/pair/status/" + code, "pair/status")
        status = body.get("status")
        if status == "claimed":
            token = body.get("device_token")
            if not isinstance(token, str) or not token:
                raise ApiError("pair/status: claimed without a device_token")
            return status, token
        if status in ("pending", "not_found"):
            return status, None
        raise ApiError("pair/status: unexpected status %r" % (status,))

    def departures(self, token):
        """Returns the raw "boards" list; see departures.build_rows."""
        body = self._request("GET", "/device/" + token, "device/<token>")
        boards = body.get("boards")
        if not isinstance(boards, list):
            raise ApiError("device/<token>: response has no boards list")
        return boards

    def _request(self, method, path, label):
        # `label` names the endpoint in error messages without the path
        # itself, which for /device/<token> contains the device credential.
        headers = None
        if method == "POST":
            # adafruit_requests only sends Content-Length when there is a
            # body; an explicit zero keeps body-less POSTs acceptable to
            # proxies and load balancers that insist on the header.
            headers = {"Content-Length": "0"}
        try:
            response = self._session.request(method, self._base + path, headers=headers, timeout=self._timeout)
        except _TRANSPORT_ERRORS as exc:
            raise ApiError("%s: request failed: %r" % (label, exc))
        try:
            status = response.status_code
            if status == 401:
                raise Unauthorized(label)
            if status != 200:
                raise ApiError("%s: HTTP %d" % (label, status))
            try:
                body = response.json()
            except _TRANSPORT_ERRORS as exc:
                raise ApiError("%s: unreadable response: %r" % (label, exc))
            if not isinstance(body, dict):
                raise ApiError("%s: response is not a JSON object" % label)
            return body
        finally:
            response.close()
