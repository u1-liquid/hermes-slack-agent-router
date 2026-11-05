"""Canonical conversation ordering and bounded history, not identity validation."""

import unittest
from dataclasses import replace

from test_semantic import prepare, snapshot

from hermes_slack_agent_router.semantic import SemanticError


class BoundaryTests(unittest.TestCase):
    def test_same_context_and_registry_order_produces_same_questions(self):
        source = snapshot()
        reversed_input = replace(source, history=source.history[::-1], recipients=source.recipients[::-1])
        self.assertEqual(prepare(source), prepare(reversed_input))
        self.assertNotIn("receiving_agent", prepare(source)["state"])

    def test_edit_reclassifies_current_source_without_retained_decision(self):
        source = snapshot()
        changed = replace(source, identity="3.0:4.0", text="Birch, review the new diagram.")
        self.assertNotEqual(prepare(source), prepare(changed))
        self.assertEqual(prepare(changed)["state"]["conversation"]["records"][-1]["text"], changed.text)

    def test_duplicate_or_nonprior_history_rejected(self):
        source = snapshot()
        for changed in (
            replace(source, history=(source.history[0], source.history[0])),
            replace(source, identity="1.0"),
        ):
            with self.assertRaises(SemanticError):
                prepare(changed)
