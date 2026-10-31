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
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from hermes_slack_agent_router.policy import Recipient, Thread

SOURCE = os.environ.get("HERMES_TEST_SOURCE")
if os.environ.get("HERMES_REQUIRE_NATIVE") == "1" and not SOURCE:
    raise RuntimeError("required native suite needs HERMES_TEST_SOURCE")


def native_answers(batch):
    from test_semantic import controlled_answers

    return {name: value["choice"] for name, value in controlled_answers(batch, {})["answers"].items()}


@unittest.skipUnless(SOURCE, "optional local native suite; CI requires it explicitly")
class NativeDispatch(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Capture the caller's documented native secret mapping BEFORE isolating the
        # test home; never write a real key into the fixture home or protocol evidence.
        self.canary_secrets = None
        if os.environ.get("JEV_FICTIONAL_CANARY_DIR"):
            from agent.secret_scope import build_profile_secret_scope
            from hermes_constants import get_hermes_home

            self.canary_secrets = build_profile_secret_scope(get_hermes_home())
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

        from hermes_slack_agent_router.plugin import Gate

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
        from gateway.session_authorities import SessionAuthorities

        self.runner.session_authorities = SessionAuthorities(self.home)
        self.authority = SimpleNamespace(profile_id=str(self.home), retiring=False)
        self.runner.session_authorities.add(self.home, self.authority)
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
        self.adapter._running = True
        self.adapter._socket_mode_task = asyncio.Future()
        self.adapter._handler = SimpleNamespace(client=SimpleNamespace(is_connected=lambda: True))
        self.peer = SlackAdapter(PlatformConfig(extra={"reply_in_thread": True}))
        self.peer.gateway_runner = self.runner
        self.peer._team_bot_user_ids = {"TDEMO": "UALPHA"}
        self.peer._team_clients = {"TDEMO": self.client}
        self.peer._running = True
        self.peer._socket_mode_task = asyncio.Future()
        self.peer._handler = SimpleNamespace(client=SimpleNamespace(is_connected=lambda: True))
        self.peer._app = self.app
        self.peer.set_message_handler(AsyncMock(return_value=None))
        # Two independently authenticated transports can serve the same runtime.
        # Production multiplex owns each via a profile map; the shared runtime is routed below.
        self.peer_home = self.home / "profiles" / "peer"
        self.peer_home.mkdir(parents=True)
        (self.peer_home / "config.yaml").write_text("{}")
        self.runner.config.multiplex_profiles = True
        self.runner.config._runtime_profile_homes = [("default", self.home), ("peer", self.peer_home)]
        self.runner.session_authorities.add(
            self.peer_home, SimpleNamespace(profile_id=str(self.peer_home), retiring=False), name="peer"
        )
        from gateway.profile_routing import ProfileRoute

        self.runner.config.profile_routes = [
            ProfileRoute("peer-to-default", "slack", "default", bot_profile="peer", chat_id="CDEMO")
        ]
        self.peer.set_owner_profile("peer")
        self.runner._profile_adapters = {"peer": {Platform.SLACK: self.peer}}
        self.process_home = patch("hermes_constants.get_process_hermes_home", return_value=self.home)
        self.process_home.start()
        self.addCleanup(self.process_home.stop)
        # Register the actual core listener FIRST, matching the pinned host ordering.
        self.app.event("message")(self.adapter._handle_slack_message)
        self.app.event("app_mention")(self.adapter._handle_slack_message)
        self.gate = Gate()
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

    async def test_latest_seven_plus_root_from_old_cursor_page(self):
        self.enable_semantic()
        records = [
            {"ts": f"{100 + i}.001", "user": "UHUMAN", "text": f"Fictional note {i}"} for i in range(13)
        ]
        # Old media outside the selected view must not restore the short-thread veto.
        records[1]["files"] = [{"id": "FOLD"}]
        self.client.conversations_replies.side_effect = [
            {
                "ok": True,
                "messages": records[:6],
                "has_more": True,
                "response_metadata": {"next_cursor": "fictional-next"},
            },
            {"ok": True, "messages": records[6:], "has_more": False},
        ]
        await self.dispatch(self.message("<@UALPHA> SUMMARY_ONLY; <@UBETA> DIAGRAM_ONLY."))
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        batch = self.gate.jev.ask.await_args.args[0]
        self.assertEqual(
            [h["source_id"] for h in batch["state"]["prior"].values()],
            [records[0]["ts"], *[m["ts"] for m in records[-7:]]],
        )
        self.assertEqual(batch["state"]["root"], "h0")
        self.assertEqual(batch["state"]["recent"], [f"h{i}" for i in range(1, 8)])
        invocations = [
            c
            for c in self.client.conversations_replies.await_args_list
            if c.kwargs.get("latest") == "201.001"
        ]
        self.assertEqual(len(invocations), 2)
        for invocation in invocations:
            self.assertEqual(invocation.kwargs["latest"], "201.001")
            self.assertFalse(invocation.kwargs["inclusive"])
        self.assertEqual(invocations[-1].kwargs["cursor"], "fictional-next")
        self.assertNotIn("SUMMARY_ONLY", self.model.await_args.args[0].text)

    async def test_history_deadline_cancels_native_fetch(self):
        import time

        started, cancelled = asyncio.Event(), asyncio.Event()
        client = AsyncMock()

        async def blocked(**kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        client.conversations_replies.side_effect = blocked
        with self.assertRaises(TimeoutError):
            await self.gate.history(client, self.key, "201.001", time.monotonic() + 1.32)
        self.assertTrue(started.is_set() and cancelled.is_set())
        client.conversations_replies.assert_awaited_once()

    async def test_history_cursor_cutoff_overlap_and_failures(self):
        import time

        from hermes_slack_agent_router.semantic import SemanticError

        root = {"ts": "100.001", "user": "UHUMAN", "text": "Fictional root", "edited": {"ts": "110.001"}}
        child = {"ts": "101.001", "user": "UBETA", "text": "Fictional prior"}

        async def collect(pages):
            client = AsyncMock()
            client.conversations_replies.side_effect = pages
            result = await self.gate.history(client, self.key, "201.001", time.monotonic() + 2.5)
            return result, client

        result, client = await collect(
            [
                {"ok": True, "messages": [root], "has_more": True, "response_metadata": {"next_cursor": "a"}},
                {"ok": True, "messages": [root, child, {"ts": "201.001", "text": "CURRENT"}]},
            ]
        )
        self.assertEqual([h.identity for h in result], ["100.001", "101.001"])
        self.assertEqual(result[0].original, root)
        self.assertEqual(result[0].provenance[0]["field"], "text")
        self.assertEqual(len(result), 2)  # Root overlaps the recent window, represented once.
        self.assertEqual(client.conversations_replies.await_count, 2)
        self.assertEqual(await self.gate.history(client, self.key, "100.001", time.monotonic() + 2.5), ())
        self.assertEqual(client.conversations_replies.await_count, 2)
        bad_pages = [
            [{"ok": False, "messages": [root]}],
            [{"ok": True, "messages": [child]}],
            [{"ok": True, "messages": [root, {**child, "team": "TOTHER"}]}],
            [{"ok": True, "messages": [root, {**child, "channel": "COTHER"}]}],
            [{"ok": True, "messages": [root, {**child, "thread_ts": "99.001"}]}],
            [{"ok": True, "messages": [root, {**child, "ts": "202.001"}]}],
            [{"ok": True, "messages": [child, root]}],
            [{"ok": True, "messages": [root, {**root, "text": "edited differently"}]}],
            [{"ok": True, "messages": [root, {**child, "ts": "NaN"}]}],
            [{"ok": True, "messages": [root, {**child, "user": None}]}],
            [{"ok": True, "messages": [root, {**child, "text": "x" * 6001}]}],
            [{"ok": True, "messages": [root], "has_more": True}],
            [{"ok": True, "messages": [root], "response_metadata": {"next_cursor": 1}}],
            [
                {"ok": True, "messages": [root], "response_metadata": {"next_cursor": "a"}},
                {"ok": True, "messages": [root], "response_metadata": {"next_cursor": "a"}},
            ],
            [
                {"ok": True, "messages": [root], "response_metadata": {"next_cursor": "a"}},
                {"ok": True, "messages": [], "response_metadata": {"next_cursor": "b"}},
            ],
            [{"ok": True, "messages": [root], "extra": "x" * 1048576}],
            [{"ok": True, "messages": [root, {**child, "files": [{"id": "FNEW"}]}]}],
            [
                {
                    "ok": True,
                    "messages": [{"ts": f"{100 + i}.001", "user": "UHUMAN", "text": "n"}],
                    "response_metadata": {"next_cursor": f"page{i}"},
                }
                for i in range(4)
            ],
        ]
        for pages in bad_pages:
            with (
                self.subTest(pages=repr(pages)[:120]),
                self.assertRaises((SemanticError, ValueError, TypeError)),
            ):
                await collect(pages)
        self.enable_semantic()

        async def failed(**kwargs):
            raise OSError("fictional retrieval failure")

        self.client.conversations_replies.side_effect = failed
        await self.assert_rejected(self.message("Please continue."))
        self.gate.jev.ask.assert_not_awaited()
        _, key = self.source_and_key()

        async def pending_then_failed(**kwargs):
            state = self.SessionState()
            state.persistent.update_prompt_pending = True
            self.runner._sessions[key] = state
            raise OSError("fictional retrieval failure")

        self.client.conversations_replies.side_effect = pending_then_failed
        await self.dispatch(self.message("yes"))
        self.assertEqual(self.downstream[-1]["event"]["text"], "yes")

    @unittest.skipUnless(
        os.environ.get("JEV_FICTIONAL_CANARY_DIR"), "explicit fictional root/recent API canary"
    )
    async def test_real_jev_root_fallback_recent_priority_native(self):
        from agent.secret_scope import reset_secret_scope, set_secret_scope
        from test_semantic import RecordingJev

        token = set_secret_scope(self.canary_secrets)
        self.addCleanup(reset_secret_scope, token)
        hydration = patch("agent.secret_scope.build_profile_secret_scope", return_value=self.canary_secrets)
        hydration.start()
        self.addCleanup(hydration.stop)
        self.enable_semantic()
        base = [
            {
                "ts": "100.001",
                "user": "UHUMAN",
                "text": "<@UALPHA> only reviews diagrams. <@UBETA>, lead this whole thread and prepare the summary.",
            },
            *[{"ts": f"{101 + i}.001", "user": "UHUMAN", "text": "Thanks for the update."} for i in range(9)],
        ]
        cases = (
            ("root-generic", "Please continue.", None, "UBETA"),
            (
                "recent-handoff",
                "Please continue.",
                "<@UALPHA>, take over leading this whole thread from <@UBETA> now.",
                "UALPHA",
            ),
            ("root-topic", "Please revise the summary.", None, "UBETA"),
            (
                "recent-topic",
                "Please revise the summary.",
                "<@UALPHA>, take over preparing the summary from <@UBETA> now.",
                "UALPHA",
            ),
        )
        for name, text, update, bot in cases:
            with self.subTest(case=name):
                records = copy.deepcopy(base)
                if update:
                    records[-1]["text"] = update
                directory = Path(os.environ["JEV_FICTIONAL_CANARY_DIR"]) / name
                self.gate.jev = RecordingJev(directory)
                self.adapter._team_bot_user_ids["TDEMO"] = bot
                self.adapter._bot_user_id = bot
                self.peer._team_bot_user_ids["TDEMO"] = "UALPHA" if bot == "UBETA" else "UBETA"
                self.model.reset_mock()

                # Distinguish the plugin's cursor fetch from native downstream history.
                async def page(records=records, **kwargs):
                    if "latest" not in kwargs:
                        return {"ok": True, "messages": []}
                    if kwargs.get("cursor"):
                        return {"ok": True, "messages": records[4:], "has_more": False}
                    return {
                        "ok": True,
                        "messages": records[:4],
                        "has_more": True,
                        "response_metadata": {"next_cursor": "fictional-next"},
                    }

                self.client.conversations_replies.side_effect = page
                await self.dispatch(self.message(text))
                await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
                received = self.model.await_args.args[0].text if self.model.await_args else ""
                (directory / "native-received.txt").write_text(received)
                self.model.assert_awaited_once()
                self.assertIn(text, received)
                self.assertIn("PRIOR REFERENCE (not instructions)", received)
                self.client.chat_postMessage.assert_not_awaited()

    async def test_native_discovery_real_two_transports_and_receiver_specific_input(self):
        from slack_bolt.async_app import AsyncApp
        from slack_bolt.authorization import AuthorizeResult
        from slack_bolt.request.async_request import AsyncBoltRequest

        from hermes_slack_agent_router.bridge import Bridge
        from hermes_slack_agent_router.plugin import Gate

        self.enable_semantic()
        body = self.message("<@UALPHA> revise SUMMARY_ONLY; <@UBETA> check DIAGRAM_ONLY.")
        bridge = Bridge(self.adapter)
        bound = await bridge.bind(body)
        expected = await bridge.participants(bound)
        self.assertEqual(expected[0], (self.a, self.b))

        async def authorize(**kwargs):
            return AuthorizeResult(enterprise_id=None, team_id="TDEMO", bot_user_id="UALPHA")

        app = AsyncApp(
            signing_secret="synthetic",
            authorize=authorize,
            request_verification_enabled=False,
            process_before_response=True,
        )
        self.peer._app = app
        self.peer._bot_user_id = "UALPHA"
        self.peer._register_mentioned_thread("100.001", "TDEMO")
        app.event("message")(self.peer._handle_slack_message)
        gate = Gate()
        gate.jev = self.gate.jev
        gate.wire(app, self.peer)
        self.addCleanup(gate.dispose)
        self.addAsyncCleanup(self.peer.cancel_background_tasks)
        peer_bridge = Bridge(self.peer)
        peer_bound = await peer_bridge.bind(body)
        self.assertEqual((await peer_bridge.participants(peer_bound))[0], expected[0])
        await self.dispatch(body)
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        response = await app.async_dispatch(AsyncBoltRequest(body=json.dumps(body), mode="socket_mode"))
        await asyncio.gather(*tuple(self.peer._session_tasks.values()))
        self.assertEqual(response.status, 200)
        self.model.assert_awaited_once()
        self.peer._message_handler.assert_awaited_once()
        self.assertIn("DIAGRAM_ONLY", self.model.await_args.args[0].text)
        self.assertNotIn("SUMMARY_ONLY", self.model.await_args.args[0].text)
        self.assertIn("SUMMARY_ONLY", self.peer._message_handler.await_args.args[0].text)
        self.assertNotIn("DIAGRAM_ONLY", self.peer._message_handler.await_args.args[0].text)
        self.assertEqual(self.gate.jev.ask.await_args_list[0], self.gate.jev.ask.await_args_list[1])
        self.client.chat_postMessage.assert_not_awaited()
        self.assertFalse(self.adapter._session_tasks)
        self.assertFalse(self.peer._session_tasks)

    async def test_native_factory_no_config_late_rewire_unload_and_same_client_limit(self):
        from hermes_slack_agent_router.plugin import register

        self.enable_semantic()
        self.gate.dispose()
        ctx = Mock()
        register(ctx)
        factory = ctx.register_platform_handler.call_args.args[1]
        manager = Mock()
        manager.get_platform_handler_factories.return_value = [(factory, "slack-agent-router")]
        with (
            patch("hermes_cli.plugins.get_plugin_manager", return_value=manager),
            patch("hermes_slack_agent_router.plugin.JevClient", return_value=self.gate.jev),
        ):
            # Native startup may attach before sockets or the live map are ready.
            with patch.object(self.adapter, "_running", False):
                self.adapter._wire_plugin_handlers(self.app)
            self.adapter.rewire_plugin_handlers()
            self.adapter.rewire_plugin_handlers()
            await self.dispatch(self.message("<@UALPHA> summary; <@UBETA> diagram."))
            await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
            self.gate.jev.ask.assert_awaited_once()
            self.model.assert_awaited_once()
            self.assertNotIn("summary", self.model.await_args.args[0].text)
            ctx.on_unload.call_args.args[0]()
            self.gate.jev.ask.reset_mock()
            self.model.reset_mock()
            # Native dedup still refers to the old factory on this SAME app.
            replacement = Mock()
            register(replacement)
            manager.get_platform_handler_factories.return_value = [
                (replacement.register_platform_handler.call_args.args[1], "slack-agent-router")
            ]
            self.adapter.rewire_plugin_handlers()
            await self.dispatch(self.message("<@UBETA> native after unload"))
            await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
            self.gate.jev.ask.assert_not_awaited()
            self.model.assert_awaited_once()
            replacement.on_unload.call_args.args[0]()

    async def test_native_nondefault_primary_and_event_routed_secondary(self):
        from gateway.profile_routing import ProfileRoute

        from hermes_slack_agent_router.bridge import Bridge

        self.runner._primary_profile_name = "captain"
        self.runner.config._runtime_profile_homes = [("captain", self.home), ("peer", self.peer_home)]
        self.runner.config.profile_routes = []
        bridge = Bridge(self.adapter)
        bound = await bridge.bind(self.message())
        view = (await bridge.participants(bound))[0]
        self.assertEqual(view, (Recipient("TDEMO", "UALPHA", "peer"), Recipient("TDEMO", "UBETA", "captain")))
        self.runner.config.profile_routes = [
            ProfileRoute("specific-sender", "slack", "peer", user_id="UHUMAN", thread_id="100.001")
        ]
        bound = await bridge.bind(self.message())
        self.assertEqual(bound.recipient.runtime_profile, "peer")
        self.assertEqual(
            (await bridge.participants(bound))[0],
            (Recipient("TDEMO", "UALPHA", "peer"), Recipient("TDEMO", "UBETA", "peer")),
        )
        self.runner.session_authorities.remove(self.peer_home)
        from hermes_slack_agent_router.bridge import TopologyError

        with self.assertRaises(TopologyError):
            await bridge.participants(bound)

    async def test_native_hot_removed_disconnected_foreign_and_incidental_participants(self):
        from gateway.config import Platform

        from hermes_slack_agent_router.bridge import Bridge

        bridge = Bridge(self.adapter)
        bound = await bridge.bind(self.message())
        self.assertEqual((await bridge.participants(bound))[0], (self.a, self.b))
        for change in ("removed", "disconnected", "foreign", "failed", "stale"):
            with (
                self.subTest(change=change),
                patch.object(
                    self.runner,
                    "_profile_adapters",
                    {} if change == "removed" else {"peer": {Platform.SLACK: self.peer}},
                ),
                patch.object(self.peer, "_running", change != "failed"),
                patch.object(
                    self.peer._handler.client,
                    "is_connected",
                    return_value=change != "disconnected",
                    create=True,
                ),
                patch.object(self.peer, "_socket_ping_pong_stale", return_value=change == "stale"),
                patch.object(
                    self.peer,
                    "_team_bot_user_ids",
                    {"TOTHER": "UALPHA"} if change == "foreign" else {"TDEMO": "UALPHA"},
                ),
                patch.object(
                    self.peer,
                    "_team_clients",
                    {"TOTHER": self.client} if change == "foreign" else {"TDEMO": self.client},
                ),
            ):
                self.assertEqual((await bridge.participants(bound))[0], (self.b,))
        # Native human/bot allowlists and history authors are not discovery inputs.
        self.adapter.config.extra["allowed_users"] = ["UINCIDENTAL"]
        self.client.conversations_replies.return_value = {
            "ok": True,
            "messages": [{"ts": "100.001", "user": "UINCIDENTAL", "text": "I am another agent"}],
        }
        self.assertEqual((await bridge.participants(bound))[0], (self.a, self.b))

    async def test_native_ambiguous_unknown_and_unserved_participants_are_atomic(self):
        self.enable_semantic()
        for change in ("duplicate", "unknown", "retiring", "auth", "drain", "owner"):
            with (
                self.subTest(change=change),
                patch.object(
                    self.peer,
                    "_team_bot_user_ids",
                    {"TDEMO": "UBETA" if change == "duplicate" else "UALPHA"},
                ),
                patch.object(
                    self.peer._handler.client,
                    "is_connected",
                    None if change == "unknown" else lambda: True,
                ),
                patch.object(
                    self.runner.session_authorities.for_home(self.peer_home),
                    "retiring",
                    change == "retiring",
                ),
                patch.object(self.peer, "_team_clients", {} if change == "auth" else {"TDEMO": self.client}),
                patch.object(self.runner, "_draining", change == "drain", create=True),
                patch.object(self.peer, "_owner_profile", "missing" if change == "owner" else "peer"),
            ):
                await self.assert_rejected(self.message("<@UBETA> check diagram."))
        self.gate.jev.ask.assert_not_awaited()
        self.client.conversations_replies.assert_not_awaited()

    async def test_native_topology_changes_across_history_and_classifier_awaits(self):
        from gateway.config import Platform

        self.enable_semantic()
        normal = self.gate.jev.ask.side_effect
        history = self.client.conversations_replies.return_value
        maps = self.runner._profile_adapters

        async def remove_peer(**kwargs):
            self.runner._profile_adapters = {}
            return history

        self.client.conversations_replies.side_effect = remove_peer
        await self.assert_rejected(self.message("<@UBETA> check diagram."))
        self.gate.jev.ask.assert_not_awaited()
        self.runner._profile_adapters = maps
        self.client.conversations_replies.side_effect = None

        for change in ("removed", "socket", "client", "route"):
            self.model.reset_mock()

            async def mutate(batch, change=change):
                answer = await normal(batch)
                if change == "removed":
                    self.runner._profile_adapters = {}
                elif change == "socket":
                    self.peer._handler = SimpleNamespace(client=SimpleNamespace(is_connected=lambda: True))
                elif change == "client":
                    self.peer._team_clients = {"TDEMO": AsyncMock()}
                else:
                    self.runner.config.profile_routes = []
                return answer

            with (
                self.subTest(change=change),
                patch.object(self.runner, "_profile_adapters", {"peer": {Platform.SLACK: self.peer}}),
                patch.object(self.peer, "_handler", self.peer._handler),
                patch.object(self.peer, "_team_clients", self.peer._team_clients),
                patch.object(self.runner.config, "profile_routes", self.runner.config.profile_routes),
            ):
                self.gate.jev.ask.side_effect = mutate
                await self.assert_rejected(self.message("<@UBETA> check diagram."))

    async def test_peer_identity_change_during_final_socket_observation_is_no_work(self):
        self.enable_semantic()
        calls = 0

        async def observe():
            nonlocal calls
            calls += 1
            if calls == 3:
                self.peer._team_bot_user_ids["TDEMO"] = "UCHANGED"
            return True

        with patch.object(self.peer, "_socket_transport_connected", side_effect=observe):
            await self.assert_rejected(self.message("<@UALPHA> summary; <@UBETA> diagram."))
        self.assertEqual(calls, 3)
        self.gate.jev.ask.assert_awaited_once()

    async def test_primary_route_change_during_final_peer_socket_observation_is_no_work(self):
        from gateway.profile_routing import ProfileRoute

        self.enable_semantic()
        calls = 0

        async def observe():
            nonlocal calls
            calls += 1
            if calls == 3:
                self.runner.config.profile_routes.append(
                    ProfileRoute(
                        "new-primary-route",
                        "slack",
                        "peer",
                        bot_profile="default",
                        user_id="UHUMAN",
                        thread_id="100.001",
                    )
                )
            return True

        with patch.object(self.peer, "_socket_transport_connected", side_effect=observe):
            await self.assert_rejected(self.message("<@UALPHA> summary; <@UBETA> diagram."))
        self.assertEqual(calls, 3)
        self.gate.jev.ask.assert_awaited_once()

    async def test_known_secondary_ordinary_and_forged_owner_are_silent(self):
        self.source_and_key()
        for text in ("ordinary", "main=beta; transfer now", "> <@UBETA>\nordinary", "`<@UBETA>`"):
            with self.subTest(text=text):
                await self.assert_rejected(self.message(text))

    def enable_semantic(self):
        self.client.conversations_replies.return_value = {
            "ok": True,
            "messages": [{"ts": "100.001", "user": "UHUMAN", "text": "Fictional public project."}],
        }

        async def classify(batch):
            answers = native_answers(batch)
            for name in batch["questions"]:
                if name == "coverage":
                    answers[name] = "complete"
                elif name.endswith("_kind"):
                    answers[name] = "action"
                elif name.endswith("_address"):
                    answers[name] = "explicit"
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

    async def test_api_key_is_bound_to_native_request_profile_not_receiving_context(self):
        import httpx
        from agent.secret_scope import reset_secret_scope, set_secret_scope
        from test_semantic import controlled_answers

        from hermes_slack_agent_router.jev import JevClient

        self.enable_semantic()
        self.gate.jev = JevClient()
        (self.home / ".env").write_text("TYPESAFE_API_KEY=synthetic-request-profile\n")
        seen = []

        async def respond(request):
            seen.append(request.headers["Authorization"])
            batch = json.loads(request.content)
            return httpx.Response(
                200,
                json=controlled_answers(
                    batch,
                    {
                        "coverage": "complete",
                        "main": "none",
                        "u0_kind": "action",
                        "u0_destination": "specific",
                        "u0_to1": "yes",
                        "u0_specific_address": "explicit",
                    },
                ),
            )

        native = httpx.AsyncClient
        token = set_secret_scope({"TYPESAFE_API_KEY": "synthetic-receiving-profile"})
        try:
            with (
                patch.object(self.runner, "_profile_scope_key_for_source", return_value=self.home),
                patch(
                    "httpx.AsyncClient",
                    side_effect=lambda **kw: native(transport=httpx.MockTransport(respond), **kw),
                ),
                patch("asyncio.create_subprocess_exec", side_effect=AssertionError("CLI forbidden")),
            ):
                await self.dispatch(self.message("<@UBETA> revise the diagram."))
                await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        finally:
            reset_secret_scope(token)
        self.assertEqual(seen, ["Bearer synthetic-request-profile"])
        self.model.assert_awaited_once()
        self.assertIn("revise the diagram", self.model.await_args.args[0].text)

    async def test_api_real_native_secret_multiplex_isolation_and_missing_scope(self):
        import httpx
        from agent import secret_scope
        from test_semantic import snapshot, two_topic_answers

        from hermes_slack_agent_router.jev import JevClient, JevError
        from hermes_slack_agent_router.semantic import prepare

        batch = prepare(snapshot())
        seen = []
        both_started = asyncio.Event()

        async def respond(request):
            seen.append(request.headers["Authorization"])
            if len(seen) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), 1)
            return httpx.Response(200, json=two_topic_answers(batch))

        native = httpx.AsyncClient
        client = JevClient()
        mode = secret_scope.set_multiplex_context(True)
        try:
            with (
                patch.dict(os.environ, {"TYPESAFE_API_KEY": "synthetic-ambient-forbidden"}),
                patch(
                    "httpx.AsyncClient",
                    side_effect=lambda **kw: native(transport=httpx.MockTransport(respond), **kw),
                ),
                patch("asyncio.create_subprocess_exec", side_effect=AssertionError("CLI forbidden")),
            ):

                async def ask_in_scope(value):
                    token = secret_scope.set_secret_scope({"TYPESAFE_API_KEY": value})
                    try:
                        await client.ask(batch)
                    finally:
                        secret_scope.reset_secret_scope(token)

                await asyncio.gather(ask_in_scope("synthetic-atlas"), ask_in_scope("synthetic-birch"))
                for mapping in ({}, None):
                    token = secret_scope.set_secret_scope(mapping)
                    try:
                        with self.assertRaises(JevError):
                            await client.ask(batch)
                    finally:
                        secret_scope.reset_secret_scope(token)
        finally:
            secret_scope.reset_multiplex_context(mode)
        self.assertCountEqual(seen, ["Bearer synthetic-atlas", "Bearer synthetic-birch"])

    async def test_api_http_fault_is_atomic_silent_and_late_pending_is_preserved(self):
        import httpx
        from agent.secret_scope import reset_secret_scope, set_secret_scope

        from hermes_slack_agent_router.jev import JevClient

        self.enable_semantic()
        self.gate.jev = JevClient()
        native = httpx.AsyncClient
        (self.home / ".env").write_text("TYPESAFE_API_KEY=synthetic-key\n")
        status = 401
        late = False
        _, session_key = self.source_and_key()
        seen = []

        async def respond(request):
            seen.append(request)
            if late:
                state = self.SessionState()
                state.persistent.update_prompt_pending = True
                self.runner._sessions[session_key] = state
            return httpx.Response(status, content=b"synthetic-private-error-body")

        token = set_secret_scope({"TYPESAFE_API_KEY": "synthetic-key"})
        try:
            with (
                patch(
                    "httpx.AsyncClient",
                    side_effect=lambda **kw: native(transport=httpx.MockTransport(respond), **kw),
                ),
                patch("asyncio.create_subprocess_exec", side_effect=AssertionError("CLI forbidden")),
            ):
                for status in (302, 401, 429, 503):
                    await self.assert_rejected(
                        self.message("<@UALPHA> revise summary; <@UBETA> check diagram.")
                    )
                self.assertEqual(len(seen), 4)
                late = True
                body = self.message("<@UBETA> yes")
                await self.dispatch(body)
                self.assertEqual(self.downstream[-1]["event"]["text"], body["event"]["text"])
        finally:
            reset_secret_scope(token)

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
            answers = native_answers(batch)
            answers.update(
                coverage="complete",
                u0_kind="action",
                u1_kind="action",
                u0_destination="specific",
                u0_specific_address="explicit",
                u1_destination="specific",
                u1_specific_address="explicit",
                u0_link1="yes",
                u1_link2="yes",
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

    async def test_semantic_joint_prior_links_reconstructed_on_new_gate(self):

        self.enable_semantic()
        self.client.conversations_replies.return_value["messages"] += [
            {"ts": "101.001", "user": "UALPHA", "text": "Add a legend to the diagram"},
            {"ts": "102.001", "user": "UBETA", "text": "Add arrows to the diagram"},
        ]

        async def grounded(batch):
            answers = native_answers(batch)
            answers.update(
                coverage="complete",
                u0_kind="action",
                u0_destination="specific",
                u0_specific_address="explicit",
                u0_link1="yes",
                u0_link2="yes",
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
        from hermes_slack_agent_router.plugin import Gate

        fresh = Gate()
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
            answers = native_answers(batch)
            answers.update(
                coverage="complete",
                u0_kind="action",
                u0_destination="specific",
                u0_address="absent",
                u0_link0="yes",
                u0_fact0="assign:r1",
            )
            if "u1_kind" in answers:
                answers.update(
                    u0_to1="no",
                    u0_to0="yes",
                    u0_specific_address="explicit",
                    u0_fact0="none",
                    u1_kind="action",
                    u1_destination="specific",
                    u1_specific_address="explicit",
                    u1_link0="yes",
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
        self.peer._team_bot_user_ids["TDEMO"] = "UBETA"
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

    async def test_missing_native_authority_no_context_no_client(self):
        self.authority.retiring = True
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
            result["u1_link0"] = "yes"
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
            answer["u1_link0"] = "yes"
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
        with self.assertLogs("hermes_slack_agent_router.plugin", level="WARNING") as logs:
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
            result = native_answers(batch)
            result.update(
                coverage="complete",
                u0_kind="action",
                u0_destination="specific",
                u0_specific_address="explicit",
                u0_to1="yes",
            )
            return result

        self.gate.jev.ask.side_effect = secondary
        await self.dispatch(self.message("<@UBETA> help"))
        self.assertEqual(len(self.downstream), 1)
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        self.model.reset_mock()

        async def generic(batch):
            result = native_answers(batch)
            result.update(
                coverage="complete",
                main_fact0="assign:r0",
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
            result = native_answers(batch)
            result.update(
                coverage="complete",
                u0_kind="action",
                u0_destination="specific",
                u0_specific_address="explicit",
                u0_to0="yes",
                u0_to1="yes",
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
            result = native_answers(batch)
            result.update(
                coverage="complete",
                main_fact0="assign:r1",
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

    async def test_monitoring_bot_preserves_native_input(self):
        self.enable_semantic()
        self.addCleanup(self.gate.jev.ask.assert_not_awaited)
        await self.dispatch(self.message("monitoring sample", bot_id="BMONITOR", user="UMONITOR"))
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

        from hermes_slack_agent_router.bridge import Bridge, Uncertain

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
        from hermes_slack_agent_router.bridge import Bridge, Uncertain

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
        self.client.conversations_replies.return_value = {"ok": True, "messages": history}
        body = self.message("<@UALPHA> revise summary; <@UBETA> check diagram.")
        await self.dispatch(body)
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        beta_batch = self.gate.jev.ask.await_args.args[0]
        self.adapter._team_bot_user_ids["TDEMO"] = "UALPHA"
        self.adapter._bot_user_id = "UALPHA"
        self.peer._team_bot_user_ids["TDEMO"] = "UBETA"
        self.client.conversations_replies.return_value["messages"] = history
        await self.dispatch(self.message(body["event"]["text"]))
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.assertEqual(self.gate.jev.ask.await_count, 2)
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

    async def test_contradictory_ack_atomic_empty_ack_before_model_busy_or_queue(self):
        self.enable_semantic()

        async def contradictory(batch):
            answer = native_answers(batch)
            answer.update(
                coverage="complete",
                u0_kind="ack",
                u0_mixed="yes",
                u0_destination="specific",
                u0_address="explicit",
                u0_specific_address="explicit",
                u0_link0="yes",
                u0_to0="yes",
                u1_kind="action",
                u1_destination="specific",
                u1_specific_address="explicit",
                u1_to1="yes",
            )
            return answer

        self.gate.jev.ask.side_effect = contradictory
        _, key = self.source_and_key()
        busy = AsyncMock(return_value=True)
        self.adapter.set_busy_session_handler(busy)
        for bot, active in (("UBETA", False), ("UALPHA", False), ("UBETA", True)):
            self.adapter._team_bot_user_ids["TDEMO"] = bot
            self.adapter._bot_user_id = bot
            self.peer._team_bot_user_ids["TDEMO"] = "UALPHA" if bot == "UBETA" else "UBETA"
            if active:
                self.adapter._active_sessions[key] = asyncio.Event()
            await self.assert_rejected(
                self.message("Thanks and <@UALPHA> revise summary; <@UBETA> check diagram.")
            )
        busy.assert_not_awaited()

    async def test_jev_failure_and_late_pending_no_invented_work_or_control_loss(self):
        from hermes_slack_agent_router.jev import JevError

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
        await self.exercise_native_canaries(
            Path(os.environ["JEV_FICTIONAL_CANARY_DIR"]) / "native", real=True
        )

    @unittest.skipUnless(os.environ.get("JEV_RECORDED_CANARY_DIR"), "explicit recorded fictional evidence")
    async def test_recorded_jev_contextual_generic_and_multitopic_native_inputs(self):
        await self.exercise_native_canaries(
            Path(os.environ["JEV_RECORDED_CANARY_DIR"]) / "native", real=False
        )

    async def exercise_native_canaries(self, root, *, real):
        from agent.secret_scope import reset_secret_scope, set_secret_scope
        from test_semantic import RecordingJev

        from hermes_slack_agent_router.jev import validate_answers

        if real:
            token = set_secret_scope(self.canary_secrets)
            self.addCleanup(reset_secret_scope, token)
            # Only fixture hydration is injected: native per-source async scope and
            # get_secret still execute. Never copy the real key into a fixture home.
            hydration = patch(
                "agent.secret_scope.build_profile_secret_scope", return_value=self.canary_secrets
            )
            hydration.start()
            self.addCleanup(hydration.stop)
        self.enable_semantic()
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
                self.peer._team_bot_user_ids["TDEMO"] = "UALPHA" if bot == "UBETA" else "UBETA"
                self.client.conversations_replies.return_value = {
                    "ok": True,
                    "messages": history
                    if name == "generic"
                    else [
                        {"ts": "100.001", "user": "UALPHA", "text": "I prepared the summary."},
                        {"ts": "101.001", "user": "UBETA", "text": "I prepared the diagram."},
                    ],
                }
                if real:
                    self.gate.jev = RecordingJev(root / name)
                else:

                    async def replay(batch, case=root / name):
                        self.assertEqual(
                            {"model": RecordingJev.model, **batch},
                            json.loads((case / "jev-request.json").read_text()),
                        )
                        return validate_answers(batch, json.loads((case / "jev-result.json").read_text()))

                    self.gate.jev = AsyncMock()
                    self.gate.jev.ask.side_effect = replay
                response = await self.dispatch(self.message(text))
                await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
                self.assertEqual(response.status, 200)
                self.model.assert_awaited_once()
                received = self.model.await_args.args[0].text
                if real:
                    (root / name / "native-received.txt").write_text(received)
                else:
                    self.assertEqual(received, (root / name / "native-received.txt").read_text())
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
