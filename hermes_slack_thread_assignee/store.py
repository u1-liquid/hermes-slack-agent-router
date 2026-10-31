"""Transactional local assignment registry, CAS audit and event snapshots."""

import json
import os
import sqlite3
import stat
from contextlib import closing, contextmanager
from pathlib import Path

from .policy import Decision, Event, Recipient, Thread


class StoreError(RuntimeError):
    pass


class Conflict(StoreError):
    pass


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class Store:
    def __init__(
        self,
        path: Path,
        database_id: str,
        registry_revision: str,
        participants: tuple[Recipient, ...],
        *,
        policy_revision="1",
    ):
        self.path = Path(path)
        self.participants = tuple(participants)
        self.policy_revision = policy_revision
        self.metadata = {
            "database_id": database_id,
            "registry_revision": registry_revision,
            "participants": sorted((p.as_dict() for p in participants), key=encode),
        }

    def _permissions(self, missing=False):
        if not self.path.is_absolute():
            raise StoreError("database path must be absolute")
        for path, directory in ((self.path.parent, True), (self.path, False)):
            try:
                info = path.lstat()
            except FileNotFoundError:
                if not directory and missing:
                    continue
                raise StoreError("database must be explicitly initialized") from None
            if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise StoreError("database and parent must be owner-only, owned, non-symlink paths")
            if directory != stat.S_ISDIR(info.st_mode) or (not directory and not stat.S_ISREG(info.st_mode)):
                raise StoreError("invalid storage path type")

    @contextmanager
    def _connect(self):
        self._permissions()
        db = None
        try:
            db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=0.1)
            if db.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise StoreError("unsupported schema; explicit migration required")
            row = db.execute("SELECT value FROM metadata WHERE key=?", ("identity",)).fetchone()
            if row is None or row[0] != encode(self.metadata):
                raise StoreError("database/registry identity mismatch")
            yield db
        except (sqlite3.Error, ValueError, TypeError) as exc:
            raise StoreError(str(exc)) from exc
        finally:
            if db is not None:
                db.close()

    def initialize(self, dry_run=False):
        self._permissions(missing=True)
        if self.path.exists():
            self.check()
            return {"initialized": False, "dry_run": dry_run}
        if dry_run:
            return {"initialized": False, "dry_run": True}
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        try:
            with closing(sqlite3.connect(self.path)) as db, db:
                db.executescript("""
                    CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE assignments (workspace TEXT, channel TEXT, root TEXT,
                        recipient TEXT, revision INTEGER NOT NULL,
                        PRIMARY KEY(workspace,channel,root));
                    CREATE TABLE audit (id INTEGER PRIMARY KEY, workspace TEXT, channel TEXT,
                        root TEXT, old_recipient TEXT, new_recipient TEXT, revision INTEGER, reason TEXT);
                    CREATE TABLE decisions (workspace TEXT, channel TEXT, root TEXT,
                        identity TEXT, provenance TEXT, evidence TEXT, recipients TEXT,
                        revision INTEGER, PRIMARY KEY(workspace,channel,root,identity,provenance));
                    PRAGMA user_version=1;
                """)
                db.execute("INSERT INTO metadata VALUES (?,?)", ("identity", encode(self.metadata)))
        except sqlite3.Error as exc:
            # Preserve failed initialization for explicit operator diagnosis; never reset it.
            raise StoreError(str(exc)) from exc
        return {"initialized": True, "dry_run": False}

    def check(self):
        with self._connect() as db:
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise StoreError("integrity check failed")
            return {"healthy": True, **self.metadata, "schema": 1, "middleware": "not checked by storage CLI"}

    @staticmethod
    def _show(db, key):
        row = db.execute(
            "SELECT recipient,revision FROM assignments WHERE workspace=? AND channel=? AND root=?",
            (key.workspace, key.channel, key.root),
        ).fetchone()
        if row is None:
            return None, 0
        if type(row[1]) is not int or row[1] < 1:
            raise StoreError("invalid persisted assignment revision")
        recipient = Recipient(**json.loads(row[0])) if row[0] is not None else None
        if recipient is not None and recipient.workspace != key.workspace:
            raise StoreError("persisted assignment workspace mismatch")
        return recipient, row[1]

    def show(self, key: Thread):
        with self._connect() as db:
            return self._show(db, key)

    def change(
        self, key: Thread, recipient: Recipient | None, expected_revision: int, reason: str, *, dry_run=False
    ):
        if recipient is not None and (
            recipient not in self.participants or recipient.workspace != key.workspace
        ):
            raise ValueError("recipient outside workspace registry")
        if not reason.strip() or len(reason) > 500 or expected_revision < 0:
            raise ValueError("reason and nonnegative revision required")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old, revision = self._show(db, key)
            if revision != expected_revision:
                raise Conflict("assignment revision changed")
            receipt = {
                "thread": vars(key),
                "old": old.as_dict() if old else None,
                "new": recipient.as_dict() if recipient else None,
                "revision": revision + 1,
                "dry_run": dry_run,
            }
            if dry_run:
                db.rollback()
                return receipt
            old_json = encode(old.as_dict()) if old else None
            new_json = encode(recipient.as_dict()) if recipient else None
            db.execute(
                "INSERT INTO assignments VALUES (?,?,?,?,?) ON CONFLICT(workspace,channel,root) "
                "DO UPDATE SET recipient=excluded.recipient,revision=excluded.revision",
                (key.workspace, key.channel, key.root, new_json, revision + 1),
            )
            db.execute(
                "INSERT INTO audit(workspace,channel,root,old_recipient,new_recipient,revision,reason) "
                "VALUES (?,?,?,?,?,?,?)",
                (key.workspace, key.channel, key.root, old_json, new_json, revision + 1, reason),
            )
            db.commit()
            return receipt

    def decide(self, event: Event, receiver: Recipient):
        if receiver not in self.participants or receiver.workspace != event.thread.workspace:
            return Decision("pass", "unverified receiver")
        if event.sender_kind != "human":
            return Decision("pass", "native sender policy")
        key = event.thread
        evidence = encode(
            {
                "sender": event.sender,
                "direct": event.direct,
                "registry": self.metadata,
                "policy": self.policy_revision,
            }
        )
        event_key = (key.workspace, key.channel, key.root, event.identity, event.provenance)
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                cached = db.execute(
                    "SELECT evidence,recipients,revision FROM decisions WHERE "
                    "workspace=? AND channel=? AND root=? AND identity=? AND provenance=?",
                    event_key,
                ).fetchone()
                if cached:
                    if cached[0] != evidence:
                        return Decision("pass", "event evidence mismatch")
                    selected, revision = json.loads(cached[1]), cached[2]
                    if not isinstance(selected, list) or type(revision) is not int or revision < 0:
                        raise StoreError("invalid persisted decision values")
                    for value in selected:
                        recipient = Recipient(**value)
                        if recipient not in self.participants or recipient.workspace != key.workspace:
                            raise StoreError("persisted decision outside registry")
                else:
                    main, revision = self._show(db, key)
                    known_direct = [
                        bot
                        for bot in event.direct
                        if any(p.workspace == key.workspace and p.bot_user == bot for p in self.participants)
                    ]
                    if known_direct:
                        selected = []
                        for bot in known_direct:
                            matches = [
                                p
                                for p in self.participants
                                if p.workspace == key.workspace and p.bot_user == bot
                            ]
                            if len(matches) > 1:
                                return Decision("pass", "ambiguous direct recipient")
                            selected.extend(p.as_dict() for p in matches)
                    else:
                        selected = [main.as_dict()] if main else []
                    db.execute(
                        "INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?)",
                        (*event_key, evidence, encode(selected), revision),
                    )
                    db.commit()
                return Decision(
                    "allow" if receiver.as_dict() in selected else "drop",
                    "captured recipient snapshot",
                    revision,
                )
        except StoreError as exc:
            return Decision("drop", "storage unavailable: " + str(exc))
