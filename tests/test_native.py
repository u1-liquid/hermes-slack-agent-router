"""Pinned-host acceptance tests; never run against a live home.

HERMES_TEST_SOURCE selects the isolated official checkout. HERMES_REQUIRE_NATIVE=1
makes absence of that checkout fatal in the required integration CI job.
Only SDK I/O and the final model handler are replaced. Host routing/pending,
message listener, source builder and eligibility implementation remain real.
"""

import asyncio
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from hermes_slack_thread_assignee.policy import Recipient, Thread

SOURCE = os.environ.get("HERMES_TEST_SOURCE")
if os.environ.get("HERMES_REQUIRE_NATIVE") == "1" and not SOURCE:
    raise RuntimeError("required native suite needs HERMES_TEST_SOURCE")


@unittest.skipUnless(SOURCE, "optional local native suite; CI requires it explicitly")
class NativeDispatch(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(mode=0o700)
        bundled = self.root / "empty-bundled"
        bundled.mkdir()
        self.env = patch.dict(
            os.environ,
            {
                # TMPDIR may itself be inside the real ~/.hermes cache. Bind both
                # platform default and explicit custom root, using supported env.
                "HOME": str(self.root),
                "HERMES_HOME": str(self.home),
                "HERMES_BUNDLED_PLUGINS": str(bundled),
                "HERMES_ENABLE_PROJECT_PLUGINS": "0",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        assert SOURCE is not None
        sys.path.insert(0, SOURCE)
        self.addCleanup(sys.path.remove, SOURCE)
        from gateway.config import GatewayConfig, Platform, PlatformConfig
        from gateway.run import GatewayRunner
        from gateway.session_state import SessionState
        from plugins.platforms.slack.adapter import SlackAdapter
        from slack_bolt.async_app import AsyncApp
        from slack_bolt.authorization import AuthorizeResult

        from hermes_slack_thread_assignee.plugin import Gate

        self.SessionState = SessionState
        self.a = Recipient("TDEMO", "UALPHA", "default")
        self.b = Recipient("TDEMO", "UBETA", "default")
        self.key = Thread("TDEMO", "CDEMO", "100.001")

        self.adapter = SlackAdapter(PlatformConfig(extra={"reply_in_thread": True}))
        # Avoid constructor startup, disk stores, process-global registration and workers.
        # These are native runner state fields, not replacement routing functions.
        self.runner = GatewayRunner.__new__(GatewayRunner)
        self.runner.config = GatewayConfig(multiplex_profiles=False)
        self.runner._primary_profile_name = "default"
        self.runner.adapters = {Platform.SLACK: self.adapter}
        self.runner._profile_adapters = {}
        self.runner._sessions = {}
        self.runner.session_store = None
        self.adapter.gateway_runner = self.runner
        self.adapter._team_bot_user_ids = {"TDEMO": "UBETA"}
        self.adapter._bot_user_id = "UBETA"
        self.client = AsyncMock()
        self.client.users_info.return_value = {
            "ok": True,
            "user": {"id": "UHUMAN", "is_bot": False, "name": "Human", "profile": {}},
        }
        self.client.conversations_info.return_value = {
            "ok": True,
            "channel": {"id": "CDEMO", "name": "demo", "is_im": False, "is_mpim": False},
        }
        self.client.conversations_replies.return_value = {"ok": True, "messages": []}
        self.adapter._team_clients = {"TDEMO": self.client}
        self.model = AsyncMock(return_value=None)
        self.adapter.set_message_handler(self.model)
        self.adapter._register_mentioned_thread("100.001", "TDEMO")

        async def authorize(**kwargs):
            return AuthorizeResult(enterprise_id=None, team_id="TDEMO", bot_user_id="UBETA")

        self.app = AsyncApp(
            signing_secret="synthetic",
            authorize=authorize,
            request_verification_enabled=False,
            process_before_response=True,
        )
        self.adapter._app = self.app
        # Register the actual core listener FIRST, matching the pinned host ordering.
        self.app.event("message")(self.adapter._handle_slack_message)
        self.app.event("app_mention")(self.adapter._handle_slack_message)
        self.gate = Gate((self.a, self.b))
        self.gate.wire(self.app, self.adapter)
        self.downstream = []

        async def observe(body, next):
            self.downstream.append(copy.deepcopy(body))
            return await next()

        self.app.use(observe)
        self.addAsyncCleanup(self.adapter.cancel_background_tasks)
        self.addCleanup(self.gate.dispose)
        self.sequence = 200

    def message(self, text="ordinary", **changes):
        self.sequence += 1
        event = {
            "type": "message",
            "channel": "CDEMO",
            "channel_type": "channel",
            "user": "UHUMAN",
            "text": text,
            "ts": f"{self.sequence}.001",
            "thread_ts": "100.001",
            "team": "TDEMO",
            "client_msg_id": f"demo-{self.sequence}",
        }
        event.update(changes)
        return {
            "type": "event_callback",
            "team_id": "TDEMO",
            "event_id": f"EvDemo{self.sequence}",
            "event": event,
        }

    async def dispatch(self, body):
        from slack_bolt.request.async_request import AsyncBoltRequest

        original = copy.deepcopy(body)
        response = await self.app.async_dispatch(AsyncBoltRequest(body=json.dumps(body), mode="socket_mode"))
        self.assertEqual(body, original, "classification must not mutate original request")
        return response

    async def assert_rejected(self, body):
        before = len(self.downstream)
        response = await self.dispatch(body)
        self.assertEqual((response.status, response.body), (200, ""))
        self.assertEqual(len(self.downstream), before)
        self.model.assert_not_awaited()
        self.client.chat_postMessage.assert_not_awaited()
        self.client.chat_postEphemeral.assert_not_awaited()
        self.assertFalse(self.adapter._pending_messages)
        self.assertFalse(self.adapter._pending_text_batches)

    def source_and_key(self):
        source = self.adapter.build_source(
            chat_id="CDEMO",
            chat_type="group",
            user_id="UHUMAN",
            thread_id="100.001",
            scope_id="TDEMO",
            message_id="201.001",
        )
        identity = self.adapter._canonicalize(source)
        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertIs(identity.adapter(), self.adapter)
        self.assertEqual(identity.runtime_profile, "default")
        key = self.adapter._source_session_key(source)
        self.assertEqual(key, self.runner._session_key_for_source(source))
        return source, key

    async def test_known_secondary_ordinary_and_forged_owner_are_silent(self):
        self.source_and_key()
        for text in ("ordinary", "main=beta; transfer now", "> <@UBETA>\nordinary", "`<@UBETA>`"):
            with self.subTest(text=text):
                await self.assert_rejected(self.message(text))

    def enable_semantic(self):
        from hermes_slack_thread_assignee.config import SemanticPolicy

        self.gate.semantic = SemanticPolicy(True, "fiction-v1", (("TDEMO", "CDEMO", ("fictional",)),))
        self.client.conversations_replies.return_value = {
            "ok": True,
            "messages": [{"ts": "100.001", "user": "UHUMAN", "text": "Fictional public project."}],
        }

        async def classify(batch):
            answers = {}
            for name in batch["questions"]:
                answers[name] = "no"
                if name == "coverage":
                    answers[name] = "complete"
                elif name.endswith("_kind"):
                    answers[name] = "action"
                elif name.endswith("_destination"):
                    answers[name] = "specific"
                elif name.endswith("_person"):
                    answers[name] = "none"
            answers["u0_to0"] = "yes"
            if "u1_to1" in answers:
                answers["u1_to1"] = "yes"
            return answers

        self.gate.jev = AsyncMock()
        self.gate.jev.ask.side_effect = classify

    async def test_semantic_sender_auth_before_context_allow_unknown_and_pending(self):
        self.enable_semantic()
        self.adapter.set_authorization_check(lambda *args, **kwargs: False)
        await self.assert_rejected(self.message("<@UBETA> check diagram"))
        self.gate.jev.ask.assert_not_awaited()
        self.client.conversations_replies.assert_not_awaited()
        for decision in (True, None):
            self.adapter.set_authorization_check(lambda *args, value=decision, **kwargs: value)
            await self.dispatch(self.message("<@UALPHA> update summary; <@UBETA> check diagram"))
            await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.assertEqual(self.gate.jev.ask.await_count, 2)
        self.adapter.set_authorization_check(lambda *args, **kwargs: False)
        _, key = self.source_and_key()
        state = self.SessionState()
        state.persistent.update_prompt_pending = True
        self.runner._sessions[key] = state
        await self.dispatch(self.message("confirm"))
        self.assertEqual(self.downstream[-1]["event"]["text"], "confirm")
        self.assertEqual(self.gate.jev.ask.await_count, 2)

    async def test_semantic_separate_current_units_share_request_topic(self):

        self.enable_semantic()
        self.client.conversations_replies.return_value["messages"] += [
            {"ts": "101.001", "user": "UALPHA", "text": "Legend proposal"},
            {"ts": "102.001", "user": "UBETA", "text": "Arrows proposal"},
        ]

        async def grounded(batch):
            answers = dict.fromkeys(batch["questions"], "no")
            answers.update(
                coverage="complete",
                u0_kind="action",
                u1_kind="action",
                u0_destination="specific",
                u1_destination="specific",
                u0_ref1="yes",
                u1_ref2="yes",
                u0_to0="yes",
                u1_to1="yes",
                same0_1="yes",
            )
            return answers

        self.gate.jev.ask.side_effect = grounded
        body = self.message("<@UALPHA> add the legend; <@UBETA> add the arrows to the same diagram.")
        await self.dispatch(body)
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.assertIn("add the arrows", self.model.await_args.args[0].text)
        self.assertNotIn("add the legend", self.model.await_args.args[0].text)
        self.model.reset_mock()
        await self.dispatch(body)
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_not_awaited()
        await self.dispatch(self.message(body["event"]["text"]))
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()

    async def test_semantic_joint_prior_refs_reconstructed_on_new_gate(self):

        self.enable_semantic()
        self.client.conversations_replies.return_value["messages"] += [
            {"ts": "101.001", "user": "UALPHA", "text": "Add a legend to the diagram"},
            {"ts": "102.001", "user": "UBETA", "text": "Add arrows to the diagram"},
        ]

        async def grounded(batch):
            answers = dict.fromkeys(batch["questions"], "no")
            answers.update(
                coverage="complete",
                u0_kind="action",
                u0_destination="specific",
                u0_ref1="yes",
                u0_ref2="yes",
                u0_to0="yes",
                u0_to1="yes",
            )
            return answers

        self.gate.jev.ask.side_effect = grounded
        original = self.message("<@UALPHA> and <@UBETA> combine your diagram changes")
        await self.dispatch(original)
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        await self.dispatch(original)
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        from hermes_slack_thread_assignee.plugin import Gate

        fresh = Gate((self.b, self.a), semantic=self.gate.semantic)
        fresh.jev = self.gate.jev
        self.gate.dispose()
        self.gate = fresh
        fresh.wire(self.app, self.adapter)
        self.addCleanup(fresh.dispose)
        self.model.reset_mock()
        await self.dispatch(self.message("<@UALPHA> and <@UBETA> combine your diagram changes again"))
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        self.assertIn("Add a legend", self.model.await_args.args[0].text)
        self.assertIn("Add arrows", self.model.await_args.args[0].text)

    async def test_semantic_wake_pattern_only_assigned_current_confers_admission(self):
        self.enable_semantic()
        self.adapter.config.extra["mention_patterns"] = ["FictionalBeta"]
        self.adapter._compiled_mention_patterns = None
        self.client.conversations_replies.return_value["messages"][0]["text"] = (
            "FictionalBeta diagram proposal"
        )

        async def grounded(batch):
            answers = dict.fromkeys(batch["questions"], "no")
            answers.update(
                coverage="complete", u0_kind="action", u0_destination="specific", u0_ref0="yes", u0_to1="yes"
            )
            if "u1_kind" in answers:
                answers.update(
                    u0_to1="no",
                    u0_to0="yes",
                    u1_kind="action",
                    u1_destination="specific",
                    u1_ref0="yes",
                    u1_to1="yes",
                )
            return answers

        self.gate.jev.ask.side_effect = grounded
        with patch.dict(os.environ, {"SLACK_STRICT_MENTION": "true"}):
            await self.dispatch(self.message("FictionalBeta check diagram"))
            await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
            self.model.assert_awaited_once()
            self.model.reset_mock()
            await self.assert_rejected(self.message("<@UALPHA> FictionalBeta update summary; check diagram"))
            await self.assert_rejected(self.message("<@UALPHA> and <@UBETA> update summary; check diagram"))

    async def test_semantic_normal_scoped_input_and_nonrecipient(self):
        self.enable_semantic()
        original = self.message("<@UALPHA> revise SUMMARY_ONLY; <@UBETA> check DIAGRAM_ONLY.")
        await self.dispatch(original)
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        received = self.model.await_args.args[0].text
        alpha = self.adapter._team_bot_user_ids["TDEMO"] == "UALPHA"
        self.assertIn("SUMMARY_ONLY" if alpha else "DIAGRAM_ONLY", received)
        self.assertNotIn("DIAGRAM_ONLY" if alpha else "SUMMARY_ONLY", received)
        self.assertIn("SUMMARY_ONLY", original["event"]["text"])
        self.model.reset_mock()
        if not alpha:
            await self.assert_rejected(self.message("<@UALPHA> revise SUMMARY_ONLY."))

    async def test_semantic_other_recipient_receives_only_own_current(self):
        self.adapter._team_bot_user_ids["TDEMO"] = "UALPHA"
        self.adapter._bot_user_id = "UALPHA"
        await self.test_semantic_normal_scoped_input_and_nonrecipient()

    async def test_semantic_rich_text_and_busy_queue_merge_replay(self):
        self.enable_semantic()
        _, key = self.source_and_key()
        self.adapter._active_sessions[key] = asyncio.Event()
        busy = AsyncMock(return_value=True)
        self.adapter.set_busy_session_handler(busy)
        body = self.message(
            "fallback includes SUMMARY_ONLY and DIAGRAM_ONLY",
            blocks=[
                {
                    "type": "rich_text",
                    "elements": [
                        {
                            "type": "rich_text_section",
                            "elements": [
                                {"type": "user", "user_id": "UALPHA"},
                                {"type": "text", "text": " revise SUMMARY_ONLY; "},
                                {"type": "user", "user_id": "UBETA"},
                                {"type": "text", "text": " check DIAGRAM_ONLY."},
                            ],
                        }
                    ],
                }
            ],
        )
        await self.dispatch(body)
        busy.assert_awaited_once()
        self.assertIn("DIAGRAM_ONLY", busy.await_args.args[0].text)
        self.assertNotIn("SUMMARY_ONLY", busy.await_args.args[0].text)
        self.adapter.set_busy_session_handler(None)
        self.adapter._busy_text_debounce_seconds = 0
        for suffix in ("ONE", "TWO"):
            await self.dispatch(self.message(f"<@UALPHA> SUMMARY_{suffix}; <@UBETA> DIAGRAM_{suffix}."))
        pending = self.adapter.get_pending_message(key)
        self.assertIsNotNone(pending)
        self.assertIn("DIAGRAM_ONE", pending.text)
        self.assertIn("DIAGRAM_TWO", pending.text)
        self.assertNotIn("SUMMARY", pending.text)
        self.adapter._active_sessions.pop(key)
        await self.adapter.handle_message(pending)
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        self.assertNotIn("SUMMARY", self.model.await_args.args[0].text)

    async def test_semantic_disabled_no_context_no_client(self):
        from hermes_slack_thread_assignee.config import SemanticPolicy

        self.gate.semantic = SemanticPolicy()
        self.gate.jev = AsyncMock()
        await self.assert_rejected(self.message("<@UBETA> private scope is not authorized"))
        self.client.conversations_replies.assert_not_awaited()
        self.gate.jev.ask.assert_not_awaited()

    async def test_semantic_shared_busy_burst_received_scope(self):
        self.enable_semantic()
        _, key = self.source_and_key()
        self.adapter._active_sessions[key] = asyncio.Event()
        received = []

        class SharedReceiver:
            session_authority = object()

            async def receive(self, event):
                received.append(event.text)

        receiver = SharedReceiver()
        self.adapter.set_message_handler(receiver.receive)
        self.adapter._busy_text_mode = "queue"
        self.adapter._busy_text_debounce_seconds = 0.3
        self.adapter._busy_text_hard_cap_seconds = 0.6
        await asyncio.gather(
            *(
                self.dispatch(self.message(f"<@UALPHA> SUMMARY_{label}; <@UBETA> DIAGRAM_{label}."))
                for label in ("ONE", "TWO")
            )
        )
        self.assertEqual(len(received), 1)
        self.assertIn("DIAGRAM_ONE", received[0])
        self.assertIn("DIAGRAM_TWO", received[0])
        self.assertNotIn("SUMMARY", received[0])
        self.model.assert_not_awaited()

    async def test_semantic_runner_fifo_preserves_scope_and_replay_order(self):
        self.enable_semantic()
        _, key = self.source_and_key()
        self.runner._sessions[key] = self.SessionState()
        self.adapter._active_sessions[key] = asyncio.Event()

        async def enqueue(event, session_key):
            self.runner._queue_or_replace_pending_event(session_key, event)
            return True

        self.adapter.set_busy_session_handler(enqueue)
        for label in ("ONE", "TWO"):
            await self.dispatch(self.message(f"<@UALPHA> SUMMARY_{label}; <@UBETA> DIAGRAM_{label}."))
        self.assertEqual(self.runner._queue_depth(key, adapter=self.adapter), 2)
        first = self.adapter.get_pending_message(key)
        second = self.runner._promote_queued_event(key, self.adapter, None)
        assert first is not None and second is not None
        self.assertIn("DIAGRAM_ONE", first.text)
        self.assertIn("DIAGRAM_TWO", second.text)
        self.assertNotIn("SUMMARY", first.text + second.text)
        self.adapter._active_sessions.pop(key)
        self.adapter.set_busy_session_handler(None)
        for event in (first, second):
            await self.adapter.handle_message(event)
            await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.assertEqual(self.model.await_count, 2)
        self.assertIn("DIAGRAM_ONE", self.model.await_args_list[0].args[0].text)
        self.assertIn("DIAGRAM_TWO", self.model.await_args_list[1].args[0].text)
        self.assertTrue(all("SUMMARY" not in call.args[0].text for call in self.model.await_args_list))

    async def test_semantic_original_and_projected_native_denial(self):
        self.enable_semantic()
        with patch.dict(os.environ, {"SLACK_IGNORE_OTHER_USER_MENTIONS": "true"}):
            await self.assert_rejected(self.message("<@UALPHA> SUMMARY_ONLY; DIAGRAM_ONLY."))
        self.gate.jev.ask.assert_not_awaited()
        classify = self.gate.jev.ask.side_effect

        async def grounded(batch):
            result = await classify(batch)
            result["u1_ref0"] = "yes"
            return result

        self.gate.jev.ask.side_effect = grounded
        with patch.dict(os.environ, {"SLACK_STRICT_MENTION": "true"}):
            await self.assert_rejected(self.message("<@UALPHA> summarize note from <@UBETA>; check diagram."))
        self.gate.jev.ask.assert_awaited_once()

    async def test_semantic_prior_rich_text_reference_keeps_original(self):

        self.enable_semantic()
        prior = {
            "ts": "100.001",
            "user": "UHUMAN",
            "text": "fallback",
            "blocks": [
                {
                    "type": "rich_text",
                    "elements": [
                        {
                            "type": "rich_text_section",
                            "elements": [{"type": "text", "text": "PRIOR_DIAGRAM context."}],
                        }
                    ],
                }
            ],
        }
        self.client.conversations_replies.return_value = {"ok": True, "messages": [prior]}
        classify = self.gate.jev.ask.side_effect

        async def referenced(batch):
            answer = await classify(batch)
            answer["u1_ref0"] = "yes"
            return answer

        self.gate.jev.ask.side_effect = referenced
        await self.dispatch(self.message("<@UALPHA> SUMMARY_ONLY; <@UBETA> DIAGRAM_ONLY."))
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.assertIn("PRIOR_DIAGRAM", self.model.await_args.args[0].text)
        self.assertNotIn("SUMMARY_ONLY", self.model.await_args.args[0].text)
        self.assertEqual(self.client.conversations_replies.return_value["messages"], [prior])

    async def test_semantic_duplicate_envelopes_native_delivery_only_once(self):
        self.enable_semantic()
        body = self.message("<@UALPHA> SUMMARY_ONLY; <@UBETA> DIAGRAM_ONLY.")
        await self.dispatch(body)
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        duplicate = copy.deepcopy(body)
        duplicate["event"]["type"] = "app_mention"
        duplicate["event_id"] = "EvFictionRetry"
        await self.dispatch(duplicate)
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        self.assertEqual(self.gate.jev.ask.await_count, 2)

    async def test_semantic_sdk_failure_pending_preserves_native_control(self):
        self.enable_semantic()
        _, key = self.source_and_key()

        async def pending_failure(**kwargs):
            state = self.SessionState()
            state.persistent.update_prompt_pending = True
            self.runner._sessions[key] = state
            raise OSError("fictional SDK failure")

        self.client.conversations_replies.side_effect = pending_failure
        body = self.message("<@UALPHA> SUMMARY_ONLY; <@UBETA> DIAGRAM_ONLY.")
        await self.dispatch(body)
        self.assertEqual(self.downstream[-1]["event"]["text"], body["event"]["text"])
        self.gate.jev.ask.assert_not_awaited()

    async def test_semantic_sdk_fault_explicit_silent_no_work(self):

        self.enable_semantic()
        self.client.conversations_replies.side_effect = OSError("fictional SDK failure")
        with self.assertLogs("hermes_slack_thread_assignee.plugin", level="WARNING") as logs:
            await self.assert_rejected(self.message("<@UBETA> check diagram"))
        self.gate.jev.ask.assert_not_awaited()
        self.assertIn("context-fetch-failed", logs.output[0])
        self.assertNotIn("fictional SDK failure", "".join(logs.output))

    async def test_semantic_pending_recheck_after_classifier_preserves_control(self):
        self.enable_semantic()
        _, key = self.source_and_key()
        classify = self.gate.jev.ask.side_effect

        async def become_pending(batch):
            result = await classify(batch)
            state = self.SessionState()
            state.persistent.update_prompt_pending = True
            self.runner._sessions[key] = state
            return result

        self.gate.jev.ask.side_effect = become_pending
        body = self.message("<@UALPHA> SUMMARY_ONLY; <@UBETA> DIAGRAM_ONLY.")
        await self.dispatch(body)
        self.assertEqual(self.downstream[-1]["event"]["text"], body["event"]["text"])

    async def test_semantic_current_history_excluded_and_root_media_unresolved(self):
        self.enable_semantic()
        body = self.message("<@UALPHA> SUMMARY_ONLY; <@UBETA> DIAGRAM_ONLY.")
        root = {"ts": "100.001", "user": "UHUMAN", "text": "Fictional root."}
        self.client.conversations_replies.return_value = {"ok": True, "messages": [root, body["event"]]}
        await self.dispatch(body)
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        state = self.gate.jev.ask.await_args.args[0]["state"]
        self.assertEqual(len(state["prior"]), 1)
        self.assertNotIn("SUMMARY_ONLY", self.model.await_args.args[0].text)
        self.model.reset_mock()
        self.gate.jev.ask.reset_mock()
        root["files"] = [{"id": "FFICTION", "mimetype": "image/png"}]
        await self.assert_rejected(self.message("<@UBETA> check root image"))
        self.gate.jev.ask.assert_not_awaited()

    async def test_rejection_precedes_legacy_busy_steer_and_text_merge(self):
        _, key = self.source_and_key()
        self.adapter._active_sessions[key] = asyncio.Event()
        # Actual native busy callback is an execution boundary, not a policy mock.
        busy = AsyncMock(return_value=True)
        self.adapter.set_busy_session_handler(busy)
        for text in ("first fragment", "second fragment"):
            await self.assert_rejected(self.message(text))
        busy.assert_not_awaited()

    async def test_explicit_secondary_then_ordinary_does_not_transfer(self):
        self.enable_semantic()

        async def secondary(batch):
            result = dict.fromkeys(batch["questions"], "no")
            result.update(coverage="complete", u0_kind="action", u0_destination="specific", u0_to1="yes")
            return result

        self.gate.jev.ask.side_effect = secondary
        await self.dispatch(self.message("<@UBETA> help"))
        self.assertEqual(len(self.downstream), 1)
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        self.model.reset_mock()

        async def generic(batch):
            result = dict.fromkeys(batch["questions"], "no")
            result.update(
                coverage="complete",
                main="r0",
                main_ref0="r0",
                u0_kind="action",
                u0_destination="generic",
                u0_to0="yes",
            )
            return result

        self.gate.jev.ask.side_effect = generic
        await self.assert_rejected(self.message("ordinary continuation"))

    async def test_pending_clarify_choice_preserves_native_control(self):
        from tools import clarify_gateway

        _, key = self.source_and_key()
        clarify_gateway.register("demo-choice", key, "Choose", ["Alpha", "Beta"])
        self.addCleanup(clarify_gateway.clear_session, key)
        response = await self.dispatch(self.message("1"))
        self.assertEqual(response.status, 200)
        # Native listener reached: metadata hydration only happens after the early gate.
        self.assertTrue(self.downstream)

    async def test_pending_slash_confirmation_preserves_native_control(self):
        from tools import slash_confirm

        _, key = self.source_and_key()
        slash_confirm.register(key, "demo-confirm", "/new", AsyncMock())
        self.addCleanup(slash_confirm.clear, key)
        response = await self.dispatch(self.message("yes"))
        self.assertEqual(response.status, 200)
        self.assertTrue(self.downstream)

    async def test_pending_update_preserves_native_control(self):
        _, key = self.source_and_key()
        state = self.SessionState()
        state.persistent.update_prompt_pending = True
        self.runner._sessions[key] = state
        response = await self.dispatch(self.message("yes"))
        self.assertEqual(response.status, 200)
        self.assertTrue(self.downstream)

    async def test_unload_is_pass_through(self):
        self.gate.dispose()
        response = await self.dispatch(self.message("<@UBETA> after unload"))
        self.assertEqual(response.status, 200)
        self.assertTrue(self.downstream)

    async def test_unknown_identity_is_not_guessed(self):
        self.adapter.gateway_runner = None
        await self.dispatch(self.message("<@UBETA> unknown route"))
        self.assertEqual(len(self.downstream), 1)

    async def test_explicit_multiple_mentions_keep_secondary_eligible(self):
        self.enable_semantic()

        async def joint(batch):
            result = dict.fromkeys(batch["questions"], "no")
            result.update(
                coverage="complete", u0_kind="action", u0_destination="specific", u0_to0="yes", u0_to1="yes"
            )
            return result

        self.gate.jev.ask.side_effect = joint
        await self.dispatch(self.message("<@UALPHA> <@UBETA> jointly"))
        self.assertEqual(len(self.downstream), 1)
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()

    async def test_inferred_main_ordinary_reaches_native_model_without_bootstrap(self):
        self.enable_semantic()
        self.client.conversations_replies.return_value["messages"][0]["text"] = (
            "Beta, lead this whole thread."
        )

        async def generic(batch):
            result = dict.fromkeys(batch["questions"], "no")
            result.update(
                coverage="complete",
                main="r1",
                main_ref0="r1",
                u0_kind="action",
                u0_destination="generic",
                u0_to1="yes",
            )
            return result

        self.gate.jev.ask.side_effect = generic
        await self.dispatch(self.message("ordinary main"))
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()

    async def test_rich_quote_does_not_leak_flat_fallback_mention(self):
        body = self.message("<@UBETA>")
        body["event"]["blocks"] = [
            {
                "type": "rich_text",
                "elements": [
                    {"type": "rich_text_quote", "elements": [{"type": "user", "user_id": "UBETA"}]},
                    {"type": "rich_text_section", "elements": [{"type": "text", "text": "ordinary"}]},
                ],
            }
        ]
        await self.assert_rejected(body)

    async def test_bot_and_dm_inputs_retain_native_handling(self):
        self.enable_semantic()
        self.addCleanup(self.gate.jev.ask.assert_not_awaited)
        for changes in (
            {"user": "UPEER", "bot_id": "BDEMO"},
            {"channel": "DDEMO", "channel_type": "im"},
            {"channel": "GDEMO", "channel_type": "mpim"},
        ):
            with self.subTest(changes=changes):
                before = len(self.downstream)
                await self.dispatch(self.message("<@UBETA> hello", **changes))
                self.assertEqual(len(self.downstream), before + 1)

    async def test_exact_monitoring_config_preserves_native_input(self):
        self.enable_semantic()
        self.addCleanup(self.gate.jev.ask.assert_not_awaited)
        from hermes_slack_thread_assignee.config import Config

        path = self.root / "config.json"
        path.write_text(
            json.dumps(
                {
                    "participants": [self.a.as_dict(), self.b.as_dict()],
                    "monitoring": [{"workspace": "TDEMO", "channel": "CDEMO", "sender": "UHUMAN"}],
                }
            )
        )
        config = Config.load(path)
        self.gate.monitoring = frozenset(config.monitoring)
        await self.dispatch(self.message("monitoring sample"))
        self.assertEqual(len(self.downstream), 1)

    async def test_downstream_error_is_not_retried(self):
        calls = []

        async def failure(body, next):
            calls.append(body)
            raise RuntimeError("synthetic downstream error")

        self.app.use(failure)
        self.gate.dispose()
        response = await self.dispatch(self.message("after dispose"))
        self.assertEqual(response.status, 500)
        self.assertEqual(len(calls), 1)

    async def test_commands_behind_mention_and_bang_preserve_native_input(self):
        self.enable_semantic()
        self.addCleanup(self.gate.jev.ask.assert_not_awaited)
        for text in ("<@UBETA> /help", "<@UBETA> !help"):
            before = len(self.downstream)
            await self.dispatch(self.message(text))
            await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
            self.assertEqual(len(self.downstream), before + 1)

    async def test_actual_routed_runtime_and_receiver_rebind(self):
        from gateway.profile_routing import ProfileRoute
        from hermes_cli.profiles import get_profile_dir

        from hermes_slack_thread_assignee.bridge import Bridge, Uncertain

        profile = get_profile_dir("demo-routed")
        self.assertTrue(profile.is_relative_to(self.home), "test must never write a live profile")
        profile.mkdir(parents=True)
        (profile / "config.yaml").write_text("{}")
        self.runner.config.multiplex_profiles = True
        self.runner.config._runtime_profile_homes = [("default", self.home), ("demo-routed", profile)]
        self.runner.config.profile_routes = [
            ProfileRoute("demo-route", "slack", "demo-routed", chat_id="CDEMO")
        ]
        bound = await Bridge(self.adapter).bind(self.message("routed ordinary"))
        self.assertEqual(bound.recipient, Recipient("TDEMO", "UBETA", "demo-routed"))
        self.assertEqual(bound.identity.transport_profile, "default")
        self.assertEqual(bound.identity.runtime_home, profile)
        self.assertEqual(bound.session_key, self.runner._session_key_for_source(bound.source))
        self.adapter._team_bot_user_ids.clear()
        with self.assertRaises(Uncertain):
            await Bridge(self.adapter).bind(self.message("receiver removed"))

    async def test_socket_mode_handler_sends_exact_empty_ack(self):
        import logging

        from slack_bolt.adapter.socket_mode.aiohttp import AsyncSocketModeHandler
        from slack_sdk.socket_mode.request import SocketModeRequest

        handler = AsyncSocketModeHandler.__new__(AsyncSocketModeHandler)
        handler.app = self.app
        socket = AsyncMock()
        socket.logger = logging.getLogger("synthetic-socket")
        request = SocketModeRequest(
            type="events_api", envelope_id="envelope-demo", payload=self.message("ordinary socket input")
        )
        await handler.handle(socket, request)
        socket.send_socket_mode_response.assert_awaited_once()
        response = socket.send_socket_mode_response.await_args.args[0]
        self.assertEqual(response.envelope_id, "envelope-demo")
        self.assertIsNone(response.payload)
        self.assertFalse(self.downstream)
        self.model.assert_not_awaited()

    async def test_genuine_blocking_approval_preserves_input_and_retires(self):
        from tools import approval
        from tools.approval_gateway_wait import _await_gateway_decision

        _, key = self.source_and_key()
        ready = asyncio.Event()
        loop = asyncio.get_running_loop()

        def notify(_data):
            loop.call_soon_threadsafe(ready.set)

        task = asyncio.create_task(
            asyncio.to_thread(
                _await_gateway_decision,
                key,
                notify,
                {"command": "synthetic command", "description": "test", "pattern_key": "synthetic"},
                surface="test",
            )
        )
        try:
            await asyncio.wait_for(ready.wait(), 3)
            self.assertTrue(approval.has_blocking_approval(key))
            await self.dispatch(self.message("yes"))
            self.assertTrue(self.downstream)
        finally:
            approval.resolve_gateway_approval(key, "deny")
            await asyncio.wait_for(task, 3)
        self.assertFalse(approval.has_blocking_approval(key))

    async def test_api_human_override_retains_verified_human_policy(self):
        self.adapter.config.extra["api_human_users"] = ["UHUMAN"]
        await self.assert_rejected(self.message("ordinary API input", app_id="ADEMO", client_msg_id=""))

    async def test_file_metadata_ambiguity_timeout_and_order(self):
        from hermes_slack_thread_assignee.bridge import Bridge, Uncertain

        bridge = Bridge(self.adapter)
        body = {
            "type": "event_callback",
            "team_id": "TDEMO",
            "event": {
                "type": "file_shared",
                "channel_id": "CDEMO",
                "channel_type": "channel",
                "file_id": "FDEMO",
                "user_id": "UHUMAN",
            },
        }
        for file in (
            {"mimetype": "video/mp4", "shares": {"public": {"COTHER": [{"ts": "220.001"}]}}},
            {
                "mimetype": "video/mp4",
                "shares": {"public": {"CDEMO": [{"ts": "220.001"}, {"ts": "221.001"}]}},
            },
            {"mimetype": "image/png"},
            {"mimetype": "video/mp4", "user": "UOTHER", "shares": {"public": {"CDEMO": [{"ts": "220.001"}]}}},
        ):
            self.client.files_info.return_value = {"ok": True, "file": file}
            with self.subTest(file=file), self.assertRaises(Uncertain):
                await bridge.bind(body)
        self.client.files_info.side_effect = TimeoutError("synthetic SDK timeout")
        with self.assertRaises(TimeoutError):
            await bridge.bind(body)
        self.client.files_info.side_effect = None
        self.client.files_info.return_value = {
            "ok": True,
            "file": {
                "mimetype": "video/mp4",
                "user": "UHUMAN",
                "shares": {"public": {"CDEMO": [{"ts": "220.001", "thread_ts": "100.001"}]}},
            },
        }
        rich = self.message("<@UBETA> explicit", ts="220.001")
        normal = await bridge.bind(rich)
        fallback = await bridge.bind(body)
        self.assertEqual(normal.event.provenance, "message")
        self.assertEqual(fallback.event.provenance, "file_shared")
        self.assertEqual(normal.event.thread, fallback.event.thread)
        self.assertEqual(normal.event.direct, ("UBETA",))
        self.assertEqual(fallback.event.direct, ())

    async def test_canonical_context_across_receivers_and_foreign_incomplete_rejection(self):
        self.enable_semantic()
        history = [
            {"ts": "100.001", "user": "UHUMAN", "text": "Fictional project root."},
            {"ts": "101.001", "user": "UBETA", "text": "Diagram prepared."},
        ]
        self.client.conversations_replies.return_value = {"ok": True, "messages": history[::-1]}
        body = self.message("<@UALPHA> revise summary; <@UBETA> check diagram.")
        await self.dispatch(body)
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        beta_batch = self.gate.jev.ask.await_args.args[0]
        self.adapter._team_bot_user_ids["TDEMO"] = "UALPHA"
        self.adapter._bot_user_id = "UALPHA"
        self.gate.participants = (self.b, self.a)
        self.client.conversations_replies.return_value["messages"] = history
        await self.dispatch(self.message(body["event"]["text"]))
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.assertEqual(beta_batch, self.gate.jev.ask.await_args.args[0])
        for mutation in (
            {"ok": True, "messages": history, "has_more": True},
            {"ok": True, "messages": [history[0], {**history[1], "team": "TOTHER"}]},
            {"ok": True, "messages": [history[0], {**history[1], "thread_ts": "99.001"}]},
            {"ok": True, "messages": [history[0], {**history[1], "ts": "999.001"}]},
            {"ok": True, "messages": [history[0], {**history[0], "text": "Conflicting root"}]},
        ):
            self.model.reset_mock()
            self.gate.jev.ask.reset_mock()
            self.client.conversations_replies.return_value = mutation
            await self.assert_rejected(self.message(body["event"]["text"]))
            self.gate.jev.ask.assert_not_awaited()

    async def test_jev_failure_and_late_pending_no_invented_work_or_control_loss(self):
        from hermes_slack_thread_assignee.jev import JevError

        self.enable_semantic()
        self.gate.jev.ask.side_effect = JevError("fictional timeout")
        await self.assert_rejected(self.message("<@UBETA> revise diagram."))
        _, key = self.source_and_key()

        async def late_failure(batch):
            state = self.SessionState()
            state.persistent.update_prompt_pending = True
            self.runner._sessions[key] = state
            raise JevError("fictional timeout")

        self.gate.jev.ask.side_effect = late_failure
        body = self.message("yes")
        await self.dispatch(body)
        self.assertEqual(self.downstream[-1]["event"]["text"], "yes")

    @unittest.skipUnless(
        os.environ.get("JEV_FICTIONAL_CANARY_DIR"), "explicit fictional external native canary"
    )
    async def test_real_jev_contextual_generic_and_multitopic_native_inputs(self):
        from test_semantic import RecordingJev

        self.enable_semantic()
        root = Path(os.environ["JEV_FICTIONAL_CANARY_DIR"]) / "native"
        history = [
            {
                "ts": "100.001",
                "user": "UHUMAN",
                "text": "<@UBETA>, lead this entire thread. <@UALPHA> only handles summaries.",
            },
            {
                "ts": "101.001",
                "user": "UBETA",
                "text": "I will coordinate the thread and prepare the diagram.",
            },
            {"ts": "102.001", "user": "UALPHA", "text": "I prepared the summary."},
        ]
        cases = (
            (
                "multi-beta",
                "UBETA",
                "<@UALPHA> revise the summary; <@UBETA> check the diagram.",
                "check the diagram",
                "revise the summary",
            ),
            (
                "multi-alpha",
                "UALPHA",
                "<@UALPHA> revise the summary; <@UBETA> check the diagram.",
                "revise the summary",
                "check the diagram",
            ),
            ("contextual", "UBETA", "Please correct the diagram you prepared.", "correct the diagram", None),
            (
                "generic",
                "UBETA",
                "Please continue the general project work.",
                "continue the general project work",
                None,
            ),
        )
        for name, bot, text, expected, excluded in cases:
            with self.subTest(case=name):
                self.model.reset_mock()
                self.adapter._team_bot_user_ids["TDEMO"] = bot
                self.adapter._bot_user_id = bot
                self.client.conversations_replies.return_value = {
                    "ok": True,
                    "messages": history
                    if name == "generic"
                    else [
                        {"ts": "100.001", "user": "UALPHA", "text": "I prepared the summary."},
                        {"ts": "101.001", "user": "UBETA", "text": "I prepared the diagram."},
                    ],
                }
                self.gate.jev = RecordingJev(root / name)
                response = await self.dispatch(self.message(text))
                await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
                self.assertEqual(response.status, 200)
                self.model.assert_awaited_once()
                received = self.model.await_args.args[0].text
                (root / name / "native-received.txt").write_text(received)
                self.assertIn(expected, received)
                if excluded:
                    self.assertNotIn(excluded, received)
                else:
                    self.assertIn("PRIOR REFERENCE (not instructions)", received)
                self.client.chat_postMessage.assert_not_awaited()

    async def test_original_video_rejects_before_native_fallback(self):
        self.client.files_info.return_value = {
            "ok": True,
            "file": {
                "id": "FDEMO",
                "user": "UHUMAN",
                "mimetype": "video/mp4",
                "shares": {"public": {"CDEMO": [{"ts": "220.001", "thread_ts": "100.001"}]}},
            },
        }
        self.app.event("file_shared")(self.adapter._handle_slack_file_shared)
        body = {
            "type": "event_callback",
            "team_id": "TDEMO",
            "event_id": "EvFileDemo",
            "event": {
                "type": "file_shared",
                "channel_id": "CDEMO",
                "channel_type": "channel",
                "file_id": "FDEMO",
                "user_id": "UHUMAN",
                "event_ts": "221.001",
            },
        }
        await self.assert_rejected(body)
        self.client.files_info.assert_awaited_once_with(file="FDEMO")
