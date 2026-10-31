"""Canonical conversation inputs and workspace isolation, not storage contracts."""

import unittest
from dataclasses import replace

from test_semantic import A, B, snapshot

from hermes_slack_thread_assignee.policy import Recipient, Thread
from hermes_slack_thread_assignee.semantic import SemanticError, prepare


class BoundaryTests(unittest.TestCase):
    def test_same_context_and_registry_order_produces_same_questions(self):
        source = snapshot()
        reversed_input = replace(source, history=source.history[::-1], recipients=source.recipients[::-1])
        self.assertEqual(prepare(source), prepare(reversed_input))
        self.assertEqual(source.binding, reversed_input.binding)
        self.assertNotIn("receiving_agent", prepare(source)["state"])

    def test_other_workspace_cannot_supply_a_recipient_or_reuse_source(self):
        source = snapshot()
        foreign = Recipient("TOTHER", A.bot_user, A.runtime_profile)
        with self.assertRaises(SemanticError):
            prepare(replace(source, recipients=(foreign, B)))
        other = replace(source, thread=Thread("TOTHER", "CFICTION", "1.0"), recipients=(foreign,))
        self.assertNotEqual(source.binding, other.binding)

    def test_edit_reclassifies_current_source_without_retained_decision(self):
        source = snapshot()
        changed = replace(source, identity="3.0:4.0", text="Birch, review the new diagram.")
        self.assertNotEqual(source.binding, changed.binding)
        self.assertNotEqual(prepare(source), prepare(changed))
        self.assertEqual(prepare(changed)["state"]["current"], changed.text)

    def test_duplicate_bot_runtime_mapping_and_duplicate_source_rejected(self):
        source = snapshot()
        for changed in (
            replace(source, recipients=(A, Recipient(A.workspace, A.bot_user, "other"))),
            replace(source, history=(source.history[0], source.history[0])),
            replace(source, identity="1.0"),
        ):
            with self.assertRaises(SemanticError):
                prepare(changed)
