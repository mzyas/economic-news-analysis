"""Safety boundary tests for the fixed daily delivery profile."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock
from unittest.mock import patch

from tools import hermes_plugin
from tools.config_loader import ROOT, load_runtime_config


def _load_native_plugin():
    module_path = ROOT / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "economic_news_analysis_daily_profile_test",
        module_path,
        submodule_search_locations=[str(ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load native plugin entry")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Context:
    def __init__(self) -> None:
        self.llm = SimpleNamespace()
        self.registration: dict | None = None

    def register_tool(self, **kwargs) -> None:
        self.registration = kwargs


class DailyEmailProfileConfigTests(TestCase):
    def test_native_schema_exposes_only_fixed_daily_profile(self) -> None:
        plugin = _load_native_plugin()
        ctx = _Context()
        plugin.register(ctx)
        assert ctx.registration is not None

        schema = ctx.registration["schema"]
        self.assertEqual(schema["required"], [])
        self.assertEqual(
            schema["properties"]["profile_config"]["enum"], ["daily_email"]
        )
        self.assertNotIn("config_path", schema["properties"])

    def test_delivery_requires_fixed_profile_but_allows_empty_text(self) -> None:
        plugin = _load_native_plugin()
        ctx = _Context()
        plugin.register(ctx)
        assert ctx.registration is not None

        with self.assertRaisesRegex(ValueError, "requires profile_config"):
            ctx.registration["handler"]({"run_mode": "deliver"})

        expected = {"status": "success", "llm_audit": []}
        with mock.patch.object(
            plugin, "run_langgraph_workflow", return_value=expected
        ) as workflow:
            result = json.loads(
                ctx.registration["handler"](
                    {"run_mode": "deliver", "profile_config": "daily_email"}
                )
            )

        self.assertEqual(result, expected)
        workflow.assert_called_once_with(
            ctx, "", run_mode="deliver", profile_config="daily_email"
        )

    def test_profile_file_must_resolve_inside_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            template = root / "daily_email_briefing.yaml"
            template.write_text("{}\n", encoding="utf-8")

            with patch.object(hermes_plugin, "ROOT", root):
                self.assertEqual(
                    hermes_plugin.resolve_profile_config("daily_email"), template
                )

    def test_profile_mapping_cannot_escape_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outside = root.parent / "outside.yaml"
            outside.write_text("{}\n", encoding="utf-8")
            try:
                with patch.object(hermes_plugin, "ROOT", root), patch.object(
                    hermes_plugin,
                    "_PROFILE_CONFIG_FILENAMES",
                    {"daily_email": "../outside.yaml"},
                ):
                    with self.assertRaisesRegex(ValueError, "must remain inside"):
                        hermes_plugin.resolve_profile_config("daily_email")
            finally:
                outside.unlink(missing_ok=True)

    def test_delivery_loads_only_the_mapped_template(self) -> None:
        ctx = SimpleNamespace(
            llm=SimpleNamespace(),
            get_config=lambda _name, default=None: default,
        )
        runtime_config = {"mode": "deliver"}
        expected = {"status": "success"}
        with patch.object(
            hermes_plugin, "load_runtime_config", return_value=runtime_config
        ) as loader, patch.object(
            hermes_plugin, "run_workflow", return_value=expected
        ) as workflow:
            result = hermes_plugin.run_langgraph_workflow(
                ctx,
                "",
                run_mode="deliver",
                profile_config="daily_email",
            )

        self.assertEqual(result, expected)
        loader.assert_called_once_with(ROOT / "daily_email_briefing.yaml")
        self.assertEqual(workflow.call_args.args[0]["mode"], "deliver")
        self.assertEqual(workflow.call_args.args[0]["stdin_text"], "")
        self.assertEqual(
            workflow.call_args.args[0]["_delivery_trace"],
            {
                "mode": "deliver",
                "profile_config": "daily_email",
                "deliver_email": False,
                "email_send": False,
                "recipient_count": 0,
            },
        )

    def test_root_template_is_safe_to_track(self) -> None:
        config = load_runtime_config(ROOT / "daily_email_briefing.yaml")

        self.assertTrue(config["deliver_email"])
        self.assertFalse(config["email"]["send"])
        self.assertNotIn("@", config["email"]["from"])
        self.assertNotIn("@", config["email"]["to"])
