from __future__ import annotations

import sqlite3
import unittest

from atlas.secret_protection import protect_secret, unprotect_secret, protection_available
from atlas.commission import read_llm_config
from atlas.server_http import ApiHandler


class SecretProtectionTests(unittest.TestCase):
    def test_round_trip(self):
        if not protection_available():
            self.skipTest("DPAPI unavailable")
        secret = "synthetic-secret-1234"
        protected = protect_secret(secret)
        self.assertTrue(protected.startswith("dpapi:"))
        self.assertEqual(unprotect_secret(protected), secret)

    def test_read_llm_config_unprotects(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT)")
        protected = protect_secret("abc") if protection_available() else "abc"
        conn.execute("INSERT INTO app_settings VALUES ('llm_config', ?)",
                     (f'{{"provider":"gemini","model":"m","keys":{{"gemini":"{protected}"}}}}',))
        config = read_llm_config(conn)
        self.assertEqual(config["keys"]["gemini"], "abc" if protection_available() else "abc")
        conn.close()


if __name__ == "__main__":
    unittest.main()