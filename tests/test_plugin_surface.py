"""Real directory discovery, registration and isolated Plugin Doctor."""

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = os.environ.get("HERMES_TEST_SOURCE")


@unittest.skipUnless(SOURCE, "requires isolated official host")
class PluginSurface(unittest.TestCase):
    def test_real_discovery_cli_doctor_and_missing_config(self):
        assert SOURCE
        sys.path.insert(0, SOURCE)
        self.addCleanup(sys.path.remove, SOURCE)
        from hermes_cli.plugin_dev import doctor_plugin
        from hermes_cli.plugins import PluginManager

        package = Path(__file__).resolve().parents[1] / "hermes_slack_thread_assignee"
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            config = root / "operator.json"
            config.write_text(
                json.dumps(
                    {
                        "database": str(root / "db"),
                        "database_id": "demo",
                        "registry_revision": "1",
                        "participants": [
                            {"workspace": "TDEMO", "bot_user": "UBETA", "runtime_profile": "default"}
                        ],
                    }
                )
            )
            with patch.dict(
                os.environ, {"HERMES_HOME": str(root), "HERMES_THREAD_ASSIGNEE_CONFIG": str(config)}
            ):
                manager = PluginManager()
                manifests = manager._scan_directory(package.parent, source="user", skip_names={".venv"})
                matches = [m for m in manifests if m.name == "slack-thread-assignee"]
                self.assertEqual(len(matches), 1)
                manager._load_plugin(matches[0])
                self.assertIsNone(manager._plugins["slack-thread-assignee"].error)
                self.assertEqual(len(manager.get_platform_handler_factories("slack")), 1)
                command = manager._cli_commands["thread-assignee"]
                parser = argparse.ArgumentParser()
                command["setup_fn"](parser)
                args = parser.parse_args(["--config", str(config), "init"])
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(command["handler_fn"](args), 0)
                self.assertTrue(json.loads(output.getvalue())["initialized"])
                report = doctor_plugin(package)
                self.assertTrue(report.ok, report.format_text())
                with patch.dict(os.environ, {"HERMES_THREAD_ASSIGNEE_CONFIG": ""}):
                    report = doctor_plugin(package)
                    self.assertTrue(report.ok, report.format_text())
                    # Discovery/CLI must work without activating native routing.
