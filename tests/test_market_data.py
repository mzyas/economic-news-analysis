import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.config_loader import ROOT, load_runtime_config
from tools.market_data.loader import build_market_context, load_market_sources
from tools.market_data.models import MarketSnapshot
from tools.market_data.providers.yfinance_provider import YFinanceProvider
from tools.market_data.registry import (
    get_market_data_provider,
    register_market_data_provider,
)
from tools.runtime import execute
from tools.schema_validation import validate_file


class FakeProvider:
    name = "fake"

    def fetch_snapshots(self, symbols, period, interval):
        return [
            MarketSnapshot(
                symbol_id=symbols[0].id,
                ticker=symbols[0].ticker,
                name=symbols[0].name,
                asset_class=symbols[0].asset_class,
                region=symbols[0].region,
                last_price=100.0,
                change_pct=1.0,
                period=period,
                interval=interval,
                as_of="2026-06-17",
                provider=self.name,
                status="success",
            )
        ]


class MarketDataTests(unittest.TestCase):
    def test_market_sources_schema_validates(self):
        data = load_market_sources(ROOT / "sources" / "market_sources.yaml")
        validate_file(data, ROOT / "schemas" / "market_sources.schema.json")
        self.assertEqual(data["provider"], "yfinance")
        self.assertGreaterEqual(len(data["symbols"]), 4)

    def test_registry_returns_registered_provider(self):
        register_market_data_provider("fake", FakeProvider)
        provider = get_market_data_provider("fake")
        self.assertEqual(provider.name, "fake")

    def test_market_context_skipped_by_default(self):
        config = load_runtime_config(ROOT / "examples" / "single_article.yaml")
        result = execute(config)
        self.assertEqual(result["market_context"]["status"], "skipped")
        self.assertFalse(result["market_context"]["enabled"])

    def test_market_context_uses_registered_provider(self):
        register_market_data_provider("fake", FakeProvider)
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "market.json"
            config_path.write_text(
                """{
                  "mode": "analyze",
                  "market_data": {
                    "enabled": true,
                    "provider": "fake",
                    "source_config": "sources/market_sources.yaml",
                    "period": "5d",
                    "interval": "1d"
                  },
                  "input_items": [{"title": "Test", "summary": "Test", "source": "test"}]
                }""",
                encoding="utf-8",
            )
            config = load_runtime_config(config_path)
            result = execute(config)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["market_context"]["status"], "success")
        self.assertEqual(result["market_context"]["snapshots"][0]["provider"], "fake")

    def test_trend_mode_runs_offline_with_fake_provider(self):
        # daily-trend needs market data; the fake provider lets it run through
        # offline (no network, no LLM) to a deterministic success — the contract
        # the offline workflow smoke relies on.
        from tools.market_data.providers.fake_provider import FakeMarketProvider

        register_market_data_provider("fake", FakeMarketProvider)
        config = load_runtime_config(ROOT / "examples" / "daily_trend.yaml")
        config["market_data"] = {**config["market_data"], "provider": "fake"}
        result = execute(config)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["trend_table"]["status"], "success")
        self.assertTrue(result["trend_table"]["rows"])

    def test_unknown_provider_does_not_fail_runtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "market.json"
            config_path.write_text(
                """{
                  "mode": "analyze",
                  "market_data": {
                    "enabled": true,
                    "provider": "unknown",
                    "source_config": "sources/market_sources.yaml"
                  },
                  "input_items": [{"title": "Test", "summary": "Test", "source": "test"}]
                }""",
                encoding="utf-8",
            )
            config = load_runtime_config(config_path)
            result = execute(config)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["market_context"]["status"], "failed")
        self.assertIn("Unknown market data provider", result["market_context"]["errors"][0]["message"])

    def test_yfinance_provider_uses_fake_module(self):
        class FakeIloc:
            def __init__(self, values):
                self.values = values

            def __getitem__(self, index):
                return self.values[index]

        class FakeClose:
            def __init__(self):
                self.values = [100.0, 105.0]
                self.index = ["2026-06-16", "2026-06-17"]
                self.iloc = FakeIloc(self.values)

            def dropna(self):
                return self

            def __len__(self):
                return len(self.values)

        class FakeHistory:
            empty = False

            def __getitem__(self, key):
                if key != "Close":
                    raise KeyError(key)
                return FakeClose()

        class FakeTicker:
            def __init__(self, ticker):
                self.ticker = ticker

            def history(self, period, interval):
                return FakeHistory()

        fake_yfinance = types.SimpleNamespace(Ticker=FakeTicker)
        symbol = load_market_sources(ROOT / "sources" / "market_sources.yaml")["symbols"][0]
        with patch.dict(sys.modules, {"yfinance": fake_yfinance}):
            snapshots = YFinanceProvider().fetch_snapshots(
                symbols=[
                    type("Symbol", (), symbol)()
                ],
                period="5d",
                interval="1d",
            )
        self.assertEqual(snapshots[0].status, "success")
        self.assertEqual(snapshots[0].last_price, 105.0)
        self.assertEqual(round(snapshots[0].change_pct, 2), 5.0)


if __name__ == "__main__":
    unittest.main()
