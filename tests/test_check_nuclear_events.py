import datetime
import pathlib
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import check_nuclear_events as monitor


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.text = ""

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class NuclearEventMonitorTests(unittest.TestCase):
    def test_nearest_recent_cpm_sample_after_event_is_selected(self):
        event_time = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=10)
        monitoring_end = event_time + datetime.timedelta(minutes=10)
        payload = [
            {
                "value": 10,
                "unit": "cpm",
                "latitude": 0,
                "longitude": 0.1,
                "captured_at": (event_time + datetime.timedelta(minutes=5)).isoformat(),
            },
            {
                "value": 200,
                "unit": "CPM",
                "latitude": 0,
                "longitude": 0.01,
                "captured_at": (event_time + datetime.timedelta(minutes=1)).isoformat(),
            },
            {
                "value": 500,
                "unit": "uSv/h",
                "latitude": 0,
                "longitude": 0.001,
                "captured_at": (event_time + datetime.timedelta(minutes=1)).isoformat(),
            },
            {
                "value": 700,
                "unit": "cpm",
                "latitude": 0,
                "longitude": 0.001,
                "captured_at": (event_time - datetime.timedelta(minutes=1)).isoformat(),
            },
        ]

        with patch.object(monitor.requests, "get", return_value=FakeResponse(payload)):
            value, unit, _ = monitor.get_nearest_radiation_sample(0, 0, event_time, monitoring_end)

        self.assertEqual(value, 200)
        self.assertEqual(unit, "CPM")

    def test_radiation_query_uses_broader_search_before_strict_filtering(self):
        event_time = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=10)
        monitoring_end = event_time + datetime.timedelta(minutes=10)
        with patch.object(monitor.requests, "get", return_value=FakeResponse([])) as get:
            monitor.get_nearest_radiation_sample(0, 0, event_time, monitoring_end)

        self.assertEqual(get.call_args.kwargs["params"]["distance"], monitor.RADIATION_QUERY_DISTANCE_KM)
        self.assertEqual(get.call_args.kwargs["params"]["captured_after"], event_time.isoformat())
        self.assertEqual(get.call_args.kwargs["params"]["captured_before"], monitoring_end.isoformat())

    def test_usgs_timeout_is_a_monitoring_failure(self):
        with patch.object(monitor.requests, "get", side_effect=monitor.requests.exceptions.Timeout):
            with self.assertRaises(monitor.MonitoringDataError):
                monitor.get_usgs_events(20)

    def test_bluesky_login_sends_password_without_logging_it(self):
        session = {"did": "did:example:test", "accessJwt": "test-token"}
        with patch.object(monitor.requests, "post", return_value=FakeResponse(session)) as post, patch.object(
            monitor,
            "debug_print",
        ) as debug:
            result = monitor.bsky_login_session("https://bsky.social", "example.test", "test-password")

        self.assertEqual(result, session)
        self.assertEqual(
            post.call_args.kwargs["json"],
            {"identifier": "example.test", "password": "test-password"},
        )
        self.assertNotIn(
            "test-password",
            " ".join(str(call.args) for call in debug.call_args_list),
        )

    def test_partial_simulation_input_is_rejected(self):
        with self.assertRaises(ValueError):
            monitor.main(simulate_lat="1", lookback_minutes=20)

    def test_missing_radiation_evidence_is_inconclusive(self):
        now = datetime.datetime.now(datetime.UTC)
        event = {
            "properties": {
                "mag": 3.2,
                "place": "Test location",
                "time": int(now.timestamp() * 1000),
                "url": "https://example.test/usgs-event",
            },
            "geometry": {"coordinates": [20, 10, 1.0]},
        }
        with patch.object(monitor, "get_usgs_events", return_value=[event]), patch.object(
            monitor,
            "get_nearest_radiation_sample",
            return_value=(None, None, None),
        ):
            result = monitor.main(lookback_minutes=20, dry_run=True)

        self.assertEqual(result, "inconclusive")

    def test_dry_run_builds_a_candidate_without_contacting_bluesky(self):
        with patch.object(monitor, "bsky_login_session") as login, patch.object(monitor, "create_bsky_post") as create_post:
            result = monitor.post_to_bsky(
                "alert",
                10,
                20,
                magnitude=3.2,
                depth=1.0,
                event_time="2026-09-19 00:00:00 UTC",
                event_url="https://example.test/usgs-event",
                radiation_level=150,
                radiation_unit="CPM",
                radiation_time="2026-09-19T00:01:00Z",
                dry_run=True,
            )

        self.assertTrue(result["dry_run"])
        self.assertIn("Unverified automated candidate event", result["text"])
        self.assertIn("https://example.test/usgs-event", result["text"])
        login.assert_not_called()
        create_post.assert_not_called()


if __name__ == "__main__":
    unittest.main()