"""Explicit opt-in synthetic production-caller probe; no Slack text or secret output."""

import json
import os
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from test_semantic import snapshot

from hermes_slack_agent_router.jev import JevClient, JevError, validate_answers
from hermes_slack_agent_router.policy import Recipient
from hermes_slack_agent_router.semantic import History, SemanticError, assemble, prepare


def japanese_improvement_source():
    """Original fixed fictional source, unchanged text/identities/history/candidates."""
    source = snapshot("Please correct the diagram you prepared.")
    return replace(
        source,
        text="模型の展示システムが正常に動くようになるまで改善してください。",
        identity="10.0",
        history=(
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
        recipients=(
            *source.recipients,
            Recipient("TFICTION", "UCEDAR", "cedar"),
            Recipient("TFICTION", "UDOGWOOD", "dogwood"),
        ),
    )


@unittest.skipUnless(os.environ.get("MIZUKI_CLASSIFIER_PROBE") == "1", "explicit Mizuki synthetic API probe")
class LiveClassifier(unittest.IsolatedAsyncioTestCase):
    async def test_native_scoped_production_caller(self):
        import httpx
        from agent.secret_scope import (
            build_profile_secret_scope,
            current_secret_scope_home,
            reset_multiplex_context,
            reset_secret_scope,
            set_multiplex_context,
            set_secret_scope,
        )

        home = Path(os.environ["MIZUKI_CLASSIFIER_HOME"])
        self.assertTrue(home.is_absolute() and home.name == "mizuki" and home.is_dir())
        multiplex = set_multiplex_context(True)
        scope = set_secret_scope(build_profile_secret_scope(home), profile_home=str(home))
        self.addCleanup(reset_multiplex_context, multiplex)
        self.addCleanup(reset_secret_scope, scope)
        self.assertEqual(current_secret_scope_home(), str(home))
        case = os.environ.get("MIZUKI_CLASSIFIER_CASE", "contextual")
        source = snapshot("Please correct the diagram you prepared.")
        if case == "native-sized":
            source = replace(
                source,
                identity="10.0",
                history=(
                    History(
                        "1.0",
                        "UFABLE",
                        "Birch, lead this whole thread and prepare the diagram. Atlas handles summaries.",
                    ),
                    History("2.0", "UBIRCH", "I will prepare the diagram and coordinate the whole thread."),
                    *tuple(History(f"{i}.0", "UFABLE", "Thanks for the update.") for i in range(3, 9)),
                ),
                recipients=(
                    *source.recipients,
                    Recipient("TFICTION", "UCEDAR", "cedar"),
                    Recipient("TFICTION", "UDOGWOOD", "dogwood"),
                ),
            )
        elif case == "native-japanese":
            source = replace(
                source,
                text="図の修正を進めてください。",
                identity="10.0",
                history=(
                    History(
                        "1.0",
                        "UFABLE",
                        "<@UBIRCH>、このスレッド全体を担当し、架空の模型展示会の会場図を作成してください。<@UATLAS>は案内文を担当します。",
                    ),
                    History("2.0", "UBIRCH", "私が会場図を担当します。通路と出入口を確認して修正します。"),
                    *tuple(
                        History(
                            f"{i}.0", "UFABLE", "途中経過ありがとうございます。引き続きよろしくお願いします。"
                        )
                        for i in range(3, 9)
                    ),
                ),
                recipients=(
                    *source.recipients,
                    Recipient("TFICTION", "UCEDAR", "cedar"),
                    Recipient("TFICTION", "UDOGWOOD", "dogwood"),
                ),
            )
        elif case == "japanese-improvement":
            source = japanese_improvement_source()
        elif case != "contextual":
            self.fail("unknown fixed probe case")
        batch = prepare(source)
        receipt = {
            "case": case,
            "scope": "mizuki",
            "model": JevClient.model,
            "questions": len(batch["questions"]),
        }
        factory = httpx.AsyncClient

        def observed_validation(batch, result):
            answers = result.get("answers", {})
            receipt["low_confidence_questions"] = [
                name
                for name in batch["questions"]
                if isinstance(answers.get(name), dict)
                and type(answers[name].get("confidence")) in (int, float)
                and answers[name]["confidence"] < 0.8
            ]
            selected = validate_answers(batch, result)
            receipt["unresolved_questions"] = [
                name for name, value in selected.items() if value == "unresolved"
            ]
            return selected

        async def response_hook(response):
            receipt["http_status"] = response.status_code

        def observed_client(*args, **kwargs):
            return factory(*args, event_hooks={"response": [response_hook]}, **kwargs)

        started = time.monotonic()
        failure = None
        try:
            with (
                patch("httpx.AsyncClient", side_effect=observed_client),
                patch("hermes_slack_agent_router.jev.validate_answers", side_effect=observed_validation),
            ):
                selected = await JevClient().ask(batch)
            receipt["stage"] = "assemble"
            plan = assemble(source, selected)
            receipt["assembly_code"] = plan.reason
            receipt["outcome"] = plan.status
            receipt["receiver_control"] = bool(plan.view(source.recipients[1]))
            receipt["nonrecipient_control"] = not plan.view(source.recipients[0])
            self.assertEqual(plan.status, "ready")
            self.assertTrue(receipt["receiver_control"] and receipt["nonrecipient_control"])
        except JevError as exc:
            message = str(exc)
            receipt["outcome"], receipt["failure_status"] = exc.diagnostic
            if message.startswith("uncertain relevant answer: "):
                receipt["outcome"] = "answer-confidence-rejected"
                name = message.removeprefix("uncertain relevant answer: ")
                if name in batch["questions"]:
                    receipt["question"] = name
            failure = receipt["outcome"]
        except SemanticError:
            receipt["outcome"] = "semantic-assembly-failed"
            failure = receipt["outcome"]
        finally:
            receipt["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
            print("MIZUKI_SYNTHETIC_RECEIPT " + json.dumps(receipt, sort_keys=True), flush=True)
        self.assertIsNone(failure, failure)


@unittest.skipUnless(os.environ.get("MIZUKI_REAL_WHOAMI_STAGE"), "explicit named real-thread opt-in")
class RealWhoamiContrast(unittest.IsolatedAsyncioTestCase):
    async def test_named_thread_production_classifier_contrast(self):
        """Read-only native acquisition, then frozen production questions; no agent dispatch."""
        import copy
        import hashlib
        import logging
        import sys
        import traceback
        from dataclasses import asdict
        from decimal import Decimal

        import aiohttp
        from slack_sdk.web.async_client import AsyncWebClient

        from hermes_slack_agent_router.bridge import canonical_text
        from hermes_slack_agent_router.jev import serialize_request
        from hermes_slack_agent_router.plugin import Gate
        from hermes_slack_agent_router.policy import Thread
        from hermes_slack_agent_router.semantic import Snapshot

        host = os.environ["HERMES_TEST_SOURCE"]
        sys.path.insert(0, host)
        self.addCleanup(sys.path.remove, host)
        from agent.secret_scope import (
            build_profile_secret_scope,
            current_secret_scope_home,
            get_secret,
            reset_multiplex_context,
            reset_secret_scope,
            set_multiplex_context,
            set_secret_scope,
        )

        private = Path(os.environ["MIZUKI_REAL_WHOAMI_PRIVATE"]).resolve()
        private.mkdir(mode=0o700, parents=True, exist_ok=True)
        private.chmod(0o700)

        def save(name, value):
            fd = os.open(private / name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump(value, stream, ensure_ascii=False, indent=2)

        def digest(value):
            return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

        stage = os.environ["MIZUKI_REAL_WHOAMI_STAGE"]
        home = Path(os.environ["MIZUKI_CLASSIFIER_HOME"])
        team = os.environ["MIZUKI_REAL_WORKSPACE"]
        channel = os.environ["MIZUKI_REAL_CHANNEL"]
        root = os.environ["MIZUKI_REAL_THREAD"]
        author = os.environ["MIZUKI_REAL_REQUESTER"]
        targets = json.loads(os.environ["MIZUKI_REAL_IDENTITIES"])
        thread = Thread(team, channel, root)
        before_logging = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, before_logging)
        mode = set_multiplex_context(True)
        scope = set_secret_scope(build_profile_secret_scope(home), profile_home=str(home))
        self.addCleanup(reset_secret_scope, scope)
        self.addCleanup(reset_multiplex_context, mode)
        try:
            if home.name != "mizuki" or not home.is_absolute() or current_secret_scope_home() != str(home):
                raise ValueError("serving scope mismatch")
            if stage == "acquire":
                if (private / "acquisition.json").exists():
                    raise ValueError("acquisition already frozen")
                token = get_secret("SLACK_BOT_TOKEN")
                if not token or "," in token:
                    raise ValueError("missing or ambiguous native Slack credential")
                calls = []

                class ObservedClient(AsyncWebClient):
                    async def conversations_replies(self, **kwargs):
                        response = await super().conversations_replies(**kwargs)
                        calls.append(
                            {
                                "method": "conversations.replies",
                                "params": kwargs,
                                "response": copy.deepcopy(response.data),
                            }
                        )
                        save("read-progress.json", {"calls": calls})
                        return response

                    async def conversations_history(self, **kwargs):
                        response = await super().conversations_history(**kwargs)
                        calls.append(
                            {
                                "method": "conversations.history",
                                "params": kwargs,
                                "response": copy.deepcopy(response.data),
                            }
                        )
                        save("read-progress.json", {"calls": calls})
                        return response

                async with aiohttp.ClientSession() as session:
                    client = ObservedClient(token=token, session=session, timeout=3)
                    auth = await client.auth_test()
                    if (
                        auth.get("ok") is not True
                        or auth.get("team_id") != team
                        or auth.get("user_id") != targets["mizuki"]
                    ):
                        raise ValueError("native authenticated principal mismatch")
                    metadata = {}
                    metadata_responses = {}
                    for name, user_id in targets.items():
                        info = await client.users_info(user=user_id)
                        user = info.get("user", {})
                        if (
                            info.get("ok") is not True
                            or user.get("id") != user_id
                            or user.get("team_id") != team
                            or user.get("is_bot") is not True
                        ):
                            raise ValueError("native participant metadata mismatch")
                        profile = user.get("profile", {})
                        metadata[name] = {
                            "user_id": user_id,
                            "username": user.get("name"),
                            "display_name": profile.get("display_name"),
                            "real_name": profile.get("real_name", user.get("real_name")),
                        }
                        metadata_responses[name] = copy.deepcopy(info.data)
                    save(
                        "metadata.json",
                        {
                            "scope_home": str(home),
                            "auth": copy.deepcopy(auth.data),
                            "metadata": metadata,
                            "users_info": metadata_responses,
                        },
                    )
                    recent = await client.conversations_replies(channel=channel, ts=root, limit=24)
                    if recent.get("ok") is not True:
                        raise ValueError("recent named thread lookup failed")
                    messages = recent.get("messages", [])
                    recent_users = sorted(
                        (m for m in messages if m.get("user") == author and m.get("ts") != root),
                        key=lambda m: Decimal(m["ts"]),
                    )[-2:]
                    ids = list(
                        dict.fromkeys(
                            [
                                *json.loads(os.environ["MIZUKI_REAL_BASELINE_POSTS"]),
                                *(m["ts"] for m in recent_users),
                            ]
                        )
                    )
                    cases = {}
                    review = {}
                    recipients = tuple(Recipient(team, user, name) for name, user in targets.items())
                    identities = tuple((w["user_id"], w) for w in metadata.values())
                    for ts in ids:
                        exact = await client.conversations_replies(
                            channel=channel, ts=root, oldest=ts, latest=ts, inclusive=True, limit=1
                        )
                        found = [m for m in exact.get("messages", []) if m.get("ts") == ts]
                        if exact.get("ok") is not True or len(found) != 1:
                            raise ValueError("exact current lookup failed")
                        current = found[0]
                        if (
                            current.get("user") != author
                            or current.get("thread_ts") != root
                            or current.get("bot_id")
                        ):
                            raise ValueError("exact requester/current/thread mismatch")
                        text, provenance = canonical_text(current)
                        started = time.monotonic()
                        history_start = len(calls)
                        native_acquisition_error = None
                        try:
                            history = await Gate.history(client, thread, ts, started + 2.5)
                        except SemanticError as exc:
                            if str(exc) != "unsupported prior block":
                                raise
                            # Classifier-only interface: preserve exact Slack text fields,
                            # raw originals and rejected native admission separately.
                            native_acquisition_error = str(exc)
                            actual = {
                                m["ts"]: m
                                for call in calls[history_start:]
                                for m in call["response"].get("messages", [])
                                if Decimal(m["ts"]) < Decimal(ts)
                            }
                            selected = [
                                actual[root],
                                *sorted(
                                    (m for key, m in actual.items() if key != root),
                                    key=lambda m: Decimal(m["ts"]),
                                )[-7:],
                            ]
                            history = tuple(
                                History(m["ts"], m["user"], m["text"], copy.deepcopy(m)) for m in selected
                            )
                        source = Snapshot(
                            thread,
                            ts,
                            author,
                            text,
                            history,
                            recipients,
                            copy.deepcopy(current),
                            provenance,
                            recipient_whoami=identities,
                        )
                        batch = prepare(source)
                        common = batch["state"]
                        self_questions = [batch["questions"]["self_" + targets[name]] for name in targets]
                        definitions = [
                            {
                                **q,
                                "instructions": {k: v for k, v in q["instructions"].items() if k != "whoami"},
                            }
                            for q in self_questions
                        ]
                        if any(q != definitions[0] for q in definitions):
                            raise ValueError("production comparison meaning/options differ")
                        cases[ts] = {
                            "source": asdict(source),
                            "binding": source.binding,
                            "request": json.loads(serialize_request(batch)),
                            "raw_request": serialize_request(batch).decode(),
                            "context_hash": digest(common),
                            "question_options_hash": digest(definitions[0]),
                            "native_acquisition_error": native_acquisition_error,
                            "classifier_history_source": "exact Slack text fields; native unsupported-block guard NOT bypassed for admission"
                            if native_acquisition_error
                            else "native Gate.history",
                            "acquisition_ms": round((time.monotonic() - started) * 1000, 3),
                        }
                        review[ts] = {
                            "current": text,
                            "units": common["message_context"]["units"],
                            "prior": common["message_context"]["prior"],
                            "root": common["message_context"]["root"],
                        }
                    save(
                        "acquisition.json",
                        {
                            "scope_home": str(home),
                            "auth": {"ok": True, "team_id": team, "user_id": auth["user_id"]},
                            "metadata": metadata,
                            "targets": targets,
                            "calls": calls,
                            "cases": cases,
                        },
                    )
                    save("case-review.json", review)
                    save("expectations.json", {ts: {name: None for name in targets} for ts in cases})
                    print(
                        "REAL_WHOAMI_ACQUIRED "
                        + json.dumps(
                            {
                                "auth_ok": True,
                                "team_id": team,
                                "user_id": auth["user_id"],
                                "scope": "mizuki",
                                "source_ids": list(cases),
                                "clients_closed_on_return": True,
                            }
                        ),
                        flush=True,
                    )
            elif stage == "evaluate":
                frozen = json.loads((private / "acquisition.json").read_text())
                expected = json.loads((private / "expectations.json").read_text())
                if (private / "evaluation.json").exists() or set(expected) != set(frozen["cases"]):
                    raise ValueError("evaluation already run or expectation coverage mismatch")
                for ts, case in frozen["cases"].items():
                    if set(expected[ts]) != set(targets) or any(
                        value is None for value in expected[ts].values()
                    ):
                        raise ValueError("expectations not frozen")
                    for value in expected[ts].values():
                        if value not in next(iter(case["request"]["questions"].values()))["criteria"]:
                            raise ValueError("expectation outside production choices")
                results = {
                    "acquisition_sha256": hashlib.sha256(
                        (private / "acquisition.json").read_bytes()
                    ).hexdigest(),
                    "expectations_sha256": hashlib.sha256(
                        (private / "expectations.json").read_bytes()
                    ).hexdigest(),
                    "cases": {},
                }
                active = None

                class CapturedJev(JevClient):
                    async def _exchange(self, raw, key):
                        if raw.decode() != active["raw_request"]:
                            raise ValueError("prepared request changed")
                        response = await super()._exchange(raw, key)
                        active["raw_response"] = response.decode()
                        active["response"] = json.loads(response)
                        return response

                for ts, case in frozen["cases"].items():
                    active = copy.deepcopy(case)
                    batch = {k: v for k, v in active["request"].items() if k != "model"}
                    if digest(batch["state"]) != active["context_hash"]:
                        raise ValueError("common context changed")
                    started = time.monotonic()
                    try:
                        await CapturedJev().ask(batch)
                        active["production_parser"] = "accepted"
                    except JevError as exc:
                        active["production_parser"] = exc.diagnostic[0]
                        active["parser_failure"] = str(exc)
                    active["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
                    raw_answers = active.get("response", {}).get("answers", {})
                    actual_model = active.get("response", {}).get("model")
                    structurally_valid = active["production_parser"] in ("accepted", "answer-confidence")
                    matrix = {}
                    for name, user in targets.items():
                        answer = raw_answers.get("self_" + user, {})
                        choice = answer.get("choice")
                        confidence = answer.get("confidence")
                        chosen = choice.split("+") if choice and choice not in ("none", "unresolved") else []
                        matrix[name] = {
                            "user_id": user,
                            "expected": expected[ts][name],
                            "choice": choice,
                            "confidence": confidence,
                            "probabilities": answer.get("probabilities"),
                            "selected_units": chosen,
                            "selected_spans": [batch["state"]["message_context"]["units"][u] for u in chosen],
                            "pass": structurally_valid
                            and actual_model == "jev-1.14.0"
                            and choice == expected[ts][name]
                            and type(confidence) in (float, int)
                            and confidence >= 0.8,
                        }
                    active["matrix"] = matrix
                    results["cases"][ts] = active
                    save("evaluation.json", results)
                    print(
                        "REAL_WHOAMI_MATRIX "
                        + json.dumps(
                            {
                                "source_id": ts,
                                "model": actual_model,
                                "elapsed_ms": active["elapsed_ms"],
                                "parser": active["production_parser"],
                                "context_hash": active["context_hash"],
                                "identities": {
                                    name: {k: row[k] for k in ("expected", "choice", "confidence", "pass")}
                                    for name, row in matrix.items()
                                },
                            }
                        ),
                        flush=True,
                    )
                if any(
                    not row["pass"] for case in results["cases"].values() for row in case["matrix"].values()
                ):
                    raise AssertionError("one or more frozen real identity contrasts failed")
            else:
                raise ValueError("unknown real contrast stage")
        except Exception:  # noqa: BLE001 — real SDK/assertion bodies stay private, never unittest stdout.
            save(stage + "-failure.json", {"traceback": traceback.format_exc()})
            raise AssertionError(
                "real whoami execution failed; inspect permission-restricted failure record"
            ) from None


@unittest.skipUnless(os.environ.get("MIZUKI_DIRECT_WHOAMI_STAGE"), "explicit elementary diagnostic opt-in")
class DirectWhoamiDiagnostic(unittest.IsolatedAsyncioTestCase):
    async def test_literal_context_and_whoami(self):
        """Elementary recipient intent only; deliberately not production routing acceptance."""
        import copy
        import hashlib
        import sys
        import traceback

        from hermes_slack_agent_router.jev import serialize_request

        parent = Path(os.environ["MIZUKI_REAL_WHOAMI_PRIVATE"])
        private = parent / "direct"
        private.mkdir(mode=0o700, exist_ok=True)
        private.chmod(0o700)
        stage = os.environ["MIZUKI_DIRECT_WHOAMI_STAGE"]

        def save(name, value):
            fd = os.open(private / name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump(value, stream, ensure_ascii=False, indent=2)

        def digest(value):
            return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

        try:
            if stage == "prepare":
                if (private / "manifest.json").exists():
                    raise ValueError("direct manifest already frozen")
                acquired = json.loads((parent / "acquisition.json").read_text())
                old_expected = json.loads((parent / "expectations.json").read_text())
                by_user = {who["user_id"]: who for who in acquired["metadata"].values()}
                question = {
                    "type": "choice",
                    "instructions": "Is the CURRENT message addressed to the Slack user identified by whoami? Use the conversation context.",
                    "criteria": {
                        "yes": "The user addresses this person, alone or with others",
                        "no": "The user is addressing someone else or is not requesting a response from this person",
                    },
                }

                def message(record):
                    original = record["original"]
                    if not isinstance(original.get("text"), str):
                        raise TypeError("original Slack text unavailable")
                    return {
                        "timestamp": record["identity"],
                        "sender": by_user.get(record["sender"], {"user_id": record["sender"]}),
                        "text": original["text"],
                    }

                manifest = {
                    "source_acquisition_sha256": hashlib.sha256(
                        (parent / "acquisition.json").read_bytes()
                    ).hexdigest(),
                    "source_expectations_sha256": hashlib.sha256(
                        (parent / "expectations.json").read_bytes()
                    ).hexdigest(),
                    "question_hash": digest(question),
                    "cases": {},
                }
                for ts, case in acquired["cases"].items():
                    source = case["source"]
                    root = [h for h in source["history"] if h["identity"] == source["thread"]["root"]]
                    if len(root) != 1:
                        raise ValueError("exact original root missing")
                    context = {
                        "root": message(root[0]),
                        "previous": [message(h) for h in source["history"] if h not in root],
                        "CURRENT": message(source),
                    }
                    rows = {}
                    for name, whoami in acquired["metadata"].items():
                        own_scope = old_expected[ts][name]
                        if not isinstance(own_scope, str):
                            raise TypeError("old expectation not frozen")
                        batch = {
                            "state": {"message_context": context, "whoami": copy.deepcopy(whoami)},
                            "questions": {"self_recipient": copy.deepcopy(question)},
                        }
                        rows[name] = {
                            "expected_addressed": bool(own_scope and own_scope != "none"),
                            "request": json.loads(serialize_request(batch)),
                            "raw_request": serialize_request(batch).decode(),
                        }
                    neutral = [copy.deepcopy(row["request"]) for row in rows.values()]
                    for request in neutral:
                        del request["state"]["whoami"]
                    if any(request != neutral[0] for request in neutral):
                        raise ValueError("more than whoami varies")
                    manifest["cases"][ts] = {
                        "context_hash": digest(context),
                        "only_whoami_differs": True,
                        "rows": rows,
                    }
                if (
                    len(manifest["cases"]) != 4
                    or sum(len(case["rows"]) for case in manifest["cases"].values()) != 12
                ):
                    raise ValueError("exact four-by-three diagnostic required")
                save("manifest.json", manifest)
                print(
                    "DIRECT_WHOAMI_PREPARED "
                    + json.dumps(
                        {
                            "source_ids": list(manifest["cases"]),
                            "requests": 12,
                            "question_hash": manifest["question_hash"],
                        }
                    ),
                    flush=True,
                )
            elif stage == "evaluate":
                if (private / "evaluation.json").exists():
                    raise ValueError("direct diagnostic already attempted")
                frozen = json.loads((private / "manifest.json").read_text())
                host = os.environ["HERMES_TEST_SOURCE"]
                sys.path.insert(0, host)
                self.addCleanup(sys.path.remove, host)
                from agent.secret_scope import (
                    build_profile_secret_scope,
                    current_secret_scope_home,
                    reset_multiplex_context,
                    reset_secret_scope,
                    set_multiplex_context,
                    set_secret_scope,
                )

                from hermes_slack_agent_router.jev import validate_answers as native_validation

                home = Path(os.environ["MIZUKI_CLASSIFIER_HOME"])
                mode = set_multiplex_context(True)
                scope = set_secret_scope(build_profile_secret_scope(home), profile_home=str(home))
                self.addCleanup(reset_secret_scope, scope)
                self.addCleanup(reset_multiplex_context, mode)
                if home.name != "mizuki" or current_secret_scope_home() != str(home):
                    raise ValueError("Mizuki serving scope mismatch")
                results = {
                    "manifest_sha256": hashlib.sha256((private / "manifest.json").read_bytes()).hexdigest(),
                    "scope_home": str(home),
                    "cases": {},
                }
                active = None

                class CapturedJev(JevClient):
                    async def _exchange(self, raw, key):
                        if raw.decode() != active["raw_request"]:
                            raise ValueError("direct request changed")
                        response = await super()._exchange(raw, key)
                        active["raw_response"] = response.decode()
                        active["response"] = json.loads(response)
                        return response

                def validate_direct(batch, response):
                    # Local parser bookkeeping only, NEVER part of model-visible state.
                    # Reuse every native structural check and the unchanged required .8 gate.
                    declaration = {
                        "state": {
                            "message_context": {"units": {}, "participants": {"recipient": {}}, "prior": {}}
                        },
                        "questions": batch["questions"],
                    }
                    return native_validation(declaration, response)

                for ts, case in frozen["cases"].items():
                    results["cases"][ts] = {"context_hash": case["context_hash"], "rows": {}}
                    for name, row in case["rows"].items():
                        active = copy.deepcopy(row)
                        batch = {k: v for k, v in active["request"].items() if k != "model"}
                        if (
                            set(batch["state"]) != {"message_context", "whoami"}
                            or digest(batch["state"]["message_context"]) != case["context_hash"]
                        ):
                            raise ValueError("direct two-component context changed")
                        started = time.monotonic()
                        try:
                            with patch(
                                "hermes_slack_agent_router.jev.validate_answers", side_effect=validate_direct
                            ):
                                await CapturedJev().ask(batch)
                            active["parser"] = "accepted"
                        except JevError as exc:
                            active["parser"] = exc.diagnostic[0]
                            active["failure"] = str(exc)
                        active["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
                        answer = active.get("response", {}).get("answers", {}).get("self_recipient", {})
                        active["actual_model"] = active.get("response", {}).get("model")
                        active["answer"] = answer
                        active["actual_addressed"] = answer.get("choice") == "yes" if answer else None
                        active["pass"] = (
                            active["parser"] == "accepted"
                            and active["actual_model"] == "jev-1.14.0"
                            and active["actual_addressed"] == active["expected_addressed"]
                        )
                        results["cases"][ts]["rows"][name] = active
                        save("evaluation.json", results)
                        print(
                            "DIRECT_WHOAMI_RESULT "
                            + json.dumps(
                                {
                                    "source_id": ts,
                                    "identity": name,
                                    "expected": active["expected_addressed"],
                                    "choice": answer.get("choice"),
                                    "confidence": answer.get("confidence"),
                                    "probabilities": answer.get("probabilities"),
                                    "model": active["actual_model"],
                                    "elapsed_ms": active["elapsed_ms"],
                                    "pass": active["pass"],
                                }
                            ),
                            flush=True,
                        )
                if any(
                    not row["pass"] for case in results["cases"].values() for row in case["rows"].values()
                ):
                    raise AssertionError("direct recipient-intent diagnostic has failed rows")
            else:
                raise ValueError("unknown direct stage")
        except Exception:  # noqa: BLE001 — preserve private API/context failures without stdout body leakage.
            save(stage + "-failure.json", {"traceback": traceback.format_exc()})
            raise AssertionError("direct diagnostic failed; inspect restricted evidence") from None


@unittest.skipUnless(
    os.environ.get("MIZUKI_COHERENT_RESPONSE_REAL_STAGE"),
    "explicit frozen readable real-source integration opt-in",
)
class CoherentResponseRealQualification(unittest.IsolatedAsyncioTestCase):
    async def test_frozen_real_integrated_requests(self):
        """Fresh production inference/assembly and pinned native input builder, not live admission."""
        import copy
        import hashlib
        import logging
        import sys
        import traceback
        from dataclasses import asdict
        from unittest.mock import AsyncMock

        from test_semantic import controlled_answers, source_from_record

        from hermes_slack_agent_router.jev import serialize_request

        host = os.environ["HERMES_TEST_SOURCE"]
        sys.path.insert(0, host)
        self.addCleanup(sys.path.remove, host)
        from agent.secret_scope import (
            build_profile_secret_scope,
            reset_multiplex_context,
            reset_secret_scope,
            set_multiplex_context,
            set_secret_scope,
        )
        from gateway.config import PlatformConfig
        from plugins.platforms.slack.adapter import SlackAdapter

        private = Path(os.environ["MIZUKI_REAL_WHOAMI_PRIVATE"]).resolve()
        output = private / "coherent-response"
        output.mkdir(mode=0o700, exist_ok=True)
        output.chmod(0o700)
        stage = os.environ["MIZUKI_COHERENT_RESPONSE_REAL_STAGE"]
        self.assertIn(stage, ("prepare", "evaluate"), "reuse existing metadata; no new Slack reads")
        disabled = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, disabled)

        def save(name, data):
            fd = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump(data, stream, ensure_ascii=False, indent=2)

        def digest(data):
            return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

        async def native_input(source, recipient, text):
            # Actual pinned native formatter, controlled network/final receiver.
            # This is NOT native Gate admission, live authentication or an agent call.
            adapter = SlackAdapter(PlatformConfig(extra={"reply_in_thread": True}))
            team, channel, root = source.thread.workspace, source.thread.channel, source.thread.root
            client = AsyncMock()
            client.users_info.return_value = {"ok": False}
            client.conversations_info.return_value = {"ok": False}
            adapter._team_clients = {team: client}
            adapter._team_bot_user_ids = {team: recipient.bot_user}
            adapter._bot_user_id = recipient.bot_user
            for user, whoami in source.recipient_whoami:
                if whoami["display_name"] or whoami["real_name"] or whoami["username"]:
                    adapter._user_name_cache[(team, user)] = (
                        whoami["display_name"] or whoami["real_name"] or whoami["username"]
                    )
            event = copy.deepcopy(source.original)
            event.update(
                text=text, user=source.sender, team=team, channel=channel, thread_ts=root, ts=source.identity
            )
            for key in ("blocks", "files", "attachments"):
                event.pop(key, None)
            own_mention = f"<@{recipient.bot_user}>" in text
            rendered = (
                adapter._apply_bot_mention(text, text, text, False, recipient.bot_user, root, team)[0]
                if own_mention
                else text.strip()
            )
            try:
                built = await adapter._build_message_event(
                    event,
                    text=rendered,
                    original_text=text,
                    command_probe_text=text,
                    is_command_text=False,
                    channel_id=channel,
                    team_id=team,
                    ts=source.identity,
                    user_id=source.sender,
                    thread_ts=root,
                    is_dm=False,
                    media_urls=[],
                    media_types=[],
                    media_text_inlined=[],
                    channel_context=None,
                )
                return {
                    "text": built.text,
                    "channel_context": built.channel_context,
                    "reply_to_text": built.reply_to_text,
                    "media_urls": built.media_urls,
                    "source": built.source.to_dict(),
                    "outbound": client.chat_postMessage.await_count,
                    "ephemeral": client.chat_postEphemeral.await_count,
                }
            finally:
                await adapter.cancel_background_tasks()

        try:
            frozen = json.loads((private / "acquisition.json").read_text())
            expected = json.loads((private / "expectations.json").read_text())
            manifest_path = output / "manifest.json"
            supplement_path = private / "chronology-people" / "metadata-supplement.json"
            if stage == "prepare":
                self.assertFalse(manifest_path.exists(), "already frozen")
                supplement = json.loads(supplement_path.read_text())
                self.assertEqual(
                    supplement["acquisition_sha256"],
                    hashlib.sha256((private / "acquisition.json").read_bytes()).hexdigest(),
                )
                rows = {}
                for ts, case in frozen["cases"].items():
                    old_source = source_from_record(case["source"])
                    self.assertEqual(old_source.binding, case["binding"])
                    people = {u: {**w, "kind": "bot"} for u, w in old_source.recipient_whoami}
                    authors = {old_source.sender, *[h.sender for h in old_source.history]}
                    people.update({u: p for u, p in supplement["people"].items() if u in authors})
                    source = replace(
                        old_source,
                        protocol="coherent-response-v1",
                        context_people=tuple(sorted(people.items())),
                    )
                    for name, user in frozen["targets"].items():
                        recipient = next(r for r in source.recipients if r.bot_user == user)
                        batch = prepare(source, recipient)
                        scope = expected[ts][name]
                        own_units = scope.split("+") if scope != "none" else []
                        self.assertTrue(
                            all(unit in batch["state"]["message_context"]["units"] for unit in own_units)
                        )
                        current = "".join(
                            batch["state"]["message_context"]["units"][unit]["text"] for unit in own_units
                        )
                        controlled = controlled_answers(batch, {"for_" + recipient.bot_user: scope})
                        plan = assemble(source, recipient, validate_answers(batch, controlled))
                        self.assertEqual(plan.view(recipient), current)
                        rows[ts + ":" + name] = {
                            "source_id": ts,
                            "identity": name,
                            "recipient": asdict(recipient),
                            "source": asdict(source),
                            "binding": source.binding,
                            "historical_binding": old_source.binding,
                            "expected_addressed": bool(own_units),
                            "expected_scope": scope,
                            "expected_current": current,
                            "native_acquisition_error": case["native_acquisition_error"],
                            "prepared_raw_request": serialize_request(batch).decode(),
                            "prepared_request": json.loads(serialize_request(batch)),
                            "context_hash": digest(batch["state"]["message_context"]),
                            "expected_native_builder": await native_input(source, recipient, current)
                            if current and not case["native_acquisition_error"]
                            else None,
                        }
                self.assertEqual(len(rows), 12)
                for ts in frozen["cases"]:
                    self.assertEqual(
                        len({r["context_hash"] for r in rows.values() if r["source_id"] == ts}), 1
                    )
                save(
                    "manifest.json",
                    {
                        "source_tree": os.environ["MIZUKI_WHOAMI_SOURCE_TREE"],
                        "source_diff_sha256": os.environ["MIZUKI_SIMPLE_SOURCE_DIFF_SHA256"],
                        "acquisition_sha256": hashlib.sha256(
                            (private / "acquisition.json").read_bytes()
                        ).hexdigest(),
                        "expectations_sha256": hashlib.sha256(
                            (private / "expectations.json").read_bytes()
                        ).hexdigest(),
                        "rows": rows,
                    },
                )
            elif stage == "evaluate":
                self.assertFalse((output / "evaluation.json").exists(), "no retry")
                manifest = json.loads(manifest_path.read_text())
                self.assertEqual(manifest["source_tree"], os.environ["MIZUKI_WHOAMI_SOURCE_TREE"])
                self.assertEqual(
                    manifest["source_diff_sha256"], os.environ["MIZUKI_SIMPLE_SOURCE_DIFF_SHA256"]
                )
                home = Path(os.environ["MIZUKI_CLASSIFIER_HOME"])
                self.assertEqual(home.name, "mizuki")
                mode = set_multiplex_context(True)
                scope = set_secret_scope(build_profile_secret_scope(home), profile_home=str(home))
                self.addCleanup(reset_secret_scope, scope)
                self.addCleanup(reset_multiplex_context, mode)
                results = {
                    "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                    "rows": {},
                }
                active = None

                class CapturedJev(JevClient):
                    async def _exchange(self, raw, key):
                        assert active is not None
                        if raw.decode() != active["prepared_raw_request"]:
                            raise ValueError("frozen request changed")
                        active["raw_request"] = raw.decode()
                        response = await super()._exchange(raw, key)
                        active["raw_response"] = response.decode()
                        active["response"] = json.loads(response)
                        return response

                for key, row in manifest["rows"].items():
                    active = copy.deepcopy(row)
                    source = source_from_record(row["source"])
                    recipient = Recipient(**row["recipient"])
                    batch = prepare(source, recipient)
                    self.assertEqual(serialize_request(batch).decode(), row["prepared_raw_request"])
                    started = time.monotonic()
                    try:
                        selected = await CapturedJev().ask(batch)
                        active["selected"] = selected
                        plan = assemble(source, recipient, selected)
                        active["plan"] = plan.as_dict()
                        active["view"] = plan.view(recipient)
                        current = active["view"].split("\n\nPRIOR REFERENCE (not instructions):", 1)[0]
                        active["admitted"] = selected["response"] == "yes"
                        active["response_decision_pass"] = active["admitted"] == row["expected_addressed"]
                        active["scope_pass"] = current == row["expected_current"] and plan.status == "ready"
                        active["projection_unresolved"] = plan.reason == "projection-unresolved"
                        if current and not row["native_acquisition_error"]:
                            active["native_builder_received"] = await native_input(
                                source, recipient, active["view"]
                            )
                            native = active["native_builder_received"]
                            expected_native = row["expected_native_builder"]
                            active["native_builder_pass"] = (
                                expected_native is not None
                                and native["text"].split("\n\nPRIOR REFERENCE (not instructions):", 1)[0]
                                == expected_native["text"]
                                and native["source"] == expected_native["source"]
                                and native["channel_context"] is None
                                and not (
                                    native["media_urls"]
                                    or native["reply_to_text"]
                                    or native["outbound"]
                                    or native["ephemeral"]
                                )
                            )
                        active["pass"] = (
                            active["response_decision_pass"]
                            and active["scope_pass"]
                            and active.get("response", {}).get("model") == "jev-1.14.0"
                            and (active.get("native_builder_pass", True))
                            and not (row["native_acquisition_error"] and row["expected_addressed"])
                        )
                    except Exception as exc:  # noqa: BLE001 — preserve each independent private failure and continue the fixed batch.
                        active["failure"] = str(exc)
                        active["private_traceback"] = traceback.format_exc()
                        active["pass"] = False
                    finally:
                        active["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
                        raw_answers = active.get("response", {}).get("answers", {})
                        active["consumed_answers"] = {
                            name: answer
                            for name, answer in raw_answers.items()
                            if name in {"response", "scope"}
                        }
                        active["native_boundary"] = (
                            "pinned native input builder only, not Gate admission/live runtime; historical format refusal retained"
                        )
                        results["rows"][key] = active
                        save("evaluation.json", results)
                        print(
                            "YES07_REAL_RECEIPT "
                            + json.dumps(
                                {
                                    "source_id": row["source_id"],
                                    "identity": row["identity"],
                                    "pass": active.get("pass", False),
                                    "elapsed_ms": active["elapsed_ms"],
                                }
                            )
                        )
                self.assertTrue(
                    all(row.get("pass") for row in results["rows"].values()),
                    "one or more required real integrations failed",
                )
            else:
                raise ValueError("unknown yes07 stage")
        except Exception:  # noqa: BLE001 — no private bodies in stdout/assertion tracebacks.
            save(stage + "-failure.json", {"traceback": traceback.format_exc()})
            raise AssertionError("yes07 real batch failed; inspect restricted evidence") from None
