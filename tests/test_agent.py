import datetime
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
import agent


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
    def completion(self, model="openai/gpt-5.4"):
        completion = MagicMock()
        completion.model = model
        completion.choices[0].message.content = json.dumps(VALID_OPINION)
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

            with patch("agent.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
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
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "history.json")
            original = '[{"score": 1}]'
            with open(path, "w") as handle:
                handle.write(original)
            with patch("agent.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    agent.update_history({"score": 2}, path)
            with open(path) as handle:
                self.assertEqual(handle.read(), original)
            self.assertEqual(os.listdir(directory), ["history.json"])


class TestOptionalPowerExponentIntegration(unittest.TestCase):
    @patch.dict(os.environ, {agent.POWER_EXPONENTS_ENABLED_ENV: "0"}, clear=False)
    @patch("agent.power_exponents.publish_power_exponents")
    def test_disabled_collection_makes_no_provider_call(self, publish):
        self.assertFalse(agent.update_power_exponent_diagnostics())
        publish.assert_not_called()

    @patch.dict(os.environ, {agent.POWER_EXPONENTS_ENABLED_ENV: "1"}, clear=False)
    @patch("agent.power_exponents.publish_power_exponents")
    def test_enabled_collection_uses_separate_artifact_and_failure_isolated(self, publish):
        publish.return_value = {"generated_at_utc": "2025-01-01T22:00:00Z"}
        self.assertTrue(agent.update_power_exponent_diagnostics())
        publish.assert_called_once_with(agent.POWER_EXPONENTS_PATH)
        publish.side_effect = OSError("test write failure")
        self.assertFalse(agent.update_power_exponent_diagnostics())


if __name__ == "__main__":
    unittest.main()
