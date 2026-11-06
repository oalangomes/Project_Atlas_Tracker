from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
AUTOCAPTURE = ROOT / "exporter" / "FC26_AutoCapture_v1.1.1.lua"
MATCHSTATS = ROOT / "exporter" / "FC26_MatchStatsExport_v1.1.0.lua"
SNAPSHOT = ROOT / "exporter" / "FC26_Snapshot_v1.1.0.lua"


class AutoCapturePostMatchSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.autocapture = AUTOCAPTURE.read_text(encoding="utf-8")
        cls.matchstats = MATCHSTATS.read_text(encoding="utf-8")
        cls.snapshot = SNAPSHOT.read_text(encoding="utf-8")

    def test_hotfix_suppresses_sync_postmatch_snapshot_and_rearm(self):
        source = self.autocapture
        self.assertIn("local VERSION = \"1.1.4\"", source)
        self.assertIn("state.post_match_export_suppressed = true", source)
        self.assertIn("if state.post_match_export_suppressed then return end", source)
        self.assertIn("auto_capture_state.post_match_candidate_finalized = true", source)
        self.assertIn('suppress_post_match_auto_export(state.last_count,', source)
        self.assertIn("not existing.post_match_export_suppressed then", source)

        start = source.index("local function check_for_new_completed_match()")
        end = source.index("function FC26ExportAutoCapture_PostCareerModeEvent", start)
        callback = source[start:end]
        self.assertNotIn('run_export("auto_after_completed_match")', callback)
        self.assertNotIn('ensure_match_stats_armed("post_match_rearm")', callback)
        self.assertIn("suppress_post_match_auto_export(count, signature", callback)

    def test_both_matchstats_copies_detach_at_final_candidate(self):
        stop_block = (
            "if phase == 'post' and FINAL_CANDIDATE_EVENTS[event_id] and\n"
            "       state.match_started then\n"
            "        stop_probe('final_candidate_event_' .. tostring(event_id))\n"
            "        return\n"
            "    end"
        )
        for name, source in (("embedded", self.autocapture), ("standalone", self.matchstats)):
            with self.subTest(copy=name):
                self.assertIn(stop_block, source)
                self.assertIn("function stop_probe(reason)", source)
                self.assertIn("if participant_complete and PIPELINE_AUTOMANAGED and ready_output_dir then", source)
                self.assertIn("os.rename(output_dir, ready_output_dir)", source)

    def test_final_candidate_detach_precedes_hub_transition_handler(self):
        for name, source in (("embedded", self.autocapture), ("standalone", self.matchstats)):
            with self.subTest(copy=name):
                candidate = source.index("stop_probe('final_candidate_event_'")
                hub = source.index("stop_probe('entered_career_hub_after_match')")
                self.assertLess(candidate, hub)

    def test_snapshot_uses_supported_case_for_team_long_form_field(self):
        for name, source in (("embedded", self.autocapture), ("standalone", self.snapshot)):
            with self.subTest(copy=name):
                self.assertIn('"teamlongform"', source)
                self.assertNotIn('"Teamlongform"', source)

    def test_event_handler_removal_uses_live_editor_event_name_and_id(self):
        for name, source in (("autocapture", self.autocapture), ("standalone matchstats", self.matchstats)):
            with self.subTest(copy=name):
                self.assertIn("state.event_handler_ids = function(event_name)", source)
                self.assertIn("state.added_event_handler_id = function(event_name, before)", source)
                self.assertIn("math.tointeger(numeric_id)", source)
                self.assertIn("state.remove_event_handler = function(event_name, raw_id)", source)
                self.assertNotIn("state.pre_handler = state._register_result", source)
                self.assertNotIn("state.post_handler = state._register_result", source)


if __name__ == "__main__":
    unittest.main()
