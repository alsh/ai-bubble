import datetime
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
import agent  # noqa: E402


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)

VALID_OPINION = fixture("valid_v2_model_response.json")


class TestContract(unittest.TestCase):
    def test_tracked_fixtures_cover_contract_inputs(self):
        self.assertEqual(fixture("legacy_history.json")[0]["score"], 20)
        self.assertEqual(fixture("degraded_evidence.json")["market_data"]["NVDA_price"], 190.0)
        with self.assertRaises(ValueError):
            agent.validate_opinion(fixture("malformed_model_response.json"))
        with self.assertRaises(ValueError):
            agent.load_history(os.path.join(FIXTURES, "corrupt_history.json"))

    def test_score_boundaries(self):
        self.assertEqual([agent.score_status(n) for n in (30, 31, 69, 70)],
                         ["GREEN", "YELLOW", "YELLOW", "RED"])
        with self.assertRaises(ValueError):
            agent.score_status(101)

    def test_validation_and_required_fields(self):
        self.assertEqual(agent.validate_opinion(VALID_OPINION)["score"], 52)
        for field in ("thesis", "reasoning", "risk_factors", "stabilizing_factors", "change_explanation"):
            bad = dict(VALID_OPINION)
            bad[field] = [] if field.endswith("factors") else ""
            with self.assertRaises(ValueError):
                agent.validate_opinion(bad)

    def test_prior_context_and_baseline(self):
        history = [{"score": 10}, {"score": 45, "thesis": "Prior"}] + [{"score": i} for i in range(8)]
        context = agent.prior_context(history)
        self.assertEqual(context["prior_score"], 7)
        self.assertEqual(len(context["recent_scores"]), 7)
        self.assertTrue(agent.prior_context([])["baseline"])

    def test_entry_delta_and_legacy_fields(self):
        history = [{"score": 45, "thesis": "old"}]
        entry = agent.build_version2_entry(
            {**VALID_OPINION, "_requested_model": "test/model", "_resolved_model": "test/model-1"},
            {"NVDA_price": 100, "MSFT_price": 200, "GOOGL_price": 300, "NVDA_pe_ratio": 40},
            [{"title": "Headline", "published": "2026-07-17T00:00:00+00:00"}], history,
            now=datetime.datetime(2026, 7, 17, tzinfo=datetime.timezone.utc))
        self.assertEqual(entry["change"]["previous_score"], 45)
        self.assertEqual(entry["change"]["delta"], 7)
        self.assertEqual(entry["status"], "YELLOW")
        self.assertEqual(entry["schema_version"], 2)
        self.assertIn("nvda_pe", entry["metrics"])

    def test_empty_evidence_rejected(self):
        with self.assertRaises(ValueError):
            agent.build_version2_entry(VALID_OPINION, {}, [], [])

    def test_sentiment_validation_legacy_compatibility_and_entry_propagation(self):
        self.assertEqual(agent.METHODOLOGY_VERSION, "canary-opinion-v3")
        self.assertEqual(agent.SCHEMA_VERSION, 2)
        self.assertNotIn("market_sentiment", agent.validate_opinion(VALID_OPINION))
        with self.assertRaisesRegex(ValueError, "market_sentiment"):
            agent.validate_opinion(VALID_OPINION, require_sentiment=True)

        live = {**VALID_OPINION, "market_sentiment": "CONSTRUCTIVE"}
        self.assertEqual(agent.validate_opinion(live, require_sentiment=True)["market_sentiment"],
                         "CONSTRUCTIVE")
        for sentiment in ("sunny", "UNKNOWN", None, 3):
            with self.subTest(sentiment=sentiment), self.assertRaises(ValueError):
                agent.validate_opinion({**VALID_OPINION, "market_sentiment": sentiment})
            with self.subTest(required_sentiment=sentiment), self.assertRaises(ValueError):
                agent.validate_opinion({**VALID_OPINION, "market_sentiment": sentiment},
                                       require_sentiment=True)

        entry = agent.build_version2_entry(
            {**live, "_requested_model": "test/requested", "_resolved_model": "test/resolved"},
            {"NVDA_price": 100}, [], [],
        )
        self.assertEqual(entry["metrics"]["market_sentiment"], "CONSTRUCTIVE")
        self.assertEqual(entry["methodology_version"], "canary-opinion-v3")
        self.assertEqual(entry["schema_version"], 2)

    def test_data_quality_honors_rfc2822_timezone_offset(self):
        now = datetime.datetime(2026, 7, 18, 22, 30, tzinfo=datetime.timezone.utc)
        quality = agent.data_quality(
            {"NVDA_price": 1, "MSFT_price": 2, "GOOGL_price": 3},
            [{"published": "Fri, 17 Jul 2026 00:00:00 +0200"}],
            now=now,
        )
        self.assertEqual(agent._parse_published("Fri, 17 Jul 2026 00:00:00 +0200"),
                         datetime.datetime(2026, 7, 16, 22, 0, tzinfo=datetime.timezone.utc))
        self.assertEqual(quality["fresh_articles"], 0)
        self.assertEqual(quality["state"], "degraded")

    def test_market_collection_normalises_non_finite_values(self):
        class CloseSeries:
            def __init__(self, value):
                self.iloc = self
                self.value = value

            def __getitem__(self, _index):
                return self.value

            def std(self):
                return float("nan")

        class History:
            empty = False

            def __getitem__(self, _key):
                return CloseSeries(100.0)

        class Ticker:
            info = {
                "trailingPE": float("nan"),
                "forwardPE": float("inf"),
                "revenueGrowth": float("nan"),
                "pegRatio": float("nan"),
                "earningsGrowth": float("nan"),
            }

            def history(self, period):
                self.period = period
                return History()

        with patch.object(agent.yf, "Ticker", return_value=Ticker()):
            market_data = agent.get_market_data()

        self.assertEqual(market_data["NVDA_price"], 100.0)
        self.assertNotIn("NVDA_volatility", market_data)
        self.assertEqual(market_data["NVDA_pe_ratio"], "N/A")
        json.dumps(market_data, allow_nan=False)

    def test_non_finite_market_values_are_degraded_and_json_safe(self):
        entry = agent.build_version2_entry(
            {**VALID_OPINION, "_resolved_model": "fixture/v1"},
            {"NVDA_price": float("nan"), "MSFT_price": 200, "GOOGL_price": 300},
            [{"title": "Headline"}],
            [],
        )
        self.assertEqual(entry["metrics"]["NVDA_price"], "N/A")
        self.assertFalse(entry["data_quality"]["market_data_complete"])
        json.dumps(entry, allow_nan=False)

class TestMarketCollection(unittest.TestCase):
    @staticmethod
    def ticker_factory(closes_by_symbol, info_by_symbol):
        class History:
            empty = False

            def __init__(self, closes):
                self.closes = closes

            def __getitem__(self, key):
                if key != "Close":
                    raise KeyError(key)
                return self.closes

        class Ticker:
            def __init__(self, symbol):
                self.symbol = symbol
                self.info = info_by_symbol[symbol]

            def history(self, **_kwargs):
                return History(closes_by_symbol[self.symbol])

        return Ticker

    def test_peer_fundamentals_returns_and_sample_realized_volatility(self):
        closes = [100.0 * (1.01 ** index) for index in range(21)]
        info = {
            "NVDA": {"trailingPE": 30, "forwardPE": 25, "revenueGrowth": 0.5,
                     "earningsGrowth": 0.2, "pegRatio": float("nan")},
            "MSFT": {"trailingPE": 20, "forwardPE": 22, "revenueGrowth": 0.15,
                     "earningsGrowth": 0, "pegRatio": None},
            "GOOGL": {"trailingPE": 18, "forwardPE": 17, "revenueGrowth": 0.24,
                      "earningsGrowth": -0.1, "pegRatio": "N/A"},
        }
        factory = self.ticker_factory(dict.fromkeys(info, closes), info)
        with patch.object(agent.yf, "Ticker", side_effect=factory) as ticker:
            market = agent.get_market_data()
        self.assertEqual([call.args[0] for call in ticker.call_args_list], list(info))
        expected_5d = round((closes[-1] / closes[-6] - 1) * 100, 2)
        expected_20d = round((closes[-1] / closes[-21] - 1) * 100, 2)
        log_returns = [math.log(right / left) for left, right in zip(closes[-21:-1], closes[-20:], strict=True)]
        expected_volatility = round(statistics.stdev(log_returns) * math.sqrt(252) * 100, 2)
        for symbol in info:
            with self.subTest(symbol=symbol):
                self.assertEqual(market[f"{symbol}_price"], round(closes[-1], 2))
                self.assertEqual(market[f"{symbol}_5d_return_pct"], expected_5d)
                self.assertEqual(market[f"{symbol}_20d_return_pct"], expected_20d)
                self.assertEqual(market[f"{symbol}_realized_vol_20d_pct"], expected_volatility)
                self.assertEqual(market[f"{symbol}_pe_ratio"], info[symbol]["trailingPE"])
                self.assertEqual(market[f"{symbol}_forward_pe"], info[symbol]["forwardPE"])
                self.assertEqual(market[f"{symbol}_revenue_growth"], info[symbol]["revenueGrowth"])
        self.assertEqual(market["NVDA_peg_ratio"], 1.5)
        self.assertEqual(market["MSFT_peg_ratio"], "N/A")
        self.assertEqual(market["GOOGL_peg_ratio"], "N/A")
        self.assertNotIn("NVDA_volatility", market)

    def test_peg_fallback_rejects_missing_nonfinite_and_nonpositive_growth(self):
        closes = [100.0 * (1.01 ** index) for index in range(21)]
        for growth in (None, float("nan"), 0, -0.2):
            info = {symbol: {"trailingPE": 30, "earningsGrowth": growth,
                             "pegRatio": None} for symbol in ("NVDA", "MSFT", "GOOGL")}
            factory = self.ticker_factory(dict.fromkeys(info, closes), info)
            with self.subTest(earnings_growth=growth), patch.object(agent.yf, "Ticker", side_effect=factory):
                market = agent.get_market_data()
            self.assertEqual([market[f"{symbol}_peg_ratio"] for symbol in info], ["N/A"] * 3)

    def test_realized_volatility_is_unavailable_with_fewer_than_five_returns(self):
        closes = [100.0, 102.0, 101.0, 104.0, 105.0]
        info = {symbol: {} for symbol in ("NVDA", "MSFT", "GOOGL")}
        factory = self.ticker_factory(dict.fromkeys(info, closes), info)
        with patch.object(agent.yf, "Ticker", side_effect=factory):
            market = agent.get_market_data()
        for symbol in info:
            self.assertEqual(market[f"{symbol}_realized_vol_20d_pct"], "N/A")

    def test_three_rss_queries_deduplicate_cap_truncate_and_fallback_publishers(self):
        now = datetime.datetime.now(datetime.timezone.utc)

        def fresh(hours_ago=2):
            return (now - datetime.timedelta(hours=hours_ago)).isoformat()

        feeds = {
            agent.RSS_FEED_URLS[0]: [
                {"title": "Shared Story - Publisher Suffix",
                 "link": "https://www.bing.com/news/apiclick.aspx?url=https%3A%2F%2Fexample.com%2Fstory%3Futm_source%3Done",
                 "published": fresh()},
                {"title": "Fresh query-one second", "link": "https://q1.example/second",
                 "published": fresh(3)},
                {"title": "Over per-query cap", "link": "https://q1.example/third",
                 "published": fresh(4)},
                {"title": "Stale query-one item", "link": "https://q1.example/stale",
                 "published": (now - datetime.timedelta(hours=49)).isoformat()},
                {"title": "Undated query-one item", "link": "https://q1.example/undated"},
            ],
            agent.RSS_FEED_URLS[1]: [
                {"title": "URL duplicate alternate", "link": "https://example.com/story",
                 "published": fresh(1)},
                {"title": "shared story", "link": "https://other.example/duplicate-title",
                 "published": fresh(2)},
                {"title": "News source fallback", "link": "https://news.example/a",
                 "news_source": "News Feed Publisher", "published": fresh(3)},
                {"title": "Hostname fallback", "link": "https://www.host.example/article",
                 "published": fresh(4)},
                {"title": "Over second-query cap", "link": "https://q2.example/fifth",
                 "published": fresh(5)},
            ],
            agent.RSS_FEED_URLS[2]: [
                {"title": "Unknown source fallback", "description": "x" * 3_000,
                 "published": fresh()},
                {"title": "Third query second", "link": "https://q3.example/second",
                 "source": {"title": "Preferred Source"}, "published": fresh(1)},
                {"title": "Over global cap", "link": "https://q3.example/third",
                 "published": fresh(2)},
            ],
        }
        requests = types.SimpleNamespace()
        requested_urls = []

        class Response:
            def __init__(self, content):
                self.content = content

            def raise_for_status(self):
                pass

        def fake_get(url, **_kwargs):
            requested_urls.append(url)
            return Response(url)

        requests.get = fake_get
        feedparser = types.SimpleNamespace(parse=lambda content: types.SimpleNamespace(entries=feeds[content]))
        with (patch.dict(sys.modules, {"requests": requests}),
              patch.object(agent, "feedparser", feedparser),
              patch.object(agent, "extract_article_content", return_value="x" * 3_000)):
            items = agent.get_news_headlines()

        self.assertEqual(requested_urls, list(agent.RSS_FEED_URLS))
        self.assertEqual(len(items), 6)
        self.assertEqual([sum(item["query_topic"] == topic for item in items)
                          for topic in ("valuation_bubble", "capex_infrastructure", "enterprise_adoption_roi")],
                         [2, 2, 2])
        self.assertEqual([item["source"] for item in items], [
            "Publisher Suffix", "q1.example", "News Feed Publisher", "host.example",
            "Preferred Source", "Unknown Source",
        ])
        self.assertNotIn("Over per-query cap", [item["title"] for item in items])
        self.assertNotIn("Stale query-one item", [item["title"] for item in items])
        self.assertNotIn("Undated query-one item", [item["title"] for item in items])
        self.assertEqual(sum(item["title"].lower().startswith("shared story") for item in items), 1)
        self.assertNotIn("Over per-query cap", [item["title"] for item in items])
        self.assertNotIn("Over second-query cap", [item["title"] for item in items])
        self.assertNotIn("Over global cap", [item["title"] for item in items])
        self.assertTrue(all(len(item["content"]) == 2_500 for item in items))

    def test_three_rss_queries_return_bounded_stale_fallback_in_degraded_mode(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        stale_date = (now - datetime.timedelta(hours=49)).isoformat()
        feeds = {
            agent.RSS_FEED_URLS[0]: [
                {"title": "Stale first query", "link": "https://q1.example/stale",
                 "published": stale_date},
                {"title": "Second stale first query", "link": "https://q1.example/older"},
            ],
            agent.RSS_FEED_URLS[1]: [
                {"title": "Undated second query", "link": "https://q2.example/undated"},
                {"title": "Second undated second query", "link": "https://q2.example/also-undated"},
            ],
            agent.RSS_FEED_URLS[2]: [
                {"title": "Stale third query", "link": "https://q3.example/stale",
                 "published": stale_date},
                {"title": "Second stale third query", "link": "https://q3.example/older"},
            ],
        }
        requests = types.SimpleNamespace()

        class Response:
            def __init__(self, content):
                self.content = content

            def raise_for_status(self):
                pass

        requests.get = lambda url, **_kwargs: Response(url)
        feedparser = types.SimpleNamespace(parse=lambda content: types.SimpleNamespace(entries=feeds[content]))
        with (patch.dict(sys.modules, {"requests": requests}),
              patch.object(agent, "feedparser", feedparser),
              patch.object(agent, "extract_article_content", return_value=None)):
            items = agent.get_news_headlines()

        self.assertEqual([item["title"] for item in items], [
            "Stale first query", "Undated second query", "Stale third query",
        ])
        self.assertEqual([item["query_topic"] for item in items], [
            "valuation_bubble", "capex_infrastructure", "enterprise_adoption_roi",
        ])
        quality = agent.data_quality(
            {"NVDA_price": 1, "MSFT_price": 2, "GOOGL_price": 3}, items, now=now)
        self.assertEqual(quality["fetched_articles"], 3)
        self.assertEqual(quality["fresh_articles"], 0)
        self.assertEqual(quality["state"], "degraded")

    def test_import_succeeds_when_optional_packages_are_blocked(self):
        source_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
        script = r'''import sys
blocked = ("openai", "numpy", "feedparser", "trafilatura", "yfinance", "fake_useragent", "power_exponents")
for name in blocked:
    sys.modules[name] = None
sys.path.insert(0, sys.argv[1])
import agent
legacy = {"score": 50, "confidence": "MEDIUM", "thesis": "t", "reasoning": "r",
          "risk_factors": ["risk"], "stabilizing_factors": ["support"],
          "change_explanation": "steady"}
assert agent.validate_opinion(legacy)["score"] == 50
'''
        result = subprocess.run([sys.executable, "-c", script, source_dir], text=True,
                                capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class TestDashboardArtifact(unittest.TestCase):
    def test_dashboard_contract_is_text_safe_and_mixed_schema_aware(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "index.html"), encoding="utf-8") as handle:
            dashboard = handle.read()
        self.assertNotIn("innerHTML", dashboard)
        for marker in ("schema_version", "risk-factors", "stabilizing-factors", "FRESHNESS_HOURS",
                       "parseHistoryPayload", "RECOVERED NON-FINITE VALUES", "Number.isFinite",
                       "data/status_history/index.json", "onClick", "show-current", "pointHitRadius",
                       "HISTORY_WINDOW_SIZE", "history-window-label", "history-older", "history-newer",
                       "power-exponents-panel", "power-exponents-status", "power-instrument",
                       "power-h-chart", "power-alpha-chart", "power-range-30", "power-range-120",
                       "docs/power-exponents.md", "spanGaps:false", "Experimental"):
            self.assertIn(marker, dashboard)
        self.assertNotIn("slice(-30)", dashboard)
        legacy = fixture("legacy_history.json")
        v2 = agent.build_version2_entry({**VALID_OPINION, "_resolved_model": "fixture/v1"},
                                         {"NVDA_price": 1}, [{"title": "<script>"}], legacy)
        self.assertEqual([entry["score"] for entry in legacy + [v2]], [20, 52])


class TestProvenanceAndPersistence(unittest.TestCase):
    def completion(self, model="openai/gpt-5.4", payload=None, finish_reason="stop"):
        completion = MagicMock()
        completion.model = model
        live_payload = payload or {**VALID_OPINION, "market_sentiment": "MIXED"}
        completion.choices[0].message.content = json.dumps(live_payload)
        completion.choices[0].finish_reason = finish_reason
        return completion

    @patch.dict(os.environ, {}, clear=True)
    def test_default_model(self):
        self.assertEqual(agent.requested_model(), agent.DEFAULT_MODEL)

    @patch.dict(os.environ, {agent.MODEL_OVERRIDE_ENV: "test/rollback"}, clear=True)
    def test_configured_model_override(self):
        self.assertEqual(agent.requested_model(), "test/rollback")

    @patch("agent.OpenAI")
    @patch("agent.OPENROUTER_API_KEY", "fake")
    def test_retry_same_model_then_success(self, mock_openai):
        client = MagicMock()
        client.chat.completions.create.side_effect = [RuntimeError("temporary"), self.completion()]
        mock_openai.return_value = client
        result = agent.analyze_market_status({"NVDA_price": 1}, [{"title": "x"}])
        self.assertEqual(result["_resolved_model"], "openai/gpt-5.4")
        calls = client.chat.completions.create.call_args_list
        self.assertEqual([call.kwargs["model"] for call in calls], [agent.DEFAULT_MODEL] * 2)
        self.assertEqual([call.kwargs["max_tokens"] for call in calls], [agent.MAX_OUTPUT_TOKENS] * 2)
        self.assertEqual(mock_openai.call_args.kwargs["timeout"], 60.0)
        self.assertEqual(calls[0].kwargs["messages"][0],
                         {"role": "system", "content": agent.EDITORIAL_SYSTEM_INSTRUCTIONS})
        self.assertEqual(result["market_sentiment"], "MIXED")

    @patch("agent.OpenAI")
    @patch("agent.OPENROUTER_API_KEY", "fake")
    def test_analyze_rejects_non_stop_finish_reasons_and_nonstandard_json(self, mock_openai):
        client = MagicMock()
        mock_openai.return_value = client
        client.chat.completions.create.return_value = self.completion(finish_reason="length")
        with self.assertRaisesRegex(RuntimeError, "did not finish normally"):
            agent.analyze_market_status({"NVDA_price": 1}, [])
        self.assertEqual(client.chat.completions.create.call_count, agent.MODEL_RETRY_ATTEMPTS)

        for constant in ("NaN", "Infinity", "-Infinity"):
            payload = json.dumps({**VALID_OPINION, "market_sentiment": "MIXED"})[:-1]
            payload += ',"invalid_numeric":' + constant + "}"
            completion = self.completion()
            completion.choices[0].message.content = payload
            client.chat.completions.create.return_value = completion
            client.chat.completions.create.reset_mock()
            with self.subTest(constant=constant), self.assertRaisesRegex(RuntimeError, "non-standard JSON constant"):
                agent.analyze_market_status({"NVDA_price": 1}, [])
            self.assertEqual(client.chat.completions.create.call_count, agent.MODEL_RETRY_ATTEMPTS)

    @patch("agent.OpenAI")
    @patch("agent.OPENROUTER_API_KEY", "fake")
    def test_missing_identity_and_exhaustion(self, mock_openai):
        client = MagicMock()
        missing_identity = self.completion()
        missing_identity.model = ""
        client.chat.completions.create.return_value = missing_identity
        mock_openai.return_value = client
        with self.assertRaises(RuntimeError):
            agent.analyze_market_status({}, [])
        self.assertEqual(client.chat.completions.create.call_count, agent.MODEL_RETRY_ATTEMPTS)

    def test_monthly_history_splits_entries_and_indexes_months(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = os.path.join(directory, "status_history")
            entries = [
                {"date": "2026-01-01T00:30:00+02:00", "score": 20},
                {"date": "2026-01-15T12:00:00+00:00", "score": 40},
            ]
            for entry in entries:
                agent.update_history(entry, storage)

            self.assertEqual(sorted(os.listdir(storage)), ["2025-12.json", "2026-01.json", "index.json"])
            with open(os.path.join(storage, "index.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), {"months": ["2025-12", "2026-01"]})
            self.assertEqual(agent.load_history(storage), entries)

    def test_legacy_history_migration_moves_entries_and_removes_source(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = os.path.join(directory, "status_history")
            legacy = os.path.join(directory, "status_history.json")
            history = [
                {"date": "2025-12-31", "score": 20},
                {"date": "2026-01-01T00:00:00+00:00", "score": 40},
            ]
            with open(legacy, "w", encoding="utf-8") as handle:
                json.dump(history, handle)

            self.assertEqual(agent.load_history(storage), history)
            self.assertFalse(os.path.exists(legacy))
            self.assertEqual(agent.load_history(storage), history)
            self.assertEqual(sorted(name for name in os.listdir(storage) if name.endswith(".json")),
                             ["2025-12.json", "2026-01.json", "index.json"])

    def test_invalid_legacy_date_stops_migration_without_removing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = os.path.join(directory, "status_history")
            legacy = os.path.join(directory, "status_history.json")
            with open(legacy, "w", encoding="utf-8") as handle:
                json.dump([{"score": 20}], handle)

            with self.assertRaises(ValueError):
                agent.migrate_legacy_history(storage, legacy)
            self.assertTrue(os.path.isfile(legacy))
            self.assertFalse(os.path.exists(storage))
            self.assertEqual(os.listdir(directory), ["status_history.json"])

    def test_monthly_atomic_replace_failure_preserves_month_file(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = os.path.join(directory, "status_history")
            entry = {"date": "2026-01-01T00:00:00+00:00", "score": 20}
            agent.update_history(entry, storage)
            month_file = os.path.join(storage, "2026-01.json")
            with open(month_file, encoding="utf-8") as handle:
                original = handle.read()

            with (patch("agent.os.replace", side_effect=OSError("replace failed")),
                  self.assertRaises(OSError)):
                agent.update_history({"date": "2026-01-02", "score": 40}, storage)
            with open(month_file, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), original)
            self.assertEqual(sorted(os.listdir(storage)), ["2026-01.json", "index.json"])

    def test_corrupt_history_unchanged_and_atomic_append(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "history.json")
            original = "{corrupt"
            with open(path, "w") as handle:
                handle.write(original)
            with self.assertRaises(json.JSONDecodeError):
                agent.update_history({"score": 1}, path)
            with open(path) as handle:
                self.assertEqual(handle.read(), original)
            with open(path, "w") as handle:
                json.dump([{"score": 1}], handle)
            agent.update_history({"score": 2}, path)
            self.assertEqual([x["score"] for x in agent.load_history(path)], [1, 2])
    def test_nonstandard_json_is_rejected_for_new_entries_and_repaired_on_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "history.json")
            original = '[{"score": 1}]'
            with open(path, "w") as handle:
                handle.write(original)

            with self.assertRaises(ValueError):
                agent.update_history({"score": 2, "metric": float("nan")}, path)
            with open(path) as handle:
                self.assertEqual(handle.read(), original)

            with open(path, "w") as handle:
                handle.write('[{"score": 1, "metric": NaN}]')
            history = agent.load_history(path)
            self.assertIsNone(history[0]["metric"])
            agent.update_history({"score": 2}, path)
            with open(path) as handle:
                repaired = handle.read()
            self.assertNotIn("NaN", repaired)
            self.assertEqual([item["score"] for item in json.loads(repaired)], [1, 2])

    def test_atomic_replace_failure_preserves_destination_and_removes_temp(self):
        with tempfile.TemporaryDirectory() as directory, patch(
                "agent.os.replace", side_effect=OSError("replace failed")):
            path = os.path.join(directory, "history.json")
            original = '[{"score": 1}]'
            with open(path, "w") as handle:
                handle.write(original)
            with self.assertRaises(OSError):
                agent.update_history({"score": 2}, path)
            with open(path) as handle:
                self.assertEqual(handle.read(), original)
            self.assertEqual(os.listdir(directory), ["history.json"])


class TestOptionalPowerExponentIntegration(unittest.TestCase):
    @patch("agent.power_exponents.publish_power_exponents")
    def test_enabled_collection_uses_separate_artifact_and_failure_isolated(self, publish):
        publish.return_value = {"generated_at_utc": "2025-01-01T22:00:00Z"}
        self.assertTrue(agent.update_power_exponent_diagnostics())
        publish.assert_called_once_with(
            agent.POWER_EXPONENTS_PATH, enrich_artifact=agent.add_power_exponent_interpretations)
        publish.side_effect = OSError("test write failure")
        self.assertFalse(agent.update_power_exponent_diagnostics())


if __name__ == "__main__":
    unittest.main()
