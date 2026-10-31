"""Wheel-only import/discovery check; execute with -I outside the source cwd."""

import importlib.metadata
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TARGET = os.environ.get("HERMES_WHEEL_TARGET")
if os.environ.get("HERMES_REQUIRE_WHEEL") == "1" and not TARGET:
    raise RuntimeError("required wheel check needs HERMES_WHEEL_TARGET")


@unittest.skipUnless(TARGET, "separate installed-wheel job")
class InstalledWheel(unittest.TestCase):
    def test_wheel_metadata_entrypoint_directory_and_cli(self):
        assert TARGET
        target = Path(TARGET).resolve()
        sys.path.insert(0, str(target))
        self.addCleanup(sys.path.remove, str(target))
        import hermes_slack_thread_assignee as package

        self.assertTrue(Path(package.__file__).resolve().is_relative_to(target))
        self.assertTrue(Path(package.__file__).with_name("plugin.yaml").is_file())
        distributions = list(importlib.metadata.distributions(path=[str(target)]))
        distribution = next(d for d in distributions if d.metadata["Name"] == "hermes-slack-thread-assignee")
        entry = next(e for e in distribution.entry_points if e.group == "hermes_agent.plugins")
        self.assertEqual(entry.name, "slack-thread-assignee")
        self.assertTrue(callable(entry.load()))
        source = os.environ["HERMES_TEST_SOURCE"]
        sys.path.append(source)
        self.addCleanup(sys.path.remove, source)
        from hermes_cli.plugin_dev import doctor_plugin
        from hermes_cli.plugins import PluginManager

        with (
            tempfile.TemporaryDirectory() as home,
            patch.dict(os.environ, {"HOME": home, "HERMES_HOME": home, "HERMES_THREAD_ASSIGNEE_CONFIG": ""}),
        ):
            manager = PluginManager()
            manifests = manager._scan_directory(target, source="user")
            manifest = next(m for m in manifests if m.name == "slack-thread-assignee")
            manager._load_plugin(manifest)
            self.assertIsNone(manager._plugins[entry.name].error)
            self.assertIn("thread-assignee", manager._cli_commands)
            report = doctor_plugin(Path(package.__file__).parent)
            self.assertTrue(report.ok, report.format_text())
