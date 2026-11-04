from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas.settings import SettingsService, application_language


class SettingsLanguageTests(unittest.TestCase):
    def test_language_choice_is_global_persistent_and_does_not_clear_simulations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "global_settings.json"

            class NoDbMutation:
                def connect(self):
                    raise AssertionError("reading a missing global preference must stay read-only")

                def transaction(self):
                    raise AssertionError("language changes must not clear world simulations")

            service = SettingsService(NoDbMutation())
            with patch("atlas.settings.global_settings_path", return_value=path):
                saved = service.save({"language": "en-GB"})
                self.assertEqual(saved["language"], "en-GB")
                self.assertEqual(application_language(), "en-GB")
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["language"], "en-GB")

    def test_unsupported_language_is_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "global_settings.json"
            service = SettingsService(object())
            with patch("atlas.settings.global_settings_path", return_value=path):
                with self.assertRaises(ValueError):
                    service.save({"language": "fr-FR"})
                self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
