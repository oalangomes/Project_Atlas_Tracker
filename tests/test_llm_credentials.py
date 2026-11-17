from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from atlas.commission import (_cloud_provider_plan, _cloud_report_payload, _cloud_report_with_failover,
                              read_llm_config, resolve_report_model)
from atlas.db import ClosingConnection
from atlas.llm_credentials import public_config, update_config
from atlas.secret_protection import protection_available
from atlas.server_http import ApiHandler


class _Database:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        return conn


class LlmCredentialsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = _Database(Path(self.tmp.name) / "credentials.sqlite3")
        with self.db.connect() as conn:
            conn.execute("CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT)")

    def _stored(self) -> str:
        with self.db.connect() as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key='llm_config'").fetchone()
        return row["value"] if row else ""

    def _legacy(self, key: str) -> None:
        with self.db.connect() as conn:
            conn.execute("INSERT INTO app_settings VALUES ('llm_config', ?)",
                         (json.dumps({"provider": "gemini", "keys": {"gemini": key}}),))

    def _request(self, method: str, payload: dict | None = None) -> dict:
        handler = ApiHandler.__new__(ApiHandler)
        handler.server = SimpleNamespace(state=SimpleNamespace(database=self.db))
        responses: list[dict] = []
        handler._json = lambda value, *args: responses.append(value)
        if method == "GET":
            handler._api_get("/api/llm/config", {})
        else:
            handler._api_post("/api/llm/config", payload or {})
        return responses[0]

    @unittest.skipUnless(protection_available(), "Windows user protection unavailable")
    def test_get_migrates_legacy_key_and_only_returns_public_fields(self) -> None:
        key = "synthetic-migration-key-6149"
        self._legacy(key)
        first = self._request("GET")
        self.assertNotIn(key, json.dumps(first))
        self.assertEqual(first["key_hints"]["gemini"], "…6149")
        self.assertTrue(first["configured"]["gemini"])
        self.assertFalse(first["migration_pending"])
        stored = self._stored()
        self.assertNotIn(key, stored)
        self.assertIn("dpapi:", stored)
        self.assertEqual(self._request("GET"), first)
        self.assertEqual(self._stored(), stored)
        with self.db.connect() as conn:
            self.assertEqual(read_llm_config(conn)["keys"]["gemini"], key)

    def test_failed_migration_preserves_only_copy_and_rejects_update(self) -> None:
        key = "synthetic-legacy-key-9257"
        self._legacy(key)
        original = self._stored()
        with patch("atlas.llm_credentials.protect_secret", return_value=None):
            public = self._request("GET")
            self.assertTrue(public["migration_pending"])
            self.assertTrue(public["configured"]["gemini"])
            self.assertNotIn(key, json.dumps(public))
            with self.assertRaisesRegex(ValueError, "Protected credential storage"):
                self._request("POST", {"provider": "ollama"})
        self.assertEqual(self._stored(), original)

    @unittest.skipUnless(protection_available(), "Windows user protection unavailable")
    def test_save_merge_remove_and_locked_user(self) -> None:
        gemini = "synthetic-gemini-6631"
        groq = "synthetic-groq-9407"
        saved = self._request("POST", {"provider": "gemini", "keys": {"gemini": gemini}})
        self.assertNotIn(gemini, json.dumps(saved))
        self._request("POST", {"provider": "groq", "keys": {"groq": groq}})
        self.assertNotIn(gemini, self._stored())
        self.assertNotIn(groq, self._stored())
        with self.db.connect() as conn:
            resolved = read_llm_config(conn)
            self.assertEqual(resolved["keys"]["gemini"], gemini)
            self.assertEqual(resolved["keys"]["groq"], groq)
        locked = self._stored().replace("dpapi:", "dpapi:invalid-", 1)
        with self.db.connect() as conn:
            conn.execute("UPDATE app_settings SET value=? WHERE key='llm_config'", (locked,))
        public = self._request("GET")
        self.assertFalse(public["configured"]["gemini"])
        self.assertTrue(public["locked"]["gemini"])
        self.assertEqual(public["key_hints"]["gemini"], "")
        self._request("POST", {"remove": ["gemini"]})
        self.assertFalse(self._request("GET")["configured"]["gemini"])
        self.assertTrue(self._request("GET")["configured"]["groq"])

    @unittest.skipUnless(protection_available(), "Windows user protection unavailable")
    def test_short_key_is_never_returned_as_hint(self) -> None:
        self._request("POST", {"keys": {"gemini": "abc"}})
        public = self._request("GET")
        self.assertTrue(public["configured"]["gemini"])
        self.assertEqual(public["key_hints"]["gemini"], "••••")
        self.assertNotIn("abc", json.dumps(public))

    @unittest.skipUnless(protection_available(), "Windows user protection unavailable")
    def test_cloud_and_backup_require_separate_consent(self) -> None:
        self._request("POST", {"provider": "gemini",
                               "keys": {"gemini": "synthetic-primary-7194",
                                        "groq": "synthetic-backup-6275"}})
        with self.db.connect() as conn:
            self.assertEqual(resolve_report_model(conn)[2], "")
        public = self._request("POST", {"cloud_consent": True})
        self.assertTrue(public["cloud_consent"])
        self.assertFalse(public["cloud_failover_consent"])
        with self.db.connect() as conn:
            provider, model, key = resolve_report_model(conn)
            self.assertEqual(key, "synthetic-primary-7194")
            self.assertEqual(len(_cloud_provider_plan(conn, provider, model, key)), 1)
        self._request("POST", {"cloud_failover_consent": True})
        with self.db.connect() as conn:
            provider, model, key = resolve_report_model(conn)
            self.assertEqual(len(_cloud_provider_plan(conn, provider, model, key)), 2)
        public = self._request("POST", {"cloud_consent": False})
        self.assertFalse(public["cloud_failover_consent"])
        with self.db.connect() as conn:
            self.assertEqual(resolve_report_model(conn)[2], "")

    @unittest.skipUnless(protection_available(), "Windows user protection unavailable")
    def test_unavailable_protection_never_saves_new_plaintext(self) -> None:
        with patch("atlas.llm_credentials.protect_secret", return_value=None):
            with self.assertRaisesRegex(ValueError, "Protected credential storage"):
                self._request("POST", {"provider": "gemini", "keys": {"gemini": "synthetic-new-key"}})
        self.assertEqual(self._stored(), "")

    def test_cloud_http_error_does_not_expose_key_in_error(self) -> None:
        key = "synthetic-url-secret-4816"
        def unauthorized(url: str, *args):
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO())
        with patch("atlas.commission._post_json", side_effect=unauthorized), \
             patch("atlas.commission.GEMINI_FALLBACK_MODELS", ("gemini-test",)):
            with self.assertRaises(ValueError) as caught:
                _cloud_report_payload("gemini", key, "gemini-test", "system", "prompt", {}, 5)
        self.assertIn("HTTP 401", str(caught.exception))
        self.assertNotIn(key, str(caught.exception))

    def test_controlled_cloud_failover_uses_second_provider(self) -> None:
        def provider_reply(url: str, *args):
            if "generativelanguage.googleapis.com" in url:
                raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO())
            return {"choices": [{"message": {"content": '{"summary":"ok"}'}}]}
        with patch("atlas.commission._post_json", side_effect=provider_reply), \
             patch("atlas.commission.GEMINI_FALLBACK_MODELS", ("gemini-test",)):
            report, provider, model = _cloud_report_with_failover(
                [("gemini", "gemini-test", "synthetic-primary-4408"),
                 ("groq", "groq-test", "synthetic-backup-7821")],
                "system", "prompt", {}, 5,
            )
        self.assertEqual(report, {"summary": "ok"})
        self.assertEqual((provider, model), ("groq", "groq-test"))

    def test_slow_request_log_omits_query_secret(self) -> None:
        handler = ApiHandler.__new__(ApiHandler)
        handler.server = SimpleNamespace(state=SimpleNamespace(database=self.db))
        handler.path = "/api/llm/config?key=synthetic-query-secret"
        responses: list[dict] = []
        handler._json = lambda value, *args: responses.append(value)
        with patch.object(ApiHandler, "_log_slow_request") as logged:
            handler.do_GET()
        self.assertEqual(len(responses), 1)
        self.assertEqual(logged.call_args.args[:2], ("GET", "/api/llm/config"))
