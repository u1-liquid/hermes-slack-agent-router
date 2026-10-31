"""Malformed persisted values must fail as storage faults, never reset state."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from hermes_slack_thread_assignee.policy import Event, Recipient, Thread
from hermes_slack_thread_assignee.store import Store, StoreError


class CorruptRows(unittest.TestCase):
    def test_invalid_assignment_json_is_a_store_fault_not_an_exception_leak(self):
        for broken in ("[]", "{broken", "null", "1", "{}"):
            with self.subTest(value=broken), tempfile.TemporaryDirectory() as root:
                a = Recipient("TDEMO", "UBOT", "default")
                store = Store(Path(root) / "db", "demo", "1", (a,))
                store.initialize()
                key = Thread("TDEMO", "CDEMO", "100.001")
                store.change(key, a, 0, "bootstrap")
                with closing(sqlite3.connect(store.path)) as db, db:
                    db.execute("update assignments set recipient=?", (broken,))
                with self.assertRaises(StoreError):
                    store.show(key)
                self.assertEqual(store.decide(Event(key, "200.001", "UHUMAN"), a).action, "drop")
                with closing(sqlite3.connect(store.path)) as db:
                    self.assertEqual(db.execute("select recipient from assignments").fetchone()[0], broken)

    def test_corrupt_cached_recipient_list_cannot_allow(self):
        with tempfile.TemporaryDirectory() as root:
            a = Recipient("TDEMO", "UBOT", "default")
            store = Store(Path(root) / "db", "demo", "1", (a,))
            store.initialize()
            key = Thread("TDEMO", "CDEMO", "100.001")
            event = Event(key, "200.001", "UHUMAN")
            store.change(key, a, 0, "bootstrap")
            self.assertEqual(store.decide(event, a).action, "allow")
            for broken in ("{broken", "{}", "[1]", "null"):
                with closing(sqlite3.connect(store.path)) as db, db:
                    db.execute("update decisions set recipients=?", (broken,))
                with self.subTest(value=broken):
                    result = store.decide(event, a)
                    self.assertEqual(result.action, "drop")
                    self.assertIn("storage unavailable", result.reason)
