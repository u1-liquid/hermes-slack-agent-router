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
from unittest.mock import AsyncMock, Mock, call, patch

from test_semantic import context_priors, context_view

from hermes_slack_agent_router.policy import Recipient, Thread

SOURCE = os.environ.get("HERMES_TEST_SOURCE")
if os.environ.get("HERMES_REQUIRE_NATIVE") == "1" and not SOURCE:
    raise RuntimeError("required native suite needs HERMES_TEST_SOURCE")


def native_answers(batch):
    """Declarative fictional per-user scopes, projected into the target's real wire schema."""
    from test_semantic import controlled_answers

    class FixtureChoices(dict):
        def __init__(self):
            super().__init__(
                (name, value["choice"]) for name, value in controlled_answers(batch, {})["answers"].items()
            )
            self.scopes = {}

        def update(self, *args, **kwargs):
            changes = dict(*args, **kwargs)
            self.scopes.update({key: changes.pop(key) for key in tuple(changes) if key.startswith("for_U")})
            if self.scopes:
                answer = controlled_answers(batch, self.scopes)["answers"]
                super().update(
                    {name: value["choice"] for name, value in answer.items() if name in {"response", "scope"}}
                )
            super().update(changes)

    return FixtureChoices()


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

        from hermes_slack_agent_router.plugin import Gate

        self.SessionState = SessionState
        self.a = Recipient("TDEMO", "UALPHA", "default")
        self.b = Recipient("TDEMO", "UBETA", "default")
        self.key = Thread("TDEMO", "CDEMO", "100.001")

        self.adapter = SlackAdapter(
            PlatformConfig(extra={"reply_in_thread": True, "allowed_users": ["UHUMAN"]})
        )
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
        self.peer = SlackAdapter(PlatformConfig(extra={"reply_in_thread": True, "allowed_users": ["UHUMAN"]}))
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
        # Native status publication is asynchronous; drain its actual writer before
        # restoring the scoped home or deleting the fixture, not via a timing wait.
        from gateway.status import flush_runtime_status_async

        async def finish_status_writes():
            self.assertTrue(await flush_runtime_status_async())

        self.addAsyncCleanup(finish_status_writes)
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

    async def test_latest_seven_plus_root_ignores_older_cursor_page(self):
        self.enable_semantic()
        records = [
            {"ts": f"{100 + i}.001", "user": "UHUMAN", "text": f"Fictional note {i}"} for i in range(13)
        ]
        # Observed native shape: ascending WITHIN newest page, cursor moves older.
        records[0].update(reply_count=173, latest_reply="301.001", thread_ts="100.001")
        records[1]["files"] = [{"id": "FOLD"}]
        self.client.conversations_replies.side_effect = [
            {
                "ok": True,
                "messages": [records[0], *records[-7:]],
                "has_more": True,
                "response_metadata": {"next_cursor": "fictional-older"},
            },
            {"ok": True, "messages": [records[0], *records[1:6]], "has_more": False},
        ]
        await self.dispatch(self.message("<@UALPHA> SUMMARY_ONLY; <@UBETA> DIAGRAM_ONLY."))
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        batch = self.gate.jev.ask.await_args.args[0]
        self.assertEqual(
            [h["timestamp"] for h in context_priors(batch["state"]).values()],
            [records[0]["ts"], *[m["ts"] for m in records[-7:]]],
        )
        self.assertEqual(context_view(batch["state"])["root"]["timestamp"], records[0]["ts"])
        self.assertEqual(
            [h["timestamp"] for h in context_view(batch["state"])["recent"]],
            [m["ts"] for m in records[-7:]],
        )
        invocations = [
            c
            for c in self.client.conversations_replies.await_args_list
            if c.kwargs.get("latest") == "201.001"
        ]
        self.assertEqual(len(invocations), 1)
        self.assertEqual(
            invocations[0].kwargs,
            {
                "channel": "CDEMO",
                "ts": "100.001",
                "latest": "201.001",
                "inclusive": False,
                "limit": 7,
            },
        )
        self.assertNotIn("SUMMARY_ONLY", self.model.await_args.args[0].text)

    async def test_native_definitive_authorization_precedes_classifier_egress(self):
        self.enable_semantic()
        self.adapter.set_authorization_check(lambda *args, **kwargs: None)
        # Native extra allowlist, not a replacement authorization predicate.
        self.adapter.config.extra["allowed_users"] = ["UOTHER"]
        self.peer.config.extra["allowed_users"] = ["UOTHER"]
        body = self.message("<@UALPHA> SUMMARY_ONLY; <@UBETA> DIAGRAM_ONLY.")
        from hermes_slack_agent_router.bridge import Bridge

        bound = await Bridge(self.adapter).bind(body)
        self.assertFalse(self.runner._is_user_authorized_for_source(bound.source))
        await self.assert_rejected(body)
        self.client.conversations_replies.assert_not_awaited()
        self.gate.jev.ask.assert_not_awaited()

    async def test_native_authorization_uses_transport_home_not_thread_routed_runtime(self):
        from gateway.profile_routing import ProfileRoute

        from hermes_slack_agent_router.bridge import Bridge

        self.enable_semantic()
        self.runner.config.profile_routes.insert(
            0, ProfileRoute("thread-runtime", "slack", "peer", chat_id="CDEMO", thread_id="100.001")
        )
        self.adapter.set_authorization_check(lambda *args, **kwargs: None)
        body = self.message("<@UALPHA> SUMMARY_ONLY; <@UBETA> DIAGRAM_ONLY.")
        bound = await Bridge(self.adapter).bind(body)
        self.assertEqual(bound.identity.authorization_home, self.home)
        self.assertEqual(bound.identity.runtime_home, self.peer_home)
        self.adapter.config.extra["allowed_users"] = ["UOTHER"]
        self.peer.config.extra["allowed_users"] = ["UHUMAN"]
        self.assertFalse(self.runner._is_user_authorized_for_source(bound.source))
        await self.assert_rejected(body)
        self.gate.jev.ask.assert_not_awaited()
        self.client.conversations_replies.assert_not_awaited()
        self.adapter.config.extra["allowed_users"] = ["UHUMAN"]
        self.peer.config.extra["allowed_users"] = ["UOTHER"]
        self.assertTrue(self.runner._is_user_authorized_for_source(bound.source))
        await self.dispatch(body)
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        self.assertEqual(self.model.await_args.args[0].source.profile, "peer")
        self.assertEqual(self.model.await_args.args[0].text, "DIAGRAM_ONLY.")

    async def test_native_fitting_preserves_root_current_and_sheds_oldest_whole_prior(self):
        import httpx
        from test_semantic import controlled_answers

        from hermes_slack_agent_router import plugin
        from hermes_slack_agent_router.jev import JevClient, serialize_request
        from hermes_slack_agent_router.semantic import assemble, prepare

        self.supply_native_names()
        records = [
            {"ts": "100.001", "user": "UROOT", "text": "R" * 160000},
            {"ts": "101.001", "user": "UDROPPED", "text": '界"\\\t' * 40000, "metadata": "m" * 70000},
            {"ts": "102.001", "user": "URETAINED", "text": "exact recent context"},
        ]
        self.client.conversations_replies.return_value = {"ok": True, "messages": records}
        text = "<@UBETA> DIAGRAM_ONLY" + "c" * 7000
        body = self.message(text)
        original = copy.deepcopy(body)
        self.gate.jev = JevClient()
        (self.home / ".env").write_text("TYPESAFE_API_KEY=fictional-budget-fixture\n")
        sent, clients = [], []
        native = httpx.AsyncClient

        async def respond(request):
            sent.append(request)
            batch = json.loads(request.content)
            return httpx.Response(200, json=controlled_answers(batch, {"for_UBETA": "u0"}))

        def client(**kwargs):
            value = native(transport=httpx.MockTransport(respond), **kwargs)
            clients.append(value)
            return value

        with (
            patch("httpx.AsyncClient", side_effect=client),
            patch.object(plugin, "assemble", wraps=assemble) as used,
        ):
            await self.dispatch(body)
            await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.assertEqual(len(sent), 1)
        used.assert_called_once()
        fitted = used.call_args.args[0]
        self.assertEqual([h.identity for h in fitted.history], ["100.001", "102.001"])
        self.assertEqual([h.original for h in fitted.history], [records[0], records[2]])
        self.assertEqual(fitted.text, text)
        self.assertEqual(sent[0].content, serialize_request(prepare(fitted, used.call_args.args[1])))
        state = json.loads(sent[0].content)["state"]
        self.assertNotIn("UDROPPED", [p["user_id"] for p in state["people"]])
        self.assertEqual(state["source_selection"]["current_record"], "conversation.records[2]")
        self.assertEqual([r["order"] for r in state["conversation"]["records"]], [0, 1, 2])
        self.assertEqual(body, original)
        self.model.assert_awaited_once()
        self.assertEqual(self.model.await_args.args[0].text, text.removeprefix("<@UBETA> "))
        self.assertTrue(all(c.is_closed for c in clients))

    async def test_native_edit_cancels_active_work_before_handoff_at_each_io_boundary(self):
        import httpx
        from test_semantic import controlled_answers

        from hermes_slack_agent_router.jev import JevClient

        self.supply_native_names()
        info = self.client.users_info.side_effect
        (self.home / ".env").write_text("TYPESAFE_API_KEY=fictional-edit-fixture\n")
        native = httpx.AsyncClient

        class AnswerStream(httpx.AsyncByteStream):
            def __init__(self, batch, wait):
                self.batch, self.wait, self.closed = batch, wait, False

            async def __aiter__(self):
                await self.wait()
                yield json.dumps(controlled_answers(self.batch, {"for_UBETA": "u0"})).encode()

            async def aclose(self):
                self.closed = True

        for ordinal, phase in enumerate(("bind", "history", "metadata", "http")):
            with self.subTest(phase=phase):
                started, cancelled, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
                held = [False]
                clients, streams = [], []

                async def block(started=started, cancelled=cancelled, closed=closed):
                    started.set()
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        cancelled.set()
                        raise
                    finally:
                        closed.set()

                async def directory(*, user, phase=phase, block=block, held=held):
                    target = "UHUMAN" if phase == "bind" else "UBETA"
                    if phase in ("bind", "metadata") and user == target and not held[0]:
                        held[0] = True
                        await block()
                    return await info(user=user)

                async def page(phase=phase, block=block, held=held, **kwargs):
                    if phase == "history" and "latest" in kwargs and not held[0]:
                        held[0] = True
                        await block()
                    return {"ok": True, "messages": [{"ts": "100.001", "user": "UHUMAN", "text": "anchor"}]}

                async def respond(request, phase=phase, block=block, streams=streams):
                    batch = json.loads(request.content)
                    if phase == "http" and "OLD_MARKER" in context_view(batch["state"])["CURRENT"]["text"]:
                        stream = AnswerStream(batch, block)
                        streams.append(stream)
                        return httpx.Response(200, stream=stream)
                    return httpx.Response(200, json=controlled_answers(batch, {"for_UBETA": "u0"}))

                def client(clients=clients, respond=respond, native=native, **kwargs):
                    value = native(transport=httpx.MockTransport(respond), **kwargs)
                    clients.append(value)
                    return value

                self.model.reset_mock()
                self.gate.jev = JevClient()
                self.client.users_info.side_effect = directory
                self.client.conversations_replies.side_effect = page
                body = self.message("<@UBETA> OLD_MARKER", ts=f"{400 + ordinal}.001")
                edited = copy.deepcopy(body)
                edited["event"] = {
                    "type": "message",
                    "subtype": "message_changed",
                    "channel": "CDEMO",
                    "channel_type": "channel",
                    "team": "TDEMO",
                    "ts": f"{500 + ordinal}.001",
                    "message": {
                        **body["event"],
                        "text": "<@UBETA> NEW_MARKER",
                        "edited": {"ts": f"{500 + ordinal}.001"},
                    },
                }
                with patch("httpx.AsyncClient", side_effect=client):
                    task = asyncio.create_task(self.dispatch(body))
                    try:
                        await started.wait()
                        await self.dispatch(edited)
                        self.assertTrue(cancelled.is_set() and closed.is_set())
                        await task
                        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
                    finally:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                self.model.assert_awaited_once()
                self.assertEqual(self.model.await_args.args[0].text, "NEW_MARKER")
                self.assertTrue(all(c.is_closed for c in clients))
                self.assertTrue(all(s.closed for s in streams))

    async def test_native_channel_gate_denials_free_channel_and_actual_wake(self):
        self.enable_semantic()

        async def infer(batch):
            answer = native_answers(batch)
            answer.update(for_UBETA="u0")
            return answer

        self.gate.jev.ask.side_effect = infer
        baseline = dict(self.adapter.config.extra)
        cases = (
            ({"allowed_channels": ["COTHER"]}, "<@UBETA> continue", False),
            ({"ignore_other_user_mentions": True}, "<@UALPHA> continue", False),
            ({"strict_mention": True, "require_mention": True}, "continue", False),
            ({"thread_require_mention": True, "require_mention": False}, "continue", False),
            ({"require_mention": False}, "continue", True),
            ({"require_mention": True}, "continue", True),
        )
        for options, text, allowed in cases:
            with self.subTest(options=options):
                self.adapter.config.extra = {**baseline, **options}
                self.model.reset_mock()
                self.gate.jev.ask.reset_mock()
                with patch.object(
                    self.adapter,
                    "_should_wake_on_unmentioned_message",
                    wraps=self.adapter._should_wake_on_unmentioned_message,
                ) as wake:
                    await self.dispatch(self.message(text))
                    await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
                self.assertEqual(self.gate.jev.ask.await_count, int(allowed))
                self.assertEqual(self.model.await_count, int(allowed))
                if options == {"require_mention": True}:
                    self.assertGreaterEqual(wake.await_count, 1)
        self.adapter.config.extra = baseline

    async def test_native_top_level_source_and_each_peer_thread_coordinates(self):
        from hermes_slack_agent_router.bridge import Bridge

        self.enable_semantic()
        self.adapter.config.extra.update(
            reply_in_thread=False, thread_require_mention=True, require_mention=False
        )
        self.peer.config.extra["reply_in_thread"] = True

        async def infer(batch):
            answer = native_answers(batch)
            answer.update(for_UBETA="u0")
            return answer

        self.gate.jev.ask.side_effect = infer
        for explicit_root in (False, True):
            with self.subTest(explicit_root=explicit_root):
                body = self.message("continue")
                body["event"]["thread_ts"] = body["event"]["ts"] if explicit_root else None
                bound = await Bridge(self.adapter).bind(body)
                self.assertIsNone(bound.source.thread_id)
                self.assertEqual(bound.event.thread.root, body["event"]["ts"])
                with patch.object(self.peer, "build_source", wraps=self.peer.build_source) as peer_source:
                    await Bridge(self.adapter).participants(bound)
                    self.assertEqual(peer_source.call_args.kwargs["thread_id"], body["event"]["ts"])
                self.model.reset_mock()
                await self.dispatch(body)
                await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
                self.model.assert_awaited_once()
                self.assertIsNone(self.model.await_args.args[0].source.thread_id)
                self.client.conversations_replies.assert_not_awaited()

    async def test_native_final_own_current_gate_mutation_is_revalidated(self):
        self.enable_semantic()
        original = self.adapter._channel_gate_allows
        calls = [0]

        async def gate(**kwargs):
            result = await original(**kwargs)
            calls[0] += 1
            if calls[0] == 2:
                self.peer._team_bot_user_ids["TDEMO"] = "UCHANGED"
            return result

        with patch.object(self.adapter, "_channel_gate_allows", side_effect=gate):
            await self.assert_rejected(self.message("<@UALPHA> SUMMARY_ONLY; <@UBETA> DIAGRAM_ONLY."))
        self.assertEqual(calls[0], 2)
        self.gate.jev.ask.assert_awaited_once()

    async def test_native_revision_race_blocks_late_result_and_rapid_edits(self):
        self.enable_semantic()
        started, cancelling, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def infer(batch):
            text = context_view(batch["state"])["CURRENT"]["text"]
            answer = native_answers(batch)
            answer.update(for_UBETA="u0")
            if "OLD_MARKER" in text:
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelling.set()
                    await release.wait()
                    return answer  # Deliberately adversarial transport returning after cancellation.
            return answer

        self.gate.jev.ask.side_effect = infer
        body = self.message("<@UBETA> OLD_MARKER")

        def edit(revision, text):
            value = copy.deepcopy(body)
            value["event"] = {
                "type": "message",
                "subtype": "message_changed",
                "channel": "CDEMO",
                "team": "TDEMO",
                "channel_type": "channel",
                "message": {**body["event"], "text": text, "edited": {"ts": revision}},
            }
            return value

        old = asyncio.create_task(self.dispatch(body))
        middle = latest = None
        try:
            await started.wait()
            middle = asyncio.create_task(self.dispatch(edit("500.001", "<@UBETA> MIDDLE_MARKER")))
            await cancelling.wait()
            # Deliver the latest edit while the original HTTP-equivalent cleanup is held.
            latest_seen = asyncio.Event()
            coordinates = self.gate.coordinates

            def observe_revision(body):
                result = coordinates(body)
                if result is not None and str(result[3]) == "501.001":
                    latest_seen.set()
                return result

            with patch.object(self.gate, "coordinates", side_effect=observe_revision):
                latest = asyncio.create_task(self.dispatch(edit("501.001", "<@UBETA> LATEST_MARKER")))
                await latest_seen.wait()  # Actual latest-revision intake, not a timer/poll.
                release.set()
                await asyncio.gather(old, middle, latest)
            await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        finally:
            release.set()
            for task in (old, middle, latest):
                if task is not None:
                    task.cancel()
            await asyncio.gather(*(t for t in (old, middle, latest) if t is not None), return_exceptions=True)
        self.model.assert_awaited_once()
        self.assertEqual(self.model.await_args.args[0].text, "LATEST_MARKER")
        self.assertFalse(self.gate.active)
        self.assertFalse(self.adapter._background_tasks)

    async def test_native_equal_duplicate_and_new_message_do_not_cancel_active_revision(self):
        self.enable_semantic()
        started, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        seen = [0]

        async def infer(batch):
            seen[0] += 1
            answer = native_answers(batch)
            answer.update(for_UBETA="u0")
            if seen[0] == 1:
                started.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
            return answer

        self.gate.jev.ask.side_effect = infer
        body = self.message("<@UBETA> ORIGINAL_MARKER", edited={"ts": "300.001"})
        old = asyncio.create_task(self.dispatch(body))
        try:
            await started.wait()
            duplicate = copy.deepcopy(body)
            duplicate["event"]["type"] = "app_mention"
            duplicate["event_id"] = "EvDuplicateIndependentEnvelope"
            await self.dispatch(duplicate)
            await self.dispatch(self.message("<@UBETA> OTHER_MESSAGE"))
            self.assertFalse(cancelled.is_set())
            release.set()
            await old
            await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        finally:
            release.set()
            old.cancel()
            await asyncio.gather(old, return_exceptions=True)
        self.assertEqual(seen[0], 3)
        self.assertEqual(self.model.await_count, 2)  # Native dedup, not exactly-once inference.
        self.assertFalse(self.gate.active)

    async def test_native_revision_validation_and_unfurl_event_ts_do_not_cancel(self):
        self.enable_semantic()
        started, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def infer(batch):
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            answer = native_answers(batch)
            answer.update(for_UBETA="u0")
            return answer

        self.gate.jev.ask.side_effect = infer
        body = self.message("<@UBETA> ORIGINAL_MARKER", edited={"ts": "300.001"})
        old = asyncio.create_task(self.dispatch(body))
        try:
            await started.wait()
            for mutation in ("sender", "root", "older", "malformed"):
                newer = copy.deepcopy(body)
                nested = {**body["event"], "edited": {"ts": "500.001"}}
                if mutation == "sender":
                    nested["user"] = "UOTHER"
                elif mutation == "root":
                    nested["thread_ts"] = "99.001"
                elif mutation == "older":
                    nested["edited"] = {"ts": "250.001"}
                else:
                    nested["edited"] = {"ts": "not-a-native-timestamp"}
                newer["event"] = {
                    "type": "message",
                    "subtype": "message_changed",
                    "channel": "CDEMO",
                    "team": "TDEMO",
                    "message": nested,
                }
                await self.dispatch(newer)
                self.assertFalse(cancelled.is_set())
                self.gate.jev.ask.assert_awaited_once()
            unfurl = copy.deepcopy(body)
            nested = dict(body["event"])
            nested.pop("edited")
            unfurl["event"] = {
                "type": "message",
                "subtype": "message_changed",
                "channel": "CDEMO",
                "team": "TDEMO",
                "event_ts": "999.001",
                "message": nested,
            }
            await self.dispatch(unfurl)
            self.assertFalse(cancelled.is_set())
            self.gate.jev.ask.assert_awaited_once()
            release.set()
            await old
            await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        finally:
            release.set()
            old.cancel()
            await asyncio.gather(old, return_exceptions=True)
        self.assertFalse(self.gate.active)

    async def test_native_protected_oversize_is_local_no_credential_no_http(self):
        from agent import secret_scope

        from hermes_slack_agent_router.jev import JevClient

        for mode in ("current", "root"):
            with self.subTest(mode=mode):
                self.gate.jev = JevClient()
                self.client.conversations_replies.return_value = {
                    "ok": True,
                    "messages": [
                        {"ts": "100.001", "user": "UHUMAN", "text": "r" * (600000 if mode == "root" else 1)}
                    ],
                }
                text = "<@UBETA> " + ("x" * 200000 if mode == "current" else "continue")
                with (
                    patch.object(secret_scope, "get_secret", wraps=secret_scope.get_secret) as secrets,
                    patch("httpx.AsyncClient") as client,
                ):
                    with self.assertLogs("hermes_slack_agent_router.plugin", level="WARNING") as logs:
                        await self.assert_rejected(self.message(text))
                    self.assertTrue(
                        any("stage=fit reason=unsupported-request-size" in line for line in logs.output)
                    )
                    self.assertNotIn(call("TYPESAFE_API_KEY"), secrets.call_args_list)
                    client.assert_not_called()

    async def test_native_edit_pending_or_command_never_resurrects_old_body(self):
        _, key = self.source_and_key()
        for mode in ("pending", "command"):
            with self.subTest(mode=mode):
                self.enable_semantic()
                started, cancelled = asyncio.Event(), asyncio.Event()

                async def infer(batch, mode=mode, started=started, cancelled=cancelled):
                    started.set()
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        cancelled.set()
                        if mode == "pending":
                            state = self.SessionState()
                            state.persistent.update_prompt_pending = True
                            self.runner._sessions[key] = state
                        raise

                self.gate.jev.ask.side_effect = infer
                body = self.message("<@UBETA> OLD_MUST_NOT_RETURN")
                newer = copy.deepcopy(body)
                newer["event"] = {
                    "type": "message",
                    "subtype": "message_changed",
                    "channel": "CDEMO",
                    "channel_type": "channel",
                    "team": "TDEMO",
                    "message": {
                        **body["event"],
                        "text": "<@UBETA> /help" if mode == "command" else "LATEST_CONTROL_REPLY",
                        "edited": {"ts": "500.001"},
                    },
                }
                before = len(self.downstream)
                task = asyncio.create_task(self.dispatch(body))
                try:
                    await started.wait()
                    await self.dispatch(newer)
                    await task
                    await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    self.runner._sessions.pop(key, None)
                self.assertTrue(cancelled.is_set())
                self.gate.jev.ask.assert_awaited_once()
                self.assertNotIn("OLD_MUST_NOT_RETURN", json.dumps(self.downstream[before:]))
                self.assertFalse(self.gate.active)

    async def test_native_shutdown_and_unload_own_only_active_evaluations(self):
        import httpx
        from test_semantic import controlled_answers

        from hermes_slack_agent_router.jev import JevClient

        class AnswerStream(httpx.AsyncByteStream):
            def __init__(self, batch, wait):
                self.batch, self.wait, self.closed = batch, wait, False

            async def __aiter__(self):
                await self.wait()
                yield json.dumps(controlled_answers(self.batch, {"for_UBETA": "u0"})).encode()

            async def aclose(self):
                self.closed = True

        for mode in ("history-shutdown", "http-shutdown", "history-unload"):
            with self.subTest(mode=mode):
                started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
                clients, streams = [], []
                self.enable_semantic()
                native = httpx.AsyncClient

                async def block(started=started, release=release, finished=finished):
                    started.set()
                    try:
                        await release.wait()
                    finally:
                        finished.set()

                async def page(mode=mode, block=block, **kwargs):
                    if mode != "http-shutdown" and "latest" in kwargs:
                        await block()
                    return {"ok": True, "messages": [{"ts": "100.001", "user": "UHUMAN", "text": "anchor"}]}

                async def respond(request, block=block, streams=streams):
                    batch = json.loads(request.content)
                    stream = AnswerStream(batch, block)
                    streams.append(stream)
                    return httpx.Response(200, stream=stream)

                def client(clients=clients, respond=respond, native=native, **kwargs):
                    value = native(transport=httpx.MockTransport(respond), **kwargs)
                    clients.append(value)
                    return value

                self.client.conversations_replies.side_effect = page
                if mode == "http-shutdown":
                    self.gate.jev = JevClient()
                    (self.home / ".env").write_text("TYPESAFE_API_KEY=fictional-shutdown-fixture\n")
                self.model.reset_mock()
                with patch("httpx.AsyncClient", side_effect=client):
                    task = asyncio.create_task(self.dispatch(self.message("<@UBETA> DIAGRAM_ONLY.")))
                    try:
                        await started.wait()
                        self.assertTrue(self.adapter._background_tasks)
                        self.assertFalse(self.adapter._session_tasks)
                        if mode == "history-unload":
                            self.gate.dispose()  # Actual synchronous registered unload action; no cancellation.
                            self.assertFalse(finished.is_set())
                            release.set()
                            await task
                            self.gate.jev.ask.assert_not_awaited()
                        else:
                            self.runner._draining = True
                            await self.adapter.cancel_background_tasks()
                            with self.assertRaises(asyncio.CancelledError):
                                await task
                        self.assertTrue(finished.is_set())
                    finally:
                        release.set()
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                        self.runner._draining = False
                self.assertTrue(all(c.is_closed for c in clients))
                self.assertFalse(self.gate.active)
                self.assertTrue(all(s.closed for s in streams))
                self.assertFalse(self.adapter._background_tasks)
                self.model.assert_not_awaited()

    async def test_delayed_native_routing_completes_without_plugin_time_cutoffs(self):
        self.enable_semantic()
        self.supply_native_names()
        info = self.client.users_info.side_effect
        classify = self.gate.jev.ask.side_effect
        records = [
            {"ts": "100.001", "user": "UHUMAN", "text": "Fictional root"},
            {"ts": "101.001", "user": "UOUTSIDE", "text": "Fictional context"},
        ]
        loop = asyncio.get_running_loop()
        for ordinal, phase in enumerate(("bind", "history", "recipient", "people", "classifier")):
            with self.subTest(phase=phase):
                started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

                async def delayed(started=started, release=release, finished=finished):
                    started.set()
                    await release.wait()
                    finished.set()

                async def page(phase=phase, delayed=delayed, **kwargs):
                    if "latest" not in kwargs:
                        return {"ok": True, "messages": []}
                    if phase == "history":
                        await delayed()
                    return {"ok": True, "messages": records}

                async def directory(*, user, phase=phase, delayed=delayed):
                    if (phase, user) in (("bind", "UHUMAN"), ("recipient", "UBETA"), ("people", "UOUTSIDE")):
                        await delayed()
                    return await info(user=user)

                async def infer(batch, phase=phase, delayed=delayed):
                    if phase == "classifier":
                        await delayed()
                    return await classify(batch)

                self.client.conversations_replies.side_effect = page
                self.client.users_info.side_effect = directory
                self.gate.jev.ask.side_effect = infer
                self.model.reset_mock()
                now = [loop.time()]
                with patch.object(loop, "time", side_effect=lambda now=now: now[0]):
                    task = asyncio.create_task(
                        self.dispatch(
                            self.message(
                                "<@UALPHA> SUMMARY_ONLY; <@UBETA> DIAGRAM_ONLY.", ts=f"{300 + ordinal}.001"
                            )
                        )
                    )
                    timer = None
                    try:
                        await started.wait()
                        # Advance the scheduler past ALL former .75/1/1.2/2.5s
                        # cutoffs, then release this actual I/O producer; no sleep.
                        timer = loop.call_at(now[0] + 9, release.set)
                        now[0] += 10
                        await task
                        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
                    finally:
                        if timer:
                            timer.cancel()
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                self.assertTrue(finished.is_set(), "required delayed producer was abandoned")
                self.model.assert_awaited_once()
                self.assertEqual(self.model.await_args.args[0].text, "DIAGRAM_ONLY.")
                state = context_view(self.gate.jev.ask.await_args.args[0]["state"])
                self.assertEqual(state["participants"]["UBETA"]["real_name"], "柚原こはる")
                self.assertEqual(state["participants"]["UOUTSIDE"]["kind"], "bot")
                self.assertFalse(self.adapter._pending_messages)
                self.client.chat_postMessage.assert_not_awaited()

    async def test_acquisition_error_and_caller_cancellation_drain_all_owned_reads(self):
        self.enable_semantic()
        assert isinstance(self.gate.jev, AsyncMock)
        self.supply_native_names()
        info = self.client.users_info.side_effect
        _, key = self.source_and_key()
        for mode in ("error", "cancel", "cancel-pending"):
            with self.subTest(mode=mode):
                history_started, metadata_started = asyncio.Event(), asyncio.Event()
                history_done, metadata_done, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

                async def page(started=history_started, release=release, done=history_done, **kwargs):
                    started.set()
                    try:
                        await release.wait()
                        raise OSError("fictional native transport failure")
                    finally:
                        done.set()

                async def directory(*, user, started=metadata_started, done=metadata_done):
                    if user != "UBETA":
                        return await info(user=user)
                    started.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        done.set()

                self.client.conversations_replies.side_effect = page
                self.client.users_info.side_effect = directory
                task = asyncio.create_task(self.dispatch(self.message("<@UBETA> DIAGRAM_ONLY.")))
                try:
                    await asyncio.gather(history_started.wait(), metadata_started.wait())
                    if mode == "error":
                        release.set()
                        response = await task
                        self.assertEqual((response.status, response.body), (200, ""))
                    else:
                        if mode == "cancel-pending":
                            state = self.SessionState()
                            state.persistent.update_prompt_pending = True
                            self.runner._sessions[key] = state
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    self.runner._sessions.pop(key, None)
                self.assertTrue(history_done.is_set() and metadata_done.is_set())
                self.gate.jev.ask.assert_not_awaited()
                self.model.assert_not_awaited()
                self.assertFalse(self.adapter._pending_messages)
                self.assertFalse(self.downstream)
                self.client.chat_postMessage.assert_not_awaited()

    async def test_newest_page_delivers_exact_scoped_input(self):
        self.enable_semantic()
        records = [
            {
                "ts": "100.001",
                "user": "UHUMAN",
                "text": "Fictional root",
                "reply_count": 173,
                "latest_reply": "301.001",
                "thread_ts": "100.001",
            },
            *[
                {
                    "type": "message",
                    "ts": ts,
                    "user": "UHUMAN",
                    "text": "Fictional note",
                    "thread_ts": "100.001",
                    "team": "TDEMO",
                }
                for ts in ("105.001", "106.950", "121.003", "169.901", "201.003", "298.001", "299.999")
            ],
        ]
        body = self.message("<@UALPHA> SUMMARY_ONLY; <@UBETA> DIAGRAM_ONLY.", ts="300.001")

        async def page(**kwargs):
            if "latest" not in kwargs:
                return {"ok": True, "messages": []}  # Separate downstream native hydration.

            # Root identity must not depend on being the first element.
            return {
                "ok": True,
                "messages": [*records[1:], records[0]],
                "has_more": True,
                "response_metadata": {"next_cursor": "opaque-older-page"},
            }

        self.client.conversations_replies.side_effect = page
        await self.dispatch(body)
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        self.assertEqual(self.model.await_args.args[0].text, "DIAGRAM_ONLY.")
        state = context_view(self.gate.jev.ask.await_args.args[0]["state"])
        self.assertEqual([h["timestamp"] for h in context_priors(state).values()], [m["ts"] for m in records])
        self.assertEqual(state["root"]["timestamp"], records[0]["ts"])
        self.assertEqual([h["timestamp"] for h in state["recent"]], [m["ts"] for m in records[1:]])
        calls = [c for c in self.client.conversations_replies.await_args_list if "latest" in c.kwargs]
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0].kwargs,
            {
                "channel": "CDEMO",
                "ts": "100.001",
                "latest": "300.001",
                "inclusive": False,
                "limit": 7,
            },
        )
        self.client.conversations_history.assert_not_awaited()
        self.client.chat_postMessage.assert_not_awaited()
        self.client.chat_postEphemeral.assert_not_awaited()

    async def test_extra_page_record_requires_exactly_one_root_and_retains_context_guards(self):
        self.enable_semantic()
        records = [{"ts": f"{100 + i}.001", "user": "UHUMAN", "text": "Fictional note"} for i in range(10)]
        self.client.conversations_history.return_value = {"ok": True, "messages": []}
        for data in (
            {"ok": True, "messages": records[1:9]},  # Eight replies with no root.
            {"ok": True, "messages": records[:9]},  # Root is not permission for nine records.
            {"ok": True, "messages": [records[0], *records[:7]]},  # Two roots in an extra-sized page.
            {"ok": True, "messages": [{**records[0], "team": "TOTHER"}, *records[1:8]]},
            {"ok": True, "messages": records[:8], "has_more": True},  # Malformed cursor metadata.
            {"ok": True, "messages": records[1:8]},  # Missing root with unsuccessful exact lookup.
            {"ok": True, "messages": [records[0], None]},
            {"ok": True, "messages": [records[0], {**records[0], "text": "Conflicting root"}]},
            {"ok": True, "messages": [records[0], {**records[1], "ts": "301.001"}]},
        ):
            with self.subTest(shape=str(data)[:100]):
                self.client.conversations_replies.return_value = data
                await self.assert_rejected(self.message("<@UBETA> DIAGRAM_ONLY.", ts="300.001"))
        self.gate.jev.ask.assert_not_awaited()

    async def test_ordinary_reply_after_native_bot_markdown_reaches_assigned_model(self):
        from slack_sdk.web.async_slack_response import AsyncSlackResponse

        self.enable_semantic()
        root = {"ts": "100.001", "user": "UHUMAN", "text": "Beta, lead this whole thread."}
        prior = {
            "type": "message",
            "ts": "101.001",
            "user": "UBETA",
            "bot_id": "BDEMO",
            "app_id": "ADEMO",
            "text": "Fictional native response.",
            # Actual pinned adapter output, not an all-human hand-written history.
            "blocks": self.adapter._markdown_block_payload("Fictional native response."),
        }
        self.client.conversations_replies.return_value = AsyncSlackResponse(
            client=self.client,
            http_verb="GET",
            api_url="https://slack.com/api/conversations.replies",
            req_args={},
            data={"ok": True, "messages": [root, prior], "has_more": False},
            headers={},
            status_code=200,
        )

        async def generic(batch):
            result = native_answers(batch)
            result.update(
                for_UBETA="u0",
                u0_prior0="include",
            )
            return result

        self.gate.jev.ask.side_effect = generic
        await self.dispatch(self.message("Please continue."))
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        self.assertIn("Please continue.", self.model.await_args.args[0].text)
        prior_state = context_priors(self.gate.jev.ask.await_args.args[0]["state"])
        self.assertEqual(prior_state["h1"]["text"], prior["blocks"][0]["text"])
        self.client.chat_postMessage.assert_not_awaited()
        self.assertFalse(self.adapter._pending_messages)

    async def test_prior_bot_section_preserves_leaf_provenance_and_scoped_delivery(self):
        self.enable_semantic()
        prior = {
            "type": "message",
            "ts": "101.001",
            "user": "UBETA",
            "bot_id": "BDEMO",
            "text": "Notification fallback must not replace the visible diagram.",
            "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "DIAGRAM_REFERENCE"}}],
        }
        self.client.conversations_replies.return_value["messages"].append(prior)
        classify = self.gate.jev.ask.side_effect

        async def referenced(batch):
            answer = await classify(batch)
            answer.update(u1_prior1="include")
            return answer

        self.gate.jev.ask.side_effect = referenced
        await self.dispatch(self.message("<@UALPHA> SUMMARY_ONLY; <@UBETA> DIAGRAM_ONLY."))
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        received = self.model.await_args.args[0].text
        self.assertIn("DIAGRAM_ONLY", received)
        self.assertIn("DIAGRAM_REFERENCE", received)
        self.assertNotIn("SUMMARY_ONLY", received)
        self.assertNotIn("Notification fallback", received)

    async def test_prior_context_lossless_and_current_negative(self):
        from hermes_slack_agent_router.bridge import canonical_text
        from hermes_slack_agent_router.semantic import SemanticError

        prior = {
            "ts": "101.001",
            "user": "UBETA",
            "text": "NOTIFICATION_NOT_VISIBLE",
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "DIAGRAM_REFERENCE", "verbatim": True},
                },
                {
                    "type": "context",
                    "block_id": "footer",
                    "elements": [
                        {"type": "mrkdwn", "text": "CONTEXT_A", "verbatim": False},
                        {"type": "plain_text", "text": "CONTEXT_B 🦊", "emoji": True},
                    ],
                },
            ],
        }
        text, provenance = canonical_text(prior, prior=True)
        self.assertEqual(text, "DIAGRAM_REFERENCE\nCONTEXT_A\nCONTEXT_B 🦊")
        leaves = [p for p in provenance if p["kind"] != "separator"]
        self.assertEqual(
            [p["field"] for p in leaves],
            ["blocks[0].text.text", "blocks[1].elements[0].text", "blocks[1].elements[1].text"],
        )
        self.assertEqual([text[p["start"] : p["end"]] for p in leaves], [p["raw"] for p in leaves])
        self.assertTrue(all(p["source_start"] == 0 and p["source_end"] == len(p["raw"]) for p in leaves))
        with self.assertRaises(SemanticError):
            canonical_text(prior)
        good = prior["blocks"][1]
        for bad in (
            {**good, "accessory": {}},
            {**good, "block_id": 7},
            {**good, "elements": []},
            {**good, "elements": "hidden"},
            {**good, "elements": [{"type": "image", "image_url": "https://example.com/visible"}]},
            {**good, "elements": [{"type": "mrkdwn", "text": ["hidden"]}]},
            {**good, "elements": [{"type": "mrkdwn", "text": "x", "verbatim": 1}]},
            {**good, "elements": [{"type": "plain_text", "text": "x", "emoji": "true"}]},
            {**good, "elements": [{"type": "mrkdwn", "text": "x", "unknown": "visible"}]},
            {**good, "elements": [{"type": "plain_text", "text": "x", "verbatim": True}]},
        ):
            with self.subTest(shape=bad), self.assertRaises(SemanticError):
                canonical_text({**prior, "blocks": [prior["blocks"][0], bad]}, prior=True)
        self.enable_semantic()
        self.client.conversations_replies.return_value["messages"].append(prior)
        classify = self.gate.jev.ask.side_effect

        async def referenced(batch):
            result = await classify(batch)
            result.update(for_UBETA="u0", u0_prior1="include")
            return result

        self.gate.jev.ask.side_effect = referenced
        await self.dispatch(self.message("<@UBETA> DIAGRAM_ONLY."))
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        delivered = self.model.await_args.args[0].text
        self.assertIn("CONTEXT_A\nCONTEXT_B 🦊", delivered)
        self.assertNotIn("NOTIFICATION_NOT_VISIBLE", delivered)
        self.assertFalse(self.adapter._pending_messages)
        self.client.chat_postMessage.assert_not_awaited()

    async def test_history_api_failures_are_distinguished_without_private_error_text(self):
        from slack_sdk.errors import SlackApiError

        self.enable_semantic()
        for code, expected in (
            ("missing_scope", "context-fetch-not-permitted"),
            ("not_allowed_token_type", "context-fetch-not-permitted"),
            ("ratelimited", "context-fetch-rate-limited"),
            ("private-unrecognized-error", "context-fetch-api-failed"),
        ):
            self.client.conversations_replies.side_effect = SlackApiError(
                "private error body", {"ok": False, "error": code}
            )
            with (
                self.subTest(code=code),
                self.assertLogs("hermes_slack_agent_router.plugin", level="WARNING") as logs,
            ):
                await self.assert_rejected(self.message("<@UBETA> continue fictional work"))
            self.assertIn(expected, logs.output[0])
            self.assertNotIn("private", "".join(logs.output))
        self.client.conversations_replies.side_effect = TimeoutError("private transport detail")
        with self.assertLogs("hermes_slack_agent_router.plugin", level="WARNING") as logs:
            await self.assert_rejected(self.message("<@UBETA> continue fictional work"))
        self.assertIn("context-fetch-transport-timeout", logs.output[0])
        self.gate.jev.ask.assert_not_awaited()

    async def test_prior_block_support_does_not_relax_current_or_skip_unknown_content(self):
        self.enable_semantic()
        for block in (
            {"type": "markdown", "text": "<@UBETA> current hidden content"},
            {"type": "section", "text": {"type": "mrkdwn", "text": "<@UBETA> current hidden content"}},
        ):
            await self.assert_rejected(self.message("fallback", blocks=[block]))
        root = self.client.conversations_replies.return_value["messages"][0]
        for prior in (
            {
                "ts": "101.001",
                "user": "UBETA",
                "blocks": [{"type": "image", "image_url": "https://example.com/a.png"}],
            },
            {"ts": "101.001", "bot_id": "BDEMO", "text": "No verified user identity"},
            {
                "ts": "101.001",
                "user": "UBETA",
                "blocks": [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": "note"},
                        "fields": [{"type": "mrkdwn", "text": "must not be dropped"}],
                    }
                ],
            },
        ):
            self.client.conversations_replies.return_value = {"ok": True, "messages": [root, prior]}
            await self.assert_rejected(self.message("<@UBETA> continue"))
        self.gate.jev.ask.assert_not_awaited()

    async def test_review_short_nonterminal_page_must_not_be_complete_latest_seven(self):
        """Retained QA detector: a repeating incomplete response cannot confer completeness."""

        from hermes_slack_agent_router.semantic import SemanticError

        root = {"ts": "100.001", "user": "UHUMAN", "text": "Fictional root"}
        replies = [{"ts": f"{110 + i}.001", "user": "UHUMAN", "text": "Fictional recent"} for i in range(7)]
        for messages in (
            [root, *replies[-6:]],
            [root, *replies[-6:], replies[-1]],
            [root, *replies[-6:], {"ts": "201.001", "text": "CURRENT"}],
        ):
            with self.subTest(messages=messages):
                client = AsyncMock()
                client.conversations_replies.return_value = {
                    "ok": True,
                    "messages": messages,
                    "has_more": True,
                    "response_metadata": {"next_cursor": "opaque-older"},
                }
                with self.assertRaises(SemanticError):
                    await self.gate.history(client, self.key, "201.001")

    async def test_review_short_nonterminal_native_input_must_not_reach_classifier(self):
        """Retained QA native detector: an uncompletable tail must not dispatch partial work."""
        self.enable_semantic()
        self.client.conversations_replies.return_value = {
            "ok": True,
            "messages": [
                {"ts": "100.001", "user": "UHUMAN", "text": "Fictional root"},
                *[{"ts": f"{110 + i}.001", "user": "UHUMAN", "text": "Fictional recent"} for i in range(6)],
            ],
            "has_more": True,
            "response_metadata": {"next_cursor": "opaque-older"},
        }
        await self.assert_rejected(self.message("<@UALPHA> SUMMARY_ONLY; <@UBETA> DIAGRAM_ONLY."))
        assert isinstance(self.gate.jev, AsyncMock)
        self.gate.jev.ask.assert_not_awaited()

    async def test_short_tail_pages_complete_before_semantic_delivery(self):
        self.enable_semantic()
        assert isinstance(self.gate.jev, AsyncMock)
        root = {"ts": "100.001", "user": "UHUMAN", "text": "Fictional root"}
        recent = [{"ts": f"{110 + i}.001", "user": "UHUMAN", "text": "Fictional recent"} for i in range(6)]
        older = {"ts": "109.001", "user": "UHUMAN", "text": "Fictional older"}
        for index, (name, first, continuation) in enumerate(
            (
                ("short", [root, *recent], {"has_more": True}),
                ("dedup", [root, *recent, recent[-1]], {"has_more": True}),
                ("cutoff", [root, *recent, {"ts": "201.001", "text": "CURRENT"}], {"has_more": True}),
                ("cursor_only", [root, *recent], {}),
                ("cursor_over_false", [root, *recent], {"has_more": False}),
            )
        ):
            with self.subTest(shape=name):
                cutoff = f"{201 + index}.001"
                if name == "cutoff":
                    first[-1]["ts"] = cutoff
                self.model.reset_mock()
                self.gate.jev.ask.reset_mock()
                self.client.conversations_replies.reset_mock()

                async def page(name=name, first=first, continuation=continuation, **kwargs):
                    if "latest" not in kwargs:
                        return {"ok": True, "messages": []}
                    if name == "short":
                        loop = asyncio.get_running_loop()
                        ready = loop.create_future()
                        timer = loop.call_later(0.30, ready.set_result, None)
                        try:
                            await ready  # Causal network-response release, not idle polling.
                        finally:
                            timer.cancel()
                    if "cursor" not in kwargs:
                        return {
                            "ok": True,
                            "messages": first,
                            **continuation,
                            "response_metadata": {"next_cursor": "opaque-older"},
                        }
                    self.assertEqual(kwargs["cursor"], "opaque-older")
                    return {
                        "ok": True,
                        "messages": [root, older],
                        "has_more": True,
                        "response_metadata": {"next_cursor": "unneeded-older"},
                    }

                self.client.conversations_replies.side_effect = page
                started = asyncio.get_running_loop().time()
                await self.dispatch(self.message("<@UALPHA> SUMMARY_ONLY; <@UBETA> DIAGRAM_ONLY.", ts=cutoff))
                await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
                if name == "short":
                    print(
                        "short-tail controlled native complete seconds:",
                        asyncio.get_running_loop().time() - started,
                    )
                self.model.assert_awaited_once()
                assert self.model.await_args is not None
                self.assertEqual(self.model.await_args.args[0].text, "DIAGRAM_ONLY.")
                state = context_view(self.gate.jev.ask.await_args.args[0]["state"])
                self.assertEqual(
                    [h["timestamp"] for h in context_priors(state).values()],
                    [root["ts"], older["ts"], *[m["ts"] for m in recent]],
                )
                calls = [
                    c.kwargs
                    for c in self.client.conversations_replies.await_args_list
                    if "latest" in c.kwargs
                ]
                query = {
                    "channel": "CDEMO",
                    "ts": "100.001",
                    "latest": cutoff,
                    "inclusive": False,
                    "limit": 7,
                }
                self.assertEqual(calls, [query, {**query, "cursor": "opaque-older"}])
                self.client.conversations_history.assert_not_awaited()

    async def test_short_tail_continuation_bounds_and_validation(self):

        from hermes_slack_agent_router.semantic import SemanticError

        root = {"ts": "100.001", "user": "UHUMAN", "text": "Fictional root"}
        recent = [{"ts": f"{110 + i}.001", "user": "UHUMAN", "text": "Fictional recent"} for i in range(6)]
        older = {"ts": "109.001", "user": "UHUMAN", "text": "Fictional older"}

        def page(messages, cursor=""):
            return {"ok": True, "messages": messages, "response_metadata": {"next_cursor": cursor}}

        async def collect(pages):
            client = AsyncMock()
            client.conversations_replies.side_effect = pages
            client.conversations_history.return_value = page([root])
            result = await self.gate.history(client, self.key, "201.001")
            return result, client

        first = page([root, *recent], "a")
        # Empty and duplicate-only pages with advancing cursors are not terminal.
        result, client = await collect(
            [first, page([], "b"), page([root, recent[0]], "c"), page([root, older], "unneeded")]
        )
        self.assertEqual([h.identity for h in result], [root["ts"], older["ts"], *[m["ts"] for m in recent]])
        self.assertEqual(client.conversations_replies.await_count, 4)
        client.conversations_history.assert_not_awaited()
        # The older page can overfill the missing slot; choose its newest, not first.
        result, client = await collect(
            [
                first,
                page(
                    [
                        root,
                        {**older, "ts": "107.001", "files": [{"id": "FUNSELECTED"}]},
                        {**older, "ts": "108.001"},
                        older,
                    ],
                    "unneeded",
                ),
            ]
        )
        self.assertEqual([h.identity for h in result], [root["ts"], older["ts"], *[m["ts"] for m in recent]])
        self.assertEqual(client.conversations_replies.await_count, 2)
        for terminal in (page([]), page([root, recent[0]])):
            result, client = await collect([first, terminal])
            self.assertEqual([h.identity for h in result], [root["ts"], *[m["ts"] for m in recent]])
            self.assertEqual(client.conversations_replies.await_count, 2)
        result, client = await collect([page(recent, "a"), page([older], "unneeded")])
        self.assertEqual([h.identity for h in result], [root["ts"], older["ts"], *[m["ts"] for m in recent]])
        client.conversations_history.assert_awaited_once_with(
            channel="CDEMO", oldest="100.001", inclusive=True, limit=1
        )

        for suffix in (
            [page([], "a")],  # Repeated cursor, no progress.
            [page([], "b"), page([], "a")],  # Cursor loop.
            [page([], "b"), page([], "c"), page([], "d")],  # Four-call cap, still incomplete.
            [page([{**root, "text": "conflicting root"}, older])],
            [page([{**recent[0], "text": "conflicting reply"}])],
            [page([older, {**older, "ts": "108.001"}])],  # Within-page disorder.
            [page([{**older, "ts": "120.001"}])],  # New record is not older.
            [page([{**older, "ts": "202.001"}])],
            [page([{**older, "team": "TOTHER"}])],
            [page([{**older, "thread_ts": "99.001"}])],
            [page([{**older, "channel": "COTHER"}])],
            [page([{**older, "ts": "NaN"}])],
            [page([None])],
            [{"ok": True, "messages": [], "has_more": True}],
            [{"ok": True, "messages": [], "response_metadata": {"next_cursor": 1}}],
            [{"ok": True, "messages": [older], "extra": "x" * 1048576}],
        ):
            with (
                self.subTest(suffix=repr(suffix)[:120]),
                self.assertRaises((SemanticError, ValueError, TypeError)),
            ):
                await collect([first, *suffix])
        # Four replies calls leave no fifth call for a missing-root fallback.
        with self.assertRaisesRegex(SemanticError, "incomplete-context"):
            await collect([page(recent, "a"), page([], "b"), page([], "c"), page([older])])

    async def test_history_caller_cancellation_drains_native_fetch(self):
        started, cancelled = asyncio.Event(), asyncio.Event()
        client = AsyncMock()

        async def blocked(**kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        async def fill(**kwargs):
            if "cursor" in kwargs:
                return await blocked(**kwargs)
            return {"ok": True, "messages": [], "response_metadata": {"next_cursor": "older"}}

        for stage in ("replies", "fill", "root"):
            with self.subTest(stage=stage):
                started, cancelled = asyncio.Event(), asyncio.Event()
                client = AsyncMock()
                if stage == "replies":
                    client.conversations_replies.side_effect = blocked
                elif stage == "fill":
                    client.conversations_replies.side_effect = fill
                else:
                    client.conversations_replies.return_value = {"ok": True, "messages": []}
                    client.conversations_history.side_effect = blocked
                task = asyncio.create_task(self.gate.history(client, self.key, "201.001"))
                try:
                    await started.wait()
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                self.assertTrue(started.is_set() and cancelled.is_set())
                self.assertEqual(client.conversations_replies.await_count, 2 if stage == "fill" else 1)
                if stage == "root":
                    client.conversations_history.assert_awaited_once_with(
                        channel="CDEMO", oldest="100.001", inclusive=True, limit=1
                    )

    async def test_history_cutoff_duplicates_exact_root_and_failures(self):

        from hermes_slack_agent_router.semantic import SemanticError

        root = {"ts": "100.001", "user": "UHUMAN", "text": "Fictional root", "edited": {"ts": "110.001"}}
        child = {"ts": "101.001", "user": "UBETA", "text": "Fictional prior"}

        async def collect(page, fallback=None, key=None, cutoff="201.001"):
            client = AsyncMock()
            client.conversations_replies.return_value = page
            client.conversations_history.return_value = fallback or {"ok": True, "messages": []}
            result = await self.gate.history(client, key or self.key, cutoff)
            return result, client

        result, client = await collect(
            {"ok": True, "messages": [root, root, child, child, {"ts": "201.001", "text": "CURRENT"}]}
        )
        self.assertEqual([h.identity for h in result], ["100.001", "101.001"])
        self.assertEqual(result[0].original, root)
        self.assertEqual(result[0].provenance[0]["field"], "text")
        client.conversations_replies.assert_awaited_once()
        client.conversations_history.assert_not_awaited()
        self.assertEqual(await self.gate.history(client, self.key, "100.001"), ())
        client.conversations_replies.assert_awaited_once()
        for messages in ([root], [root, child]):
            result, _ = await collect({"ok": True, "messages": messages})
            self.assertEqual([h.identity for h in result], [m["ts"] for m in messages])

        # Preserve observed native timestamps/metadata; private bodies/authors are not fixtures.
        timestamps = [
            "1793407089.735139",
            "1793528555.349569",
            "1793528646.854749",
            "1793528708.749289",
            "1793528729.649269",
            "1793528730.841309",
            "1793528827.079949",
            "1793528956.853099",
        ]
        wire: list[dict] = [
            {
                "type": "message",
                "ts": ts,
                "thread_ts": timestamps[0],
                "team": "TDEMO",
                "user": "UHUMAN",
                "text": "Fictional public fixture",
            }
            for ts in timestamps
        ]
        wire[0].update(reply_count=173, latest_reply="1793529442.829789")
        result, client = await collect(
            {
                "ok": True,
                "messages": wire,
                "has_more": True,
                "response_metadata": {"next_cursor": "opaque-older"},
            },
            key=Thread("TDEMO", "CDEMO", timestamps[0]),
            cutoff="1793528957.605949",
        )
        self.assertEqual([h.identity for h in result], timestamps)
        client.conversations_replies.assert_awaited_once()
        client.conversations_history.assert_not_awaited()

        result, client = await collect(
            {"ok": True, "messages": [child]}, {"ok": True, "messages": [root], "has_more": True}
        )
        self.assertEqual([h.identity for h in result], [root["ts"], child["ts"]])
        client.conversations_replies.assert_awaited_once()
        client.conversations_history.assert_awaited_once_with(
            channel="CDEMO", oldest="100.001", inclusive=True, limit=1
        )
        for bad_root in (
            [],
            [child],
            [root, child],
            [{**root, "team": "TOTHER"}],
            [{**root, "channel": "COTHER"}],
            [{**root, "thread_ts": "99.001"}],
            [{**root, "files": [{"id": "FROOT"}]}],
            [None],
        ):
            with self.subTest(root=bad_root), self.assertRaises((SemanticError, ValueError, TypeError)):
                await collect({"ok": True, "messages": [child]}, {"ok": True, "messages": bad_root})

        bad_pages = [
            {"ok": False, "messages": [root]},
            {"ok": True, "messages": [child]},
            *[
                {"ok": True, "messages": [root, {**child, field: value}]}
                for field, value in (
                    ("team", "TOTHER"),
                    ("channel", "COTHER"),
                    ("thread_ts", "99.001"),
                    ("ts", "202.001"),
                    ("ts", "NaN"),
                    ("user", None),
                    ("text", None),
                    ("files", [{"id": "FNEW"}]),
                    ("attachments", [{"text": "hidden"}]),
                )
            ],
            {"ok": True, "messages": [root, {**child, "ts": "102.001"}, child]},
            {"ok": True, "messages": [root, {**root, "text": "edited differently"}]},
            {"ok": True, "messages": [root, child, {**child, "text": "conflicting reply"}]},
            {"ok": True, "messages": [root], "has_more": True},
            {"ok": True, "messages": [root], "has_more": "true"},
            {"ok": True, "messages": [root], "response_metadata": {"next_cursor": 1}},
            {"ok": True, "messages": [root], "response_metadata": {"next_cursor": "x" * 2049}},
            {"ok": True, "messages": [root], "extra": "x" * 1048576},
        ]
        for page in bad_pages:
            with (
                self.subTest(page=repr(page)[:120]),
                self.assertRaises((SemanticError, ValueError, TypeError)),
            ):
                await collect(page)
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
        requests = [c.args[0] for c in self.gate.jev.ask.await_args_list]
        self.assertEqual(context_view(requests[0]["state"]), context_view(requests[1]["state"]))
        self.assertEqual([q["state"]["whoami"]["user_id"] for q in requests], ["UBETA", "UALPHA"])
        self.client.chat_postMessage.assert_not_awaited()
        self.assertFalse(self.adapter._session_tasks)
        self.assertFalse(self.peer._session_tasks)

    @unittest.skipUnless(os.environ.get("HERMES_NATIVE_PLUGIN_DIR"), "explicit native Git installation")
    async def test_installed_git_root_factory_delivers_only_recipient_input(self):
        import importlib

        from hermes_cli.plugin_dev import doctor_plugin
        from hermes_cli.plugins import PluginManager

        installed = Path(os.environ["HERMES_NATIVE_PLUGIN_DIR"]).resolve()
        self.enable_semantic()
        self.gate.dispose()
        self.client.conversations_replies.return_value["messages"].append(
            {
                "ts": "101.001",
                "user": "UBETA",
                "bot_id": "BDEMO",
                "text": "Native bot prior",
                "blocks": self.adapter._markdown_block_payload("Native bot prior"),
            }
        )
        manager = PluginManager()
        manifests = manager._scan_directory(installed.parent, source="user")
        matches = [m for m in manifests if m.key == "slack-agent-router"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(Path(matches[0].path).resolve(), installed)
        manager._load_plugin(matches[0])
        loaded = manager._plugins["slack-agent-router"]
        self.assertIsNone(loaded.error)
        registration = loaded.module.register
        package = importlib.import_module(registration.__module__)
        self.assertTrue(Path(package.__file__).resolve().is_relative_to(installed))
        plugin = importlib.import_module(registration.__module__ + ".plugin")
        factory, identity = manager.get_platform_handler_factories("slack")[0]
        self.assertEqual(identity, "slack-agent-router")
        self.assertTrue(Path(factory.__code__.co_filename).resolve().is_relative_to(installed))
        with patch.object(plugin, "JevClient", return_value=self.gate.jev):
            factory(self.app, self.adapter)
        await self.dispatch(self.message("<@UALPHA> SUMMARY_ONLY; <@UBETA> DIAGRAM_ONLY."))
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        received = self.model.await_args.args[0].text
        self.assertIn("DIAGRAM_ONLY", received)
        self.assertNotIn("SUMMARY_ONLY", received)
        self.model.reset_mock()
        # This factory is attached after the fixture's observer middleware. Observe
        # the real listener/model/queue boundary, not that earlier test observer.
        response = await self.dispatch(self.message("<@UALPHA> SUMMARY_ONLY."))
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.assertEqual((response.status, response.body), (200, ""))
        self.model.assert_not_awaited()
        self.assertFalse(self.adapter._pending_messages)
        self.assertFalse(self.adapter._pending_text_batches)
        self.client.chat_postMessage.assert_not_awaited()
        self.client.chat_postEphemeral.assert_not_awaited()
        (installed.parent.parent / "router-native-delivery.json").write_text(
            json.dumps(
                {
                    "plugin_id": identity,
                    "package_path": package.__file__,
                    "factory_path": factory.__code__.co_filename,
                    "received_text": received,
                    "nonrecipient_model_calls": self.model.await_count,
                    "slack_io": "controlled fictional SDK responses",
                    "classifier": "controlled finite answers",
                },
                indent=2,
            )
        )
        report = doctor_plugin(installed)
        self.assertTrue(report.ok, report.format_text())

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
            answers.update(for_UALPHA="u0")
            if "u1" in batch["state"]["source_selection"]["segments"]:
                answers.update(for_UBETA="u1")
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
                        "for_UBETA": "u0",
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

        batch = prepare(snapshot(), snapshot().recipients[0])
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
        self.adapter.config.extra["allowed_users"] = ["UOTHER"]
        self.adapter.set_authorization_check(lambda *args, **kwargs: False)
        await self.assert_rejected(self.message("<@UBETA> check diagram"))
        self.gate.jev.ask.assert_not_awaited()
        self.client.conversations_replies.assert_not_awaited()
        self.adapter.config.extra["allowed_users"] = ["UHUMAN"]
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
                for_UALPHA="u0",
                for_UBETA="u1",
                u0_prior1="include",
                u1_prior2="include",
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
                for_UALPHA="u0",
                for_UBETA="u0",
                u0_prior1="include",
                u0_prior2="include",
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
                for_UBETA="u0",
                u0_prior0="include",
            )
            if "u1" in batch["state"]["source_selection"]["segments"]:
                answers.update(
                    for_UALPHA="u0",
                    for_UBETA="u1",
                    u1_prior0="include",
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

    async def test_complete_input_excludes_native_backfill_and_keeps_selected_inert_prior(self):
        from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest

        from hermes_slack_agent_router.plugin import register

        self.enable_semantic()
        records = [
            {"ts": "100.001", "user": "UALPHA", "text": "UNSELECTED_SUMMARY_PRIOR: Alpha owns the summary."},
            {"ts": "101.001", "user": "UALPHA", "text": "SUPERSEDED_DIAGRAM_PRIOR: Alpha owned the diagram."},
            {
                "ts": "102.001",
                "user": "UBETA",
                "text": "SELECTED_DIAGRAM_PRIOR: Beta takes over the diagram.",
            },
        ]
        self.client.conversations_replies.return_value = {"ok": True, "messages": records}
        classify = self.gate.jev.ask.side_effect

        async def selected(batch):
            answer = await classify(batch)
            answer.update(
                u1_prior2="include",
            )
            return answer

        self.gate.jev.ask.side_effect = selected
        manager = PluginManager()
        register(PluginContext(PluginManifest(name="slack-agent-router"), manager))
        assembled, backfills = [], []

        async def receive(event):
            from hermes_constants import get_hermes_home

            backfills.append(event.channel_context)
            async with self.runner._async_profile_scope_for_source(event.source):
                profile = self.adapter._canonicalize(event.source).runtime_profile
                self.assertEqual(get_hermes_home(), self.peer_home if profile == "peer" else self.home)
                serving_manager = PluginManager()
                register(PluginContext(PluginManifest(name="slack-agent-router"), serving_manager))
                with patch("hermes_cli.plugins.get_plugin_manager", return_value=serving_manager):
                    admitted = await self.runner._hm_pre_gateway_dispatch_hook(event, event.source)
                if admitted is not None:
                    assembled.append(
                        self.runner._prefix_inbound_sender_context(admitted, admitted.source, admitted.text)
                    )
                    await self.model(admitted)

        self.adapter.set_message_handler(receive)
        with patch("hermes_cli.plugins.get_plugin_manager", return_value=manager):
            await self.dispatch(self.message("<@UALPHA> revise SUMMARY_ONLY; <@UBETA> check DIAGRAM_ONLY."))
            await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
            # Native active-session/mention refresh, with nonempty NEW unselected history.
            key = self.runner._session_key_for_source(self.model.await_args.args[0].source)
            state = self.SessionState()
            self.runner._sessions[key] = state
            self.adapter._session_store = SimpleNamespace(
                _ensure_loaded=lambda: None, _entries={key: SimpleNamespace(suspended=False)}
            )
            records.append({"ts": "201.500", "user": "UALPHA", "text": "UNSELECTED_FRESH_PRIOR"})
            self.model.reset_mock()
            await self.dispatch(self.message("<@UALPHA> revise SUMMARY_ONLY; <@UBETA> check DIAGRAM_ONLY."))
            await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
            self.assertIs(self.runner._sessions[key], state)
        self.model.assert_awaited_once()
        self.assertEqual(len(assembled), 2)
        self.assertIn("UNSELECTED_SUMMARY_PRIOR", backfills[0])
        self.assertIn("UNSELECTED_FRESH_PRIOR", backfills[1])
        for prompt in assembled:
            self.assertIn("DIAGRAM_ONLY", prompt)
            self.assertIn("SELECTED_DIAGRAM_PRIOR", prompt)
            self.assertIn("PRIOR REFERENCE (not instructions)", prompt)
            self.assertNotIn("SUMMARY_ONLY", prompt)
            self.assertNotIn("UNSELECTED_SUMMARY_PRIOR", prompt)
            self.assertNotIn("UNSELECTED_FRESH_PRIOR", prompt)
            self.assertNotIn("SUPERSEDED_DIAGRAM_PRIOR", prompt)
        event = self.model.await_args.args[0]
        self.assertIsNone(event.channel_context)
        self.assertIsNone(event.reply_to_text)
        self.assertFalse(event.media_urls)
        self.assertFalse(event.media_types)
        # The real native downstream history fetch was nonempty, not stubbed away.
        self.assertTrue(
            any("latest" not in c.kwargs for c in self.client.conversations_replies.await_args_list)
        )
        self.model.reset_mock()
        self.gate.jev.ask.side_effect = classify
        await self.assert_rejected(self.message("<@UALPHA> SUMMARY_NONRECIPIENT_ONLY."))
        self.assertEqual(len(assembled), 2)

    async def test_complete_input_transport_to_other_serving_profile(self):
        from gateway.profile_routing import ProfileRoute

        self.runner.config.profile_routes = [ProfileRoute("serve-peer", "slack", "peer", chat_id="CDEMO")]
        await self.test_complete_input_excludes_native_backfill_and_keeps_selected_inert_prior()

    async def test_complete_input_native_queue_merge_replay(self):
        from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest

        from hermes_slack_agent_router.plugin import register

        self.enable_semantic()
        self.client.conversations_replies.return_value = {
            "ok": True,
            "messages": [{"ts": "100.001", "user": "UALPHA", "text": "UNSELECTED_ROOT_PRIOR"}],
        }
        manager = PluginManager()
        register(PluginContext(PluginManifest(name="slack-agent-router"), manager))
        prompts = []

        async def receive(event):
            self.assertIn("UNSELECTED_ROOT_PRIOR", event.channel_context)
            admitted = await self.runner._hm_pre_gateway_dispatch_hook(event, event.source)
            self.assertIsNotNone(admitted)
            prompts.append(
                self.runner._prefix_inbound_sender_context(admitted, admitted.source, admitted.text)
            )
            self.assertIsNone(admitted.channel_context)
            json.dumps(admitted.raw_message)  # No Python transport witness survives admission.
            await self.model(admitted)

        self.adapter.set_message_handler(receive)
        _, key = self.source_and_key()
        self.adapter._active_sessions[key] = asyncio.Event()
        self.adapter._busy_text_debounce_seconds = 0
        for suffix in ("ONE", "TWO"):
            await self.dispatch(self.message(f"<@UALPHA> SUMMARY_{suffix}; <@UBETA> DIAGRAM_{suffix}."))
        pending = self.adapter.get_pending_message(key)
        self.assertIsNotNone(pending)
        self.assertIn("DIAGRAM_ONE", pending.text)
        self.assertIn("DIAGRAM_TWO", pending.text)
        self.assertNotIn("SUMMARY", pending.text)
        self.model.assert_not_awaited()
        self.adapter._active_sessions.pop(key)
        with patch("hermes_cli.plugins.get_plugin_manager", return_value=manager):
            await self.adapter.handle_message(pending)
            await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        self.assertNotIn("UNSELECTED_ROOT_PRIOR", prompts[0])
        self.assertNotIn("SUMMARY", prompts[0])
        self.assertIn("DIAGRAM_ONE", prompts[0])
        self.assertIn("DIAGRAM_TWO", prompts[0])

    async def test_backfill_witness_binding_json_forgery_and_native_snapshot(self):
        from gateway.session import SessionStore
        from gateway.session_envelope import _snapshot_native

        from hermes_slack_agent_router.plugin import _PROJECTION, constrain_backfill

        self.enable_semantic()
        self.client.conversations_replies.return_value = {
            "ok": True,
            "messages": [{"ts": "100.001", "user": "UALPHA", "text": "UNSELECTED_ROOT_PRIOR"}],
        }
        await self.dispatch(self.message("<@UALPHA> SUMMARY_ONLY; <@UBETA> DIAGRAM_ONLY."))
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        original = self.model.await_args.args[0]
        self.assertIn("UNSELECTED_ROOT_PRIOR", original.channel_context)
        for field, value in (
            ("user_id", "UOTHER"),
            ("chat_id", "COTHER"),
            ("thread_id", "99.001"),
            ("scope_id", "TOTHER"),
            ("message_id", "999.001"),
        ):
            with self.subTest(field=field):
                event = copy.deepcopy(original)
                setattr(event.source, field, value)
                self.assertEqual(constrain_backfill(event, self.runner)["action"], "skip")
                self.assertNotIn(_PROJECTION, event.raw_message)
        wrong_runtime = copy.deepcopy(original)
        self.assertEqual(constrain_backfill(wrong_runtime, object())["action"], "skip")
        for forgery in (None, "proof", {"recipient": "UBETA"}, ["proof"]):
            event = copy.deepcopy(original)
            event.raw_message[_PROJECTION] = forgery
            before = event.channel_context
            self.assertIsNone(constrain_backfill(event, self.runner))
            self.assertEqual(event.channel_context, before, "JSON cannot claim a routed projection")
        event = copy.deepcopy(original)
        event.media_urls = ["https://fictional.invalid/root.png"]
        event.media_types = ["image/png"]
        event.media_text_inlined = [False]
        event.reply_to_text = "UNSELECTED_REPLY"
        self.assertIsNone(constrain_backfill(event, self.runner))
        self.assertIsNone(event.channel_context)
        self.assertIsNone(event.reply_to_text)
        self.assertFalse(event.media_urls)
        self.assertNotIn(_PROJECTION, event.raw_message)
        self.runner.session_store = SessionStore(self.home / "sessions", config=self.runner.config)
        self.addCleanup(self.runner.session_store._db.close)
        # Exercise the actual native persistence codec, with the already-validated
        # source supplied. This is serialization proof, not a substitute auth test.
        snapshot = _snapshot_native(self.runner, event, None, encoded_source=event.source.to_dict())
        encoded = json.dumps(snapshot)
        self.assertNotIn("UNSELECTED_ROOT_PRIOR", encoded)
        self.assertNotIn(_PROJECTION, encoded)
        self.assertIn("DIAGRAM_ONLY", encoded)

    async def test_classifier_failure_diagnostics_are_stage_specific_and_payload_free(self):
        from hermes_slack_agent_router.jev import JevError
        from hermes_slack_agent_router.semantic import SemanticError

        self.enable_semantic()
        assert isinstance(self.gate.jev, AsyncMock)
        for error, expected in (
            (JevError("Jev HTTP request failed", status=422), "reason=http-rejected status=422"),
            (JevError("synthetic-private"), "reason=unclassified status=0"),
            (SemanticError("synthetic-private"), "reason=semantic-invalid status=0"),
            (TimeoutError("synthetic-private"), "reason=transport-timeout status=0"),
        ):
            self.gate.jev.ask.side_effect = error
            with self.assertLogs("hermes_slack_agent_router.plugin", level="WARNING") as logs:
                await self.assert_rejected(self.message("<@UBETA> revise PRIVATE_CURRENT."))
            output = "\n".join(logs.output)
            self.assertIn("classifier-failed stage=inference", output)
            self.assertIn(expected, output)
            self.assertIn("elapsed_ms=", output)
            self.assertIn("questions=", output)
            self.assertNotIn("synthetic-private", output)
            self.assertNotIn("PRIVATE_CURRENT", output)

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
            result["u1_prior0"] = "include"
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
            answer["u1_prior0"] = "include"
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
        state = context_view(self.gate.jev.ask.await_args.args[0]["state"])
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
                for_UBETA="u0",
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
                for_UALPHA="u0",
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
                for_UALPHA="u0",
                for_UBETA="u0",
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
                for_UBETA="u0",
                u0_prior0="include",
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

    async def test_response_native_receiver_single_threshold(self):
        from test_semantic import controlled_answers

        from hermes_slack_agent_router.jev import validate_answers

        self.enable_semantic()
        complete = self.install_scoped_receiver()
        self.client.conversations_replies.return_value = {
            "ok": True,
            "messages": [{"ts": "100.001", "user": "UHUMAN", "text": "Fictional root."}],
        }
        intent, confidence = "yes", 0.701

        async def actual(batch):
            self.assertEqual(set(batch["questions"]["response"]["criteria"]), {"yes", "no"})
            self.assertNotIn("self_recipient", batch["questions"])
            self.assertNotIn("projection", batch["questions"])
            self.assertEqual(batch["state"]["whoami"]["user_id"], "UBETA")
            raw = controlled_answers(batch, {"response": intent, "scope": "u0"})
            raw["answers"]["response"]["confidence"] = confidence
            return validate_answers(batch, raw)

        self.gate.jev.ask.side_effect = actual
        for index, (intent, confidence, admitted) in enumerate(
            (
                ("yes", 0.499, False),
                ("yes", 0.500, False),
                ("yes", 0.501, True),
                ("no", 0.01, False),
                ("no", 0.99, False),
                ("yes", 0.01, False),
                ("yes", 0.99, True),
            ),
            250,
        ):
            self.model.reset_mock()
            complete.clear()
            await self.dispatch(self.message("<@UBETA> revise the summary.", ts=f"{index}.001"))
            await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
            with self.subTest(choice=intent, confidence=confidence):
                self.assertEqual(self.model.await_count, int(admitted))
                self.assertEqual(
                    complete, ["[Human | Slack user <@UHUMAN>] revise the summary."] if admitted else []
                )
                self.assertFalse(self.adapter._pending_messages or self.adapter._pending_text_batches)
        self.client.chat_postMessage.assert_not_awaited()
        self.client.chat_postEphemeral.assert_not_awaited()

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
        # Replay the SAME source to the other simulated native receiver. Its
        # independent transport has not consumed the first receiver's dedup key.
        from gateway.platforms.helpers import MessageDeduplicator

        self.adapter._dedup = MessageDeduplicator()
        await self.dispatch(self.message(body["event"]["text"], ts=body["event"]["ts"]))
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.assertEqual(self.gate.jev.ask.await_count, 2)
        alpha_batch = self.gate.jev.ask.await_args.args[0]
        self.assertEqual(context_view(beta_batch["state"]), context_view(alpha_batch["state"]))
        self.assertEqual(beta_batch["questions"], alpha_batch["questions"])
        self.assertEqual(beta_batch["state"]["whoami"]["user_id"], "UBETA")
        self.assertEqual(alpha_batch["state"]["whoami"]["user_id"], "UALPHA")
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

    async def test_unselected_response_units_empty_ack_before_model_busy_or_queue(self):
        self.enable_semantic()

        async def contradictory(batch):
            answer = native_answers(batch)
            answer.update(
                for_UALPHA="unresolved",
                for_UBETA="unresolved",
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

    async def test_native_label_cold_lookup_scope_rejection_and_parallel_completion(self):
        import time

        from hermes_slack_agent_router.bridge import Bridge

        bridge = Bridge(self.adapter)
        bound = await bridge.bind(self.message("柚原こはるさん、図を修正してください。"))
        topology = await bridge.participants(bound)
        before = dict(self.adapter._user_name_cache)
        active = set()
        all_started = asyncio.Event()

        async def info(*, user):
            active.add(user)
            if len(active) == len(topology[0]):
                all_started.set()
            await all_started.wait()
            return {
                "ok": True,
                "user": {
                    "id": user,
                    "team_id": "TDEMO",
                    "is_bot": True,
                    "profile": {"display_name": "柚原こはる" if user == "UBETA" else "榎森あおい"},
                    "name": "native.beta" if user == "UBETA" else "native.alpha",
                    "real_name": "別の実名",
                },
            }

        self.client.users_info.side_effect = info
        started = time.monotonic()
        whoami = dict(await bridge.recipient_metadata(bound, topology))
        elapsed = time.monotonic() - started
        self.assertEqual(active, {"UALPHA", "UBETA"})

        self.assertEqual(
            whoami["UBETA"],
            {
                "user_id": "UBETA",
                "username": "native.beta",
                "display_name": "柚原こはる",
                "real_name": "別の実名",
            },
        )
        self.assertEqual(self.adapter._user_name_cache, before)
        self.client.users_info.side_effect = None
        for wrong in (
            {"id": "UOTHER", "team_id": "TDEMO", "is_bot": True},
            {"id": "UBETA", "team_id": "TFOREIGN", "is_bot": True},
            {"id": "UBETA", "team_id": "TDEMO", "is_bot": False},
        ):
            self.client.users_info.return_value = {
                "ok": True,
                "user": {**wrong, "profile": {"display_name": "柚原こはる"}},
            }
            rejected_whoami = dict(await bridge.recipient_metadata(bound, topology))
            self.assertEqual(
                rejected_whoami["UBETA"],
                {"user_id": "UBETA", "username": None, "display_name": None, "real_name": None},
            )
        print(f"NATIVE_LABEL_COLD_RECEIPT participants=2 elapsed_ms={elapsed * 1000:.3f}")

    def supply_native_names(self):
        """Fictional verified users.info; empty display, no given-name fields."""
        human = self.client.users_info.return_value

        async def info(*, user):
            if user == "UHUMAN":
                return human
            return {
                "ok": True,
                "user": {
                    "id": user,
                    "team_id": "TDEMO",
                    "is_bot": True,
                    "name": "native.beta" if user == "UBETA" else "native.alpha",
                    "profile": {
                        "display_name": "",
                        "real_name": "柚原こはる" if user == "UBETA" else "榎森あおい",
                    },
                },
            }

        self.client.users_info.side_effect = info

    async def test_warm_native_handle_cache_still_verifies_full_label(self):
        from hermes_slack_agent_router.bridge import Bridge

        self.adapter._team_bot_names["TDEMO"] = "birch"
        self.adapter._user_name_cache[("TDEMO", "UBETA")] = "birch"
        self.supply_native_names()
        bridge = Bridge(self.adapter)
        bound = await bridge.bind(self.message("こはるさん、会場図を修正してください。"))
        topology = await bridge.participants(bound)
        cache = dict(self.adapter._user_name_cache)
        whoami = dict(await bridge.recipient_metadata(bound, topology))
        self.assertEqual(
            whoami["UBETA"],
            {"user_id": "UBETA", "username": "native.beta", "display_name": "", "real_name": "柚原こはる"},
        )
        self.assertEqual(self.adapter._user_name_cache, cache)
        self.assertIn({"user": "UBETA"}, [c.kwargs for c in self.client.users_info.await_args_list])
        self.client.users_info.side_effect = None
        for malformed, display_name, real_name in (
            (None, None, None),
            ([], None, None),
            ("not-container", None, None),
            ({"display_name": [], "real_name": 10}, None, None),
            ({"display_name": "", "real_name": ""}, "", ""),
        ):
            self.client.users_info.return_value = {
                "ok": True,
                "user": {"id": "UBETA", "team_id": "TDEMO", "is_bot": True, "profile": malformed},
            }
            identity = dict(await bridge.recipient_metadata(bound, topology))["UBETA"]
            self.assertEqual(identity["username"], "birch")
            self.assertEqual(identity["display_name"], display_name)
            self.assertEqual(identity["real_name"], real_name)

    def install_scoped_receiver(self):
        from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest

        from hermes_slack_agent_router.plugin import register

        manager = PluginManager()
        register(PluginContext(PluginManifest(name="slack-agent-router"), manager))
        assembled = []

        async def receive(event):
            async with self.runner._async_profile_scope_for_source(event.source):
                with patch("hermes_cli.plugins.get_plugin_manager", return_value=manager):
                    admitted = await self.runner._hm_pre_gateway_dispatch_hook(event, event.source)
                self.assertIsNotNone(admitted)
                assembled.append(
                    self.runner._prefix_inbound_sender_context(admitted, admitted.source, admitted.text)
                )
                await self.model(admitted)

        self.adapter.set_message_handler(receive)
        return assembled

    async def test_readable_context_actual_native_source_and_input(self):
        self.enable_semantic()
        self.supply_native_names()
        assembled = self.install_scoped_receiver()
        self.client.conversations_replies.return_value = {
            "ok": True,
            "messages": [
                {"ts": "100.001", "user": "UHUMAN", "text": "架空の展示会について相談します。"},
                {"ts": "101.001", "user": "UBETA", "text": "会場図を作成しました。"},
            ],
        }

        async def classify(batch):
            context = context_view(batch["state"])
            self.assertEqual(context["CURRENT"]["sender"], context["participants"]["UHUMAN"])
            self.assertEqual(context["CURRENT"]["sender"]["kind"], "unknown")
            self.assertEqual(context["root"]["timestamp"], "100.001")
            self.assertEqual(context["recent"][0]["sender"]["user_id"], "UBETA")
            self.assertEqual(context["recent"][0]["sender"]["real_name"], "柚原こはる")
            answer = native_answers(batch)
            answer.update(for_UBETA="u0")
            return answer

        self.gate.jev.ask.side_effect = classify
        text = "柚原こはるさん、会場図を修正してください。"
        body = self.message(text)
        original = copy.deepcopy(body)
        await self.dispatch(body)
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        received = self.model.await_args.args[0]
        self.assertEqual(received.text, text)
        self.assertIsNone(received.channel_context)
        self.assertEqual(received.source.user_id, "UHUMAN")
        self.assertEqual(body, original)
        self.assertEqual(assembled, ["[Human | Slack user <@UHUMAN>] " + text])
        self.client.chat_postMessage.assert_not_awaited()
        self.peer._message_handler.assert_not_awaited()

    async def test_chronology_people_native_serving_directory(self):
        from hermes_slack_agent_router.bridge import Bridge
        from hermes_slack_agent_router.semantic import History

        self.enable_semantic()

        async def info(*, user):
            if user == "UUNKNOWN":
                return {"ok": True, "user": {"id": user, "team_id": "TFOREIGN", "is_bot": False}}
            return {
                "ok": True,
                "user": {
                    "id": user,
                    "team_id": "TDEMO",
                    "is_bot": user == "UBETA",
                    "name": "person." + user,
                    "profile": {"display_name": "", "real_name": "共通名"},
                    "email": "MUST_NOT_RETAIN",
                },
            }

        self.client.users_info.side_effect = info
        bridge = Bridge(self.adapter)
        bound = await bridge.bind(self.message("<@UBETA> explain the diagram."))
        self.peer._team_clients = {"TDEMO": AsyncMock()}
        whoami = (
            (
                "UBETA",
                {"user_id": "UBETA", "username": "bot.beta", "display_name": "共通名", "real_name": None},
            ),
        )
        history = (
            History("100.001", "UHUMAN", "anchor"),
            History("101.001", "UOUTSIDE", "context only"),
            History("102.001", "UUNKNOWN", "unavailable"),
        )
        people = dict(await bridge.context_people(bound, history, whoami))
        self.assertEqual(set(people), {"UHUMAN", "UBETA", "UOUTSIDE", "UUNKNOWN"})
        self.assertEqual(people["UHUMAN"]["kind"], "human")
        self.assertEqual(people["UHUMAN"]["display_name"], "")
        self.assertEqual(people["UOUTSIDE"]["kind"], "human")
        self.assertEqual(people["UBETA"]["kind"], "bot")
        self.assertEqual(
            people["UUNKNOWN"],
            {
                "user_id": "UUNKNOWN",
                "username": None,
                "display_name": None,
                "real_name": None,
                "kind": "unknown",
            },
        )
        calls = [c.kwargs["user"] for c in self.client.users_info.await_args_list]
        self.assertEqual(sorted(calls), ["UHUMAN", "UOUTSIDE", "UUNKNOWN"])
        self.assertNotIn("MUST_NOT_RETAIN", repr(people))
        self.peer._team_clients["TDEMO"].users_info.assert_not_awaited()
        self.assertEqual(bound.recipient.bot_user, "UBETA")

        # Genuine native transport failure leaves contextual authors unknown;
        # a changed serving transport is still rejected independently.
        from hermes_slack_agent_router.bridge import TopologyError, contextual_person

        before = self.client.users_info.await_count
        self.client.users_info.side_effect = TimeoutError("fictional native SDK timeout")
        unavailable = dict(await bridge.context_people(bound, history, whoami))
        self.assertEqual(self.client.users_info.await_count, before + 2)
        self.assertEqual(unavailable["UOUTSIDE"]["kind"], "unknown")
        for payload in (
            {"ok": False},
            {"ok": True, "user": {"id": "UWRONG", "team_id": "TDEMO", "is_bot": False}},
            {"ok": True, "user": {"id": "UOUTSIDE", "team_id": "TDEMO", "is_bot": False, "profile": []}},
        ):
            self.assertEqual(contextual_person("UOUTSIDE", payload, "TDEMO")["kind"], "unknown")
        self.adapter._team_bot_user_ids["TDEMO"] = "UOTHER"
        with self.assertRaises(TopologyError):
            await bridge.context_people(bound, history, whoami)

    async def test_full_view_native_reference_seam(self):
        from test_semantic import controlled_answers, expected_full_view

        from hermes_slack_agent_router.jev import validate_answers
        from hermes_slack_agent_router.semantic import History, Snapshot, assemble, prepare

        recipient = Recipient("TDEMO", "UBETA", "default")
        peer = Recipient("TDEMO", "UALPHA", "default")

        async def render(source, text):
            event = {
                "type": "message",
                "text": text,
                "user": "UHUMAN",
                "team": "TDEMO",
                "channel": "CDEMO",
                "ts": "200.001",
                "thread_ts": "100.001",
            }
            rendered = (
                self.adapter._apply_bot_mention(text, text, text, False, "UBETA", "100.001", "TDEMO")[0]
                if "<@UBETA>" in text
                else text
            )
            built = await self.adapter._build_message_event(
                event,
                text=rendered,
                original_text=text,
                command_probe_text=text,
                is_command_text=False,
                channel_id="CDEMO",
                team_id="TDEMO",
                ts="200.001",
                user_id="UHUMAN",
                thread_ts="100.001",
                is_dm=False,
                media_urls=[],
                media_types=[],
                media_text_inlined=[],
                channel_context=None,
            )
            return {
                "text": built.text,
                "source": built.source.to_dict(),
                "assembled_input": self.runner._prefix_inbound_sender_context(
                    built, built.source, built.text
                ),
            }

        for own_current in ("<@UBETA> revise the summary; ", "Fix the invoice parser; "):
            source = Snapshot(
                Thread("TDEMO", "CDEMO", "100.001"),
                "200.001",
                "UHUMAN",
                own_current + "<@UALPHA> handle the other artifact.",
                (History("100.001", "UALPHA", "I prepared the summary."),),
                (recipient, peer),
            )
            batch = prepare(source, recipient)
            omitted_native = None
            for include in (False, True):
                with self.subTest(current=own_current, reference=include):
                    raw = controlled_answers(
                        batch,
                        {"response": "yes", "scope": "u0", "u0_prior0": "include" if include else "omit"},
                    )
                    raw["answers"]["scope"]["confidence"] = 0.01
                    selected = validate_answers(batch, raw)
                    plan = assemble(source, recipient, selected)
                    current = "".join(
                        source.text[u.start : u.end] for u in plan.units if recipient in u.recipients
                    )
                    self.assertEqual(current, own_current)
                    expected = expected_full_view(source, ["u0"], own_current, selected)
                    self.assertEqual(plan.view(recipient), expected)
                    actual_native, expected_native = (
                        await render(source, plan.view(recipient)),
                        await render(source, expected),
                    )
                    self.assertEqual(actual_native, expected_native)
                    if not include:
                        omitted_native = actual_native
                    elif "<@UBETA>" in own_current:
                        self.assertEqual(omitted_native["text"][-1], ";")
                        self.assertEqual(actual_native["text"].split("\n\nPRIOR REFERENCE", 1)[0][-1], " ")
                        self.assertNotEqual(
                            actual_native["text"].split("\n\nPRIOR REFERENCE", 1)[0], omitted_native["text"]
                        )
                    else:
                        self.assertTrue(actual_native["text"].startswith(own_current))
                    foreign = await render(source, source.text)
                    self.assertNotEqual(foreign, expected_native)
        self.client.chat_postMessage.assert_not_awaited()
        self.client.chat_postEphemeral.assert_not_awaited()

    async def test_coherent_response_native_confidence_and_full_extent(self):
        from test_semantic import controlled_answers

        from hermes_slack_agent_router.jev import validate_answers

        self.enable_semantic()
        assembled = self.install_scoped_receiver()

        async def classify(batch):
            self.assertEqual({k for k in batch["questions"] if "_prior" not in k}, {"response", "scope"})
            raw = controlled_answers(batch, {"response": "yes", "scope": "u0+u1"})
            raw["answers"]["response"]["confidence"] = confidence
            raw["answers"]["scope"]["confidence"] = 0.01
            return validate_answers(batch, raw)

        self.gate.jev.ask.side_effect = classify
        for confidence in (0.499, 0.500, 0.501):
            self.model.reset_mock()
            assembled.clear()
            await self.dispatch(self.message("<@UBETA>, that proposal is unacceptable; explain the effect."))
            await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
            self.assertEqual(self.model.await_count, int(confidence > 0.5))
            if confidence > 0.5:
                self.assertEqual(
                    self.model.await_args.args[0].text, ", that proposal is unacceptable; explain the effect."
                )
                self.assertEqual(len(assembled), 1)

        async def unsafe(batch):
            return validate_answers(batch, controlled_answers(batch, {"response": "yes", "scope": "unsafe"}))

        self.model.reset_mock()
        assembled.clear()
        self.gate.jev.ask.side_effect = unsafe
        from hermes_slack_agent_router.plugin import logger

        with self.assertLogs(logger, level="WARNING") as logs:
            await self.assert_rejected(
                self.message("<@UBETA>, preserve an inseparable unrepresentable response.")
            )
        self.assertTrue(any("projection-unresolved" in line for line in logs.output))
        self.client.chat_postMessage.assert_not_awaited()

    async def test_response_unit_native_conversation_without_work(self):
        from hermes_slack_agent_router.jev import validate_answers

        self.enable_semantic()
        assembled = self.install_scoped_receiver()

        async def classify(batch):
            self.assertIn("response", batch["questions"])
            self.assertNotIn("self_recipient", batch["questions"])
            self.assertNotIn("projection", batch["questions"])
            return validate_answers(
                batch,
                {
                    "answers": {
                        key: {
                            "type": "choice",
                            "choice": "yes" if key == "response" else "u0" if key == "scope" else "omit",
                            "confidence": 0.701 if key == "response" else 0.1,
                            "probabilities": {
                                v: float(
                                    v == ("yes" if key == "response" else "u0" if key == "scope" else "omit")
                                )
                                for v in q["criteria"]
                            },
                        }
                        for key, q in batch["questions"].items()
                    }
                },
            )

        self.gate.jev.ask.side_effect = classify
        await self.dispatch(self.message("<@UBETA>, could you explain the diagram?"))
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        self.assertEqual(self.model.await_args.args[0].text, ", could you explain the diagram?")
        self.assertEqual(assembled, ["[Human | Slack user <@UHUMAN>] , could you explain the diagram?"])
        self.assertIsNone(self.model.await_args.args[0].channel_context)
        self.client.chat_postMessage.assert_not_awaited()

    async def test_plain_japanese_name_native_labels_and_exact_receiver(self):
        self.enable_semantic()
        self.supply_native_names()
        assembled = self.install_scoped_receiver()
        self.adapter._team_bot_names["TDEMO"] = "birch"
        self.peer._team_bot_names["TDEMO"] = "atlas"
        self.adapter._user_name_cache[("TDEMO", "UBETA")] = "柚原こはる"
        self.peer._user_name_cache[("TDEMO", "UALPHA")] = "榎森あおい"
        text = "柚原こはるさん、会場図を修正してください。"
        self.client.conversations_replies.return_value = {
            "ok": True,
            "messages": [{"ts": "100.001", "user": "UHUMAN", "text": "架空の展示会について相談します。"}],
        }

        async def named(batch):
            answer = native_answers(batch)
            answer.update(
                for_UBETA="u0",
            )
            return answer

        self.gate.jev.ask.side_effect = named
        await self.dispatch(self.message(text))
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
        self.model.assert_awaited_once()
        self.assertEqual(self.model.await_args.args[0].text, text)
        self.assertFalse(self.model.await_args.args[0].channel_context)
        self.assertIn(text, assembled[0])
        self.assertNotIn("架空の展示会について相談", assembled[0])
        batch = self.gate.jev.ask.await_args.args[0]
        whoami = batch["state"]["whoami"]
        self.assertEqual(whoami["user_id"], "UBETA")
        self.assertEqual(whoami["username"], "native.beta")
        self.assertEqual(whoami["display_name"], "")
        self.assertEqual(whoami["real_name"], "柚原こはる")
        # Warm cache cannot certify which native full names are present.
        self.assertTrue(self.client.users_info.await_args_list)
        self.assertIn({"user": "UBETA"}, [c.kwargs for c in self.client.users_info.await_args_list])

    async def test_short_route_unit_confidence_and_other_unit_independence(self):
        from test_semantic import controlled_answers

        from hermes_slack_agent_router.jev import validate_answers

        self.enable_semantic()
        self.supply_native_names()
        self.adapter._team_bot_names["TDEMO"] = "birch"
        self.peer._team_bot_names["TDEMO"] = "atlas"
        tested = []

        async def low(batch):
            choices = {"for_UBETA": "u0", "for_UALPHA": "u1"}
            raw = controlled_answers(batch, choices)
            required = ["response", "scope"]
            if not tested:
                tested.extend(required)
            raw["answers"][current]["confidence"] = 0.500
            return validate_answers(batch, raw)

        self.gate.jev.ask.side_effect = low
        current = "response"
        await self.assert_rejected(
            self.message("こはるさん、会場図を修正してください。<@UALPHA> revise the summary.")
        )
        for current in tested:
            self.model.reset_mock()
            body = self.message("こはるさん、会場図を修正してください。<@UALPHA> revise the summary.")
            if current == "response":
                await self.assert_rejected(body)
            else:
                await self.dispatch(body)
                await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
                self.model.assert_awaited_once()
                self.assertEqual(self.model.await_args.args[0].text, "こはるさん、会場図を修正してください。")
        self.assertFalse(self.adapter._session_tasks)
        print(f"SHORT_NATIVE_ATOMIC_MUTATIONS consumed={len(tested)} plus_initial=1")

    async def test_controlled_conversational_corpus_native_inputs(self):
        """Controlled conversational scopes through real native dispatch and full input formatting."""
        import hashlib
        from dataclasses import replace

        from gateway.platforms.helpers import MessageDeduplicator
        from test_semantic import controlled_answers, expected_full_view, japanese_improvement_source

        from hermes_slack_agent_router.jev import serialize_request, validate_answers
        from hermes_slack_agent_router.semantic import assemble, prepare

        self.enable_semantic()
        assembled = self.install_scoped_receiver()
        captured = {}
        fixed_history = [
            {"ts": "100.001", "user": "UALPHA", "text": "I prepared the summary."},
            {"ts": "101.001", "user": "UBETA", "text": "I prepared the diagram."},
        ]
        named_history = [
            {"ts": "100.001", "user": "UHUMAN", "text": "架空の展示会について相談します。"},
            {"ts": "101.001", "user": "UBETA", "text": "展示物の配置を確認しました。"},
            *[
                {"ts": f"{i}.001", "user": "UHUMAN", "text": "進捗の報告ありがとうございます。"}
                for i in range(102, 108)
            ],
        ]
        generic_history = [
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
        cases: tuple[tuple[str, str, str, list[dict[str, str]], int], ...] = (
            ("full-name", "UBETA", "柚原こはるさん、会場図を修正してください。", named_history, 200),
            ("short-name", "UBETA", "こはるさん、会場図を修正してください。", named_history, 220),
            (
                "multi-beta",
                "UBETA",
                "<@UALPHA> revise the summary; <@UBETA> check the diagram.",
                fixed_history,
                200,
            ),
            (
                "multi-alpha",
                "UALPHA",
                "<@UALPHA> revise the summary; <@UBETA> check the diagram.",
                fixed_history,
                201,
            ),
            ("contextual", "UBETA", "Please correct the diagram you prepared.", fixed_history, 202),
            ("generic", "UBETA", "Please continue the general project work.", generic_history, 203),
            ("joint", "UBETA", "<@UALPHA> and <@UBETA> check the diagram together.", fixed_history, 204),
            (
                "joint-alpha",
                "UALPHA",
                "<@UALPHA> and <@UBETA> check the diagram together.",
                fixed_history,
                205,
            ),
        )
        generic_text = "Please continue the general project work."
        cases += (
            ("specific-not-main", "UALPHA", "Please revise the summary.", generic_history, 230),
            (
                "main-takeover",
                "UALPHA",
                generic_text,
                [
                    *generic_history,
                    {
                        "ts": "103.001",
                        "user": "UHUMAN",
                        "text": "<@UALPHA> now takes over whole-thread leadership from <@UBETA>.",
                    },
                ],
                231,
            ),
            (
                "main-joint",
                "UBETA",
                generic_text,
                [
                    {
                        "ts": "100.001",
                        "user": "UHUMAN",
                        "text": "<@UALPHA> and <@UBETA> jointly lead this entire thread.",
                    }
                ],
                232,
            ),
            (
                "main-outside",
                "UBETA",
                generic_text,
                [
                    {
                        "ts": "100.001",
                        "user": "UHUMAN",
                        "text": "<@UBETA> and <@UOUTSIDE> jointly lead this entire thread.",
                    }
                ],
                233,
            ),
            ("main-unknown", "UBETA", generic_text, fixed_history, 234),
            (
                "main-conflict",
                "UBETA",
                generic_text,
                [
                    {
                        "ts": "100.001",
                        "user": "UHUMAN",
                        "text": "Whole-thread leadership is disputed between <@UALPHA> and <@UBETA>; neither claim has been settled.",
                    }
                ],
                235,
            ),
        )
        originals = {case[0]: case for case in cases}
        derivatives = {
            "M3": (
                "specific-not-main",
                "Please revise the summary; <@UBETA> and <@UOUTSIDE> check the diagram together.",
                None,
            ),
            "M4": (
                "main-conflict",
                "<@UALPHA> revise the summary; please continue the general project work.",
                None,
            ),
            "M5": ("contextual", "ありがとう。図を確認して；要約も直して。", None),
            "M6": (
                "main-conflict",
                "Please revise the summary.",
                [
                    *originals["main-conflict"][3],
                    {"ts": "101.001", "user": "UHUMAN", "text": "<@UALPHA> handles summaries."},
                ],
            ),
            "M7": (
                "generic",
                generic_text,
                [
                    generic_history[0],
                    *[{"ts": f"{i}.001", "user": "UHUMAN", "text": "Thanks."} for i in range(101, 108)],
                ],
            ),
            "M8": (
                "contextual",
                originals["contextual"][2],
                [
                    {
                        "ts": "100.001",
                        "user": "UALPHA",
                        "text": "<@UBETA> prepared the diagram; I only reported progress.",
                    },
                    {"ts": "101.001", "user": "UBETA", "text": "I prepared the diagram."},
                ],
            ),
            "M9": ("short-name", originals["short-name"][2], None),
            "M10": ("contextual", "> <@UBETA> check the diagram.\nThanks.", None),
        }
        cases += tuple(
            (
                name,
                "UALPHA" if name == "M6" else "UBETA" if name == "M3" else originals[base][1],
                text,
                history if history is not None else originals[base][3],
                originals[base][4],
            )
            for name, (base, text, history) in derivatives.items()
        )
        # Both native receivers, identical source/metadata, not plan-only observation.
        for base in ("main-joint", "M3", "M4", "M5", "M10"):
            _, _, text, history, sequence = next(c for c in cases if c[0] == base)
            cases += ((base + "-alpha", "UALPHA", text, history, sequence),)
        # Exercise same-name alternatives with explicit, joint, owned and unresolved scopes.
        counterpart_specs = {
            "C-owned": (
                originals["short-name"][2],
                [
                    named_history[0],
                    {
                        "ts": "101.001",
                        "user": "UBETA",
                        "text": "この会場図を私が作成しました。同じ会場図の修正も私が担当します。",
                    },
                ],
                [["UBETA"]],
            ),
            "C-handoff": (
                originals["short-name"][2],
                [
                    {"ts": "100.001", "user": "UHUMAN", "text": "<@UBETA> owns editing the venue diagram."},
                    {
                        "ts": "101.001",
                        "user": "UHUMAN",
                        "text": "<@UALPHA> now takes over editing this same venue diagram from <@UBETA>.",
                    },
                ],
                [["UALPHA"]],
            ),
            "C-explicit": ("<@UBETA>、会場図を修正してください。", named_history, [["UBETA"]]),
            "C-joint": (
                "<@UALPHA> and <@UBETA> revise the venue diagram together.",
                named_history,
                [["UALPHA", "UBETA"]],
            ),
            "C-unresolved": (
                originals["short-name"][2],
                [
                    {
                        "ts": "100.001",
                        "user": "UHUMAN",
                        "text": "Both people checked exhibit placement. Neither has created, owned or been assigned this venue diagram.",
                    }
                ],
                [],
            ),
        }
        counterpart_expectations = {}
        for base, (text, history, action_sets) in counterpart_specs.items():
            for suffix, receiver in (("beta", "UBETA"), ("alpha", "UALPHA")):
                label = base + "-" + suffix
                cases += ((label, receiver, text, history, 240),)
                counterpart_expectations[label] = action_sets
        negatives = {
            "main-unknown",
            "main-conflict",
            "M4",
            "M9",
            "M10",
            "M10-alpha",
            "C-unresolved-beta",
            "C-unresolved-alpha",
        }

        silences = negatives | {"C-owned-alpha", "C-handoff-beta", "C-explicit-alpha"}
        expected = {name: [["UBETA"]] for name, *_ in cases}
        for name in ("multi-beta", "multi-alpha"):
            expected[name] = [["UALPHA"], ["UBETA"]]
        for name in ("joint", "joint-alpha", "main-joint", "main-joint-alpha"):
            expected[name] = [["UALPHA", "UBETA"]]
        for name in ("specific-not-main", "main-takeover", "M6"):
            expected[name] = [["UALPHA"]]
        for name in ("M5", "M5-alpha"):
            expected[name] = [["UBETA"], ["UALPHA"]]
        for name in negatives:
            expected[name] = []
        expected.update(counterpart_expectations)
        for label in ("M3", "M3-alpha"):
            expected[label] = [["UALPHA"], ["UBETA"]]
        for label in ("M4", "M4-alpha"):
            expected[label] = [["UALPHA"], ["UALPHA"]]

        # Exercise both ID-only and verified native metadata for the same sources.
        normal_sources = {
            "N-" + label: label
            for label, *_ in cases
            if label not in ("full-name", "short-name", "M9") and label not in counterpart_expectations
        }
        by_label = {case[0]: case for case in cases}
        for label, base in normal_sources.items():
            _, receiver, text, history, sequence = by_label[base]
            cases += ((label, receiver, text, history, sequence),)
            expected[label] = expected[base]
            if base in silences:
                silences.add(label)
            if base in negatives:
                negatives.add(label)

        conversation_specs = (
            (
                "Q-question",
                "UBETA",
                "<@UBETA>, why is the diagram scaled differently?",
                fixed_history,
                [["UBETA"]],
            ),
            (
                "Q-explanation",
                "UBETA",
                "<@UBETA>, explain why the diagram uses metres.",
                fixed_history,
                [["UBETA"]],
            ),
            ("Q-ack", "UBETA", "<@UBETA>, please acknowledge receipt.", fixed_history, [["UBETA"]]),
            (
                "Q-support-beta",
                "UBETA",
                "<@UBETA>, could you explain the scale? The unit conversion is the concern.",
                fixed_history,
                [["UBETA"], ["UBETA"]],
            ),
            (
                "Q-support-alpha",
                "UALPHA",
                "<@UBETA>, could you explain the scale? The unit conversion is the concern.",
                fixed_history,
                [["UBETA"], ["UBETA"]],
            ),
            ("Q-courtesy", "UBETA", "Thanks for the update.", fixed_history, []),
            ("Q-data", "UBETA", "The diagram is 1:100.", fixed_history, []),
            (
                "Q-later-generic",
                "UBETA",
                generic_text,
                [
                    *generic_history,
                    {
                        "ts": "103.001",
                        "user": "UHUMAN",
                        "text": "<@UALPHA>, why does this summary omit the units?",
                    },
                ],
                [["UBETA"]],
            ),
            (
                "Q-change-alpha",
                "UALPHA",
                "<@UALPHA>, explain the summary; include its units; <@UBETA>, explain the diagram.",
                fixed_history,
                [["UALPHA"], ["UALPHA"], ["UBETA"]],
            ),
            (
                "Q-change-beta",
                "UBETA",
                "<@UALPHA>, explain the summary; include its units; <@UBETA>, explain the diagram.",
                fixed_history,
                [["UALPHA"], ["UALPHA"], ["UBETA"]],
            ),
            (
                "Q-inseparable",
                "UBETA",
                "<@UBETA> and <@UOUTSIDE>, could you jointly explain this diagram?",
                fixed_history,
                [["UBETA"]],
            ),
        )
        conversation_names = {row[0] for row in conversation_specs}
        for label, receiver, text, history, action_sets in conversation_specs:
            cases += ((label, receiver, text, history, 260),)
            expected[label] = action_sets
            if not action_sets:
                negatives.add(label)
            if not any(receiver in users for users in action_sets):
                silences.add(label)
        # Controlled chronology contrasts: same utterances, reversed appointment order.
        appointments = [
            "<@UALPHA>, you now lead this entire thread.",
            "<@UBETA>, you now lead this entire thread.",
        ]
        temporal_specs = []
        for order in ("AB", "BA"):
            texts = appointments if order == "AB" else list(reversed(appointments))
            history = [
                {"ts": "100.001", "user": "UHUMAN", "text": "We are coordinating the exhibition."},
                *[{"ts": f"{i + 101}.001", "user": "UHUMAN", "text": text} for i, text in enumerate(texts)],
            ]
            for receiver in ("UBETA", "UALPHA"):
                temporal_specs.append(
                    (
                        f"T-order-{order}-" + ("beta" if receiver == "UBETA" else "alpha"),
                        receiver,
                        "Please continue the general project work.",
                        history,
                        [["UBETA" if order == "AB" else "UALPHA"]],
                    )
                )
        topic_history = [
            {"ts": "100.001", "user": "UHUMAN", "text": "<@UBETA>, lead this entire thread."},
            {"ts": "101.001", "user": "UHUMAN", "text": "<@UALPHA>, take over only the diagram task."},
        ]
        for label, current, history, sets in (
            (
                "handoff",
                "Please continue the general project work.",
                [
                    {"ts": "100.001", "user": "UHUMAN", "text": appointments[0]},
                    {"ts": "101.001", "user": "UHUMAN", "text": appointments[1]},
                ],
                [["UBETA"]],
            ),
            (
                "report",
                "Please continue the general project work.",
                [
                    {"ts": "100.001", "user": "UHUMAN", "text": "<@UBETA>, lead this entire thread."},
                    {"ts": "101.001", "user": "UALPHA", "text": "The summary status is complete."},
                ],
                [["UBETA"]],
            ),
            ("task", "Please correct the diagram.", topic_history, [["UALPHA"]]),
            ("task-generic", "Please continue the general project work.", topic_history, [["UBETA"]]),
            (
                "repair",
                "No, that proposal is not acceptable; explain why it would send my reply to 柚原こはる.",
                [
                    {"ts": "100.001", "user": "UHUMAN", "text": "We are reviewing a routing proposal."},
                    {
                        "ts": "101.001",
                        "user": "UALPHA",
                        "text": "I propose changing the threshold to .2 so that 柚原こはる receives the reply.",
                    },
                ],
                [["UALPHA"], ["UALPHA"]],
            ),
        ):
            for receiver in ("UBETA", "UALPHA"):
                temporal_specs.append(
                    (
                        "T-" + label + "-" + ("beta" if receiver == "UBETA" else "alpha"),
                        receiver,
                        current,
                        history,
                        sets,
                    )
                )
        people_specs = [
            (
                "P-directory",
                "UBETA",
                "Please continue the general project work.",
                generic_history,
                [["UBETA"]],
            ),
            (
                "P-duplicate-beta",
                "UBETA",
                "Please correct the diagram you prepared.",
                fixed_history,
                [["UBETA"]],
            ),
            (
                "P-duplicate-alpha",
                "UALPHA",
                "Please correct the diagram you prepared.",
                fixed_history,
                [["UBETA"]],
            ),
            (
                "P-unknown",
                "UBETA",
                "Please continue the general project work.",
                [
                    {"ts": "100.001", "user": "UHUMAN", "text": "<@UBETA>, lead this entire thread."},
                    {"ts": "101.001", "user": "UUNKNOWN", "text": "Some status."},
                ],
                [["UBETA"]],
            ),
            (
                "P-outside",
                "UBETA",
                "<@UBETA> and <@UOUTSIDE>, jointly explain the diagram.",
                [
                    {"ts": "100.001", "user": "UHUMAN", "text": "We are discussing a diagram."},
                    {"ts": "101.001", "user": "UOUTSIDE", "text": "I am an external human reviewer."},
                ],
                [["UBETA"]],
            ),
        ]
        temporal_names = {row[0] for row in temporal_specs}
        people_names = {row[0] for row in people_specs}
        for label, receiver, current, history, sets in [*temporal_specs, *people_specs]:
            cases += ((label, receiver, current, history, 280),)
            expected[label] = sets
            if not sets:
                negatives.add(label)
            if not any(receiver in users for users in sets):
                silences.add(label)
        # Only mixed-owner messages need parts; all other positive rows own the
        # complete fixture text. These literals never read production segmentation.
        fixture_parts = {
            originals["multi-beta"][2]: (
                ("<@UALPHA> revise the summary; ", ("UALPHA",)),
                ("<@UBETA> check the diagram.", ("UBETA",)),
            ),
            derivatives["M3"][1]: (
                ("Please revise the summary; ", ("UALPHA",)),
                ("<@UBETA> and <@UOUTSIDE> check the diagram together.", ("UBETA",)),
            ),
            derivatives["M5"][1]: (
                ("ありがとう。", ()),
                ("図を確認して；", ("UBETA",)),
                ("要約も直して。", ("UALPHA",)),
            ),
            next(row[2] for row in conversation_specs if row[0] == "Q-change-alpha"): (
                ("<@UALPHA>, explain the summary; include its units; ", ("UALPHA",)),
                ("<@UBETA>, explain the diagram.", ("UBETA",)),
            ),
        }
        for name, bot, text, history, sequence in cases:
            parts = fixture_parts.get(text, ((text, (bot,)),))
            self.assertEqual("".join(part for part, _ in parts), text)
            current = "" if name in silences else "".join(part for part, users in parts if bot in users)
            # Cases reuse timestamps; reset only the fixture's native deduplication state.
            self.adapter._dedup = MessageDeduplicator()
            self.sequence = sequence
            self.model.reset_mock()
            assembled.clear()
            self.peer._message_handler.reset_mock()
            self.adapter._team_bot_user_ids["TDEMO"] = bot
            self.adapter._bot_user_id = bot
            self.peer._team_bot_user_ids["TDEMO"] = "UALPHA" if bot == "UBETA" else "UBETA"
            self.adapter._team_bot_names.clear()
            self.peer._team_bot_names.clear()
            self.client.users_info.side_effect = None
            self.client.users_info.reset_mock()
            if name.startswith("joint"):
                target = self.adapter if bot == "UBETA" else self.peer
                target._team_bot_names["TDEMO"] = "Human"
            if name in ("full-name", "short-name", "M9") or name in counterpart_expectations:
                self.adapter._team_bot_names["TDEMO"] = "birch"
                self.peer._team_bot_names["TDEMO"] = "atlas"
                self.adapter._user_name_cache[("TDEMO", "UBETA")] = "birch"
                self.peer._user_name_cache[("TDEMO", "UALPHA")] = "atlas"
                self.supply_native_names()
                if name == "M9" or name in counterpart_expectations:
                    original_names = self.client.users_info.side_effect

                    async def colliding_names(original_names=original_names, **kwargs):
                        result = await original_names(**kwargs)
                        result["user"]["real_name"] = "柚原こはる"
                        result["user"]["profile"]["real_name"] = "柚原こはる"
                        result["user"]["profile"]["display_name"] = "柚原こはる"
                        return result

                    self.client.users_info.side_effect = colliding_names
                if name in counterpart_expectations:
                    self.adapter._team_bot_names["TDEMO"] = "birch" if bot == "UBETA" else "atlas"
                    self.peer._team_bot_names["TDEMO"] = "atlas" if bot == "UBETA" else "birch"
                    for adapter in (self.adapter, self.peer):
                        adapter._user_name_cache[("TDEMO", "UALPHA")] = "柚原こはる"
                        adapter._user_name_cache[("TDEMO", "UBETA")] = "柚原こはる"
            self.client.conversations_replies.return_value = {"ok": True, "messages": history}
            if name in normal_sources or name in conversation_names:
                for adapter in (self.adapter, self.peer):
                    for user in ("UALPHA", "UBETA"):
                        adapter._user_name_cache.pop(("TDEMO", user), None)
                self.supply_native_names()
            if name in temporal_names or name in people_names:
                self.supply_native_names()
                base_info = self.client.users_info.side_effect

                async def contextual_info(*, user, base_info=base_info, name=name):
                    if user in {"UHUMAN", "UOUTSIDE", "UUNKNOWN"}:
                        return {
                            "ok": True,
                            "user": {
                                "id": user,
                                "team_id": "TFOREIGN" if user == "UUNKNOWN" else "TDEMO",
                                "is_bot": False,
                                "name": "Human" if user == "UHUMAN" else "outside.person",
                                "profile": {"display_name": "共通名", "real_name": "Fictional person"},
                            },
                        }
                    result = await base_info(user=user)
                    if name.startswith("P-duplicate"):
                        result["user"]["profile"]["display_name"] = "共通名"
                    return result

                self.client.users_info.side_effect = contextual_info

            observed = {}

            def observe_source(source, recipient, observed=observed):
                observed.update(source=source, recipient=recipient)
                return prepare(source, recipient)

            async def offline(batch, name=name, bot=bot, observed=observed):
                offset = 1 if normal_sources.get(name, name).startswith("M5") else 0
                own = [f"u{i}" for i, users in enumerate(expected[name], offset) if bot in users]
                choices = {"for_" + bot: "+".join(own) or "none"}
                if name == "contextual":
                    choices["u0_prior1"] = "include"
                selected = validate_answers(batch, controlled_answers(batch, choices))
                observed.update(batch=batch, selected=selected, own=own)
                return selected

            self.gate.jev = AsyncMock()
            self.gate.jev.ask.side_effect = offline
            with self.subTest(case=name):
                with patch("hermes_slack_agent_router.plugin.prepare", side_effect=observe_source):
                    response = await self.dispatch(self.message(text))
                await asyncio.gather(*tuple(self.adapter._session_tasks.values()))
                self.assertEqual(response.status, 200)
                self.gate.jev.ask.assert_awaited_once()
                source, batch = observed["source"], observed["batch"]
                plan = assemble(source, observed["recipient"], observed["selected"])
                self.assertEqual(plan.status, "ready", plan.reason)
                selected_current = "".join(
                    plan.source[unit.start : unit.end]
                    for unit in plan.units
                    if unit.disposition == "action" and observed["recipient"] in unit.recipients
                )
                self.assertEqual(selected_current, current)
                intended = expected_full_view(source, observed["own"], current, observed["selected"])
                self.assertEqual(plan.view(observed["recipient"]), intended)
                self.assertTrue(
                    all(not plan.view(r) for r in source.recipients if r != observed["recipient"])
                )
                self.assertFalse(self.adapter._pending_messages or self.adapter._pending_text_batches)
                self.client.chat_postMessage.assert_not_awaited()
                self.client.chat_postEphemeral.assert_not_awaited()
                self.peer._message_handler.assert_not_awaited()
                captured[name] = {
                    "request": serialize_request(batch).decode(),
                    "selected": observed["selected"],
                    "current": current,
                    "view": intended,
                }
                if not current:
                    self.assertIn(name, silences)
                    self.model.assert_not_awaited()
                    self.assertFalse(assembled)
                    continue
                self.assertNotIn(name, silences)
                self.model.assert_awaited_once()
                delivered = self.model.await_args.args[0]
                expected_event = copy.deepcopy(source.original)
                expected_event.update(
                    text=intended,
                    user=source.sender,
                    team=source.thread.workspace,
                    channel=source.thread.channel,
                    thread_ts=source.thread.root,
                    ts=source.identity,
                )
                for field in ("blocks", "files", "attachments"):
                    expected_event.pop(field, None)
                formatted = (
                    self.adapter._apply_bot_mention(
                        intended, intended, intended, False, bot, source.thread.root, source.thread.workspace
                    )[0]
                    if f"<@{bot}>" in intended
                    else intended
                )
                expected_native = await self.adapter._build_message_event(
                    expected_event,
                    text=formatted,
                    original_text=intended,
                    command_probe_text=intended,
                    is_command_text=False,
                    channel_id=source.thread.channel,
                    team_id=source.thread.workspace,
                    ts=source.identity,
                    user_id=source.sender,
                    thread_ts=source.thread.root,
                    is_dm=False,
                    media_urls=[],
                    media_types=[],
                    media_text_inlined=[],
                    channel_context=None,
                )
                self.assertEqual(delivered.text, expected_native.text)
                self.assertEqual(delivered.source.to_dict(), expected_native.source.to_dict())
                self.assertIsNone(delivered.channel_context)
                self.assertIsNone(delivered.reply_to_text)
                self.assertFalse(
                    delivered.media_urls or delivered.media_types or delivered.media_text_inlined
                )
                expected_input = self.runner._prefix_inbound_sender_context(
                    expected_native, expected_native.source, expected_native.text
                )
                self.assertEqual(assembled, [expected_input])
                captured[name].update(native_text=delivered.text, assembled=expected_input)

        for suffix in ("beta", "alpha"):
            ab = json.loads(captured["T-order-AB-" + suffix]["request"])["state"]
            ba = json.loads(captured["T-order-BA-" + suffix]["request"])["state"]
            self.assertEqual(ab["whoami"], ba["whoami"])
            self.assertEqual(ab["conversation"]["records"][-1], ba["conversation"]["records"][-1])
            self.assertEqual(
                [r["text"] for r in ab["conversation"]["records"][1:-1]],
                list(reversed([r["text"] for r in ba["conversation"]["records"][1:-1]])),
            )
        japanese = japanese_improvement_source()
        for name, source, users in (
            ("japanese-improvement", japanese, ["UBIRCH"]),
            (
                "joint-four",
                replace(
                    japanese,
                    text="<@UATLAS> and <@UBIRCH> and <@UCEDAR> and <@UDOGWOOD> jointly review the exhibition system.",
                ),
                ["UATLAS", "UBIRCH", "UCEDAR", "UDOGWOOD"],
            ),
            (
                "joint-two",
                replace(japanese, text="<@UATLAS> and <@UBIRCH> jointly review the exhibition system."),
                ["UATLAS", "UBIRCH"],
            ),
        ):
            for recipient in source.recipients:
                with self.subTest(case=name, receiver=recipient.bot_user):
                    batch = prepare(source, recipient)
                    selected = validate_answers(
                        batch, controlled_answers(batch, {"for_" + user: "u0" for user in users})
                    )
                    plan = assemble(source, recipient, selected)
                    own = source.text if recipient.bot_user in users else ""
                    self.assertEqual(plan.status, "ready", plan.reason)
                    self.assertEqual(plan.view(recipient), own)
                    self.assertTrue(all(not plan.view(r) for r in source.recipients if r != recipient))
                    captured[name + ":" + recipient.bot_user] = {
                        "request": serialize_request(batch).decode(),
                        "selected": selected,
                        "current": own,
                        "view": plan.view(recipient),
                    }
        raw = json.dumps(captured, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        print(
            f"CONTROLLED_CORPUS rows={len(captured)} wire_decision_native_sha256={hashlib.sha256(raw).hexdigest()}"
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
