from __future__ import annotations

import unittest
from datetime import date

from healthos.google_health import GoogleOAuthClient, data_point_to_record


class FakeHttp:
    def __init__(self) -> None:
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return {"access_token": "access-token", "expires_in": 3600, "scope": "scope-a"}


class GoogleOAuthTests(unittest.TestCase):
    def test_refresh_access_token_uses_refresh_grant_with_optional_scope_subset(self) -> None:
        http = FakeHttp()
        client = GoogleOAuthClient(http, "client-id", "client-secret")

        token = client.refresh_access_token("refresh-token", scopes=("scope-a", "scope-b"))

        self.assertEqual(token.access_token, "access-token")
        method, url, kwargs = http.calls[0]
        self.assertEqual(method, "POST")
        self.assertIn("oauth2.googleapis.com/token", url)
        self.assertEqual(kwargs["form_body"]["grant_type"], "refresh_token")
        self.assertEqual(kwargs["form_body"]["refresh_token"], "refresh-token")
        self.assertEqual(kwargs["form_body"]["scope"], "scope-a scope-b")


class GoogleHealthClientTests(unittest.TestCase):
    def test_daily_metric_filter_uses_snake_case_data_type_name(self) -> None:
        from healthos.google_health import GoogleHealthClient

        client = GoogleHealthClient(FakeHttp())

        filter_text = client._filter_for(
            "daily-heart-rate-variability",
            "dailyHeartRateVariability",
            date(2026, 8, 7),
            date(2026, 8, 10),
        )

        self.assertEqual(
            filter_text,
            'daily_heart_rate_variability.date >= "2026-08-07" '
            'AND daily_heart_rate_variability.date < "2026-08-10"',
        )

    def test_daily_rollup_sends_midnight_civil_time_range(self) -> None:
        from healthos.google_health import GoogleHealthClient

        http = FakeHttp()
        client = GoogleHealthClient(http)

        client.daily_rollup("access-token", "steps", date(2026, 8, 7), date(2026, 8, 10))

        _, _, kwargs = http.calls[0]
        payload = kwargs["json_body"]
        self.assertEqual(payload["pageSize"], 3)
        self.assertEqual(payload["range"]["start"]["time"]["hours"], 0)
        self.assertEqual(payload["range"]["end"]["time"]["hours"], 0)
        self.assertEqual(payload["range"]["start"]["date"]["day"], 7)
        self.assertEqual(payload["range"]["end"]["date"]["day"], 10)

    def test_daily_rollup_chunks_active_minutes_to_supported_range(self) -> None:
        from healthos.google_health import GoogleHealthClient

        http = FakeHttp()
        client = GoogleHealthClient(http)

        client.daily_rollup(
            "access-token",
            "active-minutes",
            date(2026, 8, 1),
            date(2026, 8, 31),
        )

        self.assertEqual(len(http.calls), 3)
        page_sizes = [call[2]["json_body"]["pageSize"] for call in http.calls]
        self.assertEqual(page_sizes, [14, 14, 2])
        starts = [call[2]["json_body"]["range"]["start"]["date"]["day"] for call in http.calls]
        self.assertEqual(starts, [1, 15, 29])


class GoogleHealthRecordTests(unittest.TestCase):
    def test_sleep_record_uses_interval_end_time_for_metric_date(self) -> None:
        record = data_point_to_record(
            "sleep",
            {
                "name": "sleep-1",
                "sleep": {
                    "interval": {
                        "startTime": "2026-08-09T05:26:00Z",
                        "endTime": "2026-08-09T14:16:00Z",
                        "startUtcOffset": "-18000s",
                        "endUtcOffset": "-18000s",
                    },
                    "summary": {"minutesAsleep": 420},
                },
            },
        )

        self.assertEqual(record.metric_date, date(2026, 8, 9))

    def test_exercise_record_uses_interval_start_time_for_metric_date(self) -> None:
        record = data_point_to_record(
            "exercise",
            {
                "name": "exercise-1",
                "exercise": {
                    "interval": {
                        "startTime": "2026-08-07T23:16:09Z",
                        "endTime": "2026-08-07T23:37:46Z",
                        "startUtcOffset": "-18000s",
                        "endUtcOffset": "-18000s",
                    },
                    "metricsSummary": {},
                },
            },
        )

        self.assertEqual(record.metric_date, date(2026, 8, 7))


if __name__ == "__main__":
    unittest.main()
