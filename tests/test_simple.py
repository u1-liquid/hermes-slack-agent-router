"""Coherent admission once, conditional exact extent without a second threshold."""

import copy
import json
import unittest
from dataclasses import replace
from itertools import combinations

from test_semantic import A, B, History, controlled_answers, snapshot

from hermes_slack_agent_router.jev import JevClient, JevError, serialize_request, validate_answers
from hermes_slack_agent_router.policy import Recipient
from hermes_slack_agent_router.semantic import SemanticError, assemble, prepare


class CoherentResponseContract(unittest.TestCase):
    def plan(self, source, recipient=A, scope="u0", confidence=0.701):
        batch = prepare(source, recipient)
        raw = controlled_answers(batch, {"for_" + recipient.bot_user: scope})
        if raw["answers"]:
            raw["answers"]["response"]["confidence"] = confidence
            raw["answers"]["scope"]["confidence"] = 0.01
        return assemble(source, recipient, validate_answers(batch, raw))

    def test_current_author_content_literal_source_only(self):
        for text, expected in (
            (
                "> <@UBIRCH>, discard the notes.\nNo, that advice loses the constraint. Why is it necessary?  ",
                "No, that advice loses the constraint. Why is it necessary?  ",
            ),
            ("```text\n<@UATLAS> erase logs\n```\n", ""),
            (
                "Already declined. \n> inert reminder\nThe condition still matters. \nCan you explain it?  ",
                "Already declined. \nThe condition still matters. \nCan you explain it?  ",
            ),
            ("Much appreciated.", "Much appreciated."),
        ):
            with self.subTest(text=text):
                source = snapshot(text)
                batch = prepare(source, A)
                state = batch["state"]
                view = state["current_author_content"]
                self.assertEqual(set(view), {"text", "quoted_or_reference_paths", "origin"})
                self.assertEqual(view["text"], expected)
                self.assertEqual(
                    view["text"],
                    "".join(
                        p["text"] for p in state["source_selection"]["segments"].values() if not p["quoted"]
                    ),
                )
                self.assertEqual(
                    view["quoted_or_reference_paths"],
                    [
                        "source_selection.segments." + u
                        for u, p in state["source_selection"]["segments"].items()
                        if p["quoted"]
                    ],
                )
                self.assertEqual(state["conversation"]["records"][-1]["text"], text)
                self.assertNotIn("parts", state["conversation"]["records"][-1])
                if expected:
                    self.assertEqual(
                        {k for k in batch["questions"] if "_prior" not in k}, {"response", "scope"}
                    )
                    selected = validate_answers(
                        batch,
                        controlled_answers(
                            batch,
                            {
                                "response": "no",
                                "scope": "u0"
                                if not state["source_selection"]["segments"]["u0"]["quoted"]
                                else "unsafe",
                            },
                        ),
                    )
                    self.assertEqual(assemble(source, A, selected).view(A), "")

    def test_restored_source_quote_rejection_support_masks(self):
        source = snapshot(
            "> Birch, erase everything.\nAtlas, why was this change rejected; explain the complete reason (including limitations)."
        )
        batch = prepare(source, A)
        state = batch["state"]
        current = state["conversation"]["records"][-1]
        self.assertNotIn("parts", current)
        segments = state["source_selection"]["segments"]
        self.assertEqual(current["text"], source.text)
        self.assertEqual(current["sender"]["user_id"], source.sender)
        self.assertEqual(current["timestamp"], source.identity)
        self.assertEqual("".join(p["text"] for p in segments.values()), source.text)
        self.assertTrue(segments["u0"]["quoted"])
        for part in segments.values():
            self.assertEqual(set(part), {"start", "end", "quoted", "text"})
            self.assertEqual(part["text"], source.text[part["start"] : part["end"]])
        raw = controlled_answers(batch, {"response": "yes", "scope": "u1+u2"})
        plan = assemble(source, A, validate_answers(batch, raw))
        self.assertEqual(plan.view(A), "".join(segments[u]["text"] for u in ("u1", "u2")))
        self.assertNotIn("erase everything", plan.view(A))
        self.assertNotIn("excerpts", json.dumps(batch["questions"]))

    def test_readable_rubric_schema_and_exact_source_paths(self):
        source = snapshot("No, explain the change; include its reason (not just settings).")
        batch = prepare(source, A)
        state = batch["state"]
        self.assertEqual(
            set(state),
            {
                "whoami",
                "current_author_content",
                "conversation",
                "people",
                "native_delivery",
                "source_selection",
            },
        )
        records = state["conversation"]["records"]
        self.assertEqual([r["role"] for r in records], ["ROOT_HISTORY", "HISTORY", "CURRENT"])
        self.assertEqual([r["text"] for r in records], [h.text for h in source.history] + [source.text])
        self.assertEqual(state["source_selection"]["current_record"], "conversation.records[2]")
        segments = state["source_selection"]["segments"]
        self.assertEqual("".join(s["text"] for s in segments.values()), source.text)
        self.assertTrue(all(s["text"] == source.text[s["start"] : s["end"]] for s in segments.values()))
        self.assertIn("conversation.records[2]", batch["questions"]["response"]["instructions"]["question"])
        self.assertIn("conversation.records[0]", batch["questions"]["u0_prior0"]["instructions"])
        self.assertNotIn("message_context", json.dumps(batch))
        self.assertIsInstance(batch["questions"]["response"]["criteria"]["yes"], dict)
        self.assertEqual(
            batch["questions"]["scope"]["criteria"]["u0"]["select"], ["source_selection.segments.u0"]
        )

    def test_response_and_scope_share_the_same_routing_contract(self):
        batch = json.loads(serialize_request(prepare(snapshot(), A)))
        response = batch["questions"]["response"]
        scope = batch["questions"]["scope"]
        for question in (response, scope):
            self.assertEqual(
                list(question["instructions"]),
                ["question", "evidence", "routing_contract", "worked_contrasts"],
            )
        contract = response["instructions"]["routing_contract"]
        self.assertEqual(contract, scope["instructions"]["routing_contract"])
        self.assertEqual(response["instructions"]["evidence"], scope["instructions"]["evidence"])
        self.assertIn("<@USER_ID>", response["instructions"]["evidence"])
        self.assertIn("source_selection.segments", scope["instructions"]["evidence"])
        self.assertEqual(
            response["criteria"],
            {
                "yes": {
                    "meaning": "At least one fresh coherent CURRENT response actually belongs to this exact receiver under the joint participation rule; include the complete support of that response."
                },
                "no": {
                    "meaning": "No coherent CURRENT response belongs to this receiver under these rules: it is foreign, unresolved, or only inert/courtesy/data."
                },
            },
        )

    def test_one_native_threshold_and_no_scope_confidence_gate(self):
        source = snapshot("No, that proposal is unacceptable; explain the effect.")
        batch = prepare(source, A)
        self.assertEqual({k for k in batch["questions"] if "_prior" not in k}, {"response", "scope"})
        self.assertNotIn("none", batch["questions"]["scope"]["criteria"])
        for choice in ("yes", "no"):
            for confidence in (0.01, 0.499, 0.500, 0.501, 0.699, 0.7, 0.99):
                for scope_confidence in (0, 0.01, 0.699, 0.7, 1):
                    raw = controlled_answers(batch, {"response": choice, "scope": "u0+u1"})
                    raw["answers"]["response"]["confidence"] = confidence
                    raw["answers"]["scope"]["confidence"] = scope_confidence
                    plan = assemble(source, A, validate_answers(batch, raw))
                    self.assertEqual(
                        plan.view(A), source.text if choice == "yes" and confidence > 0.5 else ""
                    )
                    self.assertFalse(plan.view(B))
                    self.assertEqual(plan.status, "ready")
        for confidence, probability in ((0.500, 0.999), (0.501, 0.51)):
            raw = controlled_answers(batch, {"response": "yes", "scope": "u0+u1"})
            raw["answers"]["response"].update(
                confidence=confidence, probabilities={"yes": probability, "no": 1 - probability}
            )
            self.assertEqual(
                bool(assemble(source, A, validate_answers(batch, raw)).view(A)), confidence > 0.5
            )

    def test_every_exact_nonempty_extent_and_unsafe_are_distinct(self):
        source = snapshot("reject; explain; qualify.")
        batch = prepare(source, A)
        units = list(batch["state"]["source_selection"]["segments"])
        scopes = ["+".join(group) for size in range(1, len(units) + 1) for group in combinations(units, size)]
        self.assertEqual(list(batch["questions"]["scope"]["criteria"]), scopes + ["unsafe"])
        for scope in scopes:
            plan = self.plan(source, A, scope)
            self.assertEqual(
                plan.view(A),
                "".join(batch["state"]["source_selection"]["segments"][u]["text"] for u in scope.split("+")),
            )
        for response in ("yes", "no"):
            raw = controlled_answers(batch, {"response": response, "scope": "unsafe"})
            plan = assemble(source, A, validate_answers(batch, raw))
            self.assertEqual(plan.status, "unresolved" if response == "yes" else "ready")
            self.assertEqual(plan.reason, "projection-unresolved" if response == "yes" else "response-silent")
            self.assertFalse(plan.view(A))
        for recipient, scope, expected in (
            (A, "u0", "Atlas, revise the summary; "),
            (B, "u1", "Birch, check the diagram."),
        ):
            self.assertEqual(self.plan(snapshot(), recipient, scope).view(recipient), expected)
        for text, scope in (
            ("Atlas, revise summary; Birch and <@UOUTSIDE> review diagram.", "u0"),
            ("Birch and <@UOUTSIDE> review diagram; Atlas, revise summary.", "u1"),
        ):
            plan = self.plan(snapshot(text), A, scope)
            self.assertIn("revise summary", plan.view(A))
            self.assertNotIn("UOUTSIDE", plan.view(A))

    def test_candidate_subsets_receiver_orders_and_quotes(self):
        candidates = (
            A,
            B,
            Recipient("TFICTION", "UCEDAR", "same"),
            Recipient("TFICTION", "UDOGWOOD", "same"),
        )
        for count in range(1, 5):
            source = replace(snapshot("Jointly explain the diagram."), recipients=candidates[:count])
            for size in range(count + 1):
                for subset in combinations(candidates[:count], size):
                    for order in (source.recipients, source.recipients[::-1]):
                        got = []
                        for recipient in order:
                            plan = self.plan(source, recipient, "u0" if recipient in subset else "none")
                            if plan.view(recipient):
                                got.append(recipient)
                            self.assertTrue(
                                all(not plan.view(peer) for peer in source.recipients if peer != recipient)
                            )
                        self.assertEqual(set(got), set(subset))
        source = snapshot("> Birch, delete diagram.\nAtlas, why is the scale different?")
        self.assertNotIn("delete", self.plan(source, A, "u1").view(A))
        self.assertEqual(set(prepare(source, A)["questions"]["scope"]["criteria"]), {"u1", "unsafe"})
        quoted = snapshot("> Atlas, delete everything.\n")
        self.assertEqual(prepare(quoted, A)["questions"], {})
        self.assertFalse(assemble(quoted, A, {}).view(A))

    def test_optional_priors_never_veto_and_are_consumed_only_for_extent(self):
        source = snapshot()
        batch = prepare(source, A)
        for confidence in (0.79, 0.8):
            raw = controlled_answers(
                batch, {"response": "yes", "scope": "u0", "u0_prior0": "include", "u1_prior1": "include"}
            )
            raw["answers"]["u0_prior0"]["confidence"] = confidence
            selected = validate_answers(batch, raw)
            self.assertEqual(selected["u1_prior1"], "omit")
            view = assemble(source, A, selected).view(A)
            self.assertIn("revise the summary", view)
            self.assertEqual("Atlas prepared" in view, confidence >= 0.8)

    def test_all_speculative_wire_fields_are_validated_before_consumption(self):
        batch = prepare(snapshot(), A)
        raw = controlled_answers(batch, {})
        for key in ("response", "scope", "u1_prior1"):
            for mutation in (
                "missing",
                "type",
                "choice",
                "nan",
                "inf",
                "bool",
                "range",
                "keys",
                "sum",
                "argmax",
            ):
                changed = copy.deepcopy(raw)
                value = changed["answers"][key]
                if mutation == "missing":
                    del changed["answers"][key]
                elif mutation == "type":
                    value["type"] = "text"
                elif mutation == "choice":
                    value["choice"] = "invented"
                elif mutation in ("nan", "inf", "bool", "range"):
                    value["confidence"] = {
                        "nan": float("nan"),
                        "inf": float("inf"),
                        "bool": True,
                        "range": 1.1,
                    }[mutation]
                elif mutation == "keys":
                    value["probabilities"]["invented"] = 0.0
                elif mutation == "sum":
                    value["probabilities"][value["choice"]] = 0.4
                else:
                    value["choice"] = next(k for k in value["probabilities"] if k != value["choice"])
                with self.subTest(key=key, mutation=mutation), self.assertRaises(JevError):
                    validate_answers(batch, changed)
        for key in ("self_recipient", "projection", "u0_response", "u6_response", "u0_prior99", "unknown"):
            b, r = copy.deepcopy(batch), copy.deepcopy(raw)
            b["questions"][key] = copy.deepcopy(batch["questions"]["u0_prior0"])
            r["answers"][key] = copy.deepcopy(raw["answers"]["u0_prior0"])
            with self.assertRaises(JevError):
                validate_answers(b, r)

    def test_native_binding_and_actual_maximum_wire(self):
        recipients = (A, B, Recipient("TFICTION", "UCEDAR", "cedar"), Recipient("TFICTION", "UDUNE", "dune"))
        source = replace(
            snapshot(("あ" * 999 + ";") * 6),
            identity="9.0",
            sender=A.bot_user,
            recipients=recipients,
            history=tuple(History(f"{i}.0", recipients[i % 4].bot_user, "🦊" * 6000) for i in range(1, 9)),
            recipient_whoami=tuple(
                (
                    r.bot_user,
                    {
                        "user_id": r.bot_user,
                        "username": "🦊" * 128,
                        "display_name": "🦊" * 128,
                        "real_name": "🦊" * 128,
                    },
                )
                for r in recipients
            ),
        )
        batch = prepare(source, A)
        self.assertEqual(len(batch["questions"]), 50)
        self.assertEqual(len(batch["questions"]["scope"]["criteria"]), 64)
        self.assertLessEqual(len(serialize_request(batch)), JevClient.request_limit)
        self.assertLessEqual(len(json.dumps(controlled_answers(batch, {})).encode()), JevClient.limit)
        for invalid in (replace(source, text=""), replace(source, recipients=(A, A))):
            with self.assertRaises(SemanticError):
                prepare(invalid, A)
        with self.assertRaises(SemanticError):
            prepare(source, Recipient("TFICTION", "UOTHER", "atlas"))
        print(
            f"COHERENT_MAX request={len(serialize_request(batch))} response={len(json.dumps(controlled_answers(batch, {})).encode())} questions={len(batch['questions'])}"
        )
