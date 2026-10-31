"""Storage/identity boundaries using synthetic local-only fixtures."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from hermes_slack_thread_assignee.policy import Event, Recipient, Thread
from hermes_slack_thread_assignee.store import Store, StoreError


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "state.sqlite3"
        self.a = Recipient("TONE", "UBOT", "alpha")
        self.b = Recipient("TTWO", "UBOT", "alpha")
        self.c = Recipient("TONE", "UOTHER", "alpha")
        self.store = Store(self.path, "demo", "1", (self.a, self.b, self.c))
        self.store.initialize()
        self.key = Thread("TONE", "CONE", "100.001")
        self.other = Thread("TTWO", "CONE", "100.001")

    def test_workspace_receiver_thread_and_edit_boundaries(self):
        self.store.change(self.key, self.a, 0, "bootstrap")
        self.store.change(self.other, self.b, 0, "bootstrap")
        event = Event(self.key, "200.001", "UHUMAN")
        self.assertEqual(self.store.decide(event, self.a).action, "allow")
        self.assertEqual(self.store.decide(event, self.c).action, "drop")
        self.assertEqual(self.store.decide(event, self.b).action, "pass")
        self.assertEqual(self.store.decide(Event(self.other, "200.001", "UHUMAN"), self.b).action, "allow")
        self.assertEqual(
            self.store.decide(Event(Thread("TONE", "CONE", "101.001"), "200.001", "UHUMAN"), self.a).action,
            "drop",
        )
        edited = Event(self.key, "200.001:201.001", "UHUMAN", ("UOTHER",), provenance="edit")
        self.assertEqual(self.store.decide(edited, self.c).action, "allow")
        self.assertEqual(self.store.decide(event, self.a).action, "allow")
        fallback = Event(self.key, "200.001", "UHUMAN", provenance="file_shared")
        self.assertEqual(self.store.decide(fallback, self.a).action, "allow")

    def test_sender_and_ambiguous_registry(self):
        for kind in ("bot", "unknown", "self"):
            event = Event(self.key, "200.001", "UHUMAN", sender_kind=kind)
            self.assertEqual(self.store.decide(event, self.a).action, "pass")
        other = Recipient("TONE", "UBOT", "beta")
        ambiguous = Store(self.root / "ambiguous.sqlite3", "demo", "1", (self.a, other))
        ambiguous.initialize()
        event = Event(self.key, "200.001", "UHUMAN", ("UBOT",))
        self.assertEqual(ambiguous.decide(event, self.a).action, "pass")

    def test_parent_permissions_symlink_and_identity_mismatch(self):
        self.root.chmod(0o755)
        with self.assertRaises(StoreError):
            self.store.check()
        self.root.chmod(0o700)
        link = self.root / "linked.sqlite3"
        link.symlink_to(self.path)
        with self.assertRaises(StoreError):
            Store(link, "demo", "1", (self.a, self.b, self.c)).initialize()
        with self.assertRaises(StoreError):
            Store(self.path, "wrong", "1", (self.a, self.b, self.c)).check()

    def test_decisions_never_write_assignments_or_audit(self):
        for index in range(5):
            self.store.decide(Event(self.key, str(index), "UHUMAN", ("UBOT",)), self.a)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("select count(*) from assignments").fetchone()[0], 0)
            self.assertEqual(db.execute("select count(*) from audit").fetchone()[0], 0)
