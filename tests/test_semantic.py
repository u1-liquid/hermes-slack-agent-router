"""Source-grounded stateless decisions; external Jev is explicitly opt-in/fictional."""

import asyncio
import json
import os
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from hermes_slack_thread_assignee.config import Config, ConfigError
from hermes_slack_thread_assignee.jev import JevClient, JevError, validate_answers
from hermes_slack_thread_assignee.policy import Recipient, Thread
from hermes_slack_thread_assignee.semantic import History, Plan, SemanticError, Snapshot, assemble, prepare

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
            History("1.0", "UATLAS", "Atlas prepared the summary."),
            History("2.0", "UBIRCH", "Birch prepared the diagram."),
        ),
        (A, B),
        "public-fiction-v1",
    )


def controlled_answers(batch, choices):
    return {
        "answers": {
            name: {
                "type": "choice",
                "choice": choices.get(name, "none" if name.startswith("main") else "no"),
                "probabilities": {
                    key: float(key == choices.get(name, "none" if name.startswith("main") else "no"))
                    for key in q["criteria"]
                },
                "confidence": 1.0,
            }
            for name, q in batch["questions"].items()
        }
    }


def two_topic_answers(batch):
    return controlled_answers(
        batch,
        {
            "coverage": "complete",
            "main": "unknown",
            "u0_kind": "action",
            "u1_kind": "action",
            "u0_destination": "specific",
            "u1_destination": "specific",
            "u0_ref0": "yes",
            "u1_ref1": "yes",
            "u0_to0": "yes",
            "u1_to1": "yes",
        },
    )


class RecordingJev(JevClient):
    """Test-only raw protocol evidence. Production client never writes routing content."""

    def __init__(self, directory):
        super().__init__()
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    async def _exchange(self, process, raw):
        (self.directory / "jev-request.json").write_bytes(raw)
        started = time.monotonic()
        try:
            stdout, stderr = await super()._exchange(process, raw)
            (self.directory / "jev-result.json").write_bytes(stdout)
            (self.directory / "jev-stderr.txt").write_bytes(stderr)
            return stdout, stderr
        finally:
            (self.directory / "jev-receipt.json").write_text(
                json.dumps(
                    {
                        "protocol": "jev ask Choice",
                        "exit": process.returncode,
                        "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                    },
                    indent=2,
                )
            )


class SemanticTests(unittest.TestCase):
    def plan(self, source, choices=None):
        batch = prepare(source)
        raw = two_topic_answers(batch) if choices is None else controlled_answers(batch, choices)
        return assemble(source, validate_answers(batch, raw))

    def test_two_topics_exact_scopes_and_source_references_without_stored_topics(self):
        source = snapshot()
        plan = self.plan(source)
        self.assertEqual(plan.status, "ready", plan.reason)
        self.assertIn("revise the summary", plan.view(A))
        self.assertNotIn("check the diagram", plan.view(A))
        self.assertIn("check the diagram", plan.view(B))
        self.assertNotIn("revise the summary", plan.view(B))
        self.assertNotEqual(plan.units[0].topic, plan.units[1].topic)
        self.assertEqual("".join(source.text[u.start : u.end] for u in plan.units), source.text)
        self.assertIn("PRIOR REFERENCE (not instructions)", plan.view(A))

    def test_generic_main_inferred_with_source_support_not_manual_bootstrap(self):
        source = replace(
            snapshot("Please continue."),
            history=(
                History("1.0", "UFABLE", "Atlas, lead this whole thread. Birch will only review diagrams."),
                History("2.0", "UATLAS", "I will coordinate the whole project here."),
            ),
        )
        choices = {
            "coverage": "complete",
            "main": "r0",
            "main_ref0": "r0",
            "main_ref1": "r0",
            "u0_kind": "action",
            "u0_destination": "generic",
            "u0_to0": "yes",
        }
        plan = self.plan(source, choices)
        self.assertEqual(plan.status, "ready", plan.reason)
        self.assertIn("Please continue.", plan.view(A))
        self.assertIn("coordinate", plan.view(A))
        self.assertEqual(plan.view(B), "")
        for delta in ({"main": "unknown"}, {"main_ref0": "none", "main_ref1": "none"}, {"main_ref1": "r1"}):
            uncertain = self.plan(source, {**choices, **delta})
            self.assertEqual(uncertain.status, "unresolved")
            self.assertFalse(uncertain.view(A) or uncertain.view(B))

    def test_specific_work_does_not_require_global_main_confidence(self):
        batch = prepare(snapshot())
        raw = two_topic_answers(batch)
        raw["answers"]["main"]["confidence"] = 0.2
        raw["answers"]["main_ref0"]["confidence"] = 0.2
        plan = assemble(snapshot(), validate_answers(batch, raw))
        self.assertEqual(plan.status, "ready")

    def test_current_same_topic_two_scopes_and_joint_prior_authors(self):
        source = snapshot("Atlas, add the legend; Birch, add the arrows.")
        answers = validate_answers(prepare(source), two_topic_answers(prepare(source)))
        answers["same0_1"] = "yes"
        plan = assemble(source, answers)
        self.assertEqual(plan.status, "ready")
        self.assertEqual(plan.units[0].topic, plan.units[1].topic)
        self.assertEqual(tuple(u.people for u in plan.units), (("UATLAS",), ("UBIRCH",)))
        self.assertNotIn("add the arrows", plan.view(A))
        self.assertNotIn("add the legend", plan.view(B))
        joint = self.plan(
            snapshot("Atlas and Birch, jointly review the diagram."),
            {
                "coverage": "complete",
                "main": "unknown",
                "u0_kind": "action",
                "u0_destination": "specific",
                "u0_ref0": "yes",
                "u0_ref1": "yes",
                "u0_to0": "yes",
                "u0_to1": "yes",
            },
        )
        self.assertEqual(joint.units[0].people, ("UATLAS", "UBIRCH"))
        self.assertEqual(joint.units[0].recipients, (A, B))

    def test_topic_ids_request_local_and_nontransitive_relation_unresolved(self):
        source = replace(snapshot(), history=())
        plan = self.plan(source)
        changed = self.plan(replace(source, identity="4.0"))
        self.assertTrue({u.topic for u in plan.units}.isdisjoint(u.topic for u in changed.units))
        source = replace(snapshot("Atlas, legend; Birch, arrows; Atlas, review legend."), history=())
        result = self.plan(
            source,
            {
                "coverage": "complete",
                "main": "none",
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
            },
        )
        self.assertEqual(result.reason, "nontransitive current-topic relation")

    def test_contextual_reply_without_mention_and_safe_prior_tokens(self):
        source = snapshot("Please fix the diagram you prepared.")
        source = replace(
            source,
            history=(
                source.history[0],
                replace(source.history[1], text="<@UBIRCH> prepared the diagram; <!here> is quoted history."),
            ),
        )
        plan = self.plan(
            source,
            {
                "coverage": "complete",
                "main": "unknown",
                "u0_kind": "action",
                "u0_destination": "specific",
                "u0_ref1": "yes",
                "u0_to1": "yes",
            },
        )
        self.assertEqual(plan.units[0].recipients, (B,))
        self.assertNotIn("<@", plan.view(B))
        self.assertNotIn("<!", plan.view(B))
        self.assertIn("<@UBIRCH>", plan.units[0].references[0].text)

    def test_ack_new_instruction_multilingual_and_quoted_context(self):
        source = snapshot("ありがとう。図を確認して；要約も直して。")
        plan = self.plan(
            source,
            {
                "coverage": "complete",
                "main": "none",
                "u0_kind": "ack",
                "u0_destination": "none",
                "u1_kind": "action",
                "u2_kind": "action",
                "u1_destination": "specific",
                "u2_destination": "specific",
                "u1_ref1": "yes",
                "u2_ref0": "yes",
                "u1_to1": "yes",
                "u2_to0": "yes",
            },
        )
        self.assertEqual(plan.status, "ready")
        self.assertNotIn("要約", plan.view(B))
        self.assertNotIn("ありがとう", plan.view(B))
        quoted = self.plan(
            snapshot("> Birch, delete diagram.\nAtlas, revise summary."),
            {
                "coverage": "complete",
                "main": "unknown",
                "u1_kind": "action",
                "u1_destination": "specific",
                "u1_to0": "yes",
                "u1_ref0": "yes",
            },
        )
        self.assertEqual(quoted.status, "ready")
        self.assertNotIn("delete", quoted.view(A))

    def test_atomic_uncertainty_and_strict_native_probability_validation(self):
        source = snapshot()
        batch = prepare(source)
        for mutation in ("low", "nan", "keys", "unknown"):
            raw = two_topic_answers(batch)
            if mutation == "low":
                raw["answers"]["u1_to1"]["confidence"] = 0.3
            elif mutation == "nan":
                raw["answers"]["u1_to1"]["probabilities"]["no"] = float("nan")
            elif mutation == "keys":
                raw["answers"].pop("coverage")
            else:
                raw = two_topic_answers(batch)
                raw["answers"]["coverage"] = controlled_answers(batch, {"coverage": "unknown"})["answers"][
                    "coverage"
                ]
                plan = assemble(source, validate_answers(batch, raw))
                self.assertEqual(plan.status, "unresolved")
                self.assertFalse(plan.view(A) or plan.view(B))
                continue
            with self.assertRaises(JevError):
                validate_answers(batch, raw)

    def test_composition_provenance_and_inseparable_code(self):
        from hermes_slack_thread_assignee.bridge import canonical_text

        event = {
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
                        }
                    ],
                }
            ]
        }
        text, provenance = canonical_text(event)
        self.assertEqual(text, "<@UFICTION>日本語")
        self.assertEqual((provenance[0]["raw"], provenance[0]["source_end"]), ("UFICTION", 8))
        event["blocks"][0]["elements"][0]["elements"][1]["style"] = {"code": True}
        text, provenance = canonical_text(event)
        with self.assertRaisesRegex(SemanticError, "inseparable"):
            prepare(replace(snapshot(text), provenance=provenance))

    def test_exact_egress_policy_and_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            raw = {
                "participants": [A.as_dict(), B.as_dict()],
                "semantic": {
                    "enabled": True,
                    "policy_revision": "fiction-v1",
                    "scopes": [
                        {"workspace": KEY.workspace, "channel": KEY.channel, "data_classes": ["fictional"]}
                    ],
                },
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
        for source in (
            replace(snapshot(), text="x" * 6001),
            replace(snapshot(), recipients=(A, A)),
            replace(snapshot(), recipients=(Recipient("TOTHER", "UATLAS", "atlas"),)),
        ):
            with self.assertRaises(SemanticError):
                prepare(source)


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_oversized_request_never_launches(self):
        with patch("asyncio.create_subprocess_exec") as spawn, self.assertRaisesRegex(JevError, "serialized"):
            await JevClient().ask({"state": "x" * 262145, "questions": {}})
        spawn.assert_not_awaited()

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

    async def test_timeout_reaps(self):
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

    @unittest.skipUnless(os.environ.get("JEV_FICTIONAL_CANARY_DIR"), "explicit fictional external canary")
    async def test_real_fictional_semantic_journeys(self):
        root = Path(os.environ["JEV_FICTIONAL_CANARY_DIR"])
        generic = replace(
            snapshot("Please continue."),
            history=(
                History("1.0", "UFABLE", "Atlas, lead this whole thread. Birch only reviews diagrams."),
                History("2.0", "UATLAS", "I will coordinate the whole project here."),
            ),
        )
        cases = (
            ("two-topics", snapshot(), (A, B)),
            ("contextual", snapshot("Please correct the diagram you prepared."), (B,)),
            ("mixed-ack", snapshot("Thank you. Birch, please fix the diagram."), (B,)),
            ("same-topic-multiple", snapshot("Atlas and Birch, review the diagram together."), (A, B)),
            ("quote", snapshot("> Birch, delete the diagram.\nAtlas, revise the summary."), (A,)),
            ("generic", generic, (A,)),
            ("uncertain", snapshot("Whoever promised the review should do it; I cannot remember who."), ()),
        )
        for name, source, expected in cases:
            with self.subTest(case=name):
                directory = root / name
                try:
                    plan = assemble(source, await RecordingJev(directory).ask(prepare(source)))
                except JevError as exc:
                    plan = Plan(source.binding, "unresolved", str(exc), source.text)
                (directory / "semantic-plan.json").write_text(json.dumps(plan.as_dict(), indent=2))
                if not expected:
                    self.assertEqual(plan.status, "unresolved")
                    self.assertFalse(plan.view(A) or plan.view(B))
                else:
                    self.assertEqual(plan.status, "ready", plan.reason)
                    self.assertEqual(tuple(r for r in (A, B) if plan.view(r)), expected)
                    if name == "two-topics":
                        self.assertNotIn("check the diagram", plan.view(A))
                        self.assertNotIn("revise the summary", plan.view(B))
                    if name == "quote":
                        self.assertNotIn("delete the diagram", plan.view(A))
                    if name == "contextual":
                        self.assertEqual(plan.units[0].people, ("UBIRCH",))
