"""Offline tests for separate power-exponent explanations (no paid requests)."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import agent
import power_exponents


def artifact():
    return {
        "methodology_version": power_exponents.METHOD_VERSION,
        "settings": {"dfa_window": 252, "hill_window": 1000},
        "instruments": {
            symbol: {"symbol": symbol, "status": "available", "last_session": "2026-11-04",
                     "history_type": "reconstructed", "points": [
                         {"date": "2026-11-04", "h": 0.5, "h_r_squared": 0.979,
                          "alpha": 3.309, "h_delta_1": None,
                          "alpha_sensitivity": {"5%": {"alpha": 3.576}}}]}
            for symbol in power_exponents.INSTRUMENTS
        },
    }


def completion(text="H is near the independent-returns reference. These estimates are not a crash forecast."):
    result = MagicMock()
    result.model = "test/resolved"
    result.choices[0].finish_reason = "stop"
    result.choices[0].message.content = json.dumps({"explanation": text})
    return result


class TestPowerInterpretations(unittest.TestCase):
    @patch.object(agent, "OPENROUTER_API_KEY", "fake")
    @patch.object(agent, "OpenAI")
    def test_four_separate_bounded_requests_and_provenance(self, constructor):
        create = constructor.return_value.chat.completions.create
        create.return_value = completion()
        data = artifact()
        original = copy.deepcopy(data)
        agent.add_power_exponent_interpretations(data)
        self.assertEqual(create.call_count, 4)
        for symbol, call in zip(power_exponents.INSTRUMENTS, create.call_args_list):
            evidence = json.loads(call.kwargs["messages"][1]["content"])
            self.assertEqual(evidence["symbol"], symbol)
            self.assertEqual(evidence["latest"]["alpha"], 3.309)
            self.assertIsNone(evidence["latest"]["h_delta_1"])
            self.assertEqual(evidence["settings"]["hill_window"], 1000)
            self.assertNotIn("score", evidence)
            self.assertNotIn("news", evidence)
            self.assertEqual(call.kwargs["response_format"], {"type": "json_object"})
            item = data["instruments"][symbol]
            self.assertEqual(item["interpretation"]["session_date"], item["last_session"])
            self.assertEqual(item["interpretation"]["resolved_model"], "test/resolved")
            self.assertEqual(item["points"], original["instruments"][symbol]["points"])
        self.assertEqual(constructor.call_args.kwargs["max_retries"], 0)
        self.assertEqual(constructor.call_args.kwargs["timeout"], 60.0)

    @patch.object(agent, "explain_power_exponents")
    def test_failure_isolated_and_missing_stale_inputs_skipped(self, explain):
        data = artifact()
        data["instruments"]["SOXX"]["status"] = "stale"
        data["instruments"]["NVDA"]["points"] = []
        explain.side_effect = [RuntimeError("private provider detail"), {"status": "available", "text": "SPY"}]
        agent.add_power_exponent_interpretations(data)
        self.assertEqual(explain.call_count, 2)
        self.assertEqual(data["instruments"]["QQQ"]["interpretation"], {"status": "unavailable"})
        self.assertNotIn("interpretation", data["instruments"]["SOXX"])
        self.assertEqual(data["instruments"]["NVDA"]["interpretation"]["status"], "unavailable")
        self.assertEqual(data["instruments"]["SPY"]["interpretation"]["text"], "SPY")
        self.assertNotIn("private provider detail", json.dumps(data))

    @patch.object(agent, "OPENROUTER_API_KEY", None)
    @patch.object(agent, "OpenAI")
    def test_no_key_does_not_call_provider(self, constructor):
        data = artifact()
        agent.add_power_exponent_interpretations(data)
        constructor.assert_not_called()
        self.assertTrue(all(i["interpretation"]["status"] == "unavailable"
                            for i in data["instruments"].values()))

    @patch.object(agent, "OPENROUTER_API_KEY", "fake")
    @patch.object(agent, "OpenAI")
    def test_bad_responses_rejected_without_retries(self, constructor):
        data = artifact()
        responses = ["not JSON", "[]", '{}', '{"explanation": " "}',
                     json.dumps({"explanation": "word " * 181})]
        for content in responses:
            result = completion()
            result.choices[0].message.content = content
            constructor.return_value.chat.completions.create.return_value = result
            with self.subTest(content=content[:40]), self.assertRaises(ValueError):
                agent.explain_power_exponents(data, "QQQ", data["instruments"]["QQQ"])
        result = completion()
        result.choices[0].finish_reason = "length"
        constructor.return_value.chat.completions.create.return_value = result
        with self.assertRaises(ValueError):
            agent.explain_power_exponents(data, "QQQ", data["instruments"]["QQQ"])

    @patch.object(agent, "OpenAI")
    def test_no_estimates_no_request(self, constructor):
        data = artifact()
        for item in data["instruments"].values():
            item["points"][-1].update(h=None, alpha=None)
        agent.add_power_exponent_interpretations(data)
        constructor.assert_not_called()

    def test_only_last_30_observations_sent(self):
        data = artifact()
        item = data["instruments"]["QQQ"]
        item["points"] = [dict(item["points"][0], date=str(n)) for n in range(40)]
        with patch.object(agent, "OPENROUTER_API_KEY", "fake"), patch.object(agent, "OpenAI") as constructor:
            constructor.return_value.chat.completions.create.return_value = completion()
            result = agent.explain_power_exponents(data, "QQQ", item)
            evidence = json.loads(constructor.return_value.chat.completions.create.call_args.kwargs["messages"][1]["content"])
        self.assertEqual(len(evidence["recent_points"]), 30)
        self.assertEqual(result["history_start"], "10")

    def test_enrichment_is_included_in_single_atomic_publication(self):
        data = artifact()
        with tempfile.TemporaryDirectory() as directory, patch.object(
                power_exponents, "collect_price_histories", return_value=({}, {})), patch.object(
                power_exponents, "build_artifact", return_value=data):
            path = os.path.join(directory, "power.json")
            def enrich(output):
                output["instruments"]["QQQ"]["interpretation"] = {"text": "Example"}
            power_exponents.publish_power_exponents(path, enrich_artifact=enrich)
            with open(path, encoding="utf-8") as handle:
                published = json.load(handle)
            self.assertEqual(published["instruments"]["QQQ"]["interpretation"]["text"], "Example")

    @unittest.skipUnless(shutil.which("node"), "Node is needed for the DOM contract test")
    def test_frontend_switching_stale_missing_and_text_safety(self):
        dashboard = (Path(__file__).resolve().parents[1] / "index.html").read_text()
        function = dashboard.split("function renderPowerInterpretation(instrument){", 1)[1].split("function renderPowerSelection()", 1)[0]
        script = """
const assert=require('node:assert/strict');
const nodes={};
const document={getElementById:id=>nodes[id]||(nodes[id]={textContent:'',value:'QQQ'})};
const powerInstrumentIsStale=i=>i.status==='stale';
""" + "function renderPowerInterpretation(instrument){" + function + """
const item={symbol:'QQQ',last_session:'2026-11-04',status:'available',interpretation:{status:'available',session_date:'2026-11-04',text:'<script>alert(1)</script>'}};
renderPowerInterpretation(item);
assert.equal(nodes['power-interpretation'].textContent,item.interpretation.text);
assert.match(nodes['power-interpretation-meta'].textContent,/QQQ/);
assert.match(nodes['power-interpretation-meta'].textContent,/Not an interpretation of a selected historical point/);
renderPowerInterpretation({...item,symbol:'SPY',status:'stale'});
assert.match(nodes['power-interpretation-meta'].textContent,/STALE.*SPY/);
renderPowerInterpretation({...item,last_session:'2026-11-05'});
assert.match(nodes['power-interpretation'].textContent,/No interpretation/);
assert.equal(nodes['power-interpretation-meta'].textContent,'');
renderPowerInterpretation(null);
assert.match(nodes['power-interpretation'].textContent,/No interpretation/);
renderPowerInterpretation({symbol:'NVDA'});
assert.match(nodes['power-interpretation'].textContent,/No interpretation/);
"""
        subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
        self.assertLess(dashboard.index('id="power-alpha-chart"'), dashboard.index('id="power-interpretation"'))
        self.assertNotIn("innerHTML", dashboard)


if __name__ == "__main__":
    unittest.main()
