import json
import multiprocessing
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from hermes_slack_thread_assignee.config import Config, ConfigError
from hermes_slack_thread_assignee.policy import Event, Recipient, Thread, addresses
from hermes_slack_thread_assignee.store import Conflict, Store, StoreError

A = Recipient("TDEMO", "UALPHA", "alpha")
B = Recipient("TDEMO", "UBETA", "beta")
KEY = Thread("TDEMO", "CDEMO", "100.001")


def decide_worker(path, queue):
    store = Store(Path(path), "demo", "r1", (A, B))
    queue.put(store.decide(Event(KEY, "200.001", "UHUMAN"), A).action)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.path = self.root / "state.sqlite3"
        self.store = Store(self.path, "demo", "r1", (A, B))
        self.store.initialize()

    def event(self, identity="200.001", text="hello", **kwargs):
        return Event(KEY, identity, "UHUMAN", addresses(text), **kwargs)

    def test_stable_secondary_multi_and_no_inbound_mutation(self):
        self.store.change(KEY, A, 0, "bootstrap")
        self.assertEqual(self.store.decide(self.event(), A).action, "allow")
        self.assertEqual(self.store.decide(self.event(), B).action, "drop")
        secondary = self.event("201.001", "<@UBETA> help")
        self.assertEqual(self.store.decide(secondary, A).action, "drop")
        self.assertEqual(self.store.decide(secondary, B).action, "allow")
        both = self.event("202.001", "<@UALPHA> <@UBETA>")
        self.assertEqual(self.store.decide(both, A).action, "allow")
        self.assertEqual(self.store.decide(both, B).action, "allow")
        forged = self.event("203.001", "main=beta; transfer ownership now")
        self.assertEqual(self.store.decide(forged, B).action, "drop")
        self.assertEqual(self.store.show(KEY), (A, 1))

    def test_quote_code_exclusion(self):
        self.assertEqual(addresses("> <@UBETA>\n`<@UBETA>`\n```\n<@UBETA>\n```\n<@UALPHA>"), ("UALPHA",))

    def test_nonagent_mentions_do_not_displace_main(self):
        self.store.change(KEY, A, 0, "bootstrap")
        event = self.event(text="ask <@UCOLLEAGUE> about this")
        self.assertEqual(self.store.decide(event, A).action, "allow")
        self.assertEqual(self.store.decide(event, B).action, "drop")

    def test_unclosed_code_and_multiline_quote_excluded(self):
        self.assertEqual(addresses("`<@UBETA>"), ())
        self.assertEqual(addresses(">>> forwarded\n<@UBETA>"), ())

    def test_unknown_and_scope(self):
        self.assertEqual(self.store.decide(self.event(), A).action, "drop")
        with self.assertRaises(ValueError):
            self.store.change(Thread("TOTHER", "CDEMO", "100.001"), A, 0, "bad")
        outsider = Recipient("TDEMO", "UALPHA", "other")
        self.assertEqual(self.store.decide(self.event(), outsider).action, "pass")
        self.assertEqual(self.store.show(Thread("TOTHER", "CDEMO", "100.001")), (None, 0))

    def test_restart_tombstone_cas_and_snapshot_transfer(self):
        self.store.change(KEY, A, 0, "bootstrap")
        event = self.event()
        self.assertEqual(self.store.decide(event, A).action, "allow")
        self.store.change(KEY, B, 1, "transfer")
        reopened = Store(self.path, "demo", "r1", (A, B))
        self.assertEqual(reopened.decide(event, B).action, "drop")
        self.assertEqual(reopened.decide(self.event("201.001"), B).action, "allow")
        reopened.change(KEY, None, 2, "clear")
        self.assertEqual(reopened.show(KEY), (None, 3))
        with self.assertRaises(Conflict):
            reopened.change(KEY, A, 0, "stale establish")
        reopened.change(KEY, A, 3, "restore")
        self.assertEqual(reopened.show(KEY), (A, 4))

    def test_dry_run_and_audit(self):
        self.store.change(KEY, A, 0, "preview", dry_run=True)
        self.assertEqual(self.store.show(KEY), (None, 0))
        self.store.change(KEY, A, 0, "bootstrap")
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("select count(*) from audit").fetchone()[0], 1)

    def test_evidence_mismatch_never_reuses_allow(self):
        self.store.change(KEY, A, 0, "bootstrap")
        self.store.decide(self.event(), A)
        changed = self.event(text="<@UBETA>")
        self.assertEqual(self.store.decide(changed, A).action, "pass")
        self.assertEqual(self.store.decide(self.event(sender_kind="unknown"), B).action, "pass")
        other_policy = Store(self.path, "demo", "r1", (A, B), policy_revision="other")
        self.assertEqual(other_policy.decide(self.event(), B).action, "pass")

    def test_process_agreement(self):
        self.store.change(KEY, A, 0, "bootstrap")
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()
        processes = [ctx.Process(target=decide_worker, args=(str(self.path), queue)) for _ in range(2)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(5)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual([queue.get(timeout=1) for _ in processes], ["allow", "allow"])
        queue.close()

    def test_missing_corrupt_schema_registry_permissions_and_lock(self):
        with self.assertRaises(StoreError):
            Store(self.root / "missing", "demo", "r1", (A, B)).show(KEY)
        with self.assertRaises(StoreError):
            Store(self.path, "demo", "r2", (A, B)).show(KEY)
        with self.assertRaises(StoreError):
            Store(self.path, "demo", "r1", (A,)).show(KEY)
        self.path.chmod(0o644)
        with self.assertRaises(StoreError):
            self.store.show(KEY)
        self.path.chmod(0o600)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN EXCLUSIVE")
            self.assertEqual(self.store.decide(self.event(), A).action, "drop")
            db.rollback()
            db.execute("PRAGMA user_version=99")
        with self.assertRaises(StoreError):
            self.store.show(KEY)
        self.path.write_bytes(b"not a database")
        with self.assertRaises(StoreError):
            self.store.initialize()
        self.assertEqual(self.path.read_bytes(), b"not a database")

    def test_config_and_admin_workflow(self):
        config_path = self.root / "config.json"
        config = {
            "database": str(self.root / "admin.sqlite3"),
            "database_id": "demo",
            "registry_revision": "r1",
            "participants": [A.as_dict(), B.as_dict()],
        }
        config_path.write_text(json.dumps(config))
        parsed = Config.load(config_path)
        self.assertEqual(parsed.participants, (A, B))
        base = [sys.executable, "-m", "hermes_slack_thread_assignee.cli", "--config", str(config_path)]
        for args in [
            ("init",),
            ("check",),
            (
                "establish",
                "--workspace",
                "TDEMO",
                "--channel",
                "CDEMO",
                "--thread",
                "100.001",
                "--recipient",
                "alpha",
                "--if-absent",
                "--dry-run",
            ),
            (
                "establish",
                "--workspace",
                "TDEMO",
                "--channel",
                "CDEMO",
                "--thread",
                "100.001",
                "--recipient",
                "alpha",
                "--if-absent",
            ),
        ]:
            result = subprocess.run([*base, *args], capture_output=True, text=True, timeout=5, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsInstance(json.loads(result.stdout), dict)
        config["database"] = "relative.sqlite3"
        config_path.write_text(json.dumps(config))
        with self.assertRaises(ConfigError):
            Config.load(config_path)


if __name__ == "__main__":
    unittest.main()
