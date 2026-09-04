"""Load market data config and build Runtime market context."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config_loader import ROOT
from .models import MarketDataResult, MarketSymbol
from .registry import get_market_data_provider
from ..schema_validation import validate_file

try:
    import yaml
except ImportError:
    yaml = None


def _parse_scalar(value: str) -> Any:
    value = value.strip().strip("'\"")
    if value in {"null", "~"}:
        return None
    if value in {"true", "false"}:
        return value == "true"
    return value


def _parse_market_sources_simple(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {"defaults": {}, "symbols": []}
    section: str | None = None
    current_symbol: dict[str, Any] | None = None

    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "defaults:":
            section = "defaults"
            continue
        if stripped == "symbols:":
            section = "symbols"
            continue
        if stripped.startswith("- id:"):
            if current_symbol:
                data["symbols"].append(current_symbol)
            current_symbol = {"id": _parse_scalar(stripped.partition(":")[2])}
            section = "symbols"
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        parsed = _parse_scalar(value)
        if section == "defaults":
            data["defaults"][key] = parsed
        elif section == "symbols" and current_symbol is not None:
            current_symbol[key] = parsed
        else:
            data[key] = parsed

    if current_symbol:
        data["symbols"].append(current_symbol)
    return data


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    elif yaml is not None:
        data = yaml.safe_load(text)
    else:
        data = _parse_market_sources_simple(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping at the document root")
    return data


def load_market_sources(path: str | Path) -> dict[str, Any]:
    source_path = Path(path)
    if not source_path.is_absolute():
        source_path = ROOT / source_path
    data = _load_mapping(source_path)
    validate_file(data, ROOT / "schemas" / "market_sources.schema.json")
    return data


def _market_symbol_from_mapping(item: dict[str, Any]) -> MarketSymbol:
    return MarketSymbol(
        id=str(item["id"]),
        ticker=str(item["ticker"]),
        name=str(item["name"]),
        asset_class=str(item["asset_class"]),
        region=str(item["region"]),
        currency=item.get("currency"),
        asset_type=str(item.get("asset_type", "price")),
        display_precision=int(item.get("display_precision", 2)),
        name_zh=item.get("name_zh"),
    )


def skipped_market_context(config: dict[str, Any]) -> dict[str, Any]:
    market_data = config.get("market_data", {})
    return MarketDataResult(
        enabled=False,
        provider=market_data.get("provider"),
        status="skipped",
    ).to_dict()


def build_market_context(config: dict[str, Any]) -> dict[str, Any]:
    market_data = config.get("market_data", {})
    if not market_data.get("enabled", False):
        return skipped_market_context(config)

    provider_name = str(market_data.get("provider") or "")
    try:
        data = load_market_sources(str(market_data["source_config"]))
        defaults = data.get("defaults", {})
        provider_name = str(market_data.get("provider") or data["provider"])
        period = str(market_data.get("period") or defaults.get("period") or "5d")
        interval = str(market_data.get("interval") or defaults.get("interval") or "1d")
        symbols = [
            _market_symbol_from_mapping(item)
            for item in data.get("symbols", [])
        ]
        provider = get_market_data_provider(provider_name)
        snapshots = provider.fetch_snapshots(symbols, period, interval)
    except Exception as exc:
        return MarketDataResult(
            enabled=True,
            provider=provider_name or None,
            status="failed",
            errors=[{"type": type(exc).__name__, "message": str(exc)}],
        ).to_dict()

    failed = [snapshot for snapshot in snapshots if snapshot.status != "success"]
    status = "success"
    if snapshots and failed:
        status = "failed" if len(failed) == len(snapshots) else "partial"
    elif not snapshots:
        status = "failed"
    return MarketDataResult(
        enabled=True,
        provider=provider_name,
        status=status,
        snapshots=snapshots,
        errors=[
            {
                "symbol_id": snapshot.symbol_id,
                "type": "MarketDataSnapshotError",
                "message": snapshot.error or "snapshot failed",
            }
            for snapshot in failed
        ],
    ).to_dict()
