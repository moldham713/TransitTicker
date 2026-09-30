# Google Sign-In verification and the Flask session that follows it.
#
# Uses Google Identity Services' ID-token flow (a "Sign in with Google"
# button that hands the browser a signed JWT directly), not the full OAuth
# authorization-code exchange - this app only needs to know who signed in,
# never to call a Google API on the user's behalf, so verifying an ID
# token's signature is sufficient and needs no client secret at all.

import os
from functools import wraps

from flask import session, jsonify
from google.oauth2 import id_token
from google.auth.transport import requests as google_auth_requests

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')

# Reused across verifications so google-auth can cache Google's public keys
# instead of re-fetching them on every single login.
_google_request = google_auth_requests.Request()


def verify_google_id_token(token: str) -> str:
    """
    Verify a Google-issued ID token's signature, expiry, and audience,
    returning the account's stable subject id (the `sub` claim) on success.

    Raises ValueError (directly, or via whatever google-auth itself raises)
    if the token is invalid, expired, or was issued for a different app -
    the audience check specifically is what stops a token meant for some
    other application from being replayed against this backend.
    """
    claims = id_token.verify_oauth2_token(token, _google_request, GOOGLE_CLIENT_ID)
    # verify_oauth2_token checks signature/expiry/audience but not issuer -
    # Google's own documented backend-verification example checks this
    # manually. Google has historically issued both forms as valid values.
    if claims.get('iss') not in ('accounts.google.com', 'https://accounts.google.com'):
        raise ValueError(f"Unexpected token issuer: {claims.get('iss')!r}")
    return claims['sub']


def login_required(view_func):
    """
    Decorator for Flask routes that require a logged-in session. Returns
    401 without calling the view at all if session['user_id'] isn't set.
    """
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "login required"}), 401
        return view_func(*args, **kwargs)
    return wrapped
