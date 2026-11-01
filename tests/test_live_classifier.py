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
            source = replace(
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
                    History(
                        "4.0", "UBIRCH", "作業中です。取得処理は成功しましたが、分類の詳細原因は未確定です。"
                    ),
                    History("5.0", "UFABLE", "通知しないと反応しない設定ですか？"),
                    History(
                        "6.0",
                        "UBIRCH",
                        "通知は必須ではありません。展示システムの判断段階に問題があり、返信前に停止しています。",
                    ),
                    History("7.0", "UBIRCH", "作業中 — 調査結果を確認しています。"),
                    History(
                        "8.0",
                        "UBIRCH",
                        "現在の処理は修正済みですが、展示システム全体はまだ動作していません。",
                    ),
                ),
                recipients=(
                    *source.recipients,
                    Recipient("TFICTION", "UCEDAR", "cedar"),
                    Recipient("TFICTION", "UDOGWOOD", "dogwood"),
                ),
            )
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
            receipt["unknown_questions"] = [name for name, value in selected.items() if value == "unknown"]
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
            receipt["assembly_code"] = {
                "semantic-resolved": "resolved",
                "uncertain or inseparable unit": "unit-uncertain",
                "specific assignment unresolved": "assignment-unresolved",
                "assignment-link-contradiction": "link-contradiction",
                "current-address-contradiction": "address-contradiction",
                "uncertain local assignment": "assignment-uncertain",
            }.get(plan.reason, "other-static-assembly-rejection")
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
