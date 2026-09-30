"""HTML pages and form parsing for the WiFi setup portal (portal.py).

Kept free of hardware imports so the parsing - which handles arbitrary
input from whoever joins the setup hotspot - can be tested on a desktop.
"""

MAX_SSID_BYTES = 32

_STYLE = (
    "body{font-family:system-ui,sans-serif;max-width:26em;margin:2em auto;padding:0 1em;color:#222}"
    "h1{font-size:1.4em}label{display:block;margin-top:1em;font-weight:600}"
    "input{width:100%;padding:.6em;font-size:1em;box-sizing:border-box;margin-top:.3em}"
    "button{margin-top:1.5em;padding:.7em 1.6em;font-size:1em}"
    ".err{background:#fde8e8;color:#8a1c1c;padding:.7em;border-radius:4px}"
    ".note{color:#666;font-size:.9em}"
)


def html_escape(text):
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _page(body):
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>TransitTicker WiFi setup</title><style>" + _STYLE + "</style></head>"
        "<body><h1>TransitTicker</h1>" + body + "</body></html>"
    )


def setup_page(networks, error=None, ssid=""):
    """The form: network name (with nearby networks offered as
    suggestions) and password."""
    options = "".join('<option value="' + html_escape(name) + '">' for name in networks)
    error_html = '<p class="err">' + html_escape(error) + "</p>" if error else ""
    return _page(
        error_html
        + "<p>Choose the WiFi network this display should use.</p>"
        + '<form method="post" action="/" accept-charset="utf-8">'
        + '<label>Network name<input name="ssid" list="nets" required maxlength="32"'
        + ' autocapitalize="none" autocorrect="off" spellcheck="false" value="' + html_escape(ssid) + '"></label>'
        + '<datalist id="nets">' + options + "</datalist>"
        + '<label>Password<input name="password" type="password" maxlength="64"></label>'
        + '<p class="note">Leave the password empty for an open network. '
        + "This display supports 2.4&nbsp;GHz WiFi only.</p>"
        + '<button type="submit">Connect</button></form>'
    )


def saved_page(ssid):
    return _page(
        "<p>Saved. The display is now joining <b>" + html_escape(ssid) + "</b>.</p>"
        "<p>You can reconnect this phone to your usual network. If the display"
        " can't join, it will show this setup hotspot again.</p>"
    )


def parse_form(body):
    """Decode an application/x-www-form-urlencoded body (bytes) into a
    dict of str -> str. Raises ValueError on invalid UTF-8."""
    fields = {}
    for pair in body.split(b"&"):
        if not pair:
            continue
        parts = pair.split(b"=", 1)
        key = _unquote_plus(parts[0])
        fields[key] = _unquote_plus(parts[1]) if len(parts) > 1 else ""
    return fields


def _unquote_plus(raw):
    out = bytearray()
    i = 0
    n = len(raw)
    while i < n:
        c = raw[i]
        if c == 0x2B:  # "+"
            out.append(0x20)
            i += 1
            continue
        if c == 0x25 and i + 2 < n:  # "%XX"
            try:
                out.append(int(bytes(raw[i + 1:i + 3]).decode(), 16))
                i += 3
                continue
            except ValueError:
                pass
        out.append(c)
        i += 1
    return bytes(out).decode("utf-8")


def validate_wifi(fields):
    """Returns (ssid, password, problem); `problem` is None when valid."""
    ssid = fields.get("ssid", "").strip()
    password = fields.get("password", "")
    if not ssid:
        return ssid, password, "Enter a network name."
    if len(ssid.encode("utf-8")) > MAX_SSID_BYTES:
        return ssid, password, "Network names are at most 32 bytes."
    if password and not 8 <= len(password) <= 64:
        return ssid, password, "WiFi passwords are 8 to 64 characters (or empty for an open network)."
    return ssid, password, None
