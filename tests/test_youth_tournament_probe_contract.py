from pathlib import Path
import unittest


PROBE = (
    Path(__file__).resolve().parents[1]
    / "exporter"
    / "FC26_YouthTournamentProbe_v0.1.lua"
)


class YouthTournamentProbeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PROBE.read_text(encoding="utf-8")

    def test_registers_both_event_phases(self):
        self.assertIn('"pre__CareerModeEvent"', self.source)
        self.assertIn('"post__CareerModeEvent"', self.source)

    def test_records_event_id_and_name_without_payload_inspection(self):
        self.assertIn("event_id=%s", self.source)
        self.assertIn("safe_event_name(id or event_id)", self.source)
        self.assertNotIn("event.", self.source)
        self.assertNotIn("pairs(event)", self.source)

    def test_has_no_database_or_game_memory_access(self):
        forbidden = (
            "GetTable(",
            "GetRecordFieldValue(",
            "MEMORY:",
            "SetRecordFieldValue(",
            "WriteBytes(",
            "WriteInt(",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, self.source)


if __name__ == "__main__":
    unittest.main()
