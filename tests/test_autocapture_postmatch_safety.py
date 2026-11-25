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

    def test_postmatch_rearms_at_hub_without_sync_snapshot(self):
        source = self.autocapture
        self.assertIn("local VERSION = \"1.1.6\"", source)
        self.assertNotIn("post_match_export_suppressed", source)
        self.assertIn("auto_capture_state.post_match_candidate_finalized = true", source)
        self.assertIn("reason == 'entered_career_hub_after_match'", source)
        self.assertIn("auto_capture_state.on_match_stats_hub_finish()", source)
        self.assertIn("state.on_match_stats_hub_finish = function()", source)
        self.assertIn("if event_id ~= 26 then return end", source)
        self.assertIn('ensure_match_stats_armed("post_match_hub_rearm")', source)
        self.assertIn("existing._rerun_count > (tonumber(existing.last_snapshot_count) or -1)", source)
        self.assertIn('existing.export_now("hub_rerun_after_completed_match")', source)
        self.assertIn("state.last_count - (tonumber(state.last_snapshot_count) or 0) == 1", source)
        self.assertIn("paired_capture_id = state.last_completed_capture_id", source)
        self.assertLess(
            source.rindex('arm_match_stats("auto_monitor_startup")'),
            source.rindex('AddEventHandler("post__CareerModeEvent", FC26ExportAutoCapture_PostCareerModeEvent)'),
        )

    def test_read_short_binding_survives_global_reassignment(self):
        source = self.autocapture
        binding = source.index("local native_read_short = ReadShort")
        wrapper = source.index("function MEMORY:ReadShort(addr)")
        embedded_snapshot = source.index("local EMBEDDED_EXPORTER_SOURCE = [====[")
        self.assertLess(binding, wrapper)
        self.assertLess(wrapper, embedded_snapshot)
        self.assertIn("return native_read_short(addr)", source[binding:embedded_snapshot])

        start = source.index("local function check_for_new_completed_match(event_id)")
        end = source.index("function FC26ExportAutoCapture_PostCareerModeEvent", start)
        callback = source[start:end]
        self.assertNotIn('run_export("auto_after_completed_match")', callback)
        self.assertIn('state.rearm_after_hub(count, signature, "completed_count_increased")', callback)
        self.assertIn('defer_post_match_snapshot(count, signature, "completed_count_increased")', callback)

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
