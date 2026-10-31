"""Shared source-bound semantic claims. Short transactions never enclose Jev I/O."""

import asyncio
import json
import time
from dataclasses import dataclass

from .jev import JevError
from .semantic import Plan, SemanticError, assemble, prepare
from .store import Conflict, StoreError, encode


@dataclass(frozen=True)
class Claim:
    status: str
    fence: int
    owner: bool = False


class PlanStore:
    def __init__(self, store):
        self.store = store

    def initialize(self, dry_run=False):
        """Explicit operator-only additive upgrade; no runtime repair or reset."""
        if dry_run:
            return
        with self.store._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS semantic_plans (
                workspace TEXT, channel TEXT, root TEXT, identity TEXT,
                binding TEXT NOT NULL, fence INTEGER NOT NULL, lease REAL NOT NULL,
                status TEXT NOT NULL, result TEXT,
                PRIMARY KEY(workspace,channel,root,identity))""")
            db.execute(
                "CREATE TABLE IF NOT EXISTS semantic_sources (binding TEXT PRIMARY KEY, snapshot TEXT NOT NULL)"
            )
            db.execute("""CREATE TABLE IF NOT EXISTS semantic_receipts (binding TEXT, recipient TEXT,
                state TEXT NOT NULL, PRIMARY KEY(binding,recipient))""")
            db.execute("""CREATE TABLE IF NOT EXISTS semantic_generations (binding TEXT, fence INTEGER,
                result TEXT NOT NULL, PRIMARY KEY(binding,fence))""")
            db.execute("""CREATE TABLE IF NOT EXISTS semantic_receipt_events (binding TEXT, recipient TEXT,
                state TEXT, PRIMARY KEY(binding,recipient,state))""")
            db.commit()

    @staticmethod
    def _key(source):
        return (source.thread.workspace, source.thread.channel, source.thread.root, source.identity)

    def claim(self, source, *, now=None, lease=2.5):
        now = time.time() if now is None else now
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            from dataclasses import asdict

            db.execute(
                "INSERT OR IGNORE INTO semantic_sources VALUES (?,?)",
                (source.binding, encode(asdict(source))),
            )
            row = db.execute(
                "SELECT binding,fence,lease,status FROM semantic_plans WHERE "
                "workspace=? AND channel=? AND root=? AND identity=?",
                self._key(source),
            ).fetchone()
            if row is not None:
                binding, fence, expiry, status = row
                if binding != source.binding:
                    plan = Plan(source.binding, "unresolved", "stale-evidence", source.text)
                    db.execute(
                        "UPDATE semantic_plans SET binding=?,fence=?,status='unresolved',result=? "
                        "WHERE workspace=? AND channel=? AND root=? AND identity=?",
                        (source.binding, fence + 1, encode(plan.as_dict()), *self._key(source)),
                    )
                    db.commit()
                    return Claim("unresolved", fence + 1)
                if status != "claimed" or expiry > now:
                    return Claim(status, fence)
                fence += 1
                db.execute(
                    "UPDATE semantic_plans SET fence=?,lease=? WHERE workspace=? AND channel=? "
                    "AND root=? AND identity=?",
                    (fence, now + lease, *self._key(source)),
                )
            else:
                fence = 1
                db.execute(
                    "INSERT INTO semantic_plans VALUES (?,?,?,?,?,?,?,'claimed',NULL)",
                    (*self._key(source), source.binding, fence, now + lease),
                )
            db.commit()
            return Claim("claimed", fence, True)

    def publish(self, source, fence, plan, *, deadline=None):
        if plan.binding != source.binding or plan.status not in ("ready", "unresolved"):
            raise StoreError("plan/source binding mismatch")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                self.store._show(db, source.thread) != (source.main, source.main_revision)
                or self.store.metadata["registry_revision"] != source.registry_revision
            ):
                plan = Plan(source.binding, "unresolved", "stale-main-or-registry", source.text)
            if deadline is not None and time.monotonic() >= deadline:
                plan = Plan(source.binding, "unresolved", "publication-deadline", source.text)
            updated = db.execute(
                "UPDATE semantic_plans SET status=?,result=? WHERE workspace=? "
                "AND channel=? AND root=? AND identity=? AND binding=? AND fence=? "
                "AND status='claimed'",
                (plan.status, encode(plan.as_dict()), *self._key(source), source.binding, fence),
            )
            if updated.rowcount != 1:
                raise Conflict("semantic claim fenced or already published")
            db.execute(
                "INSERT INTO semantic_generations VALUES (?,?,?)",
                (source.binding, fence, encode(plan.as_dict())),
            )
            db.commit()
            return plan

    def record(self, source, recipient, state):
        with self.store._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO semantic_receipt_events VALUES (?,?,?)",
                (source.binding, encode(recipient.as_dict()), state),
            )
            db.execute(
                "INSERT INTO semantic_receipts VALUES (?,?,?) ON CONFLICT(binding,recipient) "
                "DO UPDATE SET state=excluded.state",
                (source.binding, encode(recipient.as_dict()), state),
            )
            db.commit()

    def generation(self, binding):
        with self.store._connect() as db:
            row = db.execute(
                "SELECT result FROM semantic_generations WHERE binding=? ORDER BY fence DESC LIMIT 1",
                (binding,),
            ).fetchone()
            if row is None:
                raise StoreError("unknown retained generation")
            return Plan.from_dict(json.loads(row[0]))

    def read(self, source):
        with self.store._connect() as db:
            row = db.execute(
                "SELECT binding,status,result FROM semantic_plans WHERE workspace=? "
                "AND channel=? AND root=? AND identity=?",
                self._key(source),
            ).fetchone()
            if row is None or row[1] == "claimed":
                return None
            if row[0] != source.binding:
                raise StoreError("stale semantic evidence")
            try:
                plan = Plan.from_dict(json.loads(row[2]))
                if plan.reason == "content-purged" and plan.binding == source.binding:
                    return Plan(source.binding, "unresolved", "content-purged", source.text)
                if plan.binding != source.binding or plan.source != source.text or plan.status != row[1]:
                    raise ValueError("persisted semantic binding mismatch")
                if plan.status == "ready":
                    cursor = 0
                    for unit in plan.units:
                        if (
                            unit.start != cursor
                            or not cursor < unit.end <= len(source.text)
                            or any(r not in source.recipients for r in unit.recipients)
                            or any(r not in source.history for r in unit.references)
                        ):
                            raise ValueError("invalid persisted semantic unit")
                        cursor = unit.end
                    if cursor != len(source.text):
                        raise ValueError("persisted coverage gap")
                return plan
            except (ValueError, KeyError, TypeError) as exc:
                raise StoreError("invalid persisted semantic plan") from exc

    def inspect(self):
        """No content in routine status; explicit private database holds bounded source."""
        with self.store._connect() as db:
            result = []
            for row in db.execute(
                "SELECT workspace,channel,root,identity,binding,fence,status,result "
                "FROM semantic_plans ORDER BY workspace,channel,root,identity LIMIT 100"
            ):
                item = dict(
                    zip(("workspace", "channel", "root", "identity", "binding", "fence", "status"), row[:7])
                )
                item["reason"] = json.loads(row[7])["reason"] if row[7] else "claim-in-progress"
                item["native_receipts"] = [
                    state
                    for (state,) in db.execute(
                        "SELECT state FROM semantic_receipt_events WHERE binding=? LIMIT 20", (row[4],)
                    )
                ]
                result.append(item)
            return result

    def operate(self, operation, binding, expected_fence, *, quiescent, dry_run=True):
        if operation not in ("purge", "recover") or not quiescent:
            raise ValueError("explicit purge/recover and operator quiescence assertion required")
        if len(binding) != 64 or any(c not in "0123456789abcdef" for c in binding):
            raise ValueError("exact lowercase binding digest required")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT fence,lease,status,result FROM semantic_plans WHERE binding=?", (binding,)
            ).fetchone()
            if row is None or row[0] != expected_fence:
                raise Conflict("current binding/fence changed")
            if row[2] == "claimed" and row[1] > time.time():
                raise Conflict("active semantic claim cannot be changed")
            if operation == "recover" and (
                row[2] != "unresolved"
                or json.loads(row[3])["reason"] == "content-purged"
                or db.execute(
                    "SELECT 1 FROM semantic_generations WHERE binding=? "
                    "AND json_extract(result,'$.status')='ready' LIMIT 1",
                    (binding,),
                ).fetchone()
            ):
                raise ValueError("only retained unresolved, never accepted/purged work, is recoverable")
            receipt = {
                "operation": operation,
                "binding": binding,
                "expected_fence": expected_fence,
                "dry_run": dry_run,
                "operator_quiescence_asserted": True,
            }
            if dry_run:
                db.rollback()
                return receipt
            if operation == "recover":
                db.execute(
                    "UPDATE semantic_plans SET fence=fence+1,lease=0,status='claimed',result=NULL WHERE binding=?",
                    (binding,),
                )
            else:
                tombstone = Plan(binding, "unresolved", "content-purged", "")
                db.execute(
                    "UPDATE semantic_plans SET fence=fence+1,lease=0,status='unresolved',result=? WHERE binding=?",
                    (encode(tombstone.as_dict()), binding),
                )
                for table in (
                    "semantic_sources",
                    "semantic_generations",
                    "semantic_receipts",
                    "semantic_receipt_events",
                ):
                    db.execute(f"DELETE FROM {table} WHERE binding=?", (binding,))
            db.commit()
            return receipt

    async def resolve(self, source, client, budget=2.5):
        deadline = time.monotonic() + min(budget, 2.5)
        claim = await asyncio.to_thread(self.claim, source)
        if not claim.owner:
            # Bounded product synchronization only; contenders NEVER issue another Jev request.
            while time.monotonic() < deadline:
                result = await asyncio.to_thread(self.read, source)
                if result is not None:
                    return result
                await asyncio.sleep(min(0.01, max(0, deadline - time.monotonic())))
            return Plan(source.binding, "unresolved", "shared-claim-pending", source.text)
        try:
            async with asyncio.timeout(max(0, deadline - time.monotonic())):
                answers = await client.ask(prepare(source))
                plan = assemble(source, answers)
        except (JevError, SemanticError, TimeoutError) as exc:
            plan = Plan(source.binding, "unresolved", "classifier-failed: " + str(exc), source.text)
        except asyncio.CancelledError:
            plan = Plan(source.binding, "unresolved", "classifier-cancelled", source.text)
            await asyncio.shield(asyncio.to_thread(self.publish, source, claim.fence, plan))
            raise
        return await asyncio.to_thread(self.publish, source, claim.fence, plan, deadline=deadline)
