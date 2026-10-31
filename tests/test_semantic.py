"""Source-grounded stateless decisions; external Jev is explicitly opt-in/fictional."""

import asyncio
import json
import os
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, call, patch

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
    )


def controlled_answers(batch, choices):
    # Explicit local facts supplied by each fixture; no inferred tier/witness oracle.
    defaults = {
        name: "absent" if name.endswith("_address") else "none" if "none" in q["criteria"] else "no"
        for name, q in batch["questions"].items()
    }
    defaults.update(choices)
    return {
        "answers": {
            name: {
                "type": "choice",
                "choice": defaults[name],
                "probabilities": {key: float(key == defaults[name]) for key in q["criteria"]},
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
            "u0_kind": "action",
            "u1_kind": "action",
            "u0_destination": "specific",
            "u1_destination": "specific",
            "u0_address": "explicit",
            "u1_address": "explicit",
            "u0_link0": "yes",
            "u1_link1": "yes",
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

    async def _exchange(self, raw, key):
        (self.directory / "jev-request.json").write_bytes(raw)
        if os.environ.get("JEV_SAME_INPUTS_DIR"):
            previous = json.loads(
                (
                    Path(os.environ["JEV_SAME_INPUTS_DIR"]) / self.directory.name / "jev-request.json"
                ).read_text()
            )
            expected = {k: v for k, v in previous["state"].items() if k != "precedence"}
            if json.loads(raw)["state"] != expected:
                raise AssertionError("changed-protocol qualification must preserve the original input state")
            (self.directory / "same-inputs.txt").write_text(
                "Exact original state equality excluding removed internal precedence instructions: PASS\n"
            )
        started = time.monotonic()
        outcome = "failed"
        try:
            stdout = await super()._exchange(raw, key)
            (self.directory / "jev-result.json").write_bytes(stdout)
            outcome = "HTTP-200"
            return stdout
        finally:
            (self.directory / "jev-receipt.json").write_text(
                json.dumps(
                    {
                        "protocol": "official HTTPS System One Choice",
                        "outcome": outcome,
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

    def test_root_fallback_and_newer_explicit_handoff(self):
        source = replace(
            snapshot("Please continue."),
            history=(
                History("1.0", "UFABLE", "Atlas, lead this whole thread."),
                *[History(f"{i}.0", "UFABLE", "Thanks for the update.") for i in range(2, 9)],
            ),
            identity="9.0",
        )
        choices = {
            "coverage": "complete",
            "main_fact0": "assign:r0",
            "u0_kind": "action",
            "u0_destination": "generic",
        }
        plan = self.plan(source, choices)
        self.assertEqual(plan.status, "ready", plan.reason)
        self.assertEqual(plan.units[0].recipients, (A,))
        changed = replace(
            source,
            history=(
                *source.history[:-1],
                History("8.0", "UFABLE", "Birch, take over leading the whole thread from Atlas now."),
            ),
        )
        takeover = {
            **choices,
            "main_fact7": "takeover:r1",
        }
        plan = self.plan(changed, takeover)
        self.assertEqual(plan.status, "ready", plan.reason)
        self.assertEqual(plan.units[0].recipients, (B,))
        self.assertEqual([h.identity for h in plan.units[0].references], ["8.0"])
        for delta in (
            {"main_fact7": "assign:r1"},
            {"main_fact7": "disputes"},
            {"main_fact7": "unknown"},
            {"main_fact7": "mixed"},
        ):
            with self.subTest(delta=delta):
                self.assertEqual(self.plan(changed, {**takeover, **delta}).status, "unresolved")

    def test_full_root_recent_question_and_text_budgets(self):
        recipients = (A, B, Recipient("TFICTION", "UCEDAR", "cedar"), Recipient("TFICTION", "UDUNE", "dune"))
        source = replace(
            snapshot("Atlas, one; Birch, two; Cedar, three; Dune, four; Atlas, five; Birch, six."),
            identity="9.0",
            recipients=recipients,
            history=tuple(History(f"{i}.0", "UFABLE", "x" * 6000) for i in range(1, 9)),
        )
        batch = prepare(source)
        self.assertEqual(len(batch["questions"]), 168)
        self.assertEqual(batch["state"]["recent"], [f"h{i}" for i in range(1, 8)])
        self.assertEqual(batch["state"]["root"], "h0")
        self.assertLess(
            len(json.dumps({"model": JevClient.model, **batch}).encode()), JevClient.request_limit
        )
        for invalid in (
            replace(source, history=(*source.history, History("8.5", "UFABLE", "n"))),
            replace(source, history=(replace(source.history[0], text="x" * 6001), *source.history[1:])),
        ):
            with self.assertRaises(SemanticError):
                prepare(invalid)

    def test_specific_root_fallback_recent_priority_and_unresolved_root(self):
        source = replace(
            snapshot("Please revise the summary."),
            history=(
                History("1.0", "UFABLE", "Birch reviews diagrams; Atlas prepares the summary."),
                *[History(f"{i}.0", "UFABLE", "Thanks.") for i in range(2, 9)],
            ),
            identity="9.0",
        )
        choices = {
            "coverage": "complete",
            "u0_kind": "action",
            "u0_destination": "specific",
            "u0_fact0": "assign:r0",
            "u0_link0": "yes",
        }
        plan = self.plan(source, choices)
        self.assertEqual(plan.status, "ready", plan.reason)
        self.assertEqual(plan.units[0].recipients, (A,))
        changed = replace(
            source,
            history=(
                *source.history[:-1],
                History("8.0", "UFABLE", "Birch now takes over the summary from Atlas."),
            ),
        )
        priority = {
            **choices,
            "u0_fact7": "takeover:r1",
            "u0_link7": "yes",
        }
        self.assertEqual(self.plan(changed, priority).units[0].recipients, (B,))
        for delta in (
            {"u0_fact7": "assign:r1"},
            {"u0_fact7": "unknown"},
            {"u0_fact7": "disputes"},
            {"u0_link7": "unknown"},
        ):
            self.assertEqual(self.plan(changed, {**priority, **delta}).status, "unresolved")
        # General-lead facts are irrelevant to wholly specific work.
        batch = prepare(changed)
        raw = controlled_answers(batch, priority)
        for name in ("main_fact0", "main_fact7"):
            raw["answers"][name]["confidence"] = 0.1
        self.assertEqual(assemble(changed, validate_answers(batch, raw)).status, "ready")

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
            "main_fact0": "assign:r0",
            "main_fact1": "assign:r0",
            "u0_kind": "action",
            "u0_destination": "generic",
        }
        plan = self.plan(source, choices)
        self.assertEqual(plan.status, "ready", plan.reason)
        self.assertIn("Please continue.", plan.view(A))
        self.assertIn("coordinate", plan.view(A))
        self.assertEqual(plan.view(B), "")
        for delta in (
            {"main_fact0": "unknown"},
            {"main_fact0": "none", "main_fact1": "none"},
            {"main_fact1": "assign:r1"},
        ):
            uncertain = self.plan(source, {**choices, **delta})
            self.assertEqual(uncertain.status, "unresolved")
            self.assertFalse(uncertain.view(A) or uncertain.view(B))

    def test_specific_work_does_not_require_global_main_confidence(self):
        batch = prepare(snapshot())
        raw = two_topic_answers(batch)
        raw["answers"]["main_fact0"]["confidence"] = 0.2
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
                "u0_kind": "action",
                "u0_destination": "specific",
                "u0_link0": "yes",
                "u0_link1": "yes",
                "u0_address": "explicit",
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
                "u0_kind": "action",
                "u1_kind": "action",
                "u2_kind": "action",
                "u0_destination": "specific",
                "u1_destination": "specific",
                "u2_destination": "specific",
                "u0_to0": "yes",
                "u0_address": "explicit",
                "u1_address": "explicit",
                "u2_address": "explicit",
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
                "u0_kind": "action",
                "u0_destination": "specific",
                "u0_link1": "yes",
                "u0_fact1": "assign:r1",
                "u0_address": "contextual",
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
                "u0_kind": "ack",
                "u0_destination": "none",
                "u1_kind": "action",
                "u2_kind": "action",
                "u1_destination": "specific",
                "u2_destination": "specific",
                "u1_link1": "yes",
                "u2_link0": "yes",
                "u1_fact1": "assign:r1",
                "u2_fact0": "assign:r0",
            },
        )
        self.assertEqual(plan.status, "ready")
        self.assertNotIn("要約", plan.view(B))
        self.assertNotIn("ありがとう", plan.view(B))
        quoted = self.plan(
            snapshot("> Birch, delete diagram.\nAtlas, revise summary."),
            {
                "coverage": "complete",
                "u1_kind": "action",
                "u1_destination": "specific",
                "u1_to0": "yes",
                "u1_address": "explicit",
                "u1_link0": "yes",
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

    def test_contradictory_nonaction_cannot_erase_work_while_sibling_proceeds(self):
        source = snapshot("Thanks and revise the summary; Birch, check the diagram.")
        for kind in ("ack", "reference"):
            for conflict in (
                {"u0_mixed": "yes"},
                {"u0_mixed": "unknown"},
                {"u0_destination": "specific"},
                {"u0_link0": "yes"},
                {"u0_to0": "yes"},
            ):
                with self.subTest(kind=kind, conflict=conflict):
                    plan = self.plan(
                        source,
                        {
                            "coverage": "complete",
                            "u0_kind": kind,
                            "u0_destination": "none",
                            "u1_kind": "action",
                            "u1_destination": "specific",
                            "u1_link1": "yes",
                            "u1_to1": "yes",
                            "u1_address": "explicit",
                            **conflict,
                        },
                    )
                    self.assertEqual(plan.status, "unresolved")
                    self.assertFalse(plan.view(A) or plan.view(B))

    def test_nonaction_safety_confidence_cannot_be_waived_by_kind(self):
        source = snapshot("Thanks; Birch, check the diagram.")
        batch = prepare(source)
        choices = {
            "coverage": "complete",
            "u0_kind": "ack",
            "u0_destination": "none",
            "u1_kind": "action",
            "u1_destination": "specific",
            "u1_to1": "yes",
            "u1_address": "explicit",
        }
        raw = controlled_answers(batch, choices)
        # Irrelevant negative membership is not needed to qualify an otherwise safe ACK.
        raw["answers"]["u0_to0"]["confidence"] = 0.2
        self.assertEqual(assemble(source, validate_answers(batch, raw)).status, "ready")
        for field in ("mixed", "destination"):
            raw = controlled_answers(batch, choices)
            raw["answers"][f"u0_{field}"]["confidence"] = 0.2
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

    def test_context_and_recipient_bounds(self):
        for source in (
            replace(snapshot(), text="x" * 6001),
            replace(snapshot(), recipients=(A, A)),
            replace(snapshot(), recipients=(Recipient("TOTHER", "UATLAS", "atlas"),)),
        ):
            with self.assertRaises(SemanticError):
                prepare(source)


class SourceLocalProof(unittest.TestCase):
    def source(self, text="Please revise the summary.", root="Atlas prepares the summary.", recent="Thanks."):
        return replace(
            snapshot(text),
            identity="9.0",
            history=(
                History("1.0", "UFABLE", root),
                *[History(f"{i}.0", "UFABLE", "Thanks.") for i in range(2, 8)],
                History("8.0", "UFABLE", recent),
            ),
        )

    def plan(self, source, **choices):
        batch = prepare(source)
        defaults = {
            name: "none" if "none" in q["criteria"] else "no" for name, q in batch["questions"].items()
        }
        defaults.update(coverage="complete", u0_kind="action", u0_destination="specific", u0_address="absent")
        defaults.update(choices)
        answers = {name: defaults[name] for name in batch["questions"]}
        return assemble(source, answers)

    def test_source_local_original_root_and_takeover_paths(self):
        source = self.source(root="Birch reviews diagrams; Atlas leads this thread and prepares the summary.")
        for generic in (False, True):
            current = replace(source, text="Please continue." if generic else source.text)
            facts = {"main_fact0": "assign:r0"} if generic else {"u0_fact0": "assign:r0", "u0_link0": "yes"}
            if generic:
                facts["u0_destination"] = "generic"
            plan = self.plan(current, **facts)
            self.assertEqual(plan.status, "ready", plan.reason)
            self.assertEqual(plan.units[0].recipients, (A,))
            changed = replace(
                current,
                history=(*current.history[:-1], History("8.0", "UFABLE", "Birch takes over from Atlas.")),
            )
            facts.update(
                {"main_fact7": "takeover:r1"} if generic else {"u0_fact7": "takeover:r1", "u0_link7": "yes"}
            )
            plan = self.plan(changed, **facts)
            self.assertEqual(plan.status, "ready", plan.reason)
            self.assertEqual(plan.units[0].recipients, (B,))
            self.assertEqual([h.identity for h in plan.units[0].references], ["8.0"])

    def test_source_local_topic_only_does_not_erase_root_assignee(self):
        source = self.source(recent="The summary needs a clearer title.")
        plan = self.plan(source, u0_fact0="assign:r0", u0_link0="yes", u0_fact7="none", u0_link7="yes")
        self.assertEqual(plan.status, "ready", plan.reason)
        self.assertEqual(plan.units[0].recipients, (A,))
        self.assertEqual([h.identity for h in plan.units[0].references], ["1.0", "8.0"])

    def test_source_local_historical_joint_and_recent_joint_are_preserved(self):
        source = self.source(root="Atlas and Birch jointly prepare the summary.")
        plan = self.plan(source, u0_fact0="assign:r0+r1", u0_link0="yes")
        self.assertEqual(plan.status, "ready", plan.reason)
        self.assertEqual(plan.units[0].recipients, (A, B))
        self.assertTrue(plan.view(A) and plan.view(B))
        source = replace(
            source,
            history=(
                *source.history[:-1],
                History("8.0", "UFABLE", "Atlas and Birch jointly take over the summary."),
            ),
        )
        plan = self.plan(
            source, u0_fact0="assign:r0", u0_link0="yes", u0_fact7="takeover:r0+r1", u0_link7="yes"
        )
        self.assertEqual(plan.units[0].recipients, (A, B))
        self.assertEqual([h.identity for h in plan.units[0].references], ["8.0"])

    def test_source_local_swapped_assignments_with_identical_runtime_names(self):
        source = replace(
            self.source(root="<@UBIRCH> prepares the summary; <@UATLAS> reviews diagrams."),
            recipients=(replace(A, runtime_profile="same"), replace(B, runtime_profile="same")),
        )
        plan = self.plan(source, u0_fact0="assign:r1", u0_link0="yes")
        self.assertEqual(plan.status, "ready", plan.reason)
        self.assertEqual(plan.units[0].recipients, (source.recipients[1],))

    def test_source_local_confident_negatives_and_unsafe_facts_remain_required(self):
        source = self.source()
        batch = prepare(source)
        choices = {
            "coverage": "complete",
            "u0_kind": "action",
            "u0_destination": "specific",
            "u0_fact0": "assign:r0",
            "u0_link0": "yes",
        }
        for name in ("u0_fact7", "u0_link7", "u0_to1", "u0_address"):
            raw = controlled_answers(batch, choices)
            raw["answers"][name]["confidence"] = 0.79
            with self.subTest(name=name), self.assertRaises(JevError):
                validate_answers(batch, raw)
        generic = replace(source, text="Please continue.")
        batch = prepare(generic)
        raw = controlled_answers(
            batch,
            {
                "coverage": "complete",
                "u0_kind": "action",
                "u0_destination": "generic",
                "main_fact0": "assign:r0",
            },
        )
        raw["answers"]["main_fact7"]["confidence"] = 0.79
        with self.assertRaises(JevError):
            validate_answers(batch, raw)
        for unsafe in ("unknown", "outside", "mixed"):
            self.assertEqual(
                self.plan(
                    source, u0_fact0=unsafe, u0_link0="yes", u0_fact7="takeover:r1", u0_link7="yes"
                ).status,
                "unresolved",
            )

    def test_source_local_known_dispute_requires_explicit_resolution(self):
        source = self.source(recent="Not sure who owns the summary.")
        self.assertEqual(
            self.plan(
                source, u0_fact0="assign:r0", u0_link0="yes", u0_fact7="disputes", u0_link7="yes"
            ).status,
            "unresolved",
        )
        source = replace(
            source,
            history=(
                *source.history[:-2],
                History("7.0", "UFABLE", "Not sure who owns the summary."),
                History("8.0", "UFABLE", "Birch explicitly takes over now."),
            ),
        )
        plan = self.plan(
            source,
            u0_fact0="assign:r0",
            u0_link0="yes",
            u0_fact6="disputes",
            u0_link6="yes",
            u0_fact7="takeover:r1",
            u0_link7="yes",
        )
        self.assertEqual(plan.status, "ready", plan.reason)
        self.assertEqual(plan.units[0].recipients, (B,))

    def test_source_local_plain_conflict_dispute_and_unknown_are_atomic(self):
        source = self.source(recent="Birch will prepare the summary.")
        for fact in ("assign:r1", "disputes", "unknown", "mixed", "outside", "assign:r0+r1"):
            plan = self.plan(source, u0_fact0="assign:r0", u0_link0="yes", u0_fact7=fact, u0_link7="yes")
            self.assertEqual(plan.status, "unresolved", fact)
            self.assertFalse(plan.view(A) or plan.view(B))

    def test_source_local_explicit_current_joint_controls_and_partial_outside_rejects(self):
        source = self.source(text="Atlas and Birch, revise the summary.")
        plan = self.plan(
            source, u0_address="explicit", u0_to0="yes", u0_to1="yes", u0_fact0="assign:r0", u0_link0="yes"
        )
        self.assertEqual(plan.status, "ready", plan.reason)
        self.assertEqual(plan.units[0].recipients, (A, B))
        for address in ("outside", "mixed", "unknown"):
            self.assertEqual(self.plan(source, u0_address=address, u0_to0="yes").status, "unresolved")


class APITransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_official_http_contract_without_cli_and_request_local_key(self):
        import sys
        from types import SimpleNamespace

        import httpx

        batch = prepare(snapshot())
        sent = []

        async def respond(request):
            sent.append(request)
            return httpx.Response(200, json=two_topic_answers(batch))

        native = httpx.AsyncClient
        secret = Mock(side_effect=["synthetic-atlas", "synthetic-birch"])
        clients = []

        def factory(**kwargs):
            self.assertFalse(kwargs["follow_redirects"])
            self.assertFalse(kwargs["trust_env"])
            client = native(transport=httpx.MockTransport(respond), **kwargs)
            clients.append(client)
            return client

        with (
            patch.dict(sys.modules, {"agent.secret_scope": SimpleNamespace(get_secret=secret)}),
            patch("httpx.AsyncClient", side_effect=factory),
            patch("asyncio.create_subprocess_exec", side_effect=AssertionError("local CLI forbidden")),
        ):
            client = JevClient()
            for _ in range(2):
                self.assertEqual(await client.ask(batch), validate_answers(batch, two_topic_answers(batch)))
        self.assertEqual(secret.call_args_list, [call("TYPESAFE_API_KEY")] * 2)
        self.assertEqual(
            [r.headers["Authorization"] for r in sent], ["Bearer synthetic-atlas", "Bearer synthetic-birch"]
        )
        for request in sent:
            self.assertEqual(str(request.url), "https://api.typesafe.ai/v1/systemone")
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.headers["Content-Type"], "application/json")
            self.assertEqual(json.loads(request.content), {"model": "jev-latest", **batch})
        self.assertTrue(all(client.is_closed for client in clients))

    async def test_missing_or_inaccessible_scope_never_creates_transport(self):
        import sys
        from types import SimpleNamespace

        for outcome in (None, "", RuntimeError("synthetic-private-scope-detail")):
            resolver = (
                Mock(side_effect=outcome) if isinstance(outcome, Exception) else Mock(return_value=outcome)
            )
            with (
                self.subTest(outcome=type(outcome).__name__),
                patch.dict(sys.modules, {"agent.secret_scope": SimpleNamespace(get_secret=resolver)}),
                patch("httpx.AsyncClient") as transport,
                patch("asyncio.create_subprocess_exec", side_effect=AssertionError("local CLI forbidden")),
                self.assertRaises(JevError) as caught,
            ):
                await JevClient().ask(prepare(snapshot()))
            transport.assert_not_called()
            self.assertNotIn("synthetic-private", str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import sys
        from types import SimpleNamespace

        import httpx

        self.requests, self.clients = [], []
        native = httpx.AsyncClient

        async def respond(request):
            self.requests.append(request)
            if isinstance(self.response, Exception):
                raise self.response
            return self.response

        def factory(**kwargs):
            client = native(transport=httpx.MockTransport(respond), **kwargs)
            self.clients.append(client)
            return client

        for patcher in (
            patch.dict(
                sys.modules, {"agent.secret_scope": SimpleNamespace(get_secret=lambda name: "synthetic-key")}
            ),
            patch("httpx.AsyncClient", side_effect=factory),
            patch("asyncio.create_subprocess_exec", side_effect=AssertionError("local CLI forbidden")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def stream(self, chunks=(), *, block=False):
        import httpx

        class Stream(httpx.AsyncByteStream):
            def __init__(self):
                self.started = asyncio.Event()
                self.closed = False
                self.reads = 0
                self.cancelled = False

            async def __aiter__(self):
                self.started.set()
                if block:
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        self.cancelled = True
                        raise
                for chunk in chunks:
                    self.reads += 1
                    yield chunk

            async def aclose(self):
                self.closed = True

        return Stream()

    async def test_oversized_or_nonfinite_request_never_connects(self):
        for batch in ({"state": "x" * 524289, "questions": {}}, {"state": float("nan")}):
            with self.assertRaisesRegex(JevError, "serialized"):
                await JevClient().ask(batch)
        self.assertEqual(self.clients, [])

    async def test_status_redirect_errors_never_retry_forward_auth_or_read_body(self):
        import httpx

        for status in (301, 302, 307, 308, 400, 401, 413, 422, 429, 500, 503, 529):
            with self.subTest(status=status):
                stream = self.stream((b"synthetic-private-error-body",))
                self.response = httpx.Response(
                    status, headers={"Location": "https://other.invalid/steal"}, stream=stream
                )
                count = len(self.requests)
                with self.assertRaises(JevError) as caught:
                    await JevClient().ask(prepare(snapshot()))
                self.assertEqual(len(self.requests), count + 1)
                self.assertEqual(str(self.requests[-1].url), "https://api.typesafe.ai/v1/systemone")
                self.assertEqual(stream.reads, 0)
                self.assertTrue(stream.closed)
                self.assertTrue(self.clients[-1].is_closed)
                self.assertNotIn("synthetic", str(caught.exception))

    async def test_malformed_oversized_and_compressed_answers_close(self):
        import httpx

        cases = (
            ({}, (b"not JSON synthetic-private",)),
            ({}, (b"\\xff",)),
            ({}, (b"{}",)),
            ({}, (b"[",)),
            ({}, (b"x" * 131073, b"x" * 131073)),
            ({"Content-Length": "262145"}, (b"never read",)),
            ({"Content-Length": "garbage"}, (b"never read",)),
            ({"Content-Encoding": "gzip"}, (b"never decompress",)),
        )
        for headers, chunks in cases:
            with self.subTest(headers=headers, chunks=len(chunks)):
                stream = self.stream(chunks)
                self.response = httpx.Response(200, headers=headers, stream=stream)
                with self.assertRaises(JevError) as caught:
                    await JevClient().ask(prepare(snapshot()))
                self.assertNotIn("synthetic-private", str(caught.exception))
                self.assertTrue(stream.closed)
                self.assertTrue(self.clients[-1].is_closed)
                if headers:
                    self.assertEqual(stream.reads, 0)

    async def test_async_timeout_and_cancellation_close_stream_and_client(self):
        import httpx

        for cancel in (False, True):
            stream = self.stream(block=True)
            self.response = httpx.Response(200, stream=stream)
            client = JevClient(timeout=0.05 if not cancel else 1.2)
            started = time.monotonic()
            task = asyncio.create_task(client.ask(prepare(snapshot())))
            await asyncio.wait_for(stream.started.wait(), 1)
            if cancel:
                task.cancel()
            with self.assertRaises(asyncio.CancelledError if cancel else JevError):
                await task
            self.assertTrue(task.done())
            self.assertTrue(stream.cancelled)
            self.assertTrue(stream.closed)
            self.assertTrue(self.clients[-1].is_closed)
            self.assertLess(time.monotonic() - started, 1)

    async def test_outer_ingress_deadline_cancels_and_closes_before_subbudget(self):
        import httpx

        stream = self.stream(block=True)
        self.response = httpx.Response(200, stream=stream)
        with self.assertRaises(TimeoutError):
            async with asyncio.timeout(0.02):
                await JevClient().ask(prepare(snapshot()))
        self.assertTrue(stream.cancelled and stream.closed)
        self.assertTrue(self.clients[-1].is_closed)

    async def test_safe_transport_errors_and_typed_invalid_replies(self):
        import httpx

        for error in (
            httpx.ConnectError("synthetic-key/private"),
            httpx.ReadError("synthetic-private"),
            httpx.ReadTimeout("synthetic-private"),
        ):
            self.response = error
            with self.assertRaises(JevError) as caught:
                await JevClient().ask(prepare(snapshot()))
            self.assertNotIn("synthetic", str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)
            self.assertTrue(self.clients[-1].is_closed)
        batch = prepare(snapshot())
        for value in (float("nan"), float("inf"), 0.1):
            invalid = two_topic_answers(batch)
            invalid["answers"]["u0_kind"]["confidence"] = value
            self.response = httpx.Response(200, content=json.dumps(invalid).encode())
            with self.assertRaises(JevError):
                await JevClient().ask(batch)


class FictionalCanaries(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        if os.environ.get("JEV_FICTIONAL_CANARY_DIR"):
            from agent.secret_scope import build_profile_secret_scope, reset_secret_scope, set_secret_scope
            from hermes_constants import get_hermes_home

            home = get_hermes_home()
            token = set_secret_scope(build_profile_secret_scope(home), profile_home=str(home))
            self.addCleanup(reset_secret_scope, token)

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
