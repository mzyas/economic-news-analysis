"""Hermes plugin boundary for the LangGraph economic-news workflow."""

from __future__ import annotations
import logging
import shutil

from copy import deepcopy
from pathlib import Path
from typing import Any

from .config_loader import ROOT, load_runtime_config
from .delivery_trace import effective_delivery_config
from .graph.workflow import run_workflow


logger = logging.getLogger(__name__)

_PLUGIN_NAME = "economic-news-analysis"

_PROFILE_CONFIG_FILENAMES = {
    "daily_email": "daily_email_briefing.yaml",
}


def resolve_profile_config(profile_config: str) -> Path:
    """Resolve a fixed plugin profile configuration inside the project root."""
    try:
        filename = _PROFILE_CONFIG_FILENAMES[profile_config]
    except KeyError as exc:
        raise ValueError(f"unsupported profile_config: {profile_config!r}") from exc

    project_root = ROOT.resolve(strict=True)
    candidate = (ROOT / filename).resolve(strict=True)
    try:
        candidate.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("profile configuration must remain inside the project root") from exc
    if not candidate.is_file():
        raise ValueError("profile configuration must be a regular file")
    return candidate


def _profile_data_dir() -> Path | None:
    """This plugin's data directory under the active Hermes profile, if Hermes is present."""
    try:
        from hermes_constants import get_hermes_home
    except ImportError:
        return None
    return get_hermes_home() / "plugin-data" / _PLUGIN_NAME


def _anchored(value: Any, base: Path) -> Path | None:
    """``value`` re-homed under ``base``, or ``None`` to leave it alone.

    A relative path moves as is. ``config_loader`` already resolves ``log_path`` against
    the plugin root, so an absolute path inside the root is re-homed by its relative part.
    An absolute path anywhere else was chosen explicitly and is kept.
    """
    path = Path(str(value))
    if not path.is_absolute():
        return base / path
    try:
        return base / path.relative_to(ROOT)
    except ValueError:
        return None


def _migrate_legacy_log(legacy: Path, target: Path) -> None:
    """Copy the pre-anchoring run log once, so duplicate-news history is not lost."""
    if target.exists() or not legacy.is_file():
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, target)
    except OSError as exc:
        logger.warning("could not migrate run log %s to %s: %s", legacy, target, exc)
        return
    logger.info("migrated run log %s to %s", legacy, target)


def anchor_profile_paths(runtime_config: dict[str, Any]) -> None:
    """Keep ``output_dir`` and ``log_path`` in the profile data directory.

    A relative ``output_dir`` otherwise follows the process working directory, which
    differs between the restart-safe cron worker and other launch paths, and a
    ``log_path`` under the plugin directory is lost when the plugin is reinstalled.
    Runs outside Hermes keep their existing behaviour.
    """
    base = _profile_data_dir()
    if base is None:
        return
    for key in ("output_dir", "log_path"):
        value = runtime_config.get(key)
        if not value:
            continue
        anchored = _anchored(value, base)
        if anchored is None:
            continue
        if key == "log_path":
            _migrate_legacy_log(Path(str(value)), anchored)
        runtime_config[key] = str(anchored)


def run_langgraph_workflow(
    ctx: Any,
    source_text: str = "",
    *,
    run_mode: str = "analyze",
    profile_config: str | None = None,
    config: dict[str, Any] | None = None,
    strict_model_routes: bool = True,
) -> dict[str, Any]:
    """Run the graph through Hermes' managed LLM completion facade.

    ``model_routes`` is loaded solely from this plugin's profile-scoped
    settings. A route marked ``inherit_cron_model`` (or no route at all) leaves
    provider and model unspecified, inheriting the Cron agent's main model.

    ``profile_config`` is a closed selector, never a model-supplied path. The
    daily delivery profile is loaded from the repository root after containment
    validation, so tool arguments cannot select recipients or mail settings.
    """
    if run_mode == "deliver" and profile_config != "daily_email":
        raise ValueError("run_mode 'deliver' requires profile_config 'daily_email'")
    if run_mode != "deliver" and profile_config is not None:
        raise ValueError("profile_config is only supported with run_mode 'deliver'")
    if profile_config is not None and config is not None:
        raise ValueError("profile_config cannot be combined with an explicit config")

    if profile_config is not None:
        runtime_config = load_runtime_config(resolve_profile_config(profile_config))
        anchor_profile_paths(runtime_config)
    else:
        runtime_config = deepcopy(config) if config is not None else load_runtime_config()
    runtime_config["mode"] = run_mode
    runtime_config["stdin_text"] = source_text
    runtime_config["_delivery_trace"] = effective_delivery_config(runtime_config, profile_config)
    logger.info("effective delivery configuration: %s", runtime_config["_delivery_trace"])
    routes = ctx.get_config("model_routes", default={})
    if not isinstance(routes, dict):
        raise ValueError("plugin setting model_routes must be a mapping")
    return run_workflow(
        runtime_config,
        mode=run_mode,
        hermes_llm=ctx.llm,
        model_routes=routes,
        strict_model_routes=strict_model_routes,
    )


__all__ = ["anchor_profile_paths", "resolve_profile_config", "run_langgraph_workflow"]