"""Desktop tests for the hardware-independent firmware modules.

Run from the Embedded/ directory with any Python 3:

    python -m unittest discover -s tests -v
"""

import unittest

from fakes import FakeResponse, FakeSession, make_canvas  # noqa: E402 (sets sys.path)

from transitticker import api, departures, font, render, web
from transitticker.storage import HEADER_SIZE, DeviceStore
from transitticker.util import backoff_ms


class FontTests(unittest.TestCase):
    def test_every_glyph_has_consistent_rows(self):
        for face, height in ((font._SMALL_GLYPHS, 5), (font._LARGE_GLYPHS, 7)):
            for char, rows in face.items():
                self.assertEqual(len(rows), height, char)
                self.assertEqual(len(set(len(r) for r in rows)), 1, char)
                self.assertTrue(set("".join(rows)) <= {"X", "."}, char)

    def test_large_font_covers_pairing_alphabet_and_digits(self):
        for char in "ABCDEFGHJKMNPQRSTUVWXYZ23456789" + "0123456789":
            self.assertIn(char, font._LARGE_GLYPHS)

    def test_measure(self):
        self.assertEqual(font.LARGE.measure("12"), 11)
        self.assertEqual(font.SMALL.measure(""), 0)
        self.assertEqual(font.SMALL.measure("a"), font.SMALL.measure("A"))

    def test_unknown_characters_render_as_question_mark(self):
        self.assertEqual(font.SMALL.measure("é"), font.SMALL.measure("?"))

    def test_truncate(self):
        text = font.SMALL.truncate("X" * 40, 64)
        self.assertLessEqual(font.SMALL.measure(text), 64)
        self.assertGreater(font.SMALL.measure(text + "X"), 64)


class StorageTests(unittest.TestCase):
    def test_fresh_nvm_is_empty(self):
        store = DeviceStore(bytearray(8192))
        self.assertIsNone(store.token)
        self.assertIsNone(store.wifi)

    def test_token_and_wifi_survive_reload(self):
        nvm = bytearray(8192)
        store = DeviceStore(nvm)
        store.set_wifi("Home Net", "hunter22")
        store.set_token("abcDEF123_-xyz")
        reloaded = DeviceStore(nvm)
        self.assertEqual(reloaded.token, "abcDEF123_-xyz")
        self.assertEqual(reloaded.wifi, ("Home Net", "hunter22", False))
        reloaded.mark_wifi_verified()
        self.assertEqual(DeviceStore(nvm).wifi, ("Home Net", "hunter22", True))

    def test_clear_token_keeps_wifi(self):
        nvm = bytearray(8192)
        store = DeviceStore(nvm)
        store.set_wifi("Home", "password1")
        store.set_token("t")
        store.clear_token()
        reloaded = DeviceStore(nvm)
        self.assertIsNone(reloaded.token)
        self.assertEqual(reloaded.wifi[0], "Home")

    def test_factory_reset_erases_everything(self):
        nvm = bytearray(8192)
        store = DeviceStore(nvm)
        store.set_wifi("Home", "password1")
        store.set_token("t")
        store.factory_reset()
        self.assertIsNone(store.token)
        reloaded = DeviceStore(nvm)
        self.assertIsNone(reloaded.token)
        self.assertIsNone(reloaded.wifi)

    def test_foreign_or_corrupt_nvm_reads_as_empty(self):
        self.assertIsNone(DeviceStore(bytearray(b"\xff" * 64)).token)
        nvm = bytearray(64)
        nvm[0:6] = b"TTK1\x00\x05"
        nvm[6:11] = b"{bad}"
        self.assertIsNone(DeviceStore(nvm).token)
        nvm[4:6] = b"\xff\xff"  # length larger than nvm
        self.assertIsNone(DeviceStore(nvm).token)

    def test_unchanged_update_skips_write(self):
        class CountingNvm(bytearray):
            writes = 0

            def __setitem__(self, key, value):
                CountingNvm.writes += 1
                super().__setitem__(key, value)

        nvm = CountingNvm(1024)
        store = DeviceStore(nvm)
        store.set_token("abc")
        store.set_token("abc")
        self.assertEqual(CountingNvm.writes, 1)

    def test_too_small_nvm_raises(self):
        store = DeviceStore(bytearray(HEADER_SIZE + 4))
        with self.assertRaises(ValueError):
            store.set_token("a" * 32)

    def test_missing_nvm_raises(self):
        with self.assertRaises(RuntimeError):
            DeviceStore(None)


class DepartureTests(unittest.TestCase):
    BOARDS = [
        {"departures": [
            {"departure_time": "12:01:00", "minutes_away": 1, "is_realtime": True},
            {"departure_time": "12:05:00", "minutes_away": 5, "is_realtime": False},
            {"departure_time": "12:12:00", "minutes_away": 12, "is_realtime": True},
        ]},
        {"departures": []},
    ]

    def test_passthrough_at_zero_elapsed(self):
        rows = departures.build_rows(self.BOARDS, 0)
        self.assertEqual(rows[0]["departures"], [(1, True), (5, False), (12, True)])
        self.assertEqual(rows[1]["departures"], [])
        self.assertIsNone(rows[0]["route"])

    def test_counts_down_and_drops_departed_trains(self):
        rows = departures.build_rows(self.BOARDS, 2 * 60000 + 5000)
        self.assertEqual(rows[0]["departures"], [(3, False), (10, True)])

    def test_malformed_entries_are_skipped(self):
        boards = [
            "nonsense",
            {"departures": [{"minutes_away": "3"}, {"minutes_away": True}, None, {"minutes_away": 4}]},
            {"departures": None},
            {},
        ]
        rows = departures.build_rows(boards, 0)
        # Only the first 3 entries are considered (the backend's own cap);
        # the non-dict one among them is dropped.
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["departures"], [(4, False)])
        self.assertEqual(rows[1]["departures"], [])

    def test_caps_boards_and_departures(self):
        many = {"departures": [{"minutes_away": i, "is_realtime": False} for i in range(6)]}
        rows = departures.build_rows([many] * 5, 0)
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(rows[0]["departures"]), 3)

    def test_route_passthrough(self):
        rows = departures.build_rows([{"route": "Q", "departures": []}], 0)
        self.assertEqual(rows[0]["route"], "Q")


class ApiTests(unittest.TestCase):
    def client(self, *responses):
        session = FakeSession(responses)
        return api.ApiClient(session, "http://10.0.0.5:5000/"), session

    def test_pair_start(self):
        client, session = self.client(FakeResponse(200, {"pairing_code": "ab3xq9", "expires_in": 600}))
        self.assertEqual(client.pair_start(), ("AB3XQ9", 600))
        call = session.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], "http://10.0.0.5:5000/device/pair/start")
        self.assertEqual(call["headers"], {"Content-Length": "0"})
        self.assertIsNotNone(call["timeout"])

    def test_pair_start_defaults_missing_ttl(self):
        client, _ = self.client(FakeResponse(200, {"pairing_code": "AB3XQ9"}))
        self.assertEqual(client.pair_start()[1], api.DEFAULT_PAIRING_TTL_S)

    def test_pair_status_states(self):
        client, session = self.client(
            FakeResponse(200, {"status": "pending"}),
            FakeResponse(200, {"status": "not_found"}),
            FakeResponse(200, {"status": "claimed", "device_token": "tok"}),
        )
        self.assertEqual(client.pair_status("AB3XQ9"), ("pending", None))
        self.assertEqual(client.pair_status("AB3XQ9"), ("not_found", None))
        self.assertEqual(client.pair_status("AB3XQ9"), ("claimed", "tok"))
        self.assertTrue(session.calls[0]["url"].endswith("/device/pair/status/AB3XQ9"))

    def test_claimed_without_token_is_an_error(self):
        client, _ = self.client(FakeResponse(200, {"status": "claimed"}))
        with self.assertRaises(api.ApiError):
            client.pair_status("X")

    def test_departures(self):
        boards = [{"departures": []}]
        client, session = self.client(FakeResponse(200, {"boards": boards}))
        self.assertEqual(client.departures("tok123"), boards)
        self.assertEqual(session.calls[0]["url"], "http://10.0.0.5:5000/device/tok123")
        self.assertIsNone(session.calls[0]["headers"])

    def test_401_is_unauthorized_and_response_closed(self):
        response = FakeResponse(401, {"error": "unknown device token"})
        client, _ = self.client(response)
        with self.assertRaises(api.Unauthorized):
            client.departures("tok")
        self.assertTrue(response.closed)

    def test_failures_become_api_errors_without_leaking_token(self):
        cases = [
            FakeResponse(500, {}),
            FakeResponse(200, None, json_error=ValueError("bad json")),
            FakeResponse(200, ["not", "a", "dict"]),
            FakeResponse(200, {"boards": "nope"}),
            OSError(110, "ETIMEDOUT"),
            RuntimeError("Sending request failed"),
        ]
        for case in cases:
            client, _ = self.client(case)
            with self.assertRaises(api.ApiError) as ctx:
                client.departures("SECRET-TOKEN")
            self.assertNotIn("SECRET-TOKEN", str(ctx.exception))
            if isinstance(case, FakeResponse):
                self.assertTrue(case.closed)


class WebTests(unittest.TestCase):
    def test_parse_form(self):
        fields = web.parse_form(b"ssid=My+Caf%C3%A9+%26+Bar&password=p%40ss+w%3Drd&empty=&flag")
        self.assertEqual(fields["ssid"], "My Café & Bar")
        self.assertEqual(fields["password"], "p@ss w=rd")
        self.assertEqual(fields["empty"], "")
        self.assertEqual(fields["flag"], "")

    def test_parse_form_tolerates_stray_percent(self):
        self.assertEqual(web.parse_form(b"a=100%&b=%zz%4")["a"], "100%")
        self.assertEqual(web.parse_form(b"b=%zz%4")["b"], "%zz%4")

    def test_parse_form_rejects_invalid_utf8(self):
        with self.assertRaises(ValueError):
            web.parse_form(b"ssid=%FF%FE")

    def test_validate_wifi(self):
        self.assertIsNone(web.validate_wifi({"ssid": " Home ", "password": "12345678"})[2])
        self.assertEqual(web.validate_wifi({"ssid": " Home ", "password": ""})[:2], ("Home", ""))
        self.assertIsNotNone(web.validate_wifi({"ssid": "", "password": "12345678"})[2])
        self.assertIsNotNone(web.validate_wifi({"ssid": "x" * 33, "password": ""})[2])
        self.assertIsNotNone(web.validate_wifi({"ssid": "Home", "password": "short"})[2])

    def test_pages_escape_network_names(self):
        page = web.setup_page(['<script>alert(1)</script>'], error='bad "name"', ssid="a&b")
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("&quot;name&quot;", page)
        self.assertIn('value="a&amp;b"', page)
        self.assertNotIn("<b><i>", web.saved_page("<b><i>"))


class RenderTests(unittest.TestCase):
    """Draws every screen with worst-case inputs; FakeBitmap raises if
    anything lands off the 64x32 canvas."""

    def test_all_screens_stay_on_canvas(self):
        canvas = make_canvas()
        full = [{"route": None, "departures": [(99, True), (150, False), (0, True)]}] * 3
        render.splash(canvas)
        render.message(canvas, ["A" * 30] * 6, True)
        render.countdown_message(canvas, [("CAN'T REACH", render.WHITE), ("SERVER", render.WHITE)], 120)
        render.wifi_setup(canvas, "TICKER-4F2A", "12345678", "192.168.4.1")
        render.pairing(canvas, "AB3XQ9", 599, "ON THE WEB APP", True)
        render.pairing(canvas, "WEIRDLENGTHCODE", 0, "X" * 40)
        for held in (0, 2500, 3000, 9999, 10000, 60000):
            render.reset_hold(canvas, held, 3000, 10000)
        for n in range(4):
            render.boards(canvas, full[:n], True)
        render.boards(canvas, [{"route": "Q", "departures": []}, {"route": "GS", "departures": [(3, False)]}])

    def test_live_and_scheduled_use_distinct_colors_and_dot(self):
        canvas = make_canvas()
        render.boards(canvas, [{"route": None, "departures": [(5, True), (7, False)]}])
        used = {v for row in canvas.bitmap.pixels for v in row}
        self.assertIn(render.LIVE, used)
        self.assertIn(render.SCHEDULED, used)
        self.assertIn(render.GREEN, used)

    def test_minutes_over_99_are_clamped(self):
        a, b = make_canvas(), make_canvas()
        render.boards(a, [{"route": None, "departures": [(99, False)]}])
        render.boards(b, [{"route": None, "departures": [(250, False)]}])
        self.assertEqual(a.bitmap.pixels, b.bitmap.pixels)

    def test_brightness_scales_palette(self):
        self.assertEqual(make_canvas(100).palette[render.WHITE], 0xC8C8C8)
        self.assertEqual(make_canvas(50).palette[render.WHITE], 0x646464)


class BackoffTests(unittest.TestCase):
    def test_grows_and_caps(self):
        for _ in range(50):
            self.assertTrue(4000 <= backoff_ms(1) <= 6000)
            self.assertTrue(8000 <= backoff_ms(2) <= 12000)
            self.assertTrue(96000 <= backoff_ms(40) <= 144000)


if __name__ == "__main__":
    unittest.main()
