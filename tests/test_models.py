from __future__ import annotations

import unittest

from healthos.models import HealthRecord


class ModelTests(unittest.TestCase):
    def test_source_record_hash_is_stable_for_duplicate_records(self) -> None:
        first = HealthRecord(
            data_type="steps",
            source_record_id="same-id",
            value_json={"countSum": "100"},
            raw_json={"name": "same-id", "steps": {"countSum": "100"}},
        )
        second = HealthRecord(
            data_type="steps",
            source_record_id="same-id",
            value_json={"countSum": "100"},
            raw_json={"name": "same-id", "steps": {"countSum": "100"}},
        )

        self.assertEqual(first.source_record_hash, second.source_record_hash)


if __name__ == "__main__":
    unittest.main()

