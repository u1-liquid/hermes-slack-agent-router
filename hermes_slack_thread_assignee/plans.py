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

            retained = db.execute(
                "SELECT fence,result FROM semantic_generations WHERE binding=? ORDER BY fence DESC LIMIT 1",
                (source.binding,),
            ).fetchone()
            recovering = db.execute(
                "SELECT 1 FROM semantic_plans WHERE binding=? AND status='claimed' AND fence>?",
                (source.binding, retained[0] if retained else 0),
            ).fetchone()
            if retained and not recovering:
                return Claim(json.loads(retained[1])["status"], retained[0])
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
                    db.execute(
                        "INSERT OR IGNORE INTO semantic_generations SELECT binding,fence,result "
                        "FROM semantic_plans WHERE workspace=? AND channel=? AND root=? AND identity=? "
                        "AND result IS NOT NULL",
                        self._key(source),
                    )
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
            retained = db.execute(
                "SELECT result,fence FROM semantic_generations WHERE binding=? ORDER BY fence DESC LIMIT 1",
                (source.binding,),
            ).fetchone()
            row = db.execute(
                "SELECT binding,status,result FROM semantic_plans WHERE workspace=? "
                "AND channel=? AND root=? AND identity=?",
                self._key(source),
            ).fetchone()
            recovering = db.execute(
                "SELECT 1 FROM semantic_plans WHERE binding=? AND status='claimed' AND fence>?",
                (source.binding, retained[1] if retained else 0),
            ).fetchone()
            if retained and not recovering:
                row = (source.binding, json.loads(retained[0])["status"], retained[0])
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

    def prior_topic(self, thread, identity, sender, text, before=None):
        """Recover only exact retained reference links in this conversation."""
        with self.store._connect() as db:
            rows = db.execute(
                "SELECT g.result FROM semantic_generations g JOIN semantic_sources s USING(binding) "
                "WHERE json_extract(s.snapshot,'$.thread.workspace')=? "
                "AND json_extract(s.snapshot,'$.thread.channel')=? "
                "AND json_extract(s.snapshot,'$.thread.root')=? "
                "AND json_extract(g.result,'$.status')='ready' "
                "AND (? IS NULL OR CAST(json_extract(s.snapshot,'$.identity') AS REAL)<CAST(? AS REAL)) LIMIT 100",
                (thread.workspace, thread.channel, thread.root, before, before),
            )
            topics = {
                unit.topic
                for (raw,) in rows
                for unit in Plan.from_dict(json.loads(raw)).units
                for ref in unit.references
                if (ref.identity, ref.sender, ref.text) == (identity, sender, text)
            }
            return next(iter(topics)) if len(topics) == 1 else "prior-" + identity

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
            for binding, fence, raw in db.execute(
                "SELECT g.binding,g.fence,g.result FROM semantic_generations g "
                "WHERE NOT EXISTS (SELECT 1 FROM semantic_plans p WHERE p.binding=g.binding) "
                "AND g.fence=(SELECT max(h.fence) FROM semantic_generations h WHERE h.binding=g.binding) "
                "ORDER BY g.binding LIMIT ?",
                (100 - len(result),),
            ):
                plan = json.loads(raw)
                result.append(
                    {
                        "binding": binding,
                        "fence": fence,
                        "status": plan["status"],
                        "reason": plan["reason"],
                        "archived": True,
                        "native_receipts": [],
                    }
                )
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
            archived = row is None
            if archived:
                generation = db.execute(
                    "SELECT fence,result FROM semantic_generations WHERE binding=? ORDER BY fence DESC LIMIT 1",
                    (binding,),
                ).fetchone()
                if generation:
                    row = (generation[0], 0, json.loads(generation[1])["status"], generation[1])
                live = db.execute(
                    "SELECT 1 FROM semantic_plans p JOIN semantic_sources s ON s.binding=? "
                    "WHERE p.workspace=json_extract(s.snapshot,'$.thread.workspace') "
                    "AND p.channel=json_extract(s.snapshot,'$.thread.channel') "
                    "AND p.root=json_extract(s.snapshot,'$.thread.root') "
                    "AND p.identity=json_extract(s.snapshot,'$.identity') "
                    "AND p.status='claimed' AND p.lease>?",
                    (binding, time.time()),
                ).fetchone()
                if live:
                    raise Conflict("active semantic claim cannot be changed")
            if row is None or row[0] != expected_fence:
                raise Conflict("current binding/fence changed")
            if row[2] == "claimed" and row[1] > time.time():
                raise Conflict("active semantic claim cannot be changed")
            if operation == "recover" and (
                archived
                or row[2] != "unresolved"
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
                db.execute(
                    "INSERT INTO semantic_generations VALUES (?,?,?)",
                    (binding, expected_fence + 1, encode(tombstone.as_dict())),
                )
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
