"""Real directory discovery, registration and isolated Plugin Doctor."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = os.environ.get("HERMES_TEST_SOURCE")


@unittest.skipUnless(SOURCE, "requires isolated official host")
class PluginSurface(unittest.TestCase):
    def test_real_discovery_activation_doctor_without_database_or_admin(self):
        assert SOURCE
        sys.path.insert(0, SOURCE)
        self.addCleanup(sys.path.remove, SOURCE)
        from hermes_cli.plugin_dev import doctor_plugin
        from hermes_cli.plugins import PluginManager

        package = Path(__file__).resolve().parents[1] / "hermes_slack_thread_assignee"
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            with patch.dict(os.environ, {"HERMES_HOME": str(root)}):
                os.environ.pop("HERMES_THREAD_ASSIGNEE_CONFIG", None)
                manager = PluginManager()
                manifests = manager._scan_directory(package.parent, source="user", skip_names={".venv"})
                matches = [m for m in manifests if m.name == "slack-thread-assignee"]
                self.assertEqual(len(matches), 1)
                manager._load_plugin(matches[0])
                self.assertIsNone(manager._plugins["slack-thread-assignee"].error)
                self.assertEqual(len(manager.get_platform_handler_factories("slack")), 1)
                from unittest.mock import Mock

                native = Mock()
                manager.get_platform_handler_factories("slack")[0][0](native, Mock())
                native.use.assert_called_once()
                self.assertNotIn("thread-assignee", manager._cli_commands)
                self.assertFalse((root / "db").exists())
                report = doctor_plugin(package)
                self.assertTrue(report.ok, report.format_text())
                with patch.dict(os.environ, {"HERMES_THREAD_ASSIGNEE_CONFIG": "/nonexistent/rejected.json"}):
                    other = Mock()
                    manager.get_platform_handler_factories("slack")[0][0](other, Mock())
                    other.use.assert_called_once()
                    report = doctor_plugin(package)
                    self.assertTrue(report.ok, report.format_text())
