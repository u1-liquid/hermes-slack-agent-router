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

    async def test_inaccessible_database_parent_is_silent_and_preserves_state(self):
        parent = self.root / "database-only"
        parent.mkdir(mode=0o700)
        destination = parent / "state.sqlite3"
        self.store.path.rename(destination)
        self.store.path = destination
        original = destination.read_bytes()
        parent.chmod(0o000)
        try:
            await self.assert_rejected(self.message("ordinary inaccessible storage"))
        finally:
            parent.chmod(0o700)
        self.assertEqual(destination.read_bytes(), original)
        self.assertEqual(self.store.show(self.key), (self.a, 1))

    async def test_missing_shared_store_is_silent_for_verified_ordinary(self):
        self.store.path.unlink()
        await self.assert_rejected(self.message("ordinary with unavailable store"))
        self.assertFalse(self.store.path.exists())

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

    async def test_pending_rechecked_after_real_sqlite_decision(self):
        import sqlite3

        from tools import clarify_gateway

        _, key = self.source_and_key()
        original = sqlite3.connect

        def connection(*args, **kwargs):
            db = original(*args, **kwargs)

            def trace(statement):
                if "SELECT evidence,recipients,revision" in statement:
                    clarify_gateway.register("during-store", key, "Choose", ["One", "Two"])

            db.set_trace_callback(trace)
            return db

        self.addCleanup(clarify_gateway.clear_session, key)
        with patch("sqlite3.connect", side_effect=connection):
            await self.dispatch(self.message("late pending reply"))
        self.assertTrue(self.downstream)
        self.assertIsNotNone(clarify_gateway.get_pending_for_session(key, include_choice_prompts=True))

    async def test_api_human_override_retains_verified_human_policy(self):
        self.adapter.config.extra["api_human_users"] = ["UHUMAN"]
        await self.assert_rejected(self.message("ordinary API input", app_id="ADEMO", client_msg_id=""))
        self.assertEqual(self.store.show(self.key), (self.a, 1))

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
        for first, second in ((normal, fallback), (fallback, normal)):
            # Provenance differs, so either arrival order keeps its own evidence.
            a = self.store.decide(first.event, first.recipient)
            b = self.store.decide(second.event, second.recipient)
            self.assertEqual(
                {first.event.provenance: a.action, second.event.provenance: b.action},
                {"message": "allow", "file_shared": "drop"},
            )

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
