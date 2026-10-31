"""Stateless configuration, identity and fresh-process activation boundaries."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hermes_slack_thread_assignee.config import Config, ConfigError
from hermes_slack_thread_assignee.policy import Recipient, Thread, addresses

A = Recipient("TDEMO", "UALPHA", "alpha")
B = Recipient("TDEMO", "UBETA", "beta")
KEY = Thread("TDEMO", "CDEMO", "100.001")


class CoreTests(unittest.TestCase):
    def test_fresh_process_activation_without_database_or_initialization(self):
        # Run a real subprocess/module entry point, not an inline bootstrap script.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            config.write_text(json.dumps({"participants": [B.as_dict(), A.as_dict()]}))
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "tests",
                    "-p",
                    "test_core.py",
                    "-k",
                    "startup_receiver",
                ],
                env={**os.environ, "STATELESS_STARTUP_CONFIG": str(config)},
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["config.json"])

    @unittest.skipUnless(os.environ.get("STATELESS_STARTUP_CONFIG"), "fresh subprocess receiver")
    def test_startup_receiver(self):
        from unittest.mock import Mock, patch

        from hermes_slack_thread_assignee.plugin import register

        path = Path(os.environ["STATELESS_STARTUP_CONFIG"])
        self.assertEqual(Config.load(path).participants, (A, B))
        ctx = Mock()
        register(ctx)
        ctx.register_cli_command.assert_not_called()
        ctx.register_platform_handler.assert_called_once()
        # Actual factory/config/Gate construction must work without init or operator bootstrap.
        factory = ctx.register_platform_handler.call_args.args[1]
        with patch.dict(os.environ, {"HERMES_THREAD_ASSIGNEE_CONFIG": str(path)}):
            native = Mock()
            factory(native, Mock())
            native.use.assert_called_once()
        ctx.on_unload.call_args.args[0]()

    def test_config_rejects_ambiguous_or_legacy_state_and_defaults_no_egress(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            raw = {"participants": [A.as_dict(), B.as_dict()]}
            path.write_text(json.dumps(raw))
            self.assertFalse(Config.load(path).semantic.permits(KEY, "fictional"))
            for field in ("database", "database_id", "registry_revision"):
                path.write_text(json.dumps({**raw, field: "legacy"}))
                with self.assertRaises(ConfigError):
                    Config.load(path)
            raw["participants"] = [A.as_dict(), Recipient("TDEMO", "UALPHA", "other").as_dict()]
            path.write_text(json.dumps(raw))
            with self.assertRaises(ConfigError):
                Config.load(path)

    def test_quote_code_and_forwarded_mentions_are_not_direct(self):
        self.assertEqual(addresses("> <@UBETA>\n`<@UBETA>`\n```\n<@UBETA>\n```\n<@UALPHA>"), ("UALPHA",))
        self.assertEqual(addresses("`<@UBETA>"), ())
        self.assertEqual(addresses(">>> forwarded\n<@UBETA>"), ())

    def test_literal_identity_validation(self):
        for value in ("100", "100.001 extra", "1e2", 100.001):
            with self.assertRaises(ValueError):
                Thread("TDEMO", "CDEMO", value)
        with self.assertRaises(ValueError):
            Recipient("TDEMO", "<@UALPHA>", "alpha")
