"""Source binding, wire bounds and official transport controls; fictional opt-in only."""

import asyncio
import json
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from hermes_slack_agent_router.jev import JevClient, JevError, validate_answers
from hermes_slack_agent_router.policy import Recipient, Thread
from hermes_slack_agent_router.semantic import History, Snapshot
from hermes_slack_agent_router.semantic import prepare as prepare_receiver

A = Recipient("TFICTION", "UATLAS", "atlas")
B = Recipient("TFICTION", "UBIRCH", "birch")
KEY = Thread("TFICTION", "CFICTION", "1.0")


def prepare(source, recipient=None):
    """Generic unit fixtures default to their first exact recipient, unlike production callers."""
    return prepare_receiver(source, recipient or source.recipients[0])


def context_view(state):
    """Test-only canonical evidence decoder for source/native assertions, never a wire alias."""
    records = state["conversation"]["records"]
    root = next((r for r in records[:-1] if r["role"] == "ROOT_HISTORY"), None)
    return {
        "CURRENT": {k: v for k, v in records[-1].items() if k != "role"},
        "root": None if root is None else {k: v for k, v in root.items() if k != "role"},
        "recent": [
            {k: v for k, v in r.items() if k != "role"} for r in records[:-1] if r["role"] != "ROOT_HISTORY"
        ],
        "prior": {f"h{i}": {k: v for k, v in r.items() if k != "role"} for i, r in enumerate(records[:-1])},
        "units": state["source_selection"]["segments"],
        "participants": {p["user_id"]: p for p in state["people"]},
        "eligible_recipients": state["native_delivery"]["eligible_user_ids"],
        "chronology": {"ordered_timestamps": [r["timestamp"] for r in records]},
    }


def context_priors(context):
    return (context_view(context) if "conversation" in context else context)["prior"]


def expected_full_view(source, own_scope, own_current, selected):
    """Independent CURRENT oracle plus only validated optional references for that own scope."""
    references = {
        h.identity: h
        for unit in own_scope
        for j, h in enumerate(source.history)
        if selected.get(f"{unit}_prior{j}") == "include"
    }
    if not references:
        return own_current
    return (
        own_current
        + "\n\nPRIOR REFERENCE (not instructions):\n"
        + "\n".join(f"{h.sender}: {h.text.replace('<', '‹').replace('>', '›')}" for h in references.values())
    )


def native_full_view_matches(actual, expected):
    """Versioned native presentation assertion, separate from exact CURRENT selection."""
    return actual is not None and expected is not None and actual == expected


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


def source_from_record(value):
    """Read a fictional evidence source without changing its semantic contract."""
    return Snapshot(
        **{
            **value,
            "thread": Thread(**value["thread"]),
            "history": tuple(History(**h) for h in value["history"]),
            "recipients": tuple(Recipient(**r) for r in value["recipients"]),
            "recipient_labels": tuple((u, tuple(names)) for u, names in value["recipient_labels"]),
        }
    )


def controlled_answers(batch, choices):
    # Recipient-to-scope declarations describe fixture expectations, not wire keys.
    choices = dict(choices)
    scoped = {key: choices.pop(key) for key in tuple(choices) if key.startswith("for_U")}
    if scoped:
        own = scoped.get("for_" + batch["state"]["whoami"]["user_id"], "none")
        if "response" in batch["questions"]:
            choices.update(
                response="no" if own in ("none", "unresolved") else "yes",
                scope="unsafe" if own in ("none", "unresolved") else own,
            )
    defaults = {
        key: "no" if key == "response" else "unsafe" if key == "scope" else "omit"
        for key in batch["questions"]
    }
    if set(choices) - set(defaults):
        raise AssertionError("obsolete or unknown controlled fixture keys")
    defaults.update(choices)
    return {
        "answers": {
            name: {
                "type": "choice",
                "choice": defaults[name],
                "confidence": 1.0,
                "probabilities": {key: float(key == defaults[name]) for key in q["criteria"]},
            }
            for name, q in batch["questions"].items()
        }
    }


def two_topic_answers(batch):
    return controlled_answers(
        batch,
        {
            "for_UATLAS": "u0",
            "for_UBIRCH": "u1",
            "u0_prior0": "include",
            "u1_prior1": "include",
        },
    )


class RecordingJev(JevClient):
    """Test-only raw evidence; production client never persists routing content."""

    def __init__(self, directory):
        super().__init__()
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    async def _exchange(self, raw, key):
        (self.directory / "jev-request.json").write_bytes(raw)
        started = time.monotonic()
        outcome = "failed"
        try:
            stdout = await super()._exchange(raw, key)
            (self.directory / "jev-result.json").write_bytes(stdout)
            outcome = "HTTP-200"
            return stdout
        finally:
            (self.directory / "jev-receipt.json").write_text(
                json.dumps(
                    {
                        "protocol": "official HTTPS System One Choice",
                        "outcome": outcome,
                        "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                    },
                    indent=2,
                )
            )


class WireNormalization(unittest.TestCase):
    def test_native_wire_maxima_and_response_distributions(self):
        from hermes_slack_agent_router.bridge import canonical_text
        from hermes_slack_agent_router.jev import serialize_request

        recipients = (A, B, Recipient("TFICTION", "UCEDAR", "cedar"), Recipient("TFICTION", "UDUNE", "dune"))
        for character in ("🦊", "\x00", '"', "\\"):

            def record(text, fragmented=False):
                event = {"text": text}
                if fragmented:
                    event["blocks"] = [
                        {
                            "type": "rich_text",
                            "elements": [
                                {
                                    "type": "rich_text_section",
                                    "elements": [{"type": "text", "text": c} for c in text],
                                }
                            ],
                        }
                    ]
                canonical, provenance = canonical_text(event)
                self.assertEqual(canonical, text)
                return canonical, event, provenance

            current, original, provenance = record((character * 999 + ";") * 6, True)
            history = []
            for i in range(8):
                text, event, ranges = record(character * 6000, i % 2 == 0)
                history.append(History(f"{i + 1}.0", f"UAUTHOR{i}", text, event, ranges))
            source = Snapshot(
                KEY,
                "9.0",
                "UCURRENT",
                current,
                tuple(history),
                recipients,
                original,
                provenance,
                recipient_labels=tuple(
                    (r.bot_user, tuple(str(i) + "界" * 127 for i in range(3))) for r in recipients
                ),
                recipient_whoami=tuple(
                    (
                        r.bot_user,
                        {
                            "user_id": r.bot_user,
                            "username": "🦊" * 128,
                            "display_name": "🦊" * 128,
                            "real_name": "🦊" * 128,
                        },
                    )
                    for r in recipients
                ),
                context_people=tuple(
                    (
                        user,
                        {
                            "user_id": user,
                            "username": "🦊" * 128,
                            "display_name": "🦊" * 128,
                            "real_name": "🦊" * 128,
                            "kind": "bot" if user in {r.bot_user for r in recipients} else "human",
                        },
                    )
                    for user in [
                        "UCURRENT",
                        *[f"UAUTHOR{i}" for i in range(8)],
                        *[r.bot_user for r in recipients],
                    ]
                ),
            )
            batch = prepare(source)
            self.assertEqual(len(batch["state"]["people"]), 13)
            raw = serialize_request(batch)
            response = json.dumps(controlled_answers(batch, {}), ensure_ascii=False, allow_nan=False).encode()
            self.assertLessEqual(len(raw), JevClient.request_limit)
            self.assertLessEqual(len(response), JevClient.limit)
            self.assertTrue(all(len(q["criteria"]) <= 255 for q in batch["questions"].values()))
            self.assertEqual(
                "".join(
                    current[u["start"] : u["end"]]
                    for u in batch["state"]["source_selection"]["segments"].values()
                ),
                current,
            )
            print(
                f"SIMPLE_MAX codepoint={ord(character)} request={len(raw)} response={len(response)} questions={len(batch['questions'])}"
            )


class APITransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_coherent_response_actual_http(self):
        import sys
        from types import SimpleNamespace

        import httpx

        source = snapshot("No, that proposal is unacceptable; explain the effect.")
        captured = []
        factory = httpx.AsyncClient

        async def respond(request):
            batch = json.loads(request.content)
            captured.append(batch)
            self.assertEqual({k for k in batch["questions"] if "_prior" not in k}, {"response", "scope"})
            self.assertEqual(set(batch["questions"]["scope"]["criteria"]), {"u0", "u1", "u0+u1", "unsafe"})
            raw = controlled_answers(batch, {"response": "yes", "scope": "u0+u1"})
            raw["answers"]["response"]["confidence"] = 0.701
            raw["answers"]["scope"]["confidence"] = 0.01
            return httpx.Response(200, json=raw)

        with (
            patch.dict(
                sys.modules, {"agent.secret_scope": SimpleNamespace(get_secret=lambda name: "fictional")}
            ),
            patch(
                "httpx.AsyncClient",
                side_effect=lambda **kw: factory(transport=httpx.MockTransport(respond), **kw),
            ),
        ):
            answer = await JevClient().ask(prepare(source, A))
        from hermes_slack_agent_router.semantic import assemble

        self.assertEqual(assemble(source, A, answer).view(A), source.text)
        self.assertEqual(len(captured), 1)

    async def test_chronology_people_actual_http(self):
        import sys
        from dataclasses import replace
        from types import SimpleNamespace

        import httpx

        source = replace(
            snapshot("Could you explain this? The units matter."),
            sender="UHUMAN",
            context_people=(
                (
                    "UHUMAN",
                    {
                        "user_id": "UHUMAN",
                        "username": "fiction.human",
                        "display_name": "",
                        "real_name": "共通名",
                        "kind": "human",
                    },
                ),
            ),
        )
        captured = []
        factory = httpx.AsyncClient

        async def respond(request):
            batch = json.loads(request.content)
            context = context_view(batch["state"])
            captured.append(batch)
            self.assertEqual(context["CURRENT"]["sender"], context["participants"]["UHUMAN"])
            self.assertEqual(context["CURRENT"]["sender"]["display_name"], "")
            self.assertEqual(context["chronology"]["ordered_timestamps"], ["1.0", "2.0", "3.0"])
            self.assertEqual(context["CURRENT"]["order"], 2)
            self.assertEqual(context["root"]["order"], 0)
            self.assertEqual(set(batch["questions"]["response"]["criteria"]), {"yes", "no"})
            return httpx.Response(200, json=controlled_answers(batch, {"response": "yes", "scope": "u0+u1"}))

        with (
            patch.dict(
                sys.modules, {"agent.secret_scope": SimpleNamespace(get_secret=lambda name: "fictional")}
            ),
            patch(
                "httpx.AsyncClient",
                side_effect=lambda **kw: factory(transport=httpx.MockTransport(respond), **kw),
            ),
        ):
            for recipient in (A, B):
                await JevClient().ask(prepare(source, recipient))
        self.assertEqual(context_view(captured[0]["state"]), context_view(captured[1]["state"]))
        for history in (
            (History("3.0", "UHUMAN", "current collision"),),
            (History("4.0", "UHUMAN", "future"),),
        ):
            with self.assertRaises(ValueError):
                prepare(replace(source, history=history))

    async def test_response_unit_actual_http_single_judgment(self):
        import sys
        from types import SimpleNamespace

        import httpx

        from hermes_slack_agent_router.semantic import assemble

        factory = httpx.AsyncClient
        confidence = 0.499
        source = snapshot("Atlas, why is the scale different? The units matter.")

        async def respond(request):
            batch = json.loads(request.content)
            self.assertEqual({k for k in batch["questions"] if "_prior" not in k}, {"response", "scope"})
            self.assertNotIn("self_recipient", batch["questions"])
            self.assertNotIn("projection", batch["questions"])
            raw = {"answers": {}}
            for name, question in batch["questions"].items():
                choice = "yes" if name == "response" else "u0+u1" if name == "scope" else "omit"
                raw["answers"][name] = {
                    "type": "choice",
                    "choice": choice,
                    "confidence": confidence if name == "response" else 0.1,
                    "probabilities": {k: float(k == choice) for k in question["criteria"]},
                }
            return httpx.Response(200, json=raw)

        with (
            patch.dict(
                sys.modules, {"agent.secret_scope": SimpleNamespace(get_secret=lambda name: "fictional")}
            ),
            patch(
                "httpx.AsyncClient",
                side_effect=lambda **kw: factory(transport=httpx.MockTransport(respond), **kw),
            ),
        ):
            for confidence in (0.499, 0.500, 0.501):
                answers = await JevClient().ask(prepare(source, A))
                self.assertEqual(
                    assemble(source, A, answers).view(A), source.text if confidence > 0.5 else ""
                )

    async def test_readable_canonical_utterances_actual_wire(self):
        import sys
        from dataclasses import replace
        from types import SimpleNamespace

        import httpx

        from hermes_slack_agent_router.bridge import canonical_text

        event = {
            "text": "NOTIFICATION_FALLBACK",
            "blocks": [
                {
                    "type": "rich_text",
                    "elements": [
                        {
                            "type": "rich_text_section",
                            "elements": [{"type": "text", "text": "🦊 図を修正。"}],
                        },
                        {"type": "rich_text_quote", "elements": [{"type": "text", "text": "引用 🧪"}]},
                    ],
                }
            ],
        }
        text, provenance = canonical_text(event)
        identities = {
            A.bot_user: {
                "user_id": A.bot_user,
                "username": "exact.atlas",
                "display_name": "共通名",
                "real_name": None,
            },
            B.bot_user: {"user_id": B.bot_user, "username": None, "display_name": "", "real_name": "共通名"},
        }
        source = replace(
            snapshot(text),
            identity="10.0",
            sender=A.bot_user,
            original=event,
            provenance=provenance,
            history=(
                History("1.0", B.bot_user, "正準 root 🦊", {"text": "HIDDEN_ROOT_FALLBACK"}),
                *tuple(
                    History(f"{i}.0", "UFABLE" if i % 2 else B.bot_user, f"正準 prior {i}")
                    for i in range(2, 9)
                ),
            ),
            recipient_whoami=tuple(identities.items()),
        )
        binding = source.binding
        sent = []
        factory = httpx.AsyncClient

        async def respond(request):
            batch = json.loads(request.content)
            sent.append(batch)
            context = context_view(batch["state"])
            self.assertEqual(
                context["CURRENT"],
                {
                    "timestamp": source.identity,
                    "source_event_identity": source.identity,
                    "sender": {**identities[source.sender], "kind": "unknown"},
                    "order": 8,
                    "text": source.text,
                    "provenance": context["CURRENT"]["provenance"],
                },
            )
            self.assertEqual(context["root"]["timestamp"], "1.0")
            self.assertEqual(context["root"]["text"], "正準 root 🦊")
            self.assertEqual(context["root"]["sender"], {**identities[B.bot_user], "kind": "unknown"})
            self.assertEqual([r["timestamp"] for r in context["recent"]], [f"{i}.0" for i in range(2, 9)])
            self.assertEqual(context["recent"][1]["sender"], context["participants"]["UFABLE"])
            self.assertEqual(context["recent"][0]["sender"]["display_name"], "")
            self.assertEqual(
                [r["timestamp"] for r in context["prior"].values()], [f"{i}.0" for i in range(1, 9)]
            )
            self.assertIn("conversation.records[0]", batch["questions"]["u0_prior0"]["instructions"])
            self.assertIn("conversation.records[7]", batch["questions"]["u0_prior7"]["instructions"])
            self.assertEqual(set(context["participants"]), {*identities, "UFABLE"})
            self.assertEqual(context["CURRENT"]["text"], text)
            self.assertTrue(context["units"]["u1"]["quoted"])
            self.assertNotIn("FALLBACK", request.content.decode())
            self.assertIn("complete CURRENT", batch["questions"]["response"]["instructions"]["question"])
            self.assertEqual(set(batch["questions"]["response"]["criteria"]), {"yes", "no"})
            self.assertNotIn("u1_response", batch["questions"])  # quoted source is inert
            return httpx.Response(200, json=controlled_answers(batch, {"response": "yes", "scope": "u0"}))

        with (
            patch.dict(
                sys.modules, {"agent.secret_scope": SimpleNamespace(get_secret=lambda name: "fictional")}
            ),
            patch(
                "httpx.AsyncClient",
                side_effect=lambda **kw: factory(transport=httpx.MockTransport(respond), **kw),
            ),
        ):
            for receiver in (A, B):
                await JevClient().ask(prepare(source, receiver))
        self.assertEqual(context_view(sent[0]["state"]), context_view(sent[1]["state"]))
        self.assertEqual(source.binding, binding)
        unknown = replace(source, sender="UHUMAN")
        self.assertEqual(
            prepare(unknown)["state"]["conversation"]["records"][-1]["sender"],
            {
                "user_id": "UHUMAN",
                "username": None,
                "display_name": None,
                "real_name": None,
                "kind": "unknown",
            },
        )
        overlap = context_view(prepare(snapshot())["state"])
        self.assertNotIn(overlap["root"]["timestamp"], [r["timestamp"] for r in overlap["recent"]])

    def test_unit_question_is_response_membership_not_executable_work(self):
        batch = prepare(snapshot())
        question = batch["questions"]["response"]
        self.assertIn("necessary declarative rejection", json.dumps(question["instructions"]))
        self.assertIn("same-task", json.dumps(question["instructions"]))
        self.assertIn("independent own response", json.dumps(question["instructions"]))
        self.assertIn("foreign, unresolved", question["criteria"]["no"]["meaning"])
        self.assertNotIn("projection", batch["questions"])

    async def test_explicit_whoami_self_scope_actual_wire(self):
        import sys
        from types import SimpleNamespace

        import httpx

        native = httpx.AsyncClient
        captured = []
        expected_whoami = {
            user: {"user_id": user, "username": None, "display_name": None, "real_name": None}
            for user in ("UATLAS", "UBIRCH")
        }

        async def respond(request):
            batch = json.loads(request.content)
            captured.append(batch)
            user = batch["state"]["whoami"]["user_id"]
            self.assertEqual(batch["state"]["whoami"], expected_whoami[user])
            question = batch["questions"]["response"]
            self.assertIn("whoami", json.dumps(question["instructions"]))
            self.assertEqual(set(question["criteria"]), {"yes", "no"})
            self.assertIn("scope", batch["questions"])
            self.assertNotIn("self_recipient", batch["questions"])
            self.assertNotIn("projection", batch["questions"])
            self.assertIn("conversation", batch["state"])
            self.assertFalse(any(k.startswith("self_U") for k in batch["questions"]))
            return httpx.Response(200, json=two_topic_answers(batch))

        with (
            patch.dict(
                sys.modules, {"agent.secret_scope": SimpleNamespace(get_secret=lambda name: "fictional")}
            ),
            patch(
                "httpx.AsyncClient",
                side_effect=lambda **kw: native(transport=httpx.MockTransport(respond), **kw),
            ),
        ):
            for receiver in (A, B):
                await JevClient().ask(prepare(snapshot(), receiver))
            from dataclasses import replace

            expected_whoami = {
                "UATLAS": {
                    "user_id": "UATLAS",
                    "username": "exact.handle",
                    "display_name": "",
                    "real_name": "別の実名",
                },
                "UBIRCH": {
                    "user_id": "UBIRCH",
                    "username": "other.handle",
                    "display_name": "こはる",
                    "real_name": None,
                },
            }
            for receiver in (A, B):
                await JevClient().ask(
                    prepare(replace(snapshot(), recipient_whoami=tuple(expected_whoami.items())), receiver)
                )
        self.assertEqual(len(captured), 4)
        self.assertEqual(context_view(captured[0]["state"]), context_view(captured[1]["state"]))

    async def test_exact_literal_unit_bodies_and_actual_paths_reach_http(self):
        import sys
        from dataclasses import replace
        from types import SimpleNamespace

        import httpx

        from hermes_slack_agent_router.bridge import canonical_text
        from hermes_slack_agent_router.semantic import assemble

        authored = '🦊 図を直して；要約 "A\\B" を直して。'
        events = (
            (
                {"text": authored + "\n> 引用 🧪\nThanks."},
                ["🦊 図を直して；", '要約 "A\\B" を直して。\n', "> 引用 🧪\n", "Thanks."],
            ),
            (
                {
                    "blocks": [
                        {
                            "type": "rich_text",
                            "elements": [
                                {
                                    "type": "rich_text_section",
                                    "elements": [{"type": "text", "text": authored}],
                                },
                                {
                                    "type": "rich_text_quote",
                                    "elements": [{"type": "text", "text": "引用 🧪"}],
                                },
                                {
                                    "type": "rich_text_section",
                                    "elements": [{"type": "text", "text": "Thanks."}],
                                },
                            ],
                        }
                    ]
                },
                ["🦊 図を直して；", '要約 "A\\B" を直して。\n', "引用 🧪\n", "Thanks."],
            ),
        )
        native = httpx.AsyncClient
        sent = []
        for event, expected in events:
            text, provenance = canonical_text(event)
            source = replace(snapshot(text), original=event, provenance=provenance)
            binding = source.binding
            original = json.loads(json.dumps(event))

            async def respond(request, expected=expected):
                batch = json.loads(request.content)
                sent.append(batch)
                units = batch["state"]["source_selection"]["segments"]
                self.assertEqual([u["text"] for u in units.values()], expected)
                self.assertEqual([u["quoted"] for u in units.values()], [False, False, True, False])
                self.assertIn(batch["state"]["whoami"]["user_id"], ("UATLAS", "UBIRCH"))
                self.assertIn("whoami", json.dumps(batch["questions"]["response"]["instructions"]))
                self.assertNotIn("state.current[start:end]", request.content.decode())
                return httpx.Response(200, json=two_topic_answers(batch))

            with (
                patch.dict(
                    sys.modules, {"agent.secret_scope": SimpleNamespace(get_secret=lambda name: "fictional")}
                ),
                patch(
                    "httpx.AsyncClient",
                    side_effect=lambda **kw: native(transport=httpx.MockTransport(respond), **kw),
                ),
            ):
                for receiver, own in ((A, expected[0]), (B, expected[1])):
                    selected = await JevClient().ask(prepare(source, receiver))
                    plan = assemble(source, receiver, selected)
                    self.assertEqual(plan.status, "ready", plan.reason)
                    self.assertEqual(plan.view(receiver).split("\n\nPRIOR REFERENCE", 1)[0], own)
                    self.assertTrue(
                        all(not plan.view(peer) for peer in source.recipients if peer != receiver)
                    )
            self.assertEqual(source.binding, binding)
            self.assertEqual(event, original)
        self.assertEqual(len(sent), 4)

    def test_fixed_failure_diagnostics_do_not_echo_messages(self):
        self.assertEqual(JevError("malformed native Jev answer").diagnostic, ("answer-malformed", 0))
        self.assertEqual(
            JevError("uncertain relevant answer: synthetic-private-content").diagnostic,
            ("answer-confidence", 0),
        )
        self.assertEqual(JevError("synthetic-private-body-key").diagnostic, ("unclassified", 0))

    async def test_transport_status_and_deadline_have_distinct_safe_diagnostics(self):
        import sys
        from types import SimpleNamespace

        import httpx

        factory = httpx.AsyncClient
        response = httpx.Response(401, content=b"synthetic-private-body-key")

        async def respond(request):
            if isinstance(response, Exception):
                raise response
            return response

        def client(**kwargs):
            return factory(transport=httpx.MockTransport(respond), **kwargs)

        with (
            patch.dict(
                sys.modules, {"agent.secret_scope": SimpleNamespace(get_secret=lambda name: "fictional")}
            ),
            patch("httpx.AsyncClient", side_effect=client),
        ):
            for outcome, expected in (
                (response, ("http-rejected", 401)),
                (httpx.ReadTimeout("synthetic-private-key"), ("transport-deadline", 0)),
                (httpx.ConnectError("synthetic-private-key"), ("transport-failed", 0)),
            ):
                response = outcome
                with self.assertRaises(JevError) as caught:
                    await JevClient().ask(prepare(snapshot()))
                self.assertEqual(caught.exception.diagnostic, expected)
                self.assertNotIn("synthetic-private", str(caught.exception))

    async def test_official_http_contract_without_cli_and_request_local_key(self):
        import sys
        from types import SimpleNamespace

        import httpx

        batch = prepare(snapshot())
        sent = []

        async def respond(request):
            sent.append(request)
            return httpx.Response(200, json=two_topic_answers(batch))

        native = httpx.AsyncClient
        secret = Mock(side_effect=["synthetic-atlas", "synthetic-birch"])
        clients = []

        def factory(**kwargs):
            self.assertFalse(kwargs["follow_redirects"])
            self.assertFalse(kwargs["trust_env"])
            client = native(transport=httpx.MockTransport(respond), **kwargs)
            clients.append(client)
            return client

        with (
            patch.dict(sys.modules, {"agent.secret_scope": SimpleNamespace(get_secret=secret)}),
            patch("httpx.AsyncClient", side_effect=factory),
            patch("asyncio.create_subprocess_exec", side_effect=AssertionError("local CLI forbidden")),
        ):
            client = JevClient()
            for _ in range(2):
                self.assertEqual(await client.ask(batch), validate_answers(batch, two_topic_answers(batch)))
        self.assertEqual(secret.call_args_list, [call("TYPESAFE_API_KEY")] * 2)
        self.assertEqual(
            [r.headers["Authorization"] for r in sent], ["Bearer synthetic-atlas", "Bearer synthetic-birch"]
        )
        for request in sent:
            self.assertEqual(str(request.url), "https://api.typesafe.ai/v1/systemone")
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.headers["Content-Type"], "application/json")
            self.assertEqual(json.loads(request.content), {"model": "jev-latest", **batch})
        self.assertTrue(all(client.is_closed for client in clients))

    async def test_missing_or_inaccessible_scope_never_creates_transport(self):
        import sys
        from types import SimpleNamespace

        for outcome in (None, "", RuntimeError("synthetic-private-scope-detail")):
            resolver = (
                Mock(side_effect=outcome) if isinstance(outcome, Exception) else Mock(return_value=outcome)
            )
            with (
                self.subTest(outcome=type(outcome).__name__),
                patch.dict(sys.modules, {"agent.secret_scope": SimpleNamespace(get_secret=resolver)}),
                patch("httpx.AsyncClient") as transport,
                patch("asyncio.create_subprocess_exec", side_effect=AssertionError("local CLI forbidden")),
                self.assertRaises(JevError) as caught,
            ):
                await JevClient().ask(prepare(snapshot()))
            transport.assert_not_called()
            self.assertNotIn("synthetic-private", str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import sys
        from types import SimpleNamespace

        import httpx

        self.requests, self.clients = [], []
        native = httpx.AsyncClient

        async def respond(request):
            self.requests.append(request)
            if isinstance(self.response, Exception):
                raise self.response
            return self.response

        def factory(**kwargs):
            client = native(transport=httpx.MockTransport(respond), **kwargs)
            self.clients.append(client)
            return client

        for patcher in (
            patch.dict(
                sys.modules, {"agent.secret_scope": SimpleNamespace(get_secret=lambda name: "synthetic-key")}
            ),
            patch("httpx.AsyncClient", side_effect=factory),
            patch("asyncio.create_subprocess_exec", side_effect=AssertionError("local CLI forbidden")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def stream(self, chunks=(), *, block=False):
        import httpx

        class Stream(httpx.AsyncByteStream):
            def __init__(self):
                self.started = asyncio.Event()
                self.closed = False
                self.reads = 0
                self.cancelled = False

            async def __aiter__(self):
                self.started.set()
                if block:
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        self.cancelled = True
                        raise
                for chunk in chunks:
                    self.reads += 1
                    yield chunk

            async def aclose(self):
                self.closed = True

        return Stream()

    async def test_oversized_or_nonfinite_request_never_connects(self):
        for batch in ({"state": "x" * 524289, "questions": {}}, {"state": float("nan")}):
            with self.assertRaisesRegex(JevError, "serialized"):
                await JevClient().ask(batch)
        self.assertEqual(self.clients, [])

    async def test_status_redirect_errors_never_retry_forward_auth_or_read_body(self):
        import httpx

        for status in (301, 302, 307, 308, 400, 401, 413, 422, 429, 500, 503, 529):
            with self.subTest(status=status):
                stream = self.stream((b"synthetic-private-error-body",))
                self.response = httpx.Response(
                    status, headers={"Location": "https://other.invalid/steal"}, stream=stream
                )
                count = len(self.requests)
                with self.assertRaises(JevError) as caught:
                    await JevClient().ask(prepare(snapshot()))
                self.assertEqual(len(self.requests), count + 1)
                self.assertEqual(str(self.requests[-1].url), "https://api.typesafe.ai/v1/systemone")
                self.assertEqual(stream.reads, 0)
                self.assertTrue(stream.closed)
                self.assertTrue(self.clients[-1].is_closed)
                self.assertNotIn("synthetic", str(caught.exception))

    async def test_malformed_oversized_and_compressed_answers_close(self):
        import httpx

        cases = (
            ({}, (b"not JSON synthetic-private",)),
            ({}, (b"\\xff",)),
            ({}, (b"{}",)),
            ({}, (b"[",)),
            ({}, (b"x" * 131073, b"x" * 131073)),
            ({"Content-Length": "262145"}, (b"never read",)),
            ({"Content-Length": "garbage"}, (b"never read",)),
            ({"Content-Encoding": "gzip"}, (b"never decompress",)),
        )
        for headers, chunks in cases:
            with self.subTest(headers=headers, chunks=len(chunks)):
                stream = self.stream(chunks)
                self.response = httpx.Response(200, headers=headers, stream=stream)
                with self.assertRaises(JevError) as caught:
                    await JevClient().ask(prepare(snapshot()))
                self.assertNotIn("synthetic-private", str(caught.exception))
                self.assertTrue(stream.closed)
                self.assertTrue(self.clients[-1].is_closed)
                if headers:
                    self.assertEqual(stream.reads, 0)

    async def test_async_timeout_and_cancellation_close_stream_and_client(self):
        import httpx

        for cancel in (False, True):
            stream = self.stream(block=True)
            self.response = httpx.Response(200, stream=stream)
            client = JevClient(timeout=0.05 if not cancel else 1.2)
            started = time.monotonic()
            task = asyncio.create_task(client.ask(prepare(snapshot())))
            await asyncio.wait_for(stream.started.wait(), 1)
            if cancel:
                task.cancel()
            with self.assertRaises(asyncio.CancelledError if cancel else JevError):
                await task
            self.assertTrue(task.done())
            self.assertTrue(stream.cancelled)
            self.assertTrue(stream.closed)
            self.assertTrue(self.clients[-1].is_closed)
            self.assertLess(time.monotonic() - started, 1)

    async def test_outer_ingress_deadline_cancels_and_closes_before_subbudget(self):
        import httpx

        stream = self.stream(block=True)
        self.response = httpx.Response(200, stream=stream)
        with self.assertRaises(TimeoutError):
            async with asyncio.timeout(0.02):
                await JevClient().ask(prepare(snapshot()))
        self.assertTrue(stream.cancelled and stream.closed)
        self.assertTrue(self.clients[-1].is_closed)

    async def test_safe_transport_errors_and_typed_invalid_replies(self):
        import httpx

        for error in (
            httpx.ConnectError("synthetic-key/private"),
            httpx.ReadError("synthetic-private"),
            httpx.ReadTimeout("synthetic-private"),
        ):
            self.response = error
            with self.assertRaises(JevError) as caught:
                await JevClient().ask(prepare(snapshot()))
            self.assertNotIn("synthetic", str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)
            self.assertTrue(self.clients[-1].is_closed)
        batch = prepare(snapshot())
        for value in (float("nan"), float("inf")):
            invalid = two_topic_answers(batch)
            invalid["answers"]["response"]["confidence"] = value
            self.response = httpx.Response(200, content=json.dumps(invalid).encode())
            with self.assertRaises(JevError):
                await JevClient().ask(batch)
        raw = two_topic_answers(batch)
        raw["answers"]["response"]["confidence"] = 0.1
        self.response = httpx.Response(200, content=json.dumps(raw).encode())
        self.assertEqual((await JevClient().ask(batch))["response"], "no")
