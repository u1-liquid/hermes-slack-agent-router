"""Deterministic protocol/semantic controls; native canary is explicitly opt-in."""

import asyncio
import io
import json
import multiprocessing
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from hermes_slack_thread_assignee.config import Config, ConfigError
from hermes_slack_thread_assignee.jev import JevClient, JevError, validate_answers
from hermes_slack_thread_assignee.plans import PlanStore
from hermes_slack_thread_assignee.policy import Recipient, Thread
from hermes_slack_thread_assignee.semantic import History, Snapshot, assemble, prepare
from hermes_slack_thread_assignee.store import Conflict, Store, StoreError

A = Recipient("TFICTION", "UATLAS", "atlas")
B = Recipient("TFICTION", "UBIRCH", "birch")
KEY = Thread("TFICTION", "CFICTION", "1.0")


def snapshot(text="Atlas, revise the summary; Birch, check the diagram."):
    return Snapshot(
        KEY,
        "3.0",
        "UFABLE",
        text,
        (
            History("1.0", "UATLAS", "Atlas prepared the summary.", "summary"),
            History("2.0", "UBIRCH", "Birch prepared the diagram.", "diagram"),
        ),
        (A, B),
        "r1",
        "public-fiction-v1",
        1,
        A,
    )


def controlled_answers(batch, choices):
    result = {}
    for name, question in batch["questions"].items():
        choice = choices.get(name, "no")
        result[name] = {
            "type": "choice",
            "choice": choice,
            "probabilities": {key: float(key == choice) for key in question["criteria"]},
            "confidence": 1.0,
        }
    return {"answers": result}


def two_topic_answers(batch):
    return controlled_answers(
        batch,
        {
            "coverage": "complete",
            "u0_kind": "action",
            "u1_kind": "action",
            "u0_destination": "specific",
            "u1_destination": "specific",
            "u0_person": "p0",
            "u1_person": "p1",
            "u0_ref0": "yes",
            "u1_ref1": "yes",
            "u0_to0": "yes",
            "u1_to1": "yes",
        },
    )


def semantic_process_worker(path, barrier, counter, queue):
    store = Store(Path(path), "fiction", "r1", (A, B))

    class Client:
        async def ask(self, batch):
            with counter.get_lock():
                counter.value += 1
            return validate_answers(batch, two_topic_answers(batch))

    barrier.wait(timeout=5)
    plan = asyncio.run(PlanStore(store).resolve(snapshot(), Client()))
    queue.put((plan.status, plan.binding))


class SemanticTests(unittest.TestCase):
    def test_current_group_reconciles_actual_prior_topics_not_provisional_labels(self):
        source = replace(
            snapshot("Atlas, add the legend; Birch, add the arrows."),
            history=(
                History("1.0", "UATLAS", "Legend proposal", "prior-1.0"),
                History("2.0", "UBIRCH", "Arrows proposal", "prior-2.0"),
            ),
        )
        batch = prepare(source)
        answers = validate_answers(batch, two_topic_answers(batch))
        answers["same0_1"] = "yes"
        plan = assemble(source, answers)
        self.assertEqual(plan.status, "ready", plan.reason)
        self.assertEqual(plan.units[0].topic, plan.units[1].topic)
        self.assertEqual(tuple(u.people for u in plan.units), (("UATLAS",), ("UBIRCH",)))
        self.assertNotIn("add the arrows", plan.view(A))
        self.assertNotIn("add the legend", plan.view(B))
        known = replace(source, history=tuple(replace(h, topic="diagram") for h in source.history))
        self.assertEqual({u.topic for u in assemble(known, answers).units}, {"diagram"})
        conflicting = replace(known, history=(known.history[0], replace(known.history[1], topic="summary")))
        self.assertEqual(assemble(conflicting, answers).status, "unresolved")
        answers["same0_1"] = "unknown"
        self.assertEqual(assemble(source, answers).status, "unresolved")

    def test_fallback_topic_namespaces_source_identity_and_group_stably(self):
        source = replace(snapshot(), history=(), original={"type": "message", "text": snapshot().text})
        answers = validate_answers(prepare(source), two_topic_answers(prepare(source)))
        original = assemble(source, answers)
        self.assertEqual(original.status, "ready")
        self.assertNotEqual(original.units[0].topic, original.units[1].topic)
        retry = replace(
            source,
            policy_revision="same-content-new-policy",
            original={"type": "app_mention", "text": source.text},
        )
        self.assertEqual([u.topic for u in original.units], [u.topic for u in assemble(retry, answers).units])
        distinct = assemble(replace(source, identity="4.0"), answers)
        self.assertTrue({u.topic for u in original.units}.isdisjoint(u.topic for u in distinct.units))

    def test_nontransitive_current_topic_group_stays_unresolved(self):
        source = replace(snapshot("Atlas, add legend; Birch, add arrows; Atlas, review legend."), history=())
        batch = prepare(source)
        answers = validate_answers(
            batch,
            controlled_answers(
                batch,
                {
                    "coverage": "complete",
                    "u0_kind": "action",
                    "u1_kind": "action",
                    "u2_kind": "action",
                    "u0_destination": "specific",
                    "u1_destination": "specific",
                    "u2_destination": "specific",
                    "u0_to0": "yes",
                    "u1_to1": "yes",
                    "u2_to0": "yes",
                    "same0_1": "yes",
                    "same1_2": "yes",
                    "same0_2": "no",
                },
            ),
        )
        self.assertEqual(assemble(source, answers).reason, "nontransitive current-topic relation")

    def test_archived_purge_fence_live_claim_pointer_and_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            store = Store(root / "state.db", "fiction", "r1", (A, B))
            store.initialize()
            store.change(KEY, A, 0, "fiction bootstrap")
            plans = PlanStore(store)
            plans.initialize()
            source = snapshot()
            claim = plans.claim(source)
            plan = assemble(source, validate_answers(prepare(source), two_topic_answers(prepare(source))))
            plans.publish(source, claim.fence, plan)
            changed = replace(source, policy_revision="changed")
            pending = plans.claim(changed)
            before = plans.inspect()[0]
            self.assertTrue(next(r for r in plans.inspect() if r["binding"] == source.binding)["archived"])
            with self.assertRaises(Conflict):
                plans.operate("purge", source.binding, 99, quiescent=True)
            plans.operate("recover", changed.binding, pending.fence, quiescent=True, dry_run=False)
            live = plans.claim(changed)
            with self.assertRaises(Conflict):
                plans.operate("purge", source.binding, claim.fence, quiescent=True, dry_run=False)
            plans.publish(changed, live.fence, replace(plan, binding=changed.binding))
            current = plans.inspect()[0]
            plans.operate("purge", source.binding, claim.fence, quiescent=True, dry_run=False)
            self.assertEqual(plans.inspect()[0], current)
            self.assertEqual(before["binding"], current["binding"])
            self.assertFalse(plans.claim(source).owner)
            self.assertEqual(plans.read(source).reason, "content-purged")
            with self.assertRaises(StoreError):
                plans.operate("recover", source.binding, claim.fence + 1, quiescent=True, dry_run=False)
            with store._connect() as db:
                self.assertIsNone(
                    db.execute(
                        "SELECT snapshot FROM semantic_sources WHERE binding=?", (source.binding,)
                    ).fetchone()
                )
                self.assertEqual(db.execute("SELECT count(*) FROM audit").fetchone()[0], 1)
            self.assertEqual(store.show(KEY), (A, 1))

    def test_real_process_agreement_and_immutable_history_after_invalidation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            store = Store(root / "state.db", "fiction", "r1", (A, B))
            store.initialize()
            store.change(KEY, A, 0, "fiction bootstrap")
            plans = PlanStore(store)
            plans.initialize()
            ctx = multiprocessing.get_context("spawn")
            barrier, counter, queue = ctx.Barrier(3), ctx.Value("i", 0), ctx.Queue()
            workers = [
                ctx.Process(target=semantic_process_worker, args=(str(store.path), barrier, counter, queue))
                for _ in range(2)
            ]
            for worker in workers:
                worker.start()
            barrier.wait(timeout=5)
            for worker in workers:
                worker.join(5)
                self.assertEqual(worker.exitcode, 0)
            self.assertEqual([queue.get(timeout=1) for _ in workers], [("ready", snapshot().binding)] * 2)
            self.assertEqual(counter.value, 1)
            queue.close()
            original = plans.read(snapshot())
            plans.record(snapshot(), A, "selected-projected-not-delivery")
            stale = replace(snapshot(), policy_revision="changed")
            self.assertEqual(plans.claim(stale).status, "unresolved")
            self.assertEqual(plans.generation(snapshot().binding).as_dict(), original.as_dict())
            canonical = replace(snapshot(), original={"type": "message", "text": snapshot().text})
            duplicate = replace(canonical, original={"type": "app_mention", "text": snapshot().text})
            self.assertEqual(canonical.binding, duplicate.binding)

    def test_mixed_rich_reference_and_action_is_not_discarded_as_quote(self):
        from hermes_slack_thread_assignee.bridge import canonical_text
        from hermes_slack_thread_assignee.semantic import SemanticError

        event = {
            "blocks": [
                {
                    "type": "rich_text",
                    "elements": [
                        {
                            "type": "rich_text_section",
                            "elements": [
                                {"type": "text", "text": "Atlas, fix "},
                                {"type": "text", "text": "diagram", "style": {"code": True}},
                                {"type": "text", "text": " now."},
                            ],
                        }
                    ],
                }
            ]
        }
        text, provenance = canonical_text(event)
        with self.assertRaisesRegex(SemanticError, "inseparable"):
            prepare(replace(snapshot(text), provenance=provenance))

    def test_canonical_provenance_roundtrip_uses_raw_scalar_not_rendered_length(self):
        from hermes_slack_thread_assignee.bridge import canonical_text

        source = {
            "blocks": [
                {
                    "type": "rich_text",
                    "elements": [
                        {
                            "type": "rich_text_section",
                            "elements": [
                                {"type": "user", "user_id": "UFICTION"},
                                {"type": "text", "text": "日本語"},
                            ],
                        },
                        {"type": "rich_text_section", "elements": [{"type": "emoji", "name": "wave"}]},
                    ],
                }
            ]
        }
        text, provenance = canonical_text(source)
        self.assertEqual(text, "<@UFICTION>日本語\n:wave:")
        user, authored, separator, emoji = provenance
        self.assertEqual((user["raw"], user["source_end"]), ("UFICTION", len("UFICTION")))
        self.assertEqual(user["mapping"], "slack-user")
        self.assertEqual(text[authored["start"] : authored["end"]], authored["raw"])
        self.assertIsNone(separator["field"])
        self.assertIsNone(separator["source_end"])
        self.assertEqual((emoji["raw"], emoji["source_end"]), ("wave", 4))

    def test_people_derive_as_set_from_selected_source_references(self):
        source = replace(
            snapshot("Atlas and Birch, jointly review the diagram."),
            history=(
                History("1.0", "UATLAS", "Atlas drafted the diagram.", "diagram"),
                History("2.0", "UBIRCH", "Birch annotated the diagram.", "diagram"),
            ),
        )
        batch = prepare(source)
        answer = controlled_answers(
            batch,
            {
                "coverage": "complete",
                "u0_kind": "action",
                "u0_destination": "specific",
                "u0_person": "p0",
                "u0_ref0": "yes",
                "u0_ref1": "yes",
                "u0_to0": "yes",
                "u0_to1": "yes",
            },
        )
        plan = assemble(source, validate_answers(batch, answer))
        self.assertEqual(plan.status, "ready")
        self.assertEqual(plan.units[0].people, ("UATLAS", "UBIRCH"))
        self.assertNotIn("u0_person", batch["questions"])

    def test_prior_mentions_are_reference_only_not_native_wake_tokens(self):
        source = snapshot("Please fix the diagram.")
        source = replace(
            source,
            history=(
                source.history[0],
                replace(source.history[1], text="<@UBIRCH> prepared the diagram; <!here> is quoted history."),
            ),
        )
        batch = prepare(source)
        answer = controlled_answers(
            batch,
            {
                "coverage": "complete",
                "u0_kind": "action",
                "u0_destination": "specific",
                "u0_person": "p1",
                "u0_ref1": "yes",
                "u0_to1": "yes",
            },
        )
        plan = assemble(source, validate_answers(batch, answer))
        self.assertEqual(plan.status, "ready")
        self.assertNotIn("<@", plan.view(B))
        self.assertNotIn("<!", plan.view(B))
        self.assertIn("<@UBIRCH>", plan.units[0].references[0].text)

    def test_current_units_share_topic_without_invented_ownership(self):
        source = replace(snapshot("Atlas, draft a diagram; Birch, review that diagram."), history=())
        batch = prepare(source)
        answer = controlled_answers(
            batch,
            {
                "coverage": "complete",
                "u0_kind": "action",
                "u1_kind": "action",
                "u0_destination": "specific",
                "u1_destination": "specific",
                "u0_person": "none",
                "u1_person": "none",
                "u0_to0": "yes",
                "u1_to1": "yes",
                "same0_1": "yes",
            },
        )
        plan = assemble(source, validate_answers(batch, answer))
        self.assertEqual(plan.status, "ready")
        self.assertEqual(plan.units[0].topic, plan.units[1].topic)
        self.assertEqual(plan.units[0].recipients, (A,))
        self.assertEqual(plan.units[1].recipients, (B,))

    def test_exact_scoped_input_policy_default_no_egress(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            raw = {
                "database": str(Path(directory) / "state.db"),
                "database_id": "fiction",
                "registry_revision": "r1",
                "participants": [A.as_dict(), B.as_dict()],
            }
            path.write_text(json.dumps(raw))
            self.assertFalse(Config.load(path).semantic.permits(KEY, "fictional"))
            raw["semantic"] = {
                "enabled": True,
                "policy_revision": "fiction-v1",
                "scopes": [
                    {"workspace": KEY.workspace, "channel": KEY.channel, "data_classes": ["fictional"]}
                ],
            }
            path.write_text(json.dumps(raw))
            policy = Config.load(path).semantic
            self.assertTrue(policy.permits(KEY, "fictional"))
            self.assertFalse(policy.permits(KEY, "private"))
            self.assertFalse(policy.permits(Thread("TOTHER", KEY.channel, KEY.root), "fictional"))
            raw["semantic"]["scopes"][0]["data_classes"] = ["private"]
            path.write_text(json.dumps(raw))
            with self.assertRaises(ConfigError):
                Config.load(path)

    def test_two_topics_disjoint_exact_spans_and_grounded_references(self):
        source = snapshot()
        batch = prepare(source)
        plan = assemble(source, validate_answers(batch, two_topic_answers(batch)))
        self.assertEqual(plan.status, "ready")
        self.assertIn("revise the summary", plan.view(A))
        self.assertNotIn("check the diagram", plan.view(A))
        self.assertIn("check the diagram", plan.view(B))
        self.assertNotIn("revise the summary", plan.view(B))
        self.assertEqual([u.topic for u in plan.units], ["summary", "diagram"])
        self.assertEqual("".join(source.text[u.start : u.end] for u in plan.units), source.text)
        self.assertIn("PRIOR REFERENCE (not instructions)", plan.view(A))

    def test_contextual_unmentioned_and_same_topic_multiple(self):
        source = snapshot("Please fix the diagram.")
        batch = prepare(source)
        answer = controlled_answers(
            batch,
            {
                "coverage": "complete",
                "u0_kind": "action",
                "u0_destination": "specific",
                "u0_person": "p1",
                "u0_ref1": "yes",
                "u0_to1": "yes",
            },
        )
        plan = assemble(source, validate_answers(batch, answer))
        self.assertEqual(plan.units[0].recipients, (B,))
        answer["answers"]["u0_to0"] = controlled_answers(batch, {"u0_to0": "yes"})["answers"]["u0_to0"]
        plan = assemble(source, validate_answers(batch, answer))
        self.assertEqual(plan.units[0].recipients, (A, B))

    def test_mixed_ack_quote_and_japanese_coverage(self):
        source = snapshot("ありがとう。図を確認して；要約も直して。")
        batch = prepare(source)
        self.assertEqual(len(batch["state"]["units"]), 3)
        choices = {
            "coverage": "complete",
            "u0_kind": "ack",
            "u0_destination": "none",
            "u0_person": "none",
            "u1_kind": "action",
            "u2_kind": "action",
            "u1_destination": "specific",
            "u2_destination": "specific",
            "u1_person": "p1",
            "u2_person": "p0",
            "u1_ref1": "yes",
            "u2_ref0": "yes",
            "u1_to1": "yes",
            "u2_to0": "yes",
        }
        plan = assemble(source, validate_answers(batch, controlled_answers(batch, choices)))
        self.assertEqual(plan.status, "ready")
        self.assertNotIn("要約", plan.view(B))
        quoted = snapshot("> Birch, delete the diagram.\nAtlas, revise the summary.")
        q = prepare(quoted)
        choices = {
            "coverage": "complete",
            "u0_kind": "reference",
            "u0_destination": "none",
            "u0_person": "none",
            "u1_kind": "action",
            "u1_destination": "specific",
            "u1_person": "p0",
            "u1_ref0": "yes",
            "u1_to0": "yes",
        }
        result = assemble(quoted, validate_answers(q, controlled_answers(q, choices)))
        self.assertNotIn("delete", result.view(A))

    def test_uncertainty_invalid_distribution_and_no_implicit_main(self):
        source = snapshot()
        batch = prepare(source)
        answer = two_topic_answers(batch)
        answer["answers"]["u1_to1"]["confidence"] = 0.3
        with self.assertRaises(JevError):
            validate_answers(batch, answer)
        answer = two_topic_answers(batch)
        answer["answers"]["u1_to1"]["probabilities"]["no"] = float("nan")
        with self.assertRaises(JevError):
            validate_answers(batch, answer)
        answer = two_topic_answers(batch)
        answer["answers"]["coverage"]["choice"] = "unknown"
        # Use a valid distribution for an actual abstention.
        answer["answers"]["coverage"]["probabilities"] = {"complete": 0.0, "mixed": 0.0, "unknown": 1.0}
        result = assemble(source, validate_answers(batch, answer))
        self.assertEqual(result.status, "unresolved")
        self.assertEqual(result.view(A), "")
        self.assertEqual(result.view(B), "")


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_oversized_request_does_not_launch_or_egress(self):
        with patch("asyncio.create_subprocess_exec") as spawn, self.assertRaisesRegex(JevError, "serialized"):
            await JevClient().ask({"state": "x" * 262145, "questions": {}})
        spawn.assert_not_awaited()

    async def test_operator_metadata_recovery_and_retention_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            store = Store(root / "state.db", "fiction", "r1", (A, B))
            store.initialize()
            store.change(KEY, A, 0, "fiction bootstrap")
            plans = PlanStore(store)
            plans.initialize()
            source = snapshot()
            client = AsyncMock()
            client.ask.side_effect = JevError("fictional outage")
            failed = await plans.resolve(source, client)
            metadata = plans.inspect()[0]
            self.assertEqual(metadata["reason"], failed.reason)
            self.assertNotIn(source.text, json.dumps(metadata))
            from hermes_slack_thread_assignee.cli import main

            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "database": str(store.path),
                        "database_id": "fiction",
                        "registry_revision": "r1",
                        "participants": [A.as_dict(), B.as_dict()],
                    }
                )
            )

            def cli(*args):
                with patch("sys.stdout", new_callable=io.StringIO) as output:
                    code = main(["--config", str(config_path), *args])
                    self.assertEqual(code, 0)
                    return json.loads(output.getvalue())

            self.assertEqual(cli("plans")["plans"][0]["binding"], source.binding)
            fence = metadata["fence"]
            with self.assertRaises(ValueError):
                plans.operate("recover", source.binding, fence, quiescent=False, dry_run=False)
            plans.operate("recover", source.binding, fence, quiescent=True, dry_run=True)
            for operation in ("recover", "purge"):
                self.assertTrue(
                    cli(
                        operation,
                        "--binding",
                        source.binding,
                        "--expected-fence",
                        str(fence),
                        "--quiescent",
                        "--dry-run",
                    )["dry_run"]
                )
            self.assertEqual(plans.read(source).reason, failed.reason)
            self.assertFalse(
                cli(
                    "recover",
                    "--binding",
                    source.binding,
                    "--expected-fence",
                    str(fence),
                    "--quiescent",
                    "--apply",
                )["dry_run"]
            )
            client.ask.side_effect = None
            client.ask.return_value = validate_answers(prepare(source), two_topic_answers(prepare(source)))
            recovered = await plans.resolve(source, client)
            self.assertEqual(recovered.status, "ready")
            metadata = plans.inspect()[0]
            with self.assertRaises(StoreError):
                plans.operate("recover", source.binding, metadata["fence"], quiescent=True, dry_run=False)
            cli(
                "purge",
                "--binding",
                source.binding,
                "--expected-fence",
                str(metadata["fence"]),
                "--quiescent",
                "--apply",
            )
            self.assertEqual(store.show(KEY), (A, 1))
            self.assertEqual(plans.inspect()[0]["reason"], "content-purged")
            client.reset_mock()
            self.assertEqual((await plans.resolve(source, client)).reason, "content-purged")
            client.ask.assert_not_awaited()
            with store._connect() as db:
                self.assertIsNone(
                    db.execute(
                        "SELECT snapshot FROM semantic_sources WHERE binding=?", (source.binding,)
                    ).fetchone()
                )
                self.assertEqual(db.execute("SELECT count(*) FROM audit").fetchone()[0], 1)

    async def test_true_native_cancellation_and_stream_caps(self):
        native = asyncio.create_subprocess_exec
        started = asyncio.Event()
        processes = []

        async def spawn(*args, **kwargs):
            process = await native("/usr/bin/tail", "-f", "/dev/null", **kwargs)
            processes.append(process)
            started.set()
            return process

        with patch("asyncio.create_subprocess_exec", side_effect=spawn):
            task = asyncio.create_task(JevClient().ask(prepare(snapshot())))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNotNone(processes[0].returncode)

        async def flood(*args, **kwargs):
            process = await native("/usr/bin/yes", **kwargs)
            processes.append(process)
            return process

        with (
            patch("asyncio.create_subprocess_exec", side_effect=flood),
            self.assertRaisesRegex(JevError, "oversized"),
        ):
            await JevClient().ask(prepare(snapshot()))
        self.assertIsNotNone(processes[-1].returncode)

    async def test_timeout_and_cancellation_reap_native_process(self):
        process = AsyncMock()
        process.kill = Mock()
        process.returncode = None
        process.stdin.write = Mock()
        process.stdin.close = Mock()
        process.stdout.read.side_effect = [TimeoutError(), b""]
        process.stderr.read.return_value = b""
        with patch("asyncio.create_subprocess_exec", return_value=process), self.assertRaises(JevError):
            await JevClient().ask(prepare(snapshot()))
        process.kill.assert_called_once()
        process.wait.assert_awaited_once()

    async def test_shared_claim_restart_stale_and_fencing_preserve_main(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            store = Store(root / "state.db", "fiction", "r1", (A, B))
            store.initialize()
            store.change(KEY, A, 0, "fiction bootstrap")
            plans = PlanStore(store)
            plans.initialize()
            source = snapshot()
            claim = plans.claim(source, now=10, lease=1)
            self.assertEqual(plans.claim(source, now=10, lease=1).status, "claimed")
            successor = PlanStore(store).claim(source, now=12, lease=1)
            plan = assemble(source, validate_answers(prepare(source), two_topic_answers(prepare(source))))
            with self.assertRaises(Conflict):
                plans.publish(source, claim.fence, plan)
            plans.publish(source, successor.fence, plan)
            self.assertEqual(PlanStore(store).read(source).view(B), plan.view(B))
            stale = plans.claim(replace(source, policy_revision="changed"), now=13)
            self.assertEqual(stale.status, "unresolved")
            self.assertEqual(store.show(KEY), (A, 1))
            self.assertEqual(plans.read(replace(source, policy_revision="changed")).status, "unresolved")

    async def test_one_classifier_for_concurrent_participants_and_failure_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            store = Store(root / "state.db", "fiction", "r1", (A, B))
            store.initialize()
            store.change(KEY, A, 0, "fiction bootstrap")
            plans = PlanStore(store)
            plans.initialize()
            client = AsyncMock()
            client.ask.return_value = validate_answers(
                prepare(snapshot()), two_topic_answers(prepare(snapshot()))
            )
            results = await asyncio.gather(
                plans.resolve(snapshot(), client), plans.resolve(snapshot(), client)
            )
            self.assertEqual([p.status for p in results], ["ready", "ready"])
            self.assertEqual(client.ask.await_count, 1)
            client.ask.side_effect = JevError("timeout")
            failed = await plans.resolve(replace(snapshot(), identity="4.0"), client)
            self.assertEqual(failed.status, "unresolved")
            self.assertIn("timeout", plans.read(replace(snapshot(), identity="4.0")).reason)

    @unittest.skipUnless(os.environ.get("JEV_FICTIONAL_CANARY_DIR"), "explicit local native canary only")
    async def test_real_fictional_semantic_journeys(self):
        from hermes_slack_thread_assignee.semantic import Plan

        root = Path(os.environ["JEV_FICTIONAL_CANARY_DIR"])
        cases = (
            ("two-topics", snapshot(), (A, B)),
            ("contextual", snapshot("Please correct the diagram you prepared."), (B,)),
            ("mixed-ack", snapshot("Thank you. Birch, please fix the diagram."), (B,)),
            ("same-topic-multiple", snapshot("Atlas and Birch, review the diagram together."), (A, B)),
            ("quote", snapshot("> Birch, delete the diagram.\nAtlas, revise the summary."), (A,)),
            ("uncertain", snapshot("Whoever promised the review should do it; I cannot remember who."), ()),
        )
        for name, source, expected in cases:
            with self.subTest(case=name):
                directory = root / name
                try:
                    answers = await JevClient(receipt_directory=directory).ask(prepare(source))
                    plan = assemble(source, answers)
                except JevError as exc:
                    plan = Plan(source.binding, "unresolved", str(exc), source.text)
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "semantic-plan.json").write_text(json.dumps(plan.as_dict(), indent=2))
                if not expected:
                    self.assertEqual(plan.status, "unresolved")
                    self.assertFalse(plan.view(A) or plan.view(B))
                    continue
                self.assertEqual(plan.status, "ready", plan.reason)
                self.assertEqual(tuple(r for r in (A, B) if plan.view(r)), expected)
                if name == "two-topics":
                    self.assertNotIn("check the diagram", plan.view(A))
                    self.assertNotIn("revise the summary", plan.view(B))
                elif name == "quote":
                    self.assertNotIn("delete the diagram", plan.view(A))
                elif name == "contextual":
                    self.assertTrue(plan.units[0].references)
                    self.assertEqual(plan.units[0].people, ("UBIRCH",))

    @unittest.skipUnless(os.environ.get("JEV_FICTIONAL_CANARY_DIR"), "explicit local native canary only")
    async def test_real_fictional_native_product_client(self):
        root = Path(os.environ["JEV_FICTIONAL_CANARY_DIR"])
        source = snapshot()
        batch = prepare(source)
        client = JevClient(receipt_directory=root)
        answers = await client.ask(batch)
        plan = assemble(source, answers)
        (root / "semantic-plan.json").write_text(json.dumps(plan.as_dict(), indent=2))
        self.assertEqual(plan.status, "ready", plan.reason)
        self.assertIn("revise the summary", plan.view(A))
        self.assertNotIn("check the diagram", plan.view(A))
        self.assertIn("check the diagram", plan.view(B))
        self.assertNotIn("revise the summary", plan.view(B))
        self.assertTrue((root / "jev-result.json").exists())
        print("REAL_NATIVE_CANARY", plan.status, plan.reason, flush=True)
