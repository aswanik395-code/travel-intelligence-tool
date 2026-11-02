"""Offline unit tests: the API is mocked, so these run without internet or an API key.
    python -m unittest -v
"""
import unittest
from unittest.mock import patch

import requests

import travel_tool as t

BASE = "https://api.test/v5"
CFG = {"base_url": BASE, "api_key_env": "COUNTRY_API_KEY", "timeout_seconds": 5,
       "response_fields": "names.common"}

FRANCE = {
    "names": {"common": "France", "official": "French Republic"},
    "codes": {"alpha_3": "FRA"},
    "capitals": [{"name": "Paris", "attributes": {"primary": True}}],
    "population": 67391582,
    "currencies": {"EUR": {"name": "Euro", "symbol": "€"}},
    "languages": [{"name": "French", "iso639_3": "fra"}],
    "region": "Europe", "subregion": "Western Europe",
    "borders": ["BEL", "ESP"],
}
NEIGHBOURS = [{"names": {"common": "Spain"}}, {"names": {"common": "Belgium"}}]


def envelope(objects):
    return {"data": {"objects": objects, "meta": {"total": len(objects)}}}


class FakeResponse:
    def __init__(self, status=200, payload=None, bad_json=False):
        self.status_code, self._payload, self._bad = status, payload, bad_json
        self.ok = status < 400

    def json(self):
        if self._bad:
            raise ValueError("bad json")
        return self._payload


def router(routes):
    """Fake requests.get; routes keyed by path ('/borders/' = prefix, '/name' = exact)."""
    def fake_get(url, params=None, timeout=None, headers=None):
        path = url[len(BASE):]
        for key, resp in routes.items():
            if (key.endswith("/") and path.startswith(key)) or path == key:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"unexpected URL {url}")
    return fake_get


class TestTravelTool(unittest.TestCase):
    def setUp(self):
        p = patch.dict("os.environ", {"COUNTRY_API_KEY": "test-key"})
        p.start()
        self.addCleanup(p.stop)

    def snapshot(self, name, routes):
        with patch("requests.get", router(routes)):
            return t.get_travel_snapshot(name, CFG)

    def test_success_with_neighbours(self):
        info = self.snapshot("France", {"/names.common/": FakeResponse(200, envelope([FRANCE])),
                                        "/borders/": FakeResponse(200, envelope(NEIGHBOURS))})
        self.assertEqual(info["capital"], "Paris")
        self.assertEqual(info["neighbours"], ["Belgium", "Spain"])
        self.assertEqual(info["currency"], ["Euro (€) [EUR]"])
        self.assertEqual(info["languages"], ["French"])
        self.assertIn("67,391,582", t.format_snapshot(info))

    def test_api_key_sent_as_bearer_header(self):
        seen = {}
        def fake_get(url, params=None, timeout=None, headers=None):
            seen.update(headers or {})
            return FakeResponse(200, envelope([dict(FRANCE, borders=[])]))
        with patch("requests.get", fake_get):
            t.get_travel_snapshot("France", CFG)
        self.assertEqual(seen["Authorization"], "Bearer test-key")

    def test_missing_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(t.TravelToolError, "No API key"):
                t.get_travel_snapshot("France", CFG)

    def test_unknown_country_404_and_empty(self):
        for first in (FakeResponse(404), FakeResponse(200, envelope([]))):
            routes = {"/names.common/": first, "/name": FakeResponse(200, envelope([]))}
            with self.assertRaisesRegex(t.TravelToolError, "No country found"):
                self.snapshot("Atlantis", routes)

    def test_fallback_to_name_search(self):
        info = self.snapshot("Fran", {"/names.common/": FakeResponse(404),
                                      "/name": FakeResponse(200, envelope([dict(FRANCE, borders=[])]))})
        self.assertEqual(info["country"], "France")

    def test_pick_exact_match_over_first(self):
        niger, nigeria = {"names": {"common": "Nigeria"}}, {"names": {"common": "Niger"}}
        info = self.snapshot("Niger", {"/names.common/": FakeResponse(200, envelope([niger, nigeria]))})
        self.assertEqual(info["country"], "Niger")

    def test_deprecated_api_error_body(self):
        body = {"success": False, "data": None, "errors": [{"message": "This API version has been deprecated."}]}
        with self.assertRaisesRegex(t.TravelToolError, "deprecated"):
            self.snapshot("France", {"/names.common/": FakeResponse(200, body)})

    def test_http_errors(self):
        cases = {401: "rejected your key", 403: "forbidden", 410: "no longer active",
                 429: "Too many", 500: "having problems", 400: "rejected the request"}
        for status, msg in cases.items():
            with self.assertRaisesRegex(t.TravelToolError, msg):
                self.snapshot("France", {"/names.common/": FakeResponse(status, {"errors": []})})

    def test_timeout_and_no_internet(self):
        for exc, msg in ((requests.exceptions.Timeout(), "did not respond"),
                         (requests.exceptions.ConnectionError(), "internet")):
            with self.assertRaisesRegex(t.TravelToolError, msg):
                self.snapshot("France", {"/names.common/": exc})

    def test_invalid_json_and_unexpected_shape(self):
        with self.assertRaisesRegex(t.TravelToolError, "not valid JSON"):
            self.snapshot("France", {"/names.common/": FakeResponse(200, bad_json=True)})
        with self.assertRaisesRegex(t.TravelToolError, "unexpected format"):
            self.snapshot("France", {"/names.common/": FakeResponse(200, {"oops": 1})})

    def test_missing_fields_and_no_borders(self):
        info = self.snapshot("Nowhere", {"/names.common/": FakeResponse(200, envelope([{"names": {"common": "Nowhere"}}]))})
        self.assertEqual(info["capital"], "N/A")
        self.assertEqual(info["languages"], ["N/A"])
        self.assertIsNone(info["population"])
        out = t.format_snapshot(info)
        self.assertIn("N/A", out)
        self.assertIn("island", out)

    def test_neighbour_lookup_failure_falls_back_to_codes(self):
        info = self.snapshot("France", {"/names.common/": FakeResponse(200, envelope([FRANCE])),
                                        "/borders/": requests.exceptions.ConnectionError()})
        self.assertEqual(info["neighbours"], ["BEL", "ESP"])

    def test_flexible_shapes_for_currencies_and_languages(self):
        raw = {"names": {"common": "X"},
               "currencies": [{"code": "JPY", "name": "Japanese yen", "symbol": "¥"}],
               "languages": {"jpn": {"name": "Japanese"}},
               "capitals": [{"name": "Second"}, {"name": "Tokyo", "attributes": {"primary": True}}]}
        info = t.parse_country(raw, [])
        self.assertEqual(info["currency"], ["Japanese yen (¥) [JPY]"])
        self.assertEqual(info["languages"], ["Japanese"])
        self.assertEqual(info["capital"], "Tokyo, Second")

    def test_bad_input(self):
        for bad in ("", "   ", "12345", "!!!"):
            with self.assertRaises(t.TravelToolError):
                self.snapshot(bad, {})

    def test_config_env_override_and_missing_file(self):
        with patch.dict("os.environ", {"COUNTRY_API_BASE_URL": "https://other.example/v5/"}):
            self.assertEqual(t.load_config()["base_url"], "https://other.example/v5")
        with self.assertRaisesRegex(t.TravelToolError, "not found"):
            t.load_config("/nonexistent/config.json")


if __name__ == "__main__":
    unittest.main()