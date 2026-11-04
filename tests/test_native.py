"""Real pinned Bolt/SlackAdapter consuming paths with fictional SDK/HTTP I/O.

Native identity, authorization, channel policy, formatting, queues and pending
controls are real. Controlled decisions are not live semantic-accuracy evidence.
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

from test_semantic import context_view, controlled_answers

from hermes_slack_agent_router.policy import Thread

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
                "HOME": str(self.root),
                "HERMES_HOME": str(self.home),
                "HERMES_BUNDLED_PLUGINS": str(bundled),
                "HERMES_ENABLE_PROJECT_PLUGINS": "0",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        sys.path.insert(0, SOURCE)
        self.addCleanup(sys.path.remove, SOURCE)
        from gateway.config import GatewayConfig, Platform, PlatformConfig
        from gateway.profile_routing import ProfileRoute
        from gateway.run import GatewayRunner
        from gateway.session_authorities import SessionAuthorities
        from gateway.session_state import SessionState
        from gateway.status import flush_runtime_status_async
        from plugins.platforms.slack.adapter import SlackAdapter
        from slack_bolt.async_app import AsyncApp
        from slack_bolt.authorization import AuthorizeResult

        from hermes_slack_agent_router.plugin import Gate

        self.SessionState = SessionState
        self.key = Thread("TDEMO", "CDEMO", "100.001")
        self.adapter = SlackAdapter(
            PlatformConfig(extra={"reply_in_thread": True, "allowed_users": ["UHUMAN"]})
        )
        self.runner = GatewayRunner.__new__(GatewayRunner)
        self.runner.config = GatewayConfig(multiplex_profiles=False)
        self.runner._primary_profile_name = "default"
        self.runner.adapters = {Platform.SLACK: self.adapter}
        self.runner._profile_adapters = {}
        self.runner._sessions = {}
        self.runner.session_store = None
        self.runner.session_authorities = SessionAuthorities(self.home)
        self.authority = SimpleNamespace(profile_id=str(self.home), retiring=False)
        self.runner.session_authorities.add(self.home, self.authority)
        self.adapter.gateway_runner = self.runner
        self.adapter._team_bot_user_ids = {"TDEMO": "UBETA"}
        self.adapter._bot_user_id = "UBETA"
        self.client = AsyncMock()
        self.client.users_info.return_value = {
            "ok": True,
            "user": {"id": "UHUMAN", "team_id": "TDEMO", "is_bot": False, "name": "Human", "profile": {}},
        }
        self.supply_native_names()
        self.client.conversations_info.return_value = {
            "ok": True,
            "channel": {"id": "CDEMO", "name": "demo", "is_im": False, "is_mpim": False},
        }
        self.client.conversations_replies.return_value = {
            "ok": True,
            "messages": [{"ts": "100.001", "user": "UHUMAN", "text": "Fictional root"}],
        }
        self.adapter._team_clients = {"TDEMO": self.client}
        self.model = AsyncMock(return_value=None)

        async def receive(event):
            # The real Gateway ingress authorization remains before the controlled
            # final model seam; a raw AsyncMock would omit that native boundary.
            if self.runner._is_user_authorized_for_source(event.source):
                await self.model(event)

        self.adapter.set_message_handler(receive)
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
        self.peer_home = self.home / "profiles" / "peer"
        self.peer_home.mkdir(parents=True)
        (self.peer_home / "config.yaml").write_text("{}")
        self.runner.config.multiplex_profiles = True
        self.runner.config._runtime_profile_homes = [("default", self.home), ("peer", self.peer_home)]
        self.runner.session_authorities.add(
            self.peer_home, SimpleNamespace(profile_id=str(self.peer_home), retiring=False), name="peer"
        )
        self.runner.config.profile_routes = [
            ProfileRoute("peer-to-default", "slack", "default", bot_profile="peer", chat_id="CDEMO")
        ]
        self.peer.set_owner_profile("peer")
        self.runner._profile_adapters = {"peer": {Platform.SLACK: self.peer}}
        process_home = patch("hermes_constants.get_process_hermes_home", return_value=self.home)
        process_home.start()
        self.addCleanup(process_home.stop)
        self.app.event("message")(self.adapter._handle_slack_message)
        self.app.event("app_mention")(self.adapter._handle_slack_message)
        self.gate = Gate()
        self.gate.wire(self.app, self.adapter)
        self.downstream = []

        async def observe(body, next):
            self.downstream.append(copy.deepcopy(body))
            return await next()

        self.app.use(observe)

        async def finish_status_writes():
            self.assertTrue(await flush_runtime_status_async())

        self.addAsyncCleanup(finish_status_writes)
        self.addAsyncCleanup(self.adapter.cancel_background_tasks)
        self.addCleanup(self.gate.dispose)
        self.sequence = 200
        self.enable_semantic()

    def supply_native_names(self):
        human = self.client.users_info.return_value

        async def info(*, user):
            if user == "UHUMAN":
                return copy.deepcopy(human)
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

    def enable_semantic(self, choice="yes", confidence=1.0):
        self.gate.jev = AsyncMock()
        self.gate.jev.ask.return_value = (choice, confidence)

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

    async def drain(self):
        await asyncio.gather(*tuple(self.adapter._session_tasks.values()))

    def source_and_key(self):
        source = self.adapter.build_source(
            chat_id="CDEMO",
            chat_type="group",
            user_id="UHUMAN",
            thread_id="100.001",
            scope_id="TDEMO",
            message_id="201.001",
        )
        self.assertIsNotNone(self.adapter._canonicalize(source))
        key = self.adapter._source_session_key(source)
        self.assertEqual(key, self.runner._session_key_for_source(source))
        return source, key

    async def assert_passed(self, body):
        before = len(self.downstream)
        response = await self.dispatch(body)
        await self.drain()
        self.assertEqual(response.status, 200)
        self.assertEqual(len(self.downstream), before + 1)
        self.assertEqual(self.downstream[-1], body)

    async def assert_suppressed(self, body):
        before = len(self.downstream)
        response = await self.dispatch(body)
        self.assertEqual((response.status, response.body), (200, ""))
        self.assertEqual(len(self.downstream), before)

    async def test_unresolved_address_uses_fallback_proposition_not_proven_ownership(self):
        import httpx

        from hermes_slack_agent_router.jev import JevClient

        directory = self.client.users_info.side_effect

        async def names(*, user):
            value = await directory(user=user)
            if user in {"UALPHA", "UBETA"}:
                value["user"]["profile"].update(display_name="共通名", real_name="共通名")
            return value

        self.client.users_info.side_effect = names
        self.client.conversations_replies.return_value = {
            "ok": True,
            "messages": [{"ts": "100.001", "user": "UHUMAN", "text": "Neither is assigned this diagram."}],
        }
        (self.home / ".env").write_text("TYPESAFE_API_KEY=fictional-rework\n")
        self.gate.jev = JevClient()
        native = httpx.AsyncClient
        sent, clients = [], []

        async def respond(request):
            batch = json.loads(request.content)
            sent.append(batch)
            return httpx.Response(200, json=controlled_answers(batch, "yes", 0))

        def client(**kwargs):
            value = native(transport=httpx.MockTransport(respond), **kwargs)
            clients.append(value)
            return value

        with patch("httpx.AsyncClient", side_effect=client):
            await self.assert_passed(self.message("共通名さん、図を確認してください。"))
        self.assertEqual(len(sent), 1)
        self.model.assert_awaited_once()
        batch = sent[0]
        self.assertEqual(set(batch["questions"]), {"response"})
        self.assertEqual(
            batch["state"]["conversation"]["records"][-1]["text"], "共通名さん、図を確認してください。"
        )
        question = batch["questions"]["response"]
        # Audit the transmitted proposition; the injected YES is native fallback,
        # not evidence that a real classifier resolved this ambiguous identity.
        self.assertIn("positive evidence", question["criteria"]["no"]["meaning"])
        self.assertIn("fallback", question["criteria"]["yes"]["meaning"])
        rubric = " ".join(question["instructions"]["routing_contract"])
        self.assertNotIn("Otherwise choose no", rubric)
        self.assertIn("ambiguity alone", rubric)
        self.assertTrue(all(value.is_closed for value in clients))

    async def test_duplicate_raw_json_falls_back_once_with_safe_diagnostic_and_cleanup(self):
        import httpx

        from hermes_slack_agent_router.jev import JevClient

        (self.home / ".env").write_text("TYPESAFE_API_KEY=fictional-rework-secret\n")
        self.gate.jev = JevClient()
        native = httpx.AsyncClient
        yes = b'{"type":"choice","choice":"yes","confidence":1,"probabilities":{"yes":1,"no":0}}'
        no = b'{"type":"choice","choice":"no","confidence":1,"probabilities":{"yes":0,"no":1}}'
        payloads = (
            b'{"answers":{"response":'
            + no.replace(b'"choice":"no"', b'"choice":"yes","choice":"no"')
            + b"}}",
            b'{"answers":{"response":'
            + no.replace(b'"confidence":1', b'"confidence":0,"confidence":1')
            + b"}}",
            b'{"answers":{"response":' + yes + b',"response":' + no + b"}}",
            b'{"answers":{"response":' + yes + b'},"answers":{"response":' + no + b"}}",
            b'{"answers":{"response":'
            + no.replace(b'"type":"choice"', b'"type":"other","type":"choice"')
            + b"}}",
            b'{"answers":{"response":' + no.replace(b'"no":1', b'"no":0,"no":1') + b"}}",
            b'{"answers":{"response":' + no.replace(b'"yes":0', b'"yes":1,"yes":0') + b"}}",
            b'{"answers":{"response":'
            + no.replace(b'"choice":"no"', b'"choice":"yes","choi\\u0063e":"no"')
            + b"}}",
            b'{"answers":{"response":' + yes + b',"respon\\u0073e":' + no + b"}}",
        )
        clients, streams, requests = [], [], []

        class Stream(httpx.AsyncByteStream):
            closed = False

            async def __aiter__(self):
                yield payload

            async def aclose(self):
                self.closed = True

        async def respond(request):
            requests.append(request)
            stream = Stream()
            streams.append(stream)
            return httpx.Response(200, stream=stream)

        def client(**kwargs):
            value = native(transport=httpx.MockTransport(respond), **kwargs)
            clients.append(value)
            return value

        with patch("httpx.AsyncClient", side_effect=client):
            for index, payload in enumerate(payloads):
                with self.subTest(duplicate=index):
                    with self.assertLogs("hermes_slack_agent_router", level="WARNING") as logs:
                        before = len(requests)
                        await self.assert_passed(
                            self.message("<@UBETA> Full malformed-answer body.\n\nKeep all content.")
                        )
                        self.assertEqual(len(requests), before + 1)
                    self.assertEqual(len(logs.output), 1)
                    self.assertIn("answer-json", logs.output[0])
                    for forbidden in (
                        "fictional-rework-secret",
                        "malformed-answer body",
                        "choice",
                        "confidence",
                        "response",
                    ):
                        self.assertNotIn(forbidden, logs.output[0])
            for answer, passes in ((yes, True), (no, False)):
                # Ordinary envelope metadata remains compatible.
                payload = b'{"metadata":{"request_id":"fictional"},"answers":{"response":' + answer + b"}}"
                before = len(requests)
                body = self.message("<@UBETA> Valid sibling full body.")
                if passes:
                    await self.assert_passed(body)
                else:
                    await self.assert_suppressed(body)
                self.assertEqual(len(requests), before + 1)
        self.assertTrue(all(value.is_closed for value in clients))
        self.assertTrue(all(stream.closed for stream in streams))

    async def test_whole_message_native_fallback_contract(self):
        import httpx

        from hermes_slack_agent_router.jev import JevClient

        (self.home / ".env").write_text("TYPESAFE_API_KEY=fictional-whole-message\n")
        self.gate.jev = JevClient()
        factory = httpx.AsyncClient
        sent = []
        choice, confidence = "yes", 1.0

        async def respond(request):
            batch = json.loads(request.content)
            sent.append(batch)
            result = controlled_answers(batch, choice, confidence)
            # A selected tie is valid protocol data; confidence remains independent.
            result["answers"]["response"]["probabilities"] = {"yes": 0.5, "no": 0.5}
            return httpx.Response(200, json=result)

        with patch(
            "httpx.AsyncClient",
            side_effect=lambda **kw: factory(transport=httpx.MockTransport(respond), **kw),
        ):
            for text in (
                "<@UBETA> Explain the fictional chart.",
                (
                    "<@UBETA> Explain the chart. Keep its units! Why?\n\n"
                    "The violet line differs; the amber line bends. Is that intended?\n\n"
                    "<@UALPHA> Also check the unrelated index. Retain this complete message.\n"
                    "> Old command.\n```inert code```"
                ),
            ):
                for shape in ("absent", "null", "self", "reply"):
                    for own_thread, peer_thread in (
                        (True, True),
                        (False, False),
                        (True, False),
                        (False, True),
                    ):
                        with self.subTest(text=text, shape=shape, own=own_thread, peer=peer_thread):
                            self.adapter.config.extra.update(
                                reply_in_thread=own_thread, require_mention=False
                            )
                            self.peer.config.extra["reply_in_thread"] = peer_thread
                            body = self.message(text)
                            if shape == "absent":
                                body["event"].pop("thread_ts")
                            elif shape == "null":
                                body["event"]["thread_ts"] = None
                            elif shape == "self":
                                body["event"]["thread_ts"] = body["event"]["ts"]
                            before, calls = len(self.downstream), len(sent)
                            self.model.reset_mock()
                            history_reads = self.client.conversations_replies.await_count
                            with patch.object(
                                self.peer, "build_source", wraps=self.peer.build_source
                            ) as peer_source:
                                await self.dispatch(body)
                                await self.drain()
                            self.assertEqual(len(self.downstream), before + 1)
                            self.assertEqual(self.downstream[-1], body)
                            self.assertEqual(len(sent), calls + 1)
                            batch = sent[-1]
                            self.assertEqual(set(batch["questions"]), {"response"})
                            self.assertNotIn("source_selection", batch["state"])
                            self.assertNotIn("current_author_content", batch["state"])
                            records = batch["state"]["conversation"]["records"]
                            self.assertEqual(records[-1]["text"], text)
                            self.model.assert_awaited_once()
                            expected_thread = (
                                "100.001" if shape == "reply" else body["event"]["ts"] if own_thread else None
                            )
                            expected_peer = (
                                "100.001"
                                if shape == "reply"
                                else body["event"]["ts"]
                                if peer_thread
                                else None
                            )
                            self.assertEqual(self.model.await_args.args[0].source.thread_id, expected_thread)
                            self.assertEqual(peer_source.call_args.kwargs["thread_id"], expected_peer)
                            if shape != "reply":
                                self.assertEqual(len(records), 1)
                                self.assertEqual(records[0]["role"], "CURRENT_ROOT")
                                self.assertEqual(self.client.conversations_replies.await_count, history_reads)

            for choice, confidence, suppressed in (
                ("no", 0.499, False),
                ("no", 0.5, False),
                ("no", 0.501, True),
                ("no", 1.0, True),
                ("yes", 0.0, False),
                ("yes", 0.1, False),
                ("yes", 1.0, False),
            ):
                with self.subTest(choice=choice, confidence=confidence):
                    body = self.message("<@UBETA> Explain the fictional chart.")
                    before = len(self.downstream)
                    await self.dispatch(body)
                    await self.drain()
                    self.assertEqual(len(self.downstream), before + int(not suppressed))
                    if not suppressed:
                        self.assertEqual(self.downstream[-1], body)

    async def test_whole_message_unexpected_plugin_failure_passes_original_once(self):
        self.gate.jev.ask.side_effect = RuntimeError("fictional private failure")
        body = self.message("<@UBETA> Explain this.")
        await self.assert_passed(body)
        self.model.assert_awaited_once()

    async def test_http_failures_and_malformed_confident_no_pass_original_once(self):
        import httpx

        from hermes_slack_agent_router.jev import JevClient

        (self.home / ".env").write_text("TYPESAFE_API_KEY=fictional-fault\n")
        self.gate.jev = JevClient()
        native = httpx.AsyncClient
        clients, requests = [], []
        response = None

        async def respond(request):
            requests.append(request)
            if isinstance(response, Exception):
                raise response
            return response

        def client(**kwargs):
            value = native(transport=httpx.MockTransport(respond), **kwargs)
            clients.append(value)
            return value

        malformed = [None, {}, {"answers": {}}, {"answers": {"response": None}}]
        valid = {
            "type": "choice",
            "choice": "no",
            "confidence": 1.0,
            "probabilities": {"yes": 0.0, "no": 1.0},
        }
        for key in valid:
            row = copy.deepcopy(valid)
            del row[key]
            malformed.append({"answers": {"response": row}})
        for key, value in (
            ("confidence", True),
            ("confidence", "1"),
            ("confidence", -1.0),
            ("confidence", 2.0),
            ("confidence", float("nan")),
            ("confidence", float("inf")),
            ("choice", "NO"),
            ("type", "text"),
            ("probabilities", {"yes": 1.0, "no": 0.0}),
            ("probabilities", {"yes": 0.0, "no": 0.4}),
            ("probabilities", {"yes": False, "no": True}),
            ("probabilities", {"yes": "0", "no": "1"}),
            ("probabilities", {"yes": 0.0, "no": float("inf")}),
        ):
            malformed.append({"answers": {"response": {**valid, key: value}}})
        malformed += [
            {"answers": {"response": valid, "extra": valid}},
            {"answers": {"response": {**valid, "extra": "no"}}},
        ]
        failures = [
            httpx.Response(status, content=b"fictional-private") for status in (302, 401, 429, 500, 503)
        ]
        failures += [httpx.Response(200, content=data) for data in (b"not json", b"\xff", b"x" * 262145)]

        class Unread(httpx.AsyncByteStream):
            async def __aiter__(self):
                raise AssertionError("invalid encoding/length body must not be read")
                yield b"never read"

        failures += [
            httpx.Response(200, headers=headers, stream=Unread())
            for headers in (
                {"Content-Encoding": "gzip"},
                {"Content-Length": "garbage"},
                {"Content-Length": "262145"},
            )
        ]
        failures += [httpx.Response(200, content=json.dumps(row).encode()) for row in malformed]
        failures += [httpx.ReadTimeout("fictional-private"), httpx.ConnectError("fictional-private")]
        with patch("httpx.AsyncClient", side_effect=client):
            for response in failures:
                with self.subTest(response=type(response).__name__):
                    body = self.message("<@UBETA> Explain the fictional chart.")
                    before = len(requests)
                    self.model.reset_mock()
                    await self.assert_passed(body)
                    self.assertEqual(len(requests), before + 1)
                    self.model.assert_awaited_once()
        self.assertTrue(all(c.is_closed for c in clients))

    async def test_acquisition_metadata_topology_and_size_failures_defer_without_http(self):
        from agent import secret_scope

        from hermes_slack_agent_router.bridge import Bridge, TopologyError
        from hermes_slack_agent_router.jev import JevClient

        self.gate.jev = JevClient()
        directory = self.client.users_info.side_effect
        root = self.client.conversations_replies.return_value
        for mode in (
            "history",
            "metadata",
            "metadata-schema",
            "topology",
            "key",
            "scope",
            "current-size",
            "root-size",
            "encoding",
            "media",
        ):
            with self.subTest(mode=mode):
                text = "<@UBETA> Explain this."
                self.client.conversations_replies.side_effect = (
                    OSError("fictional-private") if mode == "history" else None
                )
                self.client.conversations_replies.return_value = root
                if mode == "root-size":
                    self.client.conversations_replies.return_value = {
                        "ok": True,
                        "messages": [
                            {"ts": "100.001", "user": "UHUMAN", "text": "x" * 600000},
                        ],
                    }
                if mode == "current-size":
                    text += "x" * 600000
                if mode == "encoding":
                    text += "\ud800"

                async def info(*, user, mode=mode):
                    if user == "UBETA" and mode == "metadata":
                        raise OSError("fictional-private")
                    if user == "UBETA" and mode == "metadata-schema":
                        return {"ok": False}
                    return await directory(user=user)

                self.client.users_info.side_effect = info
                body = self.message(text)
                if mode == "media":
                    body["event"]["attachments"] = [{"text": "full attachment"}]
                self.model.reset_mock()
                with (
                    patch.object(Bridge, "participants", side_effect=TopologyError("private"))
                    if mode == "topology"
                    else patch.object(Bridge, "participants", Bridge.participants),
                    patch.object(secret_scope, "get_secret", side_effect=RuntimeError("private"))
                    if mode == "scope"
                    else patch.object(secret_scope, "get_secret", return_value=None),
                    patch("httpx.AsyncClient") as http,
                ):
                    await self.assert_passed(body)
                http.assert_not_called()
                self.model.assert_awaited_once()

    async def test_actual_native_http_fit_preserves_protected_records_and_full_delivery(self):
        import httpx

        from hermes_slack_agent_router.jev import JevClient, serialize_request

        self.client.conversations_replies.return_value = {
            "ok": True,
            "messages": [
                {"ts": "100.001", "user": "UROOT", "text": "r" * 160000},
                {"ts": "101.001", "user": "UDROP", "text": '界"\\\t' * 60000},
                {"ts": "102.001", "user": "UKEEP", "text": "exact retained prior"},
            ],
        }
        (self.home / ".env").write_text("TYPESAFE_API_KEY=fictional-budget\n")
        self.gate.jev = JevClient()
        native = httpx.AsyncClient
        requests = []

        async def respond(request):
            requests.append(request)
            return httpx.Response(200, json=controlled_answers(json.loads(request.content)))

        body = self.message("<@UBETA> Preserve the complete request " + "c" * 7000)
        with patch(
            "httpx.AsyncClient", side_effect=lambda **kw: native(transport=httpx.MockTransport(respond), **kw)
        ):
            await self.assert_passed(body)
        self.assertEqual(len(requests), 1)
        raw = requests[0].content
        batch = json.loads(raw)
        self.assertEqual(raw, serialize_request(batch))
        self.assertLessEqual(len(raw), 524288)
        records = batch["state"]["conversation"]["records"]
        self.assertEqual([r["timestamp"] for r in records], ["100.001", "102.001", body["event"]["ts"]])
        self.assertEqual(records[0]["text"], "r" * 160000)
        self.assertEqual(records[-1]["text"], body["event"]["text"])
        self.assertNotIn("UDROP", [p["user_id"] for p in batch["state"]["people"]])
        self.model.assert_awaited_once()

    async def test_native_denial_after_ballot_and_failure_continuation(self):
        from hermes_slack_agent_router.jev import JevError

        baseline = dict(self.adapter.config.extra)
        for options, text, allowed in (
            ({"allowed_users": ["UOTHER"]}, "<@UBETA> explain", False),
            ({"allowed_channels": ["COTHER"]}, "<@UBETA> explain", False),
            ({"ignored_channels": ["CDEMO"]}, "<@UBETA> explain", False),
            ({"ignore_other_user_mentions": True}, "<@UALPHA> explain", False),
            ({"strict_mention": True, "require_mention": True}, "explain", False),
            ({"thread_require_mention": True, "require_mention": False}, "explain", False),
            ({"require_mention": False}, "explain", True),
            ({"require_mention": True}, "explain", True),
        ):
            for failure in (False, True):
                with self.subTest(options=options, failure=failure):
                    self.adapter.config.extra = {**baseline, **options}
                    self.model.reset_mock()
                    self.gate.jev.ask.reset_mock()
                    self.gate.jev.ask.side_effect = JevError("controlled failure") if failure else None
                    body = self.message(text)
                    await self.assert_passed(body)
                    self.gate.jev.ask.assert_awaited_once()
                    batch = self.gate.jev.ask.await_args.args[0]
                    self.assertEqual(set(batch["questions"]), {"response"})
                    self.assertEqual(batch["state"]["conversation"]["records"][-1]["text"], text)
                    self.assertEqual(self.model.await_count, int(allowed))
        self.adapter.config.extra = baseline

    async def test_native_authorization_transport_home_not_routed_runtime(self):
        from gateway.profile_routing import ProfileRoute

        from hermes_slack_agent_router.bridge import Bridge

        self.runner.config.profile_routes.insert(
            0, ProfileRoute("thread-runtime", "slack", "peer", chat_id="CDEMO", thread_id="100.001")
        )
        self.adapter.set_authorization_check(lambda *args, **kwargs: None)
        body = self.message("<@UBETA> Explain this.")
        bound = await Bridge(self.adapter).bind(body)
        self.assertEqual(bound.identity.authorization_home, self.home)
        self.assertEqual(bound.identity.runtime_home, self.peer_home)
        self.adapter.config.extra["allowed_users"] = ["UOTHER"]
        self.peer.config.extra["allowed_users"] = ["UHUMAN"]
        await self.assert_passed(body)
        self.gate.jev.ask.assert_awaited_once()
        self.model.assert_not_awaited()
        self.gate.jev.ask.reset_mock()
        self.adapter.config.extra["allowed_users"] = ["UHUMAN"]
        self.peer.config.extra["allowed_users"] = ["UOTHER"]
        await self.assert_passed(self.message("<@UBETA> Explain the full diagram; include all context."))
        self.gate.jev.ask.assert_awaited_once()
        self.model.assert_awaited_once()
        self.assertEqual(self.model.await_args.args[0].source.profile, "peer")

    async def test_sender_kind_is_context_not_admission_with_real_http(self):
        import httpx

        from hermes_slack_agent_router.jev import JevClient

        (self.home / ".env").write_text("TYPESAFE_API_KEY=fictional-sender-policy\n")
        self.gate.jev = JevClient()
        native = httpx.AsyncClient
        requests, clients = [], []
        choice, confidence = "yes", 1.0

        async def respond(request):
            batch = json.loads(request.content)
            requests.append(batch)
            return httpx.Response(200, json=controlled_answers(batch, choice, confidence))

        def client(**kwargs):
            value = native(transport=httpx.MockTransport(respond), **kwargs)
            clients.append(value)
            return value

        directory = self.client.users_info.side_effect
        sender_kind = "human"

        async def names(*, user):
            value = await directory(user=user)
            if user == "UHUMAN":
                value["user"]["is_bot"] = {"human": False, "bot": True, "unknown": None}[sender_kind]
            return value

        self.client.users_info.side_effect = names
        with patch("httpx.AsyncClient", side_effect=client):
            for sender_kind, changes in (
                ("human", {}),
                ("bot", {"bot_id": "BMONITOR", "subtype": "bot_message"}),
                ("bot", {}),
                ("unknown", {}),
            ):
                for allow_bots in ("all", "none"):
                    self.adapter.config.extra["allow_bots"] = allow_bots
                    os.environ["SLACK_ALLOW_BOTS"] = allow_bots
                    self.assertEqual(self.adapter._slack_allow_bots(), allow_bots)
                    # Native identity cache is fixture-local; do not reuse a prior kind.
                    self.adapter._user_is_bot_cache.clear()
                    for choice, confidence, suppressed in (
                        ("yes", 1.0, False),
                        ("no", 0.5, False),
                        ("no", 0.501, True),
                    ):
                        with self.subTest(
                            kind=sender_kind,
                            changes=changes,
                            allow=allow_bots,
                            choice=choice,
                            confidence=confidence,
                        ):
                            self.model.reset_mock()
                            before = len(requests)
                            body = self.message(
                                "<@UBETA> Explain all of this.\n\nKeep the full body.", **changes
                            )
                            if suppressed:
                                await self.assert_suppressed(body)
                            else:
                                await self.assert_passed(body)
                            self.assertEqual(len(requests), before + 1)
                            batch = requests[-1]
                            self.assertEqual(set(batch["questions"]), {"response"})
                            current = batch["state"]["conversation"]["records"][-1]
                            self.assertEqual(current["text"], body["event"]["text"])
                            self.assertEqual(current["sender"]["kind"], sender_kind)
                            self.assertEqual(
                                self.model.await_count,
                                int(not suppressed and (sender_kind != "bot" or allow_bots == "all")),
                            )
        self.assertTrue(all(value.is_closed for value in clients))

    async def test_native_self_dm_mpim_and_commands_keep_ordinary_controls(self):
        for changes, text in (
            ({"user": "UBETA"}, "self"),
            ({"channel_type": "im"}, "DM"),
            ({"channel_type": "mpim"}, "MPIM"),
            ({}, "<@UBETA> /help"),
            ({}, "!help"),
        ):
            with self.subTest(changes=changes, text=text):
                self.gate.jev.ask.reset_mock()
                body = self.message(text, **changes)
                if changes.get("user") == "UBETA":
                    await self.dispatch(body)  # Bolt's own self-event middleware runs before ours.
                else:
                    await self.assert_passed(body)
                self.gate.jev.ask.assert_not_awaited()

    async def test_pending_controls_and_late_pending_bypass_confident_no(self):
        from tools import clarify_gateway, slash_confirm

        _, key = self.source_and_key()
        self.enable_semantic("no")
        for mode in ("clarify", "slash", "update", "late"):
            with self.subTest(mode=mode):
                self.gate.jev.ask.reset_mock()
                if mode == "clarify":
                    clarify_gateway.register("demo-choice", key, "Choose", ["Alpha", "Beta"])
                elif mode == "slash":
                    slash_confirm.register(key, "demo-confirm", "/new", AsyncMock())
                elif mode == "update":
                    state = self.SessionState()
                    state.persistent.update_prompt_pending = True
                    self.runner._sessions[key] = state

                else:

                    async def become_pending(batch):
                        state = self.SessionState()
                        state.persistent.update_prompt_pending = True
                        self.runner._sessions[key] = state
                        return "no", 1.0

                    self.gate.jev.ask.side_effect = become_pending
                try:
                    await self.assert_passed(self.message("1" if mode == "clarify" else "yes"))
                    self.assertEqual(self.gate.jev.ask.await_count, int(mode == "late"))
                finally:
                    clarify_gateway.clear_session(key)
                    slash_confirm.clear(key)
                    self.runner._sessions.pop(key, None)

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
            await ready.wait()
            self.assertTrue(approval.has_blocking_approval(key))
            await self.assert_passed(self.message("yes"))
            self.gate.jev.ask.assert_not_awaited()
        finally:
            approval.resolve_gateway_approval(key, "deny")
            await task
        self.assertFalse(approval.has_blocking_approval(key))

    async def test_original_structured_payload_native_history_busy_merge_fifo_and_replay(self):
        from gateway.profile_routing import ProfileRoute
        from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest
        from hermes_constants import get_hermes_home

        from hermes_slack_agent_router.plugin import register

        manager = PluginManager()
        register(PluginContext(PluginManifest(name="slack-agent-router"), manager))
        plugin_manager = patch("hermes_cli.plugins.get_plugin_manager", return_value=manager)
        plugin_manager.start()
        self.addCleanup(plugin_manager.stop)
        assembled, admitted_events = [], []

        async def receive(event):
            async with self.runner._async_profile_scope_for_source(event.source):
                self.assertEqual(
                    get_hermes_home(), self.peer_home if event.source.profile == "peer" else self.home
                )
                admitted = await self.runner._hm_pre_gateway_dispatch_hook(event, event.source)
                self.assertIs(admitted, event)
                if not self.runner._is_user_authorized_for_source(admitted.source):
                    return
                text = self.runner._prefix_inbound_sender_context(admitted, admitted.source, admitted.text)
                text = self.runner._prepend_inbound_reply_context(admitted, admitted.source, text)
                assembled.append(text)
                admitted_events.append(copy.deepcopy(admitted))
                await self.model(admitted)

        self.adapter.set_message_handler(receive)
        bot_prior = {
            "ts": "101.001",
            "user": "UBETA",
            "bot_id": "BFICTION",
            "text": "BOT_NOTIFICATION",
            "blocks": self.adapter._markdown_block_payload("BOT_VISIBLE_NATIVE_MARKDOWN"),
        }
        self.client.conversations_replies.return_value = {
            "ok": True,
            "messages": [{"ts": "100.001", "user": "UHUMAN", "text": "ROOT_NATIVE_CONTEXT"}, bot_prior],
        }
        for routed in (False, True):
            if routed:
                self.runner.config.profile_routes.insert(
                    0, ProfileRoute("rework-runtime", "slack", "peer", bot_profile="default", chat_id="CDEMO")
                )
            for choice, confidence in (("yes", 0), ("no", 0.5)):
                self.enable_semantic(choice, confidence)
                mixed = self.message(
                    "<@UBETA> OWN.\n\n<@UALPHA> FOREIGN.\n> Quoted; do not cut.\n```code``` "
                )
                before = len(assembled)
                await self.assert_passed(mixed)
                self.assertEqual(len(assembled), before + 1)
                for marker in (
                    "OWN",
                    "FOREIGN",
                    "Quoted; do not cut",
                    "code",
                    "ROOT_NATIVE_CONTEXT",
                    "BOT_NOTIFICATION",
                ):
                    self.assertIn(marker, assembled[-1])
                batch = self.gate.jev.ask.await_args.args[0]
                self.assertEqual(
                    batch["state"]["conversation"]["records"][-1]["text"], mixed["event"]["text"]
                )
                self.assertEqual(
                    batch["state"]["conversation"]["records"][1]["blocks"], tuple(bot_prior["blocks"])
                )
        assembled.clear()
        admitted_events.clear()
        self.model.reset_mock()
        _, key = self.source_and_key()
        body = self.message(
            "<@UALPHA> SUMMARY; <@UBETA> DIAGRAM.",
            blocks=[
                {
                    "type": "rich_text",
                    "elements": [
                        {
                            "type": "rich_text_section",
                            "elements": [{"type": "text", "text": "SUMMARY; DIAGRAM."}],
                        },
                        {"type": "rich_text_quote", "elements": [{"type": "text", "text": "quoted prior"}]},
                        {
                            "type": "rich_text_preformatted",
                            "elements": [{"type": "text", "text": "code prior"}],
                        },
                    ],
                }
            ],
        )
        await self.assert_passed(body)
        batch = self.gate.jev.ask.await_args.args[0]
        self.assertEqual(
            batch["state"]["conversation"]["records"][-1]["blocks"], tuple(body["event"]["blocks"])
        )
        delivered = self.model.await_args.args[0]
        self.assertIn("SUMMARY", delivered.text)
        self.assertIn("DIAGRAM", delivered.text)
        self.assertTrue(delivered.channel_context or delivered.reply_to_text)
        self.model.reset_mock()
        self.adapter._active_sessions[key] = asyncio.Event()
        busy = AsyncMock(return_value=True)
        self.adapter.set_busy_session_handler(busy)
        await self.assert_passed(self.message("<@UBETA> FIRST; foreign SUMMARY."))
        busy.assert_awaited_once()
        self.assertIn("foreign SUMMARY", busy.await_args.args[0].text)
        self.adapter.set_busy_session_handler(None)
        self.adapter._busy_text_debounce_seconds = 0
        for label in ("ONE", "TWO"):
            await self.assert_passed(self.message(f"<@UBETA> DIAGRAM_{label}; SUMMARY_{label}."))
        pending = self.adapter.get_pending_message(key)
        self.assertIsNotNone(pending)
        self.assertIn("SUMMARY_ONE", pending.text)
        self.assertIn("SUMMARY_TWO", pending.text)
        self.adapter._active_sessions.pop(key)
        await self.adapter.handle_message(pending)
        await self.drain()
        self.model.assert_awaited_once()
        self.assertIn("SUMMARY_ONE", self.model.await_args.args[0].text)
        self.runner._sessions[key] = self.SessionState()
        self.adapter._active_sessions[key] = asyncio.Event()

        async def enqueue(event, session_key):
            self.runner._queue_or_replace_pending_event(session_key, event)
            return True

        self.adapter.set_busy_session_handler(enqueue)
        for label in ("THREE", "FOUR"):
            await self.assert_passed(self.message(f"<@UBETA> DIAGRAM_{label}; SUMMARY_{label}."))
        self.assertEqual(self.runner._queue_depth(key, adapter=self.adapter), 2)
        first = self.adapter.get_pending_message(key)
        second = self.runner._promote_queued_event(key, self.adapter, None)
        self.assertIn("SUMMARY_THREE", first.text)
        self.assertIn("SUMMARY_FOUR", second.text)
        self.adapter._active_sessions.pop(key)
        self.adapter.set_busy_session_handler(None)
        for event in (first, second):
            await self.adapter.handle_message(event)
            await self.drain()
        self.assertIn("SUMMARY_FOUR", self.model.await_args.args[0].text)
        self.assertEqual(len(assembled), 4)
        for text in assembled:
            for marker in ("ROOT_NATIVE_CONTEXT", "BOT_NOTIFICATION", "SUMMARY", "DIAGRAM"):
                self.assertIn(marker, text)
        self.assertIn("SUMMARY_ONE", assembled[1])
        self.assertIn("SUMMARY_TWO", assembled[1])
        self.assertIn("SUMMARY_THREE", assembled[2])
        self.assertIn("SUMMARY_FOUR", assembled[3])
        self.assertTrue(all(event.channel_context for event in admitted_events))

    async def test_media_and_attachments_reach_native_without_classifier_projection(self):
        cached = self.root / "fictional-chart.png"
        cached.write_bytes(b"fictional controlled cached media")
        body = self.message(
            "<@UBETA> Explain this chart.",
            files=[
                {
                    "id": "FCHART",
                    "mimetype": "image/png",
                    "url_private": "https://files.invalid/chart.png",
                }
            ],
            attachments=[{"title": "Fictional attachment", "text": "FULL_ATTACHMENT_CONTEXT"}],
        )
        with patch.object(
            self.adapter, "_cache_slack_file", return_value=(str(cached), "image/png", None)
        ) as cache:
            await self.assert_passed(body)
        self.gate.jev.ask.assert_not_awaited()
        cache.assert_awaited_once()
        self.model.assert_awaited_once()
        delivered = self.model.await_args.args[0]
        self.assertEqual(delivered.media_urls, [str(cached)])
        self.assertEqual(delivered.media_types, ["image/png"])
        self.assertIn("FULL_ATTACHMENT_CONTEXT", delivered.text)
        self.assertTrue(delivered.channel_context or delivered.reply_to_text)

    async def test_confident_no_never_model_steer_queue_and_native_dedup_remains(self):
        _, key = self.source_and_key()
        self.adapter._active_sessions[key] = asyncio.Event()
        busy = AsyncMock(return_value=True)
        self.adapter.set_busy_session_handler(busy)
        self.enable_semantic("no", 0.501)
        await self.assert_suppressed(self.message("<@UALPHA> Explain the summary."))
        busy.assert_not_awaited()
        self.assertFalse(self.adapter._pending_messages or self.adapter._pending_text_batches)
        self.model.assert_not_awaited()
        self.adapter._active_sessions.pop(key)
        self.adapter.set_busy_session_handler(None)
        self.enable_semantic()
        body = self.message("<@UBETA> Original full text.")
        await self.assert_passed(body)
        duplicate = copy.deepcopy(body)
        duplicate["event"]["type"] = "app_mention"
        duplicate["event_id"] = "EvOtherEnvelope"
        await self.assert_passed(duplicate)
        self.model.assert_awaited_once()
        self.assertEqual(self.gate.jev.ask.await_count, 2)

    async def test_latest_seven_root_short_tail_and_history_validation(self):
        from hermes_slack_agent_router.plugin import Gate
        from hermes_slack_agent_router.semantic import SemanticError

        records = [{"ts": f"{100 + i}.001", "user": "UHUMAN", "text": f"note {i}"} for i in range(13)]
        self.client.conversations_replies.side_effect = [
            {
                "ok": True,
                "messages": [records[0], *records[-7:]],
                "has_more": True,
                "response_metadata": {"next_cursor": "older"},
            },
        ]
        result = await Gate.history(self.client, self.key, "201.001")
        self.assertEqual([h.identity for h in result], [records[0]["ts"], *[m["ts"] for m in records[-7:]]])
        self.client.conversations_replies.assert_awaited_once_with(
            channel="CDEMO", ts="100.001", latest="201.001", inclusive=False, limit=7
        )
        self.client.conversations_replies.reset_mock()
        self.client.conversations_replies.side_effect = [
            {
                "ok": True,
                "messages": [records[0], *records[-2:]],
                "has_more": True,
                "response_metadata": {"next_cursor": "older"},
            },
            {"ok": True, "messages": [records[0], *records[-7:-2]], "has_more": False},
        ]
        result = await Gate.history(self.client, self.key, "201.001")
        self.assertEqual([h.identity for h in result], [records[0]["ts"], *[m["ts"] for m in records[-7:]]])
        self.assertEqual(self.client.conversations_replies.await_args_list[-1].kwargs["cursor"], "older")
        self.client.conversations_replies.side_effect = None
        for bad in (
            {"ok": False},
            {"ok": True, "messages": [*records[:1], {**records[1], "team": "TFOREIGN"}]},
            {"ok": True, "messages": [records[0], records[2], records[1]]},
            {"ok": True, "messages": [records[0], {**records[1], "ts": "999.001"}]},
            {"ok": True, "messages": [records[0], {**records[0], "text": "conflict"}]},
            {"ok": True, "messages": records[:9]},
            {"ok": True, "messages": [], "has_more": True},
        ):
            self.client.conversations_replies.return_value = bad
            with self.assertRaises(SemanticError):
                await Gate.history(self.client, self.key, "201.001")
        self.client.conversations_replies.return_value = {"ok": True, "messages": records[1:3]}
        self.client.conversations_history.return_value = {"ok": True, "messages": records[:1]}
        result = await Gate.history(self.client, self.key, "201.001")
        self.assertEqual(result[0].identity, "100.001")
        self.client.conversations_history.assert_awaited_with(
            channel="CDEMO", oldest="100.001", inclusive=True, limit=1
        )

    async def test_history_advancing_short_empty_duplicate_pages_root_placement_and_cutoff(self):
        from hermes_slack_agent_router.plugin import Gate
        from hermes_slack_agent_router.semantic import SemanticError

        root = {"ts": "100.001", "user": "UHUMAN", "text": "Root"}
        recent = [{"ts": f"{110 + i}.001", "user": "UHUMAN", "text": "Recent"} for i in range(6)]
        older = {"ts": "109.001", "user": "UHUMAN", "text": "Older"}
        for flags in ({"has_more": True}, {"has_more": False}, {}):
            client = AsyncMock()
            client.conversations_replies.side_effect = [
                {
                    "ok": True,
                    "messages": [*recent, root, {"ts": "201.001"}],
                    **flags,
                    "response_metadata": {"next_cursor": "a"},
                },
                {"ok": True, "messages": [], "response_metadata": {"next_cursor": "b"}},
                {"ok": True, "messages": [root, recent[0]], "response_metadata": {"next_cursor": "c"}},
                {"ok": True, "messages": [root, older], "response_metadata": {"next_cursor": "unused"}},
            ]
            with self.subTest(flags=flags):
                result = await Gate.history(client, self.key, "201.001")
                self.assertEqual(
                    [r.identity for r in result],
                    ["100.001", "109.001", *[f"{110 + i}.001" for i in range(6)]],
                )
                self.assertEqual(client.conversations_replies.await_count, 4)
                self.assertEqual(
                    [c.kwargs.get("cursor") for c in client.conversations_replies.await_args_list],
                    [None, "a", "b", "c"],
                )
                client.conversations_history.assert_not_awaited()
        for fault in ("loop", "four-call-missing-root", "conflict", "foreign-root"):
            client = AsyncMock()
            first = {"ok": True, "messages": recent, "response_metadata": {"next_cursor": "a"}}
            if fault == "loop":
                pages = [first, {"ok": True, "messages": [], "response_metadata": {"next_cursor": "a"}}]
            elif fault == "four-call-missing-root":
                pages = [
                    first,
                    {"ok": True, "messages": [], "response_metadata": {"next_cursor": "b"}},
                    {"ok": True, "messages": [], "response_metadata": {"next_cursor": "c"}},
                    {"ok": True, "messages": [older]},
                ]
            elif fault == "conflict":
                pages = [first, {"ok": True, "messages": [{**recent[0], "text": "conflicting"}]}]
            else:
                pages = [{"ok": True, "messages": recent}]
                client.conversations_history.return_value = {
                    "ok": True,
                    "messages": [{**root, "channel": "COTHER"}],
                }
            client.conversations_replies.side_effect = pages
            with self.subTest(fault=fault), self.assertRaises(SemanticError):
                await Gate.history(client, self.key, "201.001")
            if fault == "four-call-missing-root":
                self.assertEqual(client.conversations_replies.await_count, 4)
                client.conversations_history.assert_not_awaited()

    async def test_native_topology_change_after_inference_passes_instead_of_suppressing(self):
        async def infer(batch):
            self.peer._team_bot_user_ids["TDEMO"] = "UCHANGED"
            return "no", 1.0

        self.gate.jev.ask.side_effect = infer
        await self.assert_passed(self.message("<@UBETA> Full unchanged message."))
        self.model.assert_awaited_once()

    async def test_malformed_metadata_field_defers_instead_of_inventing_null(self):
        directory = self.client.users_info.side_effect

        async def info(*, user):
            response = await directory(user=user)
            if user == "UBETA":
                response["user"]["profile"]["real_name"] = ["not a name"]
            return response

        self.client.users_info.side_effect = info
        self.enable_semantic("no", 1.0)
        await self.assert_passed(self.message("<@UBETA> Full original message."))
        self.gate.jev.ask.assert_not_awaited()

    async def test_valid_unknown_context_kind_is_not_an_acquisition_failure(self):
        directory = self.client.users_info.side_effect

        async def info(*, user):
            if user == "UCONTEXT":
                return {"ok": True, "user": {"id": user, "team_id": "TDEMO", "profile": {}}}
            return await directory(user=user)

        self.client.users_info.side_effect = info
        self.client.conversations_replies.return_value = {
            "ok": True,
            "messages": [
                {"ts": "100.001", "user": "UCONTEXT", "text": "<@UBETA> was assigned this task."},
            ],
        }
        await self.assert_passed(self.message("<@UBETA> Explain this."))
        self.gate.jev.ask.assert_awaited_once()
        people = context_view(self.gate.jev.ask.await_args.args[0]["state"])["participants"]
        self.assertEqual(people["UCONTEXT"]["kind"], "unknown")

    async def test_native_same_complete_message_two_receivers_and_topology_controls(self):
        from slack_bolt.async_app import AsyncApp
        from slack_bolt.authorization import AuthorizeResult
        from slack_bolt.request.async_request import AsyncBoltRequest

        from hermes_slack_agent_router.plugin import Gate

        async def authorize(**kwargs):
            return AuthorizeResult(enterprise_id=None, team_id="TDEMO", bot_user_id="UALPHA")

        peer_app = AsyncApp(
            signing_secret="fictional-peer",
            authorize=authorize,
            request_verification_enabled=False,
            process_before_response=True,
        )
        self.peer._app = peer_app
        self.peer._bot_user_id = "UALPHA"
        self.peer._register_mentioned_thread("100.001", "TDEMO")
        peer_app.event("message")(self.peer._handle_slack_message)
        peer_gate = Gate()
        peer_gate.jev = self.gate.jev
        peer_gate.wire(peer_app, self.peer)
        self.addCleanup(peer_gate.dispose)
        self.addAsyncCleanup(self.peer.cancel_background_tasks)
        peer_handoffs = []

        async def observe(body, next):
            peer_handoffs.append(copy.deepcopy(body))
            return await next()

        peer_app.use(observe)

        body = self.message(
            "<@UALPHA> Explain the summary.\n\n<@UBETA> Explain the diagram; include every unit!"
        )
        await self.assert_passed(body)
        result = await peer_app.async_dispatch(AsyncBoltRequest(body=json.dumps(body), mode="socket_mode"))
        await asyncio.gather(*tuple(self.peer._session_tasks.values()))
        self.assertEqual(result.status, 200)
        self.assertEqual(self.downstream, [body])
        self.assertEqual(peer_handoffs, [body])
        self.model.assert_awaited_once()
        self.peer._message_handler.assert_awaited_once()
        for event in (self.model.await_args.args[0], self.peer._message_handler.await_args.args[0]):
            self.assertIn("summary", event.text)
            self.assertIn("diagram", event.text)
            self.assertTrue(event.channel_context)
        seen = [copy.deepcopy(call.args[0]) for call in self.gate.jev.ask.await_args_list]
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0]["state"].pop("whoami")["user_id"], "UBETA")
        self.assertEqual(seen[1]["state"].pop("whoami")["user_id"], "UALPHA")
        self.assertEqual(seen[0], seen[1])
        for mode in ("duplicate", "unserved", "unknown-socket", "disconnected", "foreign"):
            with self.subTest(mode=mode):
                self.gate.jev.ask.reset_mock()
                old = self.peer._team_bot_user_ids
                authority = self.runner.session_authorities.for_home(self.peer_home)
                try:
                    if mode == "duplicate":
                        self.peer._team_bot_user_ids = {"TDEMO": "UBETA"}
                    elif mode == "unserved":
                        authority.retiring = True
                    elif mode == "foreign":
                        self.peer._team_bot_user_ids = {"TFOREIGN": "UALPHA"}
                    elif mode == "disconnected":
                        self.peer._running = False
                    with (
                        patch.object(self.peer, "_socket_transport_connected", return_value=None)
                        if mode == "unknown-socket"
                        else patch.object(
                            self.peer,
                            "_socket_transport_connected",
                            wraps=self.peer._socket_transport_connected,
                        )
                    ):
                        await self.assert_passed(self.message("<@UBETA> Keep the complete text."))
                    if mode in {"duplicate", "unserved", "unknown-socket", "foreign"}:
                        self.gate.jev.ask.assert_not_awaited()
                    else:
                        self.gate.jev.ask.assert_awaited_once()
                finally:
                    self.peer._team_bot_user_ids = old
                    self.peer._running = True
                    authority.retiring = False

    async def test_native_secret_scope_multiplex_and_routed_runtime(self):
        import httpx
        from agent import secret_scope
        from gateway.profile_routing import ProfileRoute
        from test_semantic import prepare, snapshot

        from hermes_slack_agent_router.jev import JevClient, JevError

        native = httpx.AsyncClient
        seen = []
        both = asyncio.Event()

        async def respond(request):
            seen.append(request.headers["Authorization"])
            if len(seen) == 2:
                both.set()
            await both.wait()
            return httpx.Response(200, json=controlled_answers(json.loads(request.content)))

        mode = secret_scope.set_multiplex_context(True)
        try:
            with patch(
                "httpx.AsyncClient",
                side_effect=lambda **kw: native(transport=httpx.MockTransport(respond), **kw),
            ):

                async def ask(value):
                    token = secret_scope.set_secret_scope({"TYPESAFE_API_KEY": value})
                    try:
                        return await JevClient().ask(prepare(snapshot()))
                    finally:
                        secret_scope.reset_secret_scope(token)

                await asyncio.gather(ask("synthetic-atlas"), ask("synthetic-birch"))
                for mapping in ({}, None):
                    token = secret_scope.set_secret_scope(mapping)
                    try:
                        with self.assertRaises(JevError):
                            await JevClient().ask(prepare(snapshot()))
                    finally:
                        secret_scope.reset_secret_scope(token)
        finally:
            secret_scope.reset_multiplex_context(mode)
        self.assertCountEqual(seen, ["Bearer synthetic-atlas", "Bearer synthetic-birch"])
        (self.home / ".env").write_text("TYPESAFE_API_KEY=synthetic-transport\n")
        (self.peer_home / ".env").write_text("TYPESAFE_API_KEY=synthetic-runtime\n")
        self.runner.config.profile_routes.insert(
            0, ProfileRoute("runtime", "slack", "peer", bot_profile="default", chat_id="CDEMO")
        )
        self.gate.jev = JevClient()
        with patch(
            "httpx.AsyncClient", side_effect=lambda **kw: native(transport=httpx.MockTransport(respond), **kw)
        ):
            await self.assert_passed(self.message("<@UBETA> Explain this."))
        self.assertEqual(seen[-1], "Bearer synthetic-runtime")

    async def test_caller_edit_shutdown_unload_and_late_results_lifecycle(self):
        for mode in ("caller", "edit", "shutdown", "unload"):
            with self.subTest(mode=mode):
                self.gate.disposed = False
                self.enable_semantic()
                started, closed, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

                async def infer(batch, started=started, release=release, closed=closed, mode=mode):
                    if "OLD_MARKER" not in context_view(batch["state"])["CURRENT"]["text"]:
                        return "yes", 1.0
                    started.set()
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        if mode == "edit":
                            return "yes", 1.0  # Adversarial late result cannot resurrect obsolete input.
                        raise
                    finally:
                        closed.set()
                    return "no", 1.0

                self.gate.jev.ask.side_effect = infer
                body = self.message("<@UBETA> OLD_MARKER")
                before = len(self.downstream)
                task = asyncio.create_task(self.dispatch(body))
                try:
                    await started.wait()
                    if mode == "caller":
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                    elif mode == "shutdown":
                        self.runner._draining = True
                        await self.adapter.cancel_background_tasks()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                    elif mode == "edit":
                        edited = copy.deepcopy(body)
                        edited["event"] = {
                            "type": "message",
                            "subtype": "message_changed",
                            "channel": "CDEMO",
                            "team": "TDEMO",
                            "channel_type": "channel",
                            "message": {
                                **body["event"],
                                "text": "<@UBETA> NEW_MARKER",
                                "edited": {"ts": "900.001"},
                            },
                        }
                        await self.dispatch(edited)
                        await task
                    else:
                        self.gate.dispose()
                        release.set()
                        await task
                    await self.drain()
                    self.assertTrue(closed.is_set())
                    if mode in ("caller", "shutdown"):
                        self.assertEqual(len(self.downstream), before)
                    elif mode == "edit":
                        self.assertEqual(len(self.downstream), before + 1)
                        self.assertIn("NEW_MARKER", json.dumps(self.downstream[-1]))
                    else:
                        self.assertEqual(self.downstream[-1], body)
                    self.assertFalse(self.gate.active or self.adapter._background_tasks)
                finally:
                    release.set()
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    self.runner._draining = False
        self.gate.dispose()
        self.runner._draining = True
        await self.assert_suppressed(self.message("<@UBETA> shutdown after unload"))
        self.runner._draining = False
        await self.assert_passed(self.message("<@UBETA> live after unload"))

    async def test_real_http_lifecycle_closes_stream_and_preserves_unload_delivery(self):
        import httpx

        from hermes_slack_agent_router.jev import JevClient

        native = httpx.AsyncClient
        (self.home / ".env").write_text("TYPESAFE_API_KEY=fictional-lifecycle\n")
        for mode in ("caller", "edit", "shutdown", "unload"):
            with self.subTest(mode=mode):
                started, release = asyncio.Event(), asyncio.Event()
                streams, clients = [], []
                self.gate.disposed = False
                self.gate.jev = JevClient()

                class Stream(httpx.AsyncByteStream):
                    def __init__(self, batch, started=started, release=release):
                        self.batch, self.closed = batch, False
                        self.started, self.release = started, release

                    async def __aiter__(self):
                        self.started.set()
                        await self.release.wait()
                        yield json.dumps(controlled_answers(self.batch, "no")).encode()

                    async def aclose(self):
                        self.closed = True

                async def respond(request, streams=streams, Stream=Stream):
                    batch = json.loads(request.content)
                    if "OLD_MARKER" in context_view(batch["state"])["CURRENT"]["text"]:
                        stream = Stream(batch)
                        streams.append(stream)
                        return httpx.Response(200, stream=stream)
                    return httpx.Response(200, json=controlled_answers(batch))

                def client(clients=clients, respond=respond, **kwargs):
                    value = native(transport=httpx.MockTransport(respond), **kwargs)
                    clients.append(value)
                    return value

                body = self.message("<@UBETA> OLD_MARKER")
                before = len(self.downstream)
                with patch("httpx.AsyncClient", side_effect=client):
                    task = asyncio.create_task(self.dispatch(body))
                    try:
                        await started.wait()
                        if mode == "caller":
                            task.cancel()
                            with self.assertRaises(asyncio.CancelledError):
                                await task
                        elif mode == "shutdown":
                            self.runner._draining = True
                            await self.adapter.cancel_background_tasks()
                            with self.assertRaises(asyncio.CancelledError):
                                await task
                        elif mode == "edit":
                            edited = copy.deepcopy(body)
                            edited["event"] = {
                                "type": "message",
                                "subtype": "message_changed",
                                "channel": "CDEMO",
                                "team": "TDEMO",
                                "channel_type": "channel",
                                "message": {
                                    **body["event"],
                                    "text": "<@UBETA> NEW_MARKER",
                                    "edited": {"ts": "900.001"},
                                },
                            }
                            await self.dispatch(edited)
                            await task
                        else:
                            self.gate.dispose()
                            release.set()
                            await task
                        await self.drain()
                        self.assertEqual(len(self.downstream), before + int(mode in {"edit", "unload"}))
                        if mode == "unload":
                            self.assertEqual(self.downstream[-1], body)
                        self.assertTrue(streams and all(s.closed for s in streams))
                        self.assertTrue(clients and all(c.is_closed for c in clients))
                        self.assertFalse(self.gate.active or self.adapter._background_tasks)
                    finally:
                        release.set()
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                        self.runner._draining = False

    async def test_edit_during_binding_history_metadata_drains_obsolete_acquisition(self):
        directory = self.client.users_info.side_effect
        for phase in ("bind", "history", "metadata"):
            with self.subTest(phase=phase):
                started, closed = asyncio.Event(), asyncio.Event()
                held = [False]
                self.enable_semantic()

                async def block(held=held, started=started, closed=closed):
                    held[0] = True
                    started.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        closed.set()

                async def info(*, user, held=held, phase=phase, block=block):
                    if not held[0] and phase == "metadata" and user == "UBETA":
                        await block()
                    return await directory(user=user)

                async def conversation(*, channel, held=held, phase=phase, block=block):
                    if not held[0] and phase == "bind":
                        await block()
                    return {"ok": True, "channel": {"id": channel, "is_im": False, "is_mpim": False}}

                async def page(held=held, phase=phase, block=block, **kwargs):
                    if not held[0] and phase == "history" and "latest" in kwargs:
                        await block()
                    return {"ok": True, "messages": [{"ts": "100.001", "user": "UHUMAN", "text": "anchor"}]}

                self.client.users_info.side_effect = info
                self.client.conversations_info.side_effect = conversation
                self.client.conversations_replies.side_effect = page
                body = self.message("<@UBETA> OLD_MARKER")
                if phase == "bind":
                    body["event"].pop("channel_type")
                edited = copy.deepcopy(body)
                edited["event"] = {
                    "type": "message",
                    "subtype": "message_changed",
                    "channel": "CDEMO",
                    "team": "TDEMO",
                    "channel_type": "channel",
                    "message": {**body["event"], "text": "<@UBETA> NEW_MARKER", "edited": {"ts": "900.001"}},
                }
                before = len(self.downstream)
                task = asyncio.create_task(self.dispatch(body))
                try:
                    await started.wait()
                    await self.dispatch(edited)
                    await task
                    await self.drain()
                    self.assertTrue(closed.is_set())
                    self.assertEqual(len(self.downstream), before + 1)
                    self.assertIn("NEW_MARKER", json.dumps(self.downstream[-1]))
                    self.assertFalse(self.gate.active or self.adapter._background_tasks)
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    async def test_equal_duplicates_distinct_messages_and_stale_active_revision(self):
        started, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        count = 0

        async def infer(batch):
            nonlocal count
            count += 1
            if count == 1:
                started.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
            return "yes", 1.0

        self.gate.jev.ask.side_effect = infer
        body = self.message("<@UBETA> ORIGINAL_MARKER", edited={"ts": "500.001"})
        task = asyncio.create_task(self.dispatch(body))
        try:
            await started.wait()
            stale = copy.deepcopy(body)
            stale["event"]["edited"] = {"ts": "400.001"}
            await self.assert_suppressed(stale)
            duplicate = copy.deepcopy(body)
            duplicate["event"]["type"] = "app_mention"
            duplicate["event_id"] = "EvDuplicate"
            await self.assert_passed(duplicate)
            await self.assert_passed(self.message("<@UBETA> DISTINCT_MESSAGE"))
            self.assertFalse(cancelled.is_set())
            release.set()
            await task
            await self.drain()
            self.assertEqual(count, 3)
            self.assertEqual(self.model.await_count, 2)
            self.assertFalse(self.gate.active)
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_rapid_edits_invalidate_before_awaiting_old_cleanup(self):
        started, cancelling, release, latest_seen = (asyncio.Event() for _ in range(4))

        async def infer(batch):
            if "OLD_MARKER" in context_view(batch["state"])["CURRENT"]["text"]:
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelling.set()
                    await release.wait()
                    return "yes", 1.0
            return "yes", 1.0

        self.gate.jev.ask.side_effect = infer
        body = self.message("<@UBETA> OLD_MARKER")

        def edit(revision, text):
            result = copy.deepcopy(body)
            result["event"] = {
                "type": "message",
                "subtype": "message_changed",
                "channel": "CDEMO",
                "team": "TDEMO",
                "channel_type": "channel",
                "message": {**body["event"], "text": text, "edited": {"ts": revision}},
            }
            return result

        coordinates = self.gate.coordinates

        def intake(value):
            result = coordinates(value)
            if result is not None and str(result[3]) == "901.001":
                latest_seen.set()
            return result

        old = asyncio.create_task(self.dispatch(body))
        middle = latest = None
        try:
            await started.wait()
            middle = asyncio.create_task(self.dispatch(edit("900.001", "<@UBETA> MIDDLE_MARKER")))
            await cancelling.wait()
            with patch.object(self.gate, "coordinates", side_effect=intake):
                latest = asyncio.create_task(self.dispatch(edit("901.001", "<@UBETA> LATEST_MARKER")))
                await latest_seen.wait()
                release.set()
                await asyncio.gather(old, middle, latest)
            await self.drain()
            self.model.assert_awaited_once()
            self.assertEqual(self.model.await_args.args[0].text, "LATEST_MARKER")
            self.assertFalse(self.gate.active or self.adapter._background_tasks)
        finally:
            release.set()
            tasks = [task for task in (old, middle, latest) if task is not None]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_acquisition_failure_and_caller_cancellation_drain_siblings(self):
        directory = self.client.users_info.side_effect
        for cancel in (False, True):
            started, metadata, finished, metadata_done, release = (asyncio.Event() for _ in range(5))

            async def page(started=started, release=release, finished=finished, **kwargs):
                started.set()
                try:
                    await release.wait()
                    raise OSError("fictional-private")
                finally:
                    finished.set()

            async def info(*, user, metadata=metadata, metadata_done=metadata_done):
                if user != "UBETA":
                    return await directory(user=user)
                metadata.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    metadata_done.set()

            self.client.conversations_replies.side_effect = page
            self.client.users_info.side_effect = info
            body = self.message("<@UBETA> Full message.")
            before = len(self.downstream)
            task = asyncio.create_task(self.dispatch(body))
            try:
                await asyncio.gather(started.wait(), metadata.wait())
                if cancel:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                else:
                    release.set()
                    await task
                await self.drain()
                self.assertTrue(finished.is_set() and metadata_done.is_set())
                self.assertEqual(len(self.downstream), before + int(not cancel))
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_next_failure_never_retried_active_or_fallback(self):
        from slack_bolt.request.async_request import AsyncBoltRequest

        for failure in (False, True):
            self.enable_semantic()
            if failure:
                self.gate.jev.ask.side_effect = RuntimeError("fictional-private")
            native = Mock()
            self.gate.wire(native, self.adapter)
            middleware = native.use.call_args.args[0]
            body = self.message("<@UBETA> Explain this.")
            next_call = AsyncMock(side_effect=RuntimeError("native downstream"))
            request = AsyncBoltRequest(body=json.dumps(body), mode="socket_mode")
            with self.assertRaisesRegex(RuntimeError, "native downstream"):
                await middleware(body, next_call, request)
            next_call.assert_awaited_once()
            self.assertEqual(request.body, body)

    async def test_controlled_conversational_corpus_native_inputs(self):
        """Retained fictional inputs; whole-message expectations replace partial masks.

        These declared decisions exercise transport, not live language accuracy.
        No expectation is derived from production message structure.
        """
        import hashlib
        from dataclasses import replace

        from gateway.platforms.helpers import MessageDeduplicator
        from test_semantic import japanese_improvement_source

        from hermes_slack_agent_router.jev import serialize_request, validate_answers
        from hermes_slack_agent_router.semantic import prepare

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
        cases = (
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
        originals = {row[0]: row for row in cases}
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
        for base in ("main-joint", "M3", "M4", "M5", "M10"):
            _, _, text, history, sequence = next(row for row in cases if row[0] == base)
            cases += ((base + "-alpha", "UALPHA", text, history, sequence),)
        counterparts = {
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
                {"UBETA"},
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
                {"UALPHA"},
            ),
            "C-explicit": ("<@UBETA>、会場図を修正してください。", named_history, {"UBETA"}),
            "C-joint": (
                "<@UALPHA> and <@UBETA> revise the venue diagram together.",
                named_history,
                {"UALPHA", "UBETA"},
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
                {"UALPHA", "UBETA"},
            ),
        }
        recipients = {name: {"UBETA"} for name, *_ in cases}
        for name in (
            "multi-beta",
            "multi-alpha",
            "joint",
            "joint-alpha",
            "main-joint",
            "main-joint-alpha",
            "M3",
            "M3-alpha",
            "M5",
            "M5-alpha",
        ):
            recipients[name] = {"UALPHA", "UBETA"}
        for name in ("specific-not-main", "main-takeover", "M6", "M4", "M4-alpha"):
            recipients[name] = {"UALPHA"}
        # These are continuation expectations, not proven owners or a joint set.
        fallback_cases = {"main-unknown", "main-conflict", "M9", "C-unresolved-beta", "C-unresolved-alpha"}
        for name in ("main-unknown", "main-conflict", "M9"):
            recipients[name] = {"UALPHA", "UBETA"}
        for name in ("M10", "M10-alpha"):
            recipients[name] = set()
        counterpart_names = set()
        for base, (text, history, users) in counterparts.items():
            for suffix, receiver in (("beta", "UBETA"), ("alpha", "UALPHA")):
                name = base + "-" + suffix
                cases += ((name, receiver, text, history, 240),)
                recipients[name] = users
                counterpart_names.add(name)
        normal_sources = {
            "N-" + label: label
            for label, *_ in cases
            if label not in ("full-name", "short-name", "M9") and label not in counterpart_names
        }
        by_label = {row[0]: row for row in cases}
        for label, base in normal_sources.items():
            _, receiver, text, history, sequence = by_label[base]
            cases += ((label, receiver, text, history, sequence),)
            recipients[label] = recipients[base]
            if base in fallback_cases:
                fallback_cases.add(label)
        conversation_specs = (
            (
                "Q-question",
                "UBETA",
                "<@UBETA>, why is the diagram scaled differently?",
                fixed_history,
                {"UBETA"},
            ),
            (
                "Q-explanation",
                "UBETA",
                "<@UBETA>, explain why the diagram uses metres.",
                fixed_history,
                {"UBETA"},
            ),
            ("Q-ack", "UBETA", "<@UBETA>, please acknowledge receipt.", fixed_history, {"UBETA"}),
            (
                "Q-support-beta",
                "UBETA",
                "<@UBETA>, could you explain the scale? The unit conversion is the concern.",
                fixed_history,
                {"UBETA"},
            ),
            (
                "Q-support-alpha",
                "UALPHA",
                "<@UBETA>, could you explain the scale? The unit conversion is the concern.",
                fixed_history,
                {"UBETA"},
            ),
            ("Q-courtesy", "UBETA", "Thanks for the update.", fixed_history, set()),
            ("Q-data", "UBETA", "The diagram is 1:100.", fixed_history, set()),
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
                {"UBETA"},
            ),
            (
                "Q-change-alpha",
                "UALPHA",
                "<@UALPHA>, explain the summary; include its units; <@UBETA>, explain the diagram.",
                fixed_history,
                {"UALPHA", "UBETA"},
            ),
            (
                "Q-change-beta",
                "UBETA",
                "<@UALPHA>, explain the summary; include its units; <@UBETA>, explain the diagram.",
                fixed_history,
                {"UALPHA", "UBETA"},
            ),
            (
                "Q-inseparable",
                "UBETA",
                "<@UBETA> and <@UOUTSIDE>, could you jointly explain this diagram?",
                fixed_history,
                {"UBETA"},
            ),
        )
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
                        generic_text,
                        history,
                        {"UBETA" if order == "AB" else "UALPHA"},
                    )
                )
        topic_history = [
            {"ts": "100.001", "user": "UHUMAN", "text": "<@UBETA>, lead this entire thread."},
            {"ts": "101.001", "user": "UHUMAN", "text": "<@UALPHA>, take over only the diagram task."},
        ]
        for label, current, history, users in (
            (
                "handoff",
                generic_text,
                [
                    {"ts": "100.001", "user": "UHUMAN", "text": appointments[0]},
                    {"ts": "101.001", "user": "UHUMAN", "text": appointments[1]},
                ],
                {"UBETA"},
            ),
            (
                "report",
                generic_text,
                [
                    {"ts": "100.001", "user": "UHUMAN", "text": "<@UBETA>, lead this entire thread."},
                    {"ts": "101.001", "user": "UALPHA", "text": "The summary status is complete."},
                ],
                {"UBETA"},
            ),
            ("task", "Please correct the diagram.", topic_history, {"UALPHA"}),
            ("task-generic", generic_text, topic_history, {"UBETA"}),
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
                {"UALPHA"},
            ),
        ):
            for receiver in ("UBETA", "UALPHA"):
                temporal_specs.append(
                    (
                        "T-" + label + "-" + ("beta" if receiver == "UBETA" else "alpha"),
                        receiver,
                        current,
                        history,
                        users,
                    )
                )
        people_specs = [
            ("P-directory", "UBETA", generic_text, generic_history, {"UBETA"}),
            (
                "P-duplicate-beta",
                "UBETA",
                "Please correct the diagram you prepared.",
                fixed_history,
                {"UBETA"},
            ),
            (
                "P-duplicate-alpha",
                "UALPHA",
                "Please correct the diagram you prepared.",
                fixed_history,
                {"UBETA"},
            ),
            (
                "P-unknown",
                "UBETA",
                generic_text,
                [
                    {"ts": "100.001", "user": "UHUMAN", "text": "<@UBETA>, lead this entire thread."},
                    {"ts": "101.001", "user": "UUNKNOWN", "text": "Some status."},
                ],
                {"UBETA"},
            ),
            (
                "P-outside",
                "UBETA",
                "<@UBETA> and <@UOUTSIDE>, jointly explain the diagram.",
                [
                    {"ts": "100.001", "user": "UHUMAN", "text": "We are discussing a diagram."},
                    {"ts": "101.001", "user": "UOUTSIDE", "text": "I am an external human reviewer."},
                ],
                {"UBETA"},
            ),
        ]
        for label, receiver, text, history, users in [*conversation_specs, *temporal_specs, *people_specs]:
            cases += ((label, receiver, text, history, 260 if label.startswith("Q-") else 280),)
            recipients[label] = users
        captured = {}
        for name, bot, text, history, sequence in cases:
            with self.subTest(case=name):
                expected_pass = bot in recipients[name]
                self.adapter._dedup = MessageDeduplicator()
                self.sequence = sequence
                self.model.reset_mock()
                self.adapter._team_bot_user_ids["TDEMO"] = bot
                self.adapter._bot_user_id = bot
                self.peer._team_bot_user_ids["TDEMO"] = "UALPHA" if bot == "UBETA" else "UBETA"
                self.adapter._team_bot_names.clear()
                self.peer._team_bot_names.clear()
                self.supply_native_names()
                directory = self.client.users_info.side_effect

                async def names(*, user, directory=directory, name=name):
                    value = await directory(user=user)
                    if name in counterpart_names or name == "M9":
                        value["user"]["profile"].update(real_name="柚原こはる", display_name="柚原こはる")
                        value["user"]["real_name"] = "柚原こはる"
                    if name.startswith("P-duplicate"):
                        value["user"]["profile"]["display_name"] = "共通名"
                    if name in {row[0] for row in [*temporal_specs, *people_specs]} and user in {
                        "UHUMAN",
                        "UOUTSIDE",
                        "UUNKNOWN",
                    }:
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
                    return value

                self.client.users_info.side_effect = names
                self.client.conversations_replies.return_value = {"ok": True, "messages": history}
                seen = []

                async def offline(batch, expected_pass=expected_pass, seen=seen):
                    seen.append(batch)
                    return validate_answers(
                        batch, controlled_answers(batch, "yes" if expected_pass else "no")
                    )

                self.gate.jev.ask.side_effect = offline
                body = self.message(text)
                before = len(self.downstream)
                await self.dispatch(body)
                await self.drain()
                self.assertEqual(len(self.downstream), before + int(expected_pass))
                if name == "P-unknown":
                    # The retained foreign metadata input now fails classification,
                    # correctly deferring instead of inventing an unknown identity.
                    self.assertEqual(seen, [])
                else:
                    self.assertEqual(len(seen), 1)
                    self.assertEqual(set(seen[0]["questions"]), {"response"})
                    self.assertEqual(seen[0]["state"]["conversation"]["records"][-1]["text"], text)
                if expected_pass:
                    self.assertEqual(self.downstream[-1], body)
                    self.model.assert_awaited_once()
                    delivered = self.model.await_args.args[0]
                    # Ordinary native mention rendering, not source slicing.
                    expected_text = (
                        self.adapter._apply_bot_mention(text, text, text, False, bot, "100.001", "TDEMO")[0]
                        if f"<@{bot}>" in text
                        else text
                    )
                    expected_text = await self.adapter._humanize_user_mentions(
                        expected_text, chat_id="CDEMO", team_id="TDEMO"
                    )
                    self.assertEqual(delivered.text, expected_text)
                else:
                    self.model.assert_not_awaited()
                captured[name] = {
                    "input": body,
                    "pass": expected_pass,
                    "fallback_unresolved": name in fallback_cases,
                    "request": serialize_request(seen[0]).decode() if seen else None,
                }
        japanese = japanese_improvement_source()
        for name, source, users in (
            ("japanese-improvement", japanese, {"UBIRCH"}),
            (
                "joint-four",
                replace(
                    japanese,
                    text="<@UATLAS> and <@UBIRCH> and <@UCEDAR> and <@UDOGWOOD> jointly review the exhibition system.",
                ),
                {"UATLAS", "UBIRCH", "UCEDAR", "UDOGWOOD"},
            ),
            (
                "joint-two",
                replace(japanese, text="<@UATLAS> and <@UBIRCH> jointly review the exhibition system."),
                {"UATLAS", "UBIRCH"},
            ),
        ):
            for recipient in source.recipients:
                batch = prepare(source, recipient)
                expected_pass = recipient.bot_user in users
                decision = validate_answers(
                    batch, controlled_answers(batch, "yes" if expected_pass else "no")
                )
                self.assertEqual(decision, ("yes" if expected_pass else "no", 1.0))
                self.assertEqual(batch["state"]["conversation"]["records"][-1]["text"], source.text)
                captured[name + ":" + recipient.bot_user] = {
                    "request": serialize_request(batch).decode(),
                    "pass": expected_pass,
                    "text": source.text,
                }
        self.assertEqual(len(captured), 103)
        raw = json.dumps(captured, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        print(
            f"CONTROLLED_CORPUS rows={len(captured)} wire_decision_native_sha256={hashlib.sha256(raw).hexdigest()}"
        )
