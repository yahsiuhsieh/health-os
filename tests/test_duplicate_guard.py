from __future__ import annotations

import unittest

from healthos.rollup import should_send_email


class DuplicateGuardTests(unittest.TestCase):
    def test_skips_same_hash_after_send(self) -> None:
        row = {"morning_email_sent_at": "2026-06-02T13:00:00Z", "morning_data_hash": "abc"}

        self.assertFalse(should_send_email(row, "morning", "abc"))

    def test_skips_changed_hash_after_send_to_avoid_duplicate_email(self) -> None:
        row = {"evening_email_sent_at": "2026-06-03T02:30:00Z", "evening_data_hash": "old"}

        self.assertFalse(should_send_email(row, "evening", "new"))

    def test_force_allows_resend(self) -> None:
        row = {"morning_email_sent_at": "2026-06-02T13:00:00Z", "morning_data_hash": "abc"}

        self.assertTrue(should_send_email(row, "morning", "abc", force=True))


if __name__ == "__main__":
    unittest.main()

