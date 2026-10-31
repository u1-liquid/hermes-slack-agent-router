"""Prepared, UNEXECUTED pinned-host acceptance tests; never run against a live home.

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
from hermes_slack_thread_assignee.store import Store

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
        self.env = patch.dict(os.environ, {"HERMES_HOME": str(self.home)})
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
        self.store = Store(self.root / "state.sqlite3", "demo", "1", (self.a, self.b))
        self.store.initialize()
        self.store.change(self.key, self.a, 0, "synthetic bootstrap")
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
        self.gate = Gate(self.store)
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
        self.assertEqual(self.store.show(self.key), (self.a, 1))

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
        await self.dispatch(self.message("<@UBETA> help"))
        self.assertEqual(len(self.downstream), 1)
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        self.assertEqual(self.store.show(self.key), (self.a, 1))
        self.model.reset_mock()
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
        await self.dispatch(self.message("<@UALPHA> <@UBETA> jointly"))
        self.assertEqual(len(self.downstream), 1)
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        self.assertEqual(self.store.show(self.key), (self.a, 1))

    async def test_main_ordinary_reaches_native_model_boundary(self):
        self.store.change(self.key, self.b, 1, "synthetic transfer")
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
        from hermes_slack_thread_assignee.config import Config

        path = self.root / "config.json"
        path.write_text(
            json.dumps(
                {
                    "database": str(self.store.path),
                    "database_id": "demo",
                    "registry_revision": "1",
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
        for text in ("<@UBETA> /help", "<@UBETA> !help"):
            before = len(self.downstream)
            await self.dispatch(self.message(text))
            await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
            self.assertEqual(len(self.downstream), before + 1)

    async def test_missing_shared_store_is_silent_for_verified_ordinary(self):
        self.store.path.unlink()
        await self.assert_rejected(self.message("ordinary with unavailable store"))
        self.assertFalse(self.store.path.exists())

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
