# -*- coding: utf-8 -*-
"""SQLite/GeoPackage identifier quoting and injection-resistance tests."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from results_lifecycle import (  # noqa: E402
    count_rows_in_sqlite_table,
    quote_sqlite_identifier,
    sqlite_table_exists,
    validate_gpkg_sqlite,
)


class SqliteIdentifierSecurityTests(unittest.TestCase):
    def test_01_normal_table_name(self):
        self.assertEqual(quote_sqlite_identifier("Final_Suitable_Areas"), '"Final_Suitable_Areas"')

    def test_02_table_name_with_spaces(self):
        self.assertEqual(quote_sqlite_identifier("My Layer"), '"My Layer"')

    def test_03_embedded_double_quotes_escaped(self):
        self.assertEqual(quote_sqlite_identifier('a"b'), '"a""b"')

    def test_04_reject_empty_none_nul_control(self):
        with self.assertRaises(ValueError):
            quote_sqlite_identifier("")
        with self.assertRaises(ValueError):
            quote_sqlite_identifier(None)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            quote_sqlite_identifier("ab\x00c")
        with self.assertRaises(ValueError):
            quote_sqlite_identifier("ab\nc")

    def test_05_malicious_breakout_cannot_execute_extra_sql(self):
        """
        Classic breakout payloads must remain inside a single quoted identifier
        and must not create/drop tables when used only after existence checks.
        """
        payloads = [
            'x"; DROP TABLE victims;--',
            'x" OR 1=1 --',
            'x"); DELETE FROM sqlite_master;--',
            'a"; ATTACH DATABASE \'evil.db\' AS e;--',
        ]
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "t.sqlite")
            conn = sqlite3.connect(db)
            try:
                conn.execute('CREATE TABLE victims (id INTEGER)')
                conn.execute('INSERT INTO victims VALUES (1)')
                conn.commit()
                for payload in payloads:
                    quoted = quote_sqlite_identifier(payload)
                    self.assertTrue(quoted.startswith('"') and quoted.endswith('"'))
                    self.assertNotIn(payload, quoted)  # raw payload not unescaped
                    # Existence check (parameterized) must fail for non-existent names
                    self.assertFalse(sqlite_table_exists(conn, payload))
                    with self.assertRaises(ValueError):
                        count_rows_in_sqlite_table(conn, payload)
                # victims intact
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM victims").fetchone()[0], 1)
            finally:
                conn.close()

    def test_06_nonexistent_table_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "t.sqlite")
            conn = sqlite3.connect(db)
            try:
                conn.execute("CREATE TABLE real_layer (id INTEGER)")
                conn.commit()
                with self.assertRaises(ValueError):
                    count_rows_in_sqlite_table(conn, "missing_layer")
            finally:
                conn.close()

    def test_07_count_existing_table_with_space_and_quote(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "t.sqlite")
            conn = sqlite3.connect(db)
            try:
                conn.execute('CREATE TABLE "Weird ""Name""" (id INTEGER)')
                conn.execute('INSERT INTO "Weird ""Name""" VALUES (1), (2)')
                conn.commit()
                name = 'Weird "Name"'
                self.assertTrue(sqlite_table_exists(conn, name))
                self.assertEqual(count_rows_in_sqlite_table(conn, name), 2)
            finally:
                conn.close()

    def test_08_validate_gpkg_uses_safe_counter(self):
        """Minimal sqlite file shaped like a GPKG contents table."""
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "mini.gpkg")
            conn = sqlite3.connect(path)
            try:
                conn.execute(
                    "CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT, identifier TEXT)"
                )
                conn.execute(
                    "INSERT INTO gpkg_contents VALUES ('feats', 'features', 'feats')"
                )
                conn.execute("CREATE TABLE feats (id INTEGER, geom BLOB)")
                conn.execute("INSERT INTO feats VALUES (1, NULL), (2, NULL)")
                conn.commit()
            finally:
                conn.close()
            ok, err = validate_gpkg_sqlite(path, expected_layers=["feats"], min_features=2)
            self.assertTrue(ok, err)
            ok2, err2 = validate_gpkg_sqlite(path, expected_layers=["feats"], min_features=99)
            self.assertFalse(ok2)
            self.assertIn("feature count", err2)


class BestEffortExceptionTests(unittest.TestCase):
    def test_best_effort_ignore_never_raises(self):
        from results_lifecycle import best_effort_ignore

        best_effort_ignore(RuntimeError("boom"), "unit-test")
        best_effort_ignore(OSError(13, "denied"), "cleanup")


if __name__ == "__main__":
    unittest.main()
