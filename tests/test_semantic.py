"""Whole-message context, exact wire fitting and controlled official HTTP protocol."""

import asyncio
import copy
import json
import sys
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from hermes_slack_agent_router.jev import JevClient, JevError, serialize_request
from hermes_slack_agent_router.policy import Recipient, Thread
from hermes_slack_agent_router.semantic import History, Snapshot
from hermes_slack_agent_router.semantic import prepare as prepare_receiver

A = Recipient("TFICTION", "UATLAS", "atlas")
B = Recipient("TFICTION", "UBIRCH", "birch")
KEY = Thread("TFICTION", "CFICTION", "1.0")


def prepare(source, recipient=None):
    return prepare_receiver(source, recipient or source.recipients[0])


def context_view(state):
    records = state["conversation"]["records"]
    return {
        "CURRENT": records[-1],
        "root": next((r for r in records[:-1] if r["role"] == "ROOT_HISTORY"), None),
        "recent": [r for r in records[:-1] if r["role"] != "ROOT_HISTORY"],
        "prior": {f"h{i}": r for i, r in enumerate(records[:-1])},
        "participants": {p["user_id"]: p for p in state["people"]},
        "eligible_recipients": state["native_delivery"]["eligible_user_ids"],
        "chronology": {"ordered_timestamps": [r["timestamp"] for r in records]},
    }


def context_priors(state):
    return context_view(state)["prior"]


def snapshot(text="Atlas, revise the summary; Birch, check the diagram."):
    return Snapshot(
        KEY,
        "3.0",
        "UFABLE",
        text,
        (
            History("1.0", "UATLAS", "Atlas prepared the summary."),
            History("2.0", "UBIRCH", "Birch prepared the diagram."),
        ),
        (A, B),
    )


def japanese_improvement_source():
    return Snapshot(
        KEY,
        "10.0",
        "UFABLE",
        "模型の展示システムが正常に動くようになるまで改善してください。",
        (
            History(
                "1.0",
                "UFABLE",
                "<@UBIRCH>、架空の模型展示会のシステムを担当してください。<@UATLAS>は案内文の編集を担当します。",
            ),
            History(
                "2.0",
                "UBIRCH",
                "展示システムの修正コードを確認しました。取得処理は独立検証済みですが、展示システムの分類段階でエラーが発生しています。修正を続けます。",
            ),
            History("3.0", "UFABLE", "起動し直しました。状態を確認してもらえますか？"),
            History("4.0", "UBIRCH", "作業中です。取得処理は成功しましたが、分類の詳細原因は未確定です。"),
            History("5.0", "UFABLE", "通知しないと反応しない設定ですか？"),
            History(
                "6.0",
                "UBIRCH",
                "通知は必須ではありません。展示システムの判断段階に問題があり、返信前に停止しています。",
            ),
            History("7.0", "UBIRCH", "作業中 — 調査結果を確認しています。"),
            History("8.0", "UBIRCH", "現在の処理は修正済みですが、展示システム全体はまだ動作していません。"),
        ),
        (A, B, Recipient("TFICTION", "UCEDAR", "cedar"), Recipient("TFICTION", "UDOGWOOD", "dogwood")),
    )


def controlled_answers(batch, choice="yes", confidence=1.0):
    assert set(batch["questions"]) == {"response"}
    return {
        "answers": {
            "response": {
                "type": "choice",
                "choice": choice,
                "confidence": confidence,
                "probabilities": {"yes": float(choice == "yes"), "no": float(choice == "no")},
            }
        }
    }


class ContextTests(unittest.TestCase):
    def test_same_whole_context_across_exact_receivers(self):
        source = snapshot()
        first, second = prepare(source, A), prepare(source, B)
        self.assertEqual(first["questions"], second["questions"])
        self.assertEqual(context_view(first["state"]), context_view(second["state"]))
        self.assertEqual(first["state"]["whoami"]["user_id"], A.bot_user)
        self.assertEqual(second["state"]["whoami"]["user_id"], B.bot_user)
        self.assertEqual(
            context_view(first["state"])["chronology"]["ordered_timestamps"], ["1.0", "2.0", "3.0"]
        )

    def test_structured_content_retains_quote_code_and_original_text(self):
        from hermes_slack_agent_router.bridge import message_content

        event = {
            "text": "notification fallback",
            "blocks": [
                {
                    "type": "rich_text",
                    "elements": [
                        {
                            "type": "rich_text_section",
                            "elements": [
                                {"type": "text", "text": "Explain 🦊; why?"},
                                {"type": "text", "text": "inert command", "style": {"code": True}},
                            ],
                        },
                        {"type": "rich_text_quote", "elements": [{"type": "text", "text": "quoted command"}]},
                        {
                            "type": "rich_text_preformatted",
                            "elements": [{"type": "text", "text": "code command"}],
                        },
                    ],
                }
            ],
        }
        original = copy.deepcopy(event)
        text, blocks = message_content(event)
        source = replace(snapshot(text), blocks=blocks)
        record = prepare(source)["state"]["conversation"]["records"][-1]
        self.assertEqual(record["text"], original["text"])
        self.assertEqual(list(record["blocks"]), original["blocks"])
        self.assertEqual(event, original)
        for block in (
            {"type": "image"},
            {"type": "section", "accessory": {}},
            {"type": "rich_text", "elements": [{"type": "unsupported"}]},
        ):
            with self.assertRaises(ValueError):
                message_content({"text": "must not classify only this", "blocks": [block]})

    def test_fitting_exact_utf8_limit_and_oldest_whole_removal(self):
        from hermes_slack_agent_router.plugin import Gate

        root, seed = History("1.0", "UROOT", "protected root"), History("2.0", "UDROP", '界"\\\t')
        source = replace(snapshot("Birch, continue."), history=(root, seed))
        padding = JevClient.request_limit - len(serialize_request(prepare(source, B)))
        equal = replace(source, history=(root, replace(seed, text=seed.text + "x" * padding)))
        self.assertEqual(len(serialize_request(prepare(equal, B))), 524288)
        self.assertEqual(Gate.fit(equal, B)[0], equal)
        above = replace(equal, history=(root, replace(equal.history[1], text=equal.history[1].text + "x")))
        fitted, batch = Gate.fit(above, B)
        self.assertEqual(fitted.history, (root,))
        self.assertEqual(fitted.text, source.text)
        self.assertEqual([r["order"] for r in batch["state"]["conversation"]["records"]], [0, 1])
        huge = replace(
            source,
            identity="5.0",
            history=(
                replace(root, text="r" * 300000),
                History("2.0", "UDROP", "a" * 300000),
                History("3.0", "UDROPTWO", "b" * 300000),
                History("4.0", "UKEEP", "keep"),
            ),
        )
        huge = replace(
            huge,
            context_people=tuple(
                (
                    u,
                    {
                        "user_id": u,
                        "username": u,
                        "display_name": None,
                        "real_name": None,
                    },
                )
                for u in ("UROOT", "UDROP", "UDROPTWO", "UKEEP", huge.sender)
            ),
        )
        fitted, batch = Gate.fit(huge, B)
        self.assertEqual(fitted.history, (huge.history[0], huge.history[3]))
        self.assertEqual({u for u, _ in fitted.context_people}, {"UROOT", "UKEEP", huge.sender})

    def test_protected_size_and_invalid_encoding_fail_locally(self):
        from hermes_slack_agent_router.plugin import Gate

        for source in (
            snapshot("x" * 600000),
            replace(snapshot(), history=(History("1.0", "UROOT", "r" * 600000),)),
        ):
            with self.assertRaises(JevError) as caught:
                Gate.fit(source, B)
            self.assertEqual(caught.exception.diagnostic, ("unsupported-request-size", 0))
        with self.assertRaises(JevError) as caught:
            Gate.fit(snapshot("bad surrogate \ud800"), B)
        self.assertEqual(caught.exception.diagnostic, ("request-invalid", 0))


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import httpx

        self.requests, self.clients = [], []
        native = httpx.AsyncClient
        self.secret = Mock(return_value="synthetic-key")

        async def respond(request):
            self.requests.append(request)
            if isinstance(self.response, Exception):
                raise self.response
            return self.response

        def factory(**kwargs):
            self.assertIsNone(kwargs["timeout"])
            self.assertFalse(kwargs["follow_redirects"] or kwargs["trust_env"])
            client = native(transport=httpx.MockTransport(respond), **kwargs)
            self.clients.append(client)
            return client

        for patcher in (
            patch.dict(sys.modules, {"agent.secret_scope": SimpleNamespace(get_secret=self.secret)}),
            patch("httpx.AsyncClient", side_effect=factory),
            patch("asyncio.create_subprocess_exec", side_effect=AssertionError("CLI forbidden")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def stream(self, chunks=(), *, release=None):
        import httpx

        class Stream(httpx.AsyncByteStream):
            def __init__(self):
                self.started, self.closed, self.reads, self.cancelled = asyncio.Event(), False, 0, False

            async def __aiter__(self):
                self.started.set()
                if release is not None:
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        self.cancelled = True
                        raise
                for chunk in chunks:
                    self.reads += 1
                    yield chunk

            async def aclose(self):
                self.closed = True

        return Stream()

    async def test_actual_http_single_question_and_request_owned_secret(self):
        import httpx

        batch = prepare(snapshot())
        self.secret.side_effect = ["synthetic-atlas", "synthetic-birch"]
        self.response = httpx.Response(200, json=controlled_answers(batch, "yes", 0.1))
        for _ in range(2):
            self.assertEqual(await JevClient().ask(batch), ("yes", 0.1))
        self.assertEqual(self.secret.call_args_list, [call("TYPESAFE_API_KEY")] * 2)
        self.assertEqual(
            [r.headers["Authorization"] for r in self.requests],
            ["Bearer synthetic-atlas", "Bearer synthetic-birch"],
        )
        for request in self.requests:
            self.assertEqual(str(request.url), "https://api.typesafe.ai/v1/systemone")
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.headers["Accept-Encoding"], "identity")
            self.assertEqual(request.content, serialize_request(batch))
            self.assertEqual(set(json.loads(request.content)["questions"]), {"response"})
        self.assertTrue(all(c.is_closed for c in self.clients))

    async def test_missing_scope_key_and_invalid_request_never_connect(self):
        for value in (None, "", RuntimeError("synthetic-private")):
            self.secret.side_effect = value if isinstance(value, Exception) else None
            self.secret.return_value = value
            with self.assertRaises(JevError):
                await JevClient().ask(prepare(snapshot()))
        for batch in ({"state": "x" * 524289, "questions": {}}, {"state": float("nan")}):
            with self.assertRaises(JevError):
                await JevClient().ask(batch)
        self.assertEqual(self.clients, [])

    async def test_status_redirect_errors_never_retry_or_read_body(self):
        import httpx

        for status in (301, 302, 307, 308, 400, 401, 413, 422, 429, 500, 503, 529):
            with self.subTest(status=status):
                stream = self.stream((b"synthetic-private-error-body",))
                self.response = httpx.Response(
                    status, headers={"Location": "https://other.invalid/steal"}, stream=stream
                )
                before = len(self.requests)
                with self.assertRaises(JevError) as caught:
                    await JevClient().ask(prepare(snapshot()))
                self.assertEqual(caught.exception.diagnostic, ("http-rejected", status))
                self.assertEqual(len(self.requests), before + 1)
                self.assertEqual(stream.reads, 0)
                self.assertTrue(stream.closed and self.clients[-1].is_closed)

    async def test_malformed_oversized_compressed_answers_and_transport_close(self):
        import httpx

        for headers, chunks in (
            ({}, (b"not JSON synthetic-private",)),
            ({}, (b"\xff",)),
            ({}, (b"{}",)),
            ({}, (b"[",)),
            ({}, (b"x" * 131073, b"x" * 131073)),
            ({"Content-Length": "262145"}, (b"never read",)),
            ({"Content-Length": "garbage"}, (b"never read",)),
            ({"Content-Encoding": "gzip"}, (b"never decompress",)),
        ):
            stream = self.stream(chunks)
            self.response = httpx.Response(200, headers=headers, stream=stream)
            with self.assertRaises(JevError) as caught:
                await JevClient().ask(prepare(snapshot()))
            self.assertNotIn("synthetic-private", str(caught.exception))
            self.assertTrue(stream.closed and self.clients[-1].is_closed)
            if headers:
                self.assertEqual(stream.reads, 0)
        for error, diagnostic in (
            (httpx.ReadTimeout("private"), "transport-timeout"),
            (httpx.ConnectError("private"), "transport-failed"),
        ):
            self.response = error
            with self.assertRaises(JevError) as caught:
                await JevClient().ask(prepare(snapshot()))
            self.assertEqual(caught.exception.diagnostic, (diagnostic, 0))
            self.assertIsNone(caught.exception.__cause__)
            self.assertTrue(self.clients[-1].is_closed)

    async def test_caller_cancellation_and_delayed_answer_resource_cleanup(self):
        import httpx

        batch = prepare(snapshot())
        for cancel in (True, False):
            release = asyncio.Event()
            stream = self.stream((json.dumps(controlled_answers(batch)).encode(),), release=release)
            self.response = httpx.Response(200, stream=stream)
            task = asyncio.create_task(JevClient().ask(batch))
            try:
                await stream.started.wait()
                if cancel:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                else:
                    release.set()
                    self.assertEqual(await task, ("yes", 1.0))
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self.assertEqual(stream.cancelled, cancel)
            self.assertTrue(stream.closed and self.clients[-1].is_closed)
            self.assertEqual(
                self.requests[-1].extensions["timeout"],
                {"connect": None, "read": None, "write": None, "pool": None},
            )
