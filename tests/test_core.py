"""Config-free registration without optional native SDK dependencies."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hermes_slack_agent_router.policy import Recipient, Thread, addresses

A = Recipient("TDEMO", "UALPHA", "alpha")
B = Recipient("TDEMO", "UBETA", "beta")
KEY = Thread("TDEMO", "CDEMO", "100.001")


class CoreTests(unittest.TestCase):
    def test_fresh_process_registration_without_config_or_initialization(self):
        # Run a real subprocess/module entry point, not an inline bootstrap script.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            result = subprocess.run(
                [
                    sys.executable,
                    "-S",  # Core startup must not inherit optional native SDK packages.
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
                env={**os.environ, "STATELESS_STARTUP_RECEIVER": "1", "HERMES_HOME": str(root)},
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(list(root.iterdir()), [])

    @unittest.skipUnless(os.environ.get("STATELESS_STARTUP_RECEIVER"), "fresh subprocess receiver")
    def test_startup_receiver(self):
        from unittest.mock import Mock

        from hermes_slack_agent_router.plugin import register

        ctx = Mock()
        register(ctx)
        ctx.register_cli_command.assert_not_called()
        ctx.register_platform_handler.assert_called_once()
        # Actual factory activation is mandatory in the separate native/discovery/wheel lane.
        ctx.on_unload.call_args.args[0]()

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
