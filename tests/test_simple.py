"""Whole-message service validation; probability never substitutes for confidence."""

import copy
import unittest

from test_semantic import controlled_answers, prepare, snapshot

from hermes_slack_agent_router.jev import JevError, validate_answers


class WholeResponseContract(unittest.TestCase):
    def test_selected_confidence_is_returned_unchanged_including_ties(self):
        batch = prepare(snapshot())
        for choice in ("yes", "no"):
            for confidence in (0.0, 0.1, 0.499, 0.5, 0.501, 1.0):
                for probability in (0.5, 0.501, 1.0):
                    with self.subTest(choice=choice, confidence=confidence, probability=probability):
                        raw = controlled_answers(batch, choice, confidence)
                        raw["answers"]["response"]["probabilities"] = {
                            choice: probability,
                            "no" if choice == "yes" else "yes": 1 - probability,
                        }
                        self.assertEqual(validate_answers(batch, raw), (choice, confidence))

    def test_malformed_service_answers_cannot_become_confident_no(self):
        batch = prepare(snapshot())
        seed = controlled_answers(batch, "no")
        invalid = [None, [], {}, {"answers": {}}, {"answers": []}]
        for field in ("type", "choice", "confidence", "probabilities"):
            raw = copy.deepcopy(seed)
            del raw["answers"]["response"][field]
            invalid.append(raw)
        for field, values in (
            ("type", (None, "wrong", True, [], {})),
            ("choice", (None, "NO", True, [], {})),
            ("confidence", (None, True, False, "0.9", -0.01, 1.01, float("nan"), float("inf"))),
            (
                "probabilities",
                (
                    None,
                    [],
                    {},
                    {"yes": 0.0, "no": 0.2},
                    {"yes": 1.0, "no": 0.0},
                    {"yes": 0.5, "no": 0.5, "extra": 0.0},
                ),
            ),
        ):
            for value in values:
                raw = copy.deepcopy(seed)
                raw["answers"]["response"][field] = value
                invalid.append(raw)
        for value in (None, True, "1", -1.0, 2.0, float("nan"), float("inf")):
            raw = copy.deepcopy(seed)
            raw["answers"]["response"]["probabilities"]["no"] = value
            invalid.append(raw)
        raw = copy.deepcopy(seed)
        raw["answers"]["extra"] = raw["answers"]["response"]
        invalid.append(raw)
        raw = copy.deepcopy(seed)
        raw["answers"]["response"]["extra"] = "no"
        invalid.append(raw)
        for raw in invalid:
            with self.subTest(raw=repr(raw)), self.assertRaises(JevError):
                validate_answers(batch, raw)

    def test_long_quoted_unicode_content_is_one_complete_question(self):
        text = "> An inert command.\n```code; code!```\n\n" + "🦊 Explain this; why? Keep the units.\n\n" * 60
        batch = prepare(snapshot(text))
        self.assertEqual(set(batch["questions"]), {"response"})
        self.assertEqual(batch["state"]["conversation"]["records"][-1]["text"], text)
        self.assertNotIn("source_selection", batch["state"])
        self.assertNotIn("current_author_content", batch["state"])
        self.assertEqual(validate_answers(batch, controlled_answers(batch, "yes", 0.0)), ("yes", 0.0))
