"""Wheel-only import/discovery check; execute with -I outside the source cwd."""

import configparser
import importlib.metadata
import importlib.util
import os
import sys
import tarfile
import tempfile
import unittest
import zipfile
from email.parser import Parser
from pathlib import Path
from unittest.mock import patch

TARGET = os.environ.get("HERMES_WHEEL_TARGET")
if os.environ.get("HERMES_REQUIRE_WHEEL") == "1" and not TARGET:
    raise RuntimeError("required wheel check needs HERMES_WHEEL_TARGET")


@unittest.skipUnless(TARGET, "separate installed-wheel job")
class InstalledWheel(unittest.TestCase):
    def test_wheel_entrypoint_activation_without_database_or_admin(self):
        assert TARGET
        target = Path(TARGET).resolve()
        sys.path.insert(0, str(target))
        self.addCleanup(sys.path.remove, str(target))
        import hermes_slack_agent_router as package

        self.assertTrue(Path(package.__file__).resolve().is_relative_to(target))
        self.assertTrue(Path(package.__file__).with_name("plugin.yaml").is_file())
        distributions = list(importlib.metadata.distributions(path=[str(target)]))
        distribution = next(d for d in distributions if d.metadata["Name"] == "hermes-slack-agent-router")
        self.assertFalse(
            any(d.metadata["Name"] == "hermes-slack-" + "thread-assignee" for d in distributions)
        )
        self.assertIsNone(importlib.util.find_spec("hermes_slack_" + "thread_assignee"))
        self.assertFalse(any("thread_assignee" in str(f) for f in distribution.files or ()))
        self.assertEqual(
            distribution.metadata["Summary"],
            "Context-aware multi-agent Slack message routing for Hermes, powered by Jev.",
        )
        self.assertIn("context-aware", distribution.metadata["Keywords"])
        self.assertIn(
            "Repository, https://github.com/u1-liquid/hermes-slack-agent-router",
            distribution.metadata.get_all("Project-URL"),
        )
        self.assertIn("Hermes Slack Agent Router", distribution.metadata.get_payload())
        entry = next(e for e in distribution.entry_points if e.group == "hermes_agent.plugins")
        self.assertEqual(entry.name, "slack-agent-router")
        self.assertEqual(
            [
                (e.name, e.value)
                for d in distributions
                for e in d.entry_points
                if e.group == "hermes_agent.plugins"
            ],
            [("slack-agent-router", "hermes_slack_agent_router:register")],
        )
        self.assertTrue(callable(entry.load()))
        self.assertFalse(any(e.group == "console_scripts" for e in distribution.entry_points))
        for module in ("store", "plans", "cli", "config"):
            self.assertIsNone(importlib.util.find_spec("hermes_slack_agent_router." + module))
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
            manifest = next(m for m in manifests if m.name == "slack-agent-router")
            self.assertNotIn("slack-" + "thread-assignee", [m.name for m in manifests])
            manager._load_plugin(manifest)
            self.assertIsNone(manager._plugins[entry.name].error)
            self.assertNotIn("thread-assignee", manager._cli_commands)
            from unittest.mock import Mock

            native = Mock()
            manager.get_platform_handler_factories("slack")[0][0](native, Mock())
            native.use.assert_called_once()
            report = doctor_plugin(Path(package.__file__).parent)
            self.assertTrue(report.ok, report.format_text())

    def test_fresh_wheel_and_sdist_have_only_router_package_and_metadata(self):
        directory = os.environ.get("HERMES_DIST_DIR")
        if not directory:
            self.skipTest("explicit fresh build directory required for archive inspection")
        root = Path(directory)
        wheels, sdists = list(root.glob("*.whl")), list(root.glob("*.tar.gz"))
        self.assertEqual(len(wheels), 1)
        self.assertEqual(len(sdists), 1)
        with zipfile.ZipFile(wheels[0]) as wheel:
            names = wheel.namelist()
            self.assertIn("hermes_slack_agent_router/plugin.yaml", names)
            self.assertFalse(any("thread_assignee" in name or "thread-assignee" in name for name in names))
            metadata = Parser().parsestr(
                wheel.read(next(n for n in names if n.endswith("/METADATA"))).decode()
            )
            self.assertEqual(metadata["Name"], "hermes-slack-agent-router")
            entries = configparser.ConfigParser()
            entries.read_string(
                wheel.read(next(n for n in names if n.endswith("/entry_points.txt"))).decode()
            )
            self.assertEqual(
                dict(entries["hermes_agent.plugins"]),
                {"slack-agent-router": "hermes_slack_agent_router:register"},
            )
        with tarfile.open(sdists[0]) as archive:
            names = archive.getnames()
            self.assertTrue(any(n.endswith("/hermes_slack_agent_router/plugin.yaml") for n in names))
            self.assertFalse(any("thread_assignee" in name or "thread-assignee" in name for name in names))
            info = archive.extractfile(
                next(n for n in names if n.count("/") == 1 and n.endswith("/PKG-INFO"))
            )
            assert info
            with info:
                self.assertEqual(Parser().parsestr(info.read().decode())["Name"], "hermes-slack-agent-router")
