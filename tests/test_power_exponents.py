import datetime as dt
import math
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
import power_exponents as power


class TestDFA(unittest.TestCase):
    def reference_dfa(self, returns, scales, min_segments=4):
        profile = np.cumsum(returns - np.mean(returns))
        scales_used = []
        fluctuations = []
        for tau in scales:
            count = len(profile) // tau
            if count < min_segments:
                continue
            usable = count * tau
            partitions = [profile[:usable].reshape(count, tau)]
            if usable < len(profile):
                partitions.append(profile[-usable:].reshape(count, tau))
            residual_squares = []
            for partition in partitions:
                x = np.arange(tau, dtype=float)
                design = np.column_stack((np.ones(tau), x))
                for segment in partition:
                    coefficients = np.linalg.lstsq(design, segment, rcond=None)[0]
                    residual = segment - design @ coefficients
                    residual_squares.append(float(residual @ residual))
            scales_used.append(tau)
            fluctuations.append(math.sqrt(sum(residual_squares) /
                                          (len(residual_squares) * tau)))
        slope, intercept = np.polyfit(np.log(scales_used), np.log(fluctuations), 1)
        fitted = slope * np.log(scales_used) + intercept
        total = np.sum((np.log(fluctuations) - np.mean(np.log(fluctuations))) ** 2)
        residual = np.sum((np.log(fluctuations) - fitted) ** 2)
        return slope, 1 - residual / total, scales_used

    def test_matches_independent_least_squares_reference_and_counts_partitions(self):
        rng = np.random.default_rng(24)
        returns = rng.normal(0, 0.01, 180)
        scales = [5, 7, 9, 12, 15, 18, 24, 30, 36]
        expected_h, expected_r2, expected_scales = self.reference_dfa(returns, scales)
        result = power.compute_dfa_scaling_law(returns, scales)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["scales"], expected_scales)
        self.assertAlmostEqual(result["h"], expected_h, places=12)
        self.assertAlmostEqual(result["r_squared"], expected_r2, places=12)
        self.assertEqual(result["segment_counts"]["5"], 36)

    def test_default_configuration_matches_documented_scales(self):
        config = power.MonitorConfig()
        self.assertEqual(config.dfa_window, 252)
        self.assertEqual(config.scales, (8, 10, 12, 14, 17, 20, 25, 30, 36, 43, 52, 63))
        self.assertEqual(config.hill_window, 1000)
        self.assertEqual(config.output_points, 120)

    def test_degenerate_and_invalid_dfa_inputs_are_explicit(self):
        result = power.compute_dfa_scaling_law(np.zeros(252))
        self.assertEqual(result["status"], "insufficient_valid_scales")
        self.assertIsNone(result["h"])
        short = power.compute_dfa_scaling_law(np.arange(20.0), [8, 10, 12, 14, 16, 18])
        self.assertIn(short["status"], {"insufficient_valid_scales", "available"})
        with self.assertRaises(ValueError):
            power.compute_dfa_scaling_law([0.0, np.nan, 1.0])
        with self.assertRaises(ValueError):
            power.compute_dfa_scaling_law(np.zeros((2, 3)))


class TestHill(unittest.TestCase):
    def test_uses_next_order_statistic_cutoff(self):
        returns = np.arange(1.0, 13.0)
        result = power.hill_tail_estimate(returns, 0.25, min_tail_observations=2)
        expected = 3 / sum(math.log(value / 9) for value in (10, 11, 12))
        self.assertEqual(result["k"], 3)
        self.assertEqual(result["x_min"], 9)
        self.assertAlmostEqual(result["alpha"], expected, places=12)

    def test_pareto_tail_recovery_and_degenerate_states(self):
        rng = np.random.default_rng(61)
        magnitudes = rng.pareto(3.0, 50000) + 1.0
        signed = magnitudes * rng.choice((-1.0, 1.0), size=magnitudes.size)
        estimate = power.hill_tail_estimate(signed, 0.10)
        self.assertEqual(estimate["status"], "available")
        self.assertEqual(estimate["k"], 5000)
        self.assertAlmostEqual(estimate["alpha"], 3.0, delta=0.12)
        zeros = power.hill_tail_estimate(np.zeros(100), 0.10)
        self.assertEqual(zeros["status"], "insufficient_tail_observations")
        tied = power.hill_tail_estimate(np.ones(100), 0.10)
        self.assertEqual(tied["status"], "degenerate_tail")
        with self.assertRaises(ValueError):
            power.hill_tail_estimate([1.0, float("inf")])


class TestCausalRollingPoints(unittest.TestCase):
    def setUp(self):
        self.config = power.MonitorConfig(
            dfa_window=60, min_scale=6, max_scale=12, num_scales=6,
            min_segments=3, min_valid_scales=4, hill_window=40,
            tail_fraction=0.10, sensitivity_fractions=(0.05, 0.15),
            min_tail_observations=5, baseline_window=6, output_points=120,
        )
        rng = np.random.default_rng(9)
        returns = rng.normal(0.0002, 0.01, 120)
        self.prices = 100 * np.exp(np.cumsum(np.r_[0.0, returns]))
        first = dt.date(2025, 1, 2)
        dates = []
        candidate = first
        while len(dates) < len(self.prices):
            if candidate.weekday() < 5:
                dates.append(candidate.isoformat())
            candidate += dt.timedelta(days=1)
        self.dates = dates

    def test_window_alignment_first_and_last_sessions_are_included(self):
        points = power.compute_indicator_points(self.dates, self.prices, self.config)
        first_h = next(point for point in points if point["h"] is not None)
        first_alpha = next(point for point in points if point["alpha"] is not None)
        self.assertEqual(first_h["date"], self.dates[self.config.dfa_window])
        self.assertEqual(first_h["return_count"], self.config.dfa_window)
        self.assertEqual(first_alpha["date"], self.dates[self.config.hill_window])
        self.assertEqual(first_alpha["return_count"], self.config.hill_window)
        self.assertEqual(points[-1]["date"], self.dates[-1])
        self.assertEqual(points[-1]["return_count"], len(self.prices) - 1)
        self.assertEqual(set(points[-1]["alpha_sensitivity"]), {"5%", "15%"})

    def test_fixed_input_prefix_invariance_including_rolling_fields(self):
        all_points = power.compute_indicator_points(self.dates, self.prices, self.config)
        prefix_size = 108
        prefix_points = power.compute_indicator_points(
            self.dates[:prefix_size], self.prices[:prefix_size], self.config)
        indexed = {point["date"]: point for point in all_points}
        for prefix_point in prefix_points:
            self.assertEqual(prefix_point, indexed[prefix_point["date"]])
        self.assertIsNotNone(all_points[-1]["h_delta_1"])
        self.assertIsNotNone(all_points[-1]["h_delta_5"])
        self.assertIsNotNone(all_points[-1]["h_baseline_z"])
        self.assertEqual(all_points[-1]["h_baseline_n"], self.config.baseline_window)

    def test_invalid_prices_or_dates_are_rejected(self):
        with self.assertRaises(ValueError):
            power.compute_indicator_points(["2025-01-02", "2025-01-03"], [10, 0], self.config)
        with self.assertRaises(ValueError):
            power.compute_indicator_points(["2025-01-03", "2025-01-02"], [10, 11], self.config)
        with self.assertRaises(ValueError):
            power.compute_indicator_points(["2025-01-02", "2025-01-02"], [10, 11], self.config)


class TestProviderCollectionAndPublication(unittest.TestCase):
    def setUp(self):
        self.frames = pd.DataFrame(
            {"Close": [100.0, 101.0, 102.0]},
            index=pd.to_datetime(["2025-07-03", "2025-07-07", "2025-07-08"]),
        )

    def test_provider_kwargs_and_conservative_session_cutoff(self):
        frame = self.frames
        class Ticker:
            def __init__(self):
                self.kwargs = None

            def history(self, **kwargs):
                self.kwargs = kwargs
                return frame

        ticker = Ticker()
        factory = lambda _symbol: ticker
        dates, prices = power.fetch_adjusted_daily_prices(
            "QQQ", now=dt.datetime.fromisoformat("2025-07-07T19:59:00+00:00"),
            ticker_factory=factory)
        self.assertEqual(dates, ["2025-07-03"])
        self.assertEqual(prices, [100.0])
        self.assertEqual(ticker.kwargs, {"period": "5y", "interval": "1d",
                                        "auto_adjust": True, "prepost": False,
                                        "repair": False, "timeout": 20})

    def test_completed_bar_and_both_seasonal_utc_offsets(self):
        summer = self.frames
        winter = pd.DataFrame({"Close": [100.0, 101.0, 102.0]},
                              index=pd.to_datetime(["2025-01-03", "2025-01-06", "2025-01-07"]))
        for frame, symbol, instant, expected in (
                (summer, "QQQ", "2025-07-07T20:15:00+00:00", "2025-07-07"),
                (winter, "SPY", "2025-01-06T21:15:00+00:00", "2025-01-06")):
            class Ticker:
                def history(_self, **_kwargs):
                    return frame
            dates, _prices = power.fetch_adjusted_daily_prices(
                symbol, now=dt.datetime.fromisoformat(instant),
                ticker_factory=lambda _symbol: Ticker())
            self.assertEqual(dates[-1], expected)
        class WinterTicker:
            def history(_self, **_kwargs):
                return winter
        dates, _prices = power.fetch_adjusted_daily_prices(
            "SPY", now=dt.datetime.fromisoformat("2025-01-06T20:59:00+00:00"),
            ticker_factory=lambda _symbol: WinterTicker())
        self.assertEqual(dates, ["2025-01-03"])

    def test_invalid_session_frame_is_rejected_and_batch_failure_is_isolated(self):
        duplicate = pd.DataFrame({"Close": [1.0, 2.0]},
                                 index=pd.to_datetime(["2025-01-02", "2025-01-02"]))
        class DuplicateTicker:
            def history(_self, **_kwargs):
                return duplicate
        with self.assertRaises(ValueError):
            power.fetch_adjusted_daily_prices(
                "QQQ", ticker_factory=lambda _symbol: DuplicateTicker())

        frame = self.frames
        class Ticker:
            def __init__(self, symbol):
                self.symbol = symbol
            def history(self, **_kwargs):
                if self.symbol == "SOXX":
                    raise RuntimeError("feed unavailable")
                return frame
        histories, failures = power.collect_price_histories(
            now=dt.datetime.fromisoformat("2025-07-07T19:59:00+00:00"),
            ticker_factory=lambda symbol: Ticker(symbol))
        self.assertEqual(set(histories), {"QQQ", "NVDA", "SPY"})
        self.assertIn("SOXX", failures)

    def test_artifact_is_bounded_strict_and_preserves_old_failed_symbol(self):
        rng = np.random.default_rng(7)
        returns = rng.normal(0.0001, 0.01, 100)
        prices = 80 * np.exp(np.cumsum(np.r_[0.0, returns]))
        dates = []
        day = dt.date(2025, 1, 2)
        while len(dates) < len(prices):
            if day.weekday() < 5:
                dates.append(day.isoformat())
            day += dt.timedelta(days=1)
        config = power.MonitorConfig(
            dfa_window=40, min_scale=5, max_scale=10, num_scales=6,
            min_segments=3, min_valid_scales=4, hill_window=30,
            min_tail_observations=5, baseline_window=4, output_points=8,
        )
        old_entry = {"symbol": "SOXX", "status": "available",
                     "retrieved_at_utc": "2025-04-01T22:00:00Z",
                     "last_session": "2025-04-01", "points": [{"date": "2025-04-01"}]}
        previous = {"instruments": {"SOXX": old_entry}}
        invalid_dates = (dates[1], dates[0])
        artifact = power.build_artifact(
            {"QQQ": (dates, prices), "NVDA": (invalid_dates, [100.0, 101.0])},
            now=dt.datetime.fromisoformat("2025-05-28T22:00:00+00:00"),
            failures={"SOXX": "mock timeout"}, previous=previous, config=config,
            provider_version="test-version")
        self.assertEqual(len(artifact["instruments"]["QQQ"]["points"]), 8)
        self.assertEqual(artifact["instruments"]["QQQ"]["history_type"], "reconstructed")
        self.assertEqual(artifact["instruments"]["QQQ"]["source"], power.SOURCE_NAME)
        self.assertEqual(artifact["instruments"]["SOXX"]["status"], "stale")
        self.assertEqual(artifact["instruments"]["SOXX"]["retrieved_at_utc"],
                         "2025-04-01T22:00:00Z")
        self.assertEqual(artifact["instruments"]["NVDA"]["status"], "unavailable")
        self.assertEqual(artifact["provider"]["client_version"], "test-version")
        serialized = json.dumps(artifact, allow_nan=False)
        self.assertNotIn("raw_prices", serialized)
        self.assertNotIn("100.0", serialized)

    def test_artifact_builder_also_excludes_incomplete_and_future_sessions(self):
        config = power.MonitorConfig(output_points=5)
        history = {"QQQ": (["2025-07-02", "2025-07-03", "2025-07-07", "2025-07-08"],
                            [99.0, 100.0, 101.0, 102.0])}
        artifact = power.build_artifact(
            history, now=dt.datetime.fromisoformat("2025-07-07T19:59:00+00:00"),
            config=config)
        instrument = artifact["instruments"]["QQQ"]
        self.assertEqual(instrument["last_session"], "2025-07-03")
        self.assertEqual(instrument["points"][-1]["date"], "2025-07-03")

    def test_weekends_are_not_added_as_return_observations(self):
        points = power.compute_indicator_points(
            ["2025-01-03", "2025-01-06"], [100.0, 101.0], power.MonitorConfig())
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["date"], "2025-01-06")
        self.assertEqual(points[0]["return_count"], 1)

    def test_stale_and_suspicious_gap_are_distinguished_from_new_data(self):
        config = power.MonitorConfig(output_points=5)
        history = {"QQQ": (["2025-01-06", "2025-01-15"], [100.0, 101.0])}
        artifact = power.build_artifact(
            history, now=dt.datetime.fromisoformat("2025-02-01T22:00:00+00:00"),
            config=config)
        instrument = artifact["instruments"]["QQQ"]
        self.assertEqual(instrument["status"], "stale")
        self.assertEqual(instrument["last_session"], "2025-01-15")
        self.assertIn("gap over", instrument["gap_warning"])
        self.assertEqual(instrument["points"][-1]["date"], "2025-01-15")
        self.assertIsNone(instrument["points"][-1]["h"])
        self.assertIsNone(instrument["points"][-1]["alpha"])

    def test_publication_enforces_the_120_point_cap_even_for_larger_settings(self):
        rng = np.random.default_rng(11)
        prices = 100 * np.exp(np.cumsum(np.r_[0.0, rng.normal(0, 0.01, 170)]))
        dates = []
        day = dt.date(2024, 8, 1)
        while len(dates) < len(prices):
            if day.weekday() < 5:
                dates.append(day.isoformat())
            day += dt.timedelta(days=1)
        config = power.MonitorConfig(
            dfa_window=40, min_scale=5, max_scale=10, num_scales=6,
            min_segments=3, min_valid_scales=4, hill_window=30,
            min_tail_observations=5, baseline_window=4, output_points=200,
        )
        artifact = power.build_artifact(
            {"QQQ": (dates, prices)},
            now=dt.datetime.fromisoformat("2025-05-28T22:00:00+00:00"),
            config=config)
        self.assertEqual(len(artifact["instruments"]["QQQ"]["points"]), 120)

    def test_failed_or_invalid_history_retains_only_bounded_prior_points(self):
        old_points = [{"date": "2025-01-01"} for _ in range(150)]
        previous = {"instruments": {"QQQ": {
            "points": old_points, "last_session": "2025-01-01",
            "retrieved_at_utc": "2025-01-01T22:00:00Z"}}}
        for histories in ({}, {"QQQ": (["2025-01-01", "2025-01-02"], [0.0, 1.0])}):
            with self.subTest(histories=histories):
                artifact = power.build_artifact(histories, previous=previous)
                retained = artifact["instruments"]["QQQ"]
                self.assertEqual(len(retained["points"]), 120)
                self.assertEqual(retained["status"], "stale")
                self.assertEqual(retained["retrieved_at_utc"], "2025-01-01T22:00:00Z")
                self.assertEqual(len(previous["instruments"]["QQQ"]["points"]), 150)


    def test_atomic_replace_failure_preserves_file_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "power_exponents.json")
            original = '{"old":true}'
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(original)
            with patch("power_exponents.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    power.write_artifact_atomic(path, {"finite": 1.0})
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), original)
            self.assertEqual(os.listdir(directory), ["power_exponents.json"])

    def test_strict_json_rejects_nan_without_replacing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "power_exponents.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"old":true}')
            with self.assertRaises(ValueError):
                power.write_artifact_atomic(path, {"bad": float("nan")})
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), '{"old":true}')
            self.assertEqual(os.listdir(directory), ["power_exponents.json"])


class TestPowerDashboardDomStub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("Node.js is required for the dashboard DOM/Chart stub test")
        with open(os.path.join(os.path.dirname(__file__), "..", "index.html"),
                  encoding="utf-8") as handle:
            html = handle.read()
        scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.DOTALL)
        if len(scripts) != 1:
            raise AssertionError("expected one inline dashboard script")
        cls.dashboard_script = scripts[0]

    def run_dashboard(self, artifact, fail_diagnostics=False):
        history = [{"date": f"2025-01-{(index % 28) + 1:02d}T22:00:00Z",
                    "score": index % 100, "status": "GREEN", "reasoning": "fixture",
                    "metrics": {}} for index in range(40)]
        artifact_json = json.dumps(artifact, separators=(",", ":")) if artifact else "null"
        history_json = json.dumps(history, separators=(",", ":"))
        harness = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const artifact = JSON.parse(__ARTIFACT__);
const failDiagnostics = __FAIL_DIAGNOSTICS__;
const editorialHistory = JSON.parse(__HISTORY__);
const elements = new Map();
function element(id=''){
  const listeners={};
  const node={id,textContent:'',className:'',disabled:false,value:id==='power-instrument'?'QQQ':'',children:[],attributes:{},listeners,
    addEventListener(name,fn){listeners[name]=fn;},dispatch(name){if(listeners[name])listeners[name]({target:this});},
    setAttribute(name,value){this.attributes[name]=value;},appendChild(child){this.children.push(child);return child;},
    replaceChildren(...children){this.children=children;},getContext(){return{};},
    classList:{add(...values){node.className=[node.className,...values].filter(Boolean).join(' ');}}};
  return node;
}
const document={getElementById(id){if(!elements.has(id))elements.set(id,element(id));return elements.get(id);},createElement(){return element();}};
const calls=[];
async function fetch(url){
  calls.push(url);
  if(url==='data/power_exponents.json')return failDiagnostics?{ok:false,status:503}:artifact?{ok:true,status:200,json:async()=>artifact}:{ok:false,status:404};
  if(url==='data/status_history/index.json')return{ok:true,status:200,json:async()=>({months:['2025-01']})};
  if(url==='data/status_history/2025-01.json')return{ok:true,status:200,text:async()=>JSON.stringify(editorialHistory)};
  throw new Error('unexpected fetch '+url);
}
class Chart{
  static instances=[];
  constructor(_ctx,config){this.data=config.data;this.options=config.options;this.config=config;this.destroyed=false;Chart.instances.push(this);}
  update(){this.updated=true;}
  destroy(){this.destroyed=true;}
}
const context={document,fetch,Chart,console,Date,Number,Math,String,Object,Array,JSON,Promise,setTimeout,clearTimeout};
vm.runInNewContext(__SCRIPT__,context);
(async()=>{
  await new Promise(resolve=>setTimeout(resolve,0));
  assert.equal(elements.get('status-indicator').textContent,'GREEN');
  assert.ok(calls.includes('data/status_history/index.json'));
  assert.ok(calls.includes('data/power_exponents.json'));
  if(artifact){
    assert.equal(Chart.instances.length,3);
    assert.equal(elements.get('power-exponents-status').textContent.includes('Data through'),true);
    const h=Chart.instances.find(chart=>chart.config.data.datasets[0].label==='DFA-1 H');
    const alpha=Chart.instances.find(chart=>chart.config.data.datasets[0].label==='Hill α');
    assert.ok(elements.get('power-tail-count').textContent.includes('Hill window n=1000'));
    assert.ok(h.options.plugins.tooltip.callbacks.label({dataIndex:29,datasetIndex:0}).includes('DFA window n: 252'));
    const originalSession=artifact.instruments.QQQ.last_session;
    artifact.instruments.QQQ.last_session='2000-01-01';
    elements.get('power-instrument').dispatch('change');
    assert.ok(elements.get('power-exponents-status').textContent.startsWith('STALE:'));
    artifact.instruments.QQQ.last_session=originalSession;
    assert.equal(h.data.datasets[0].data.length,30);
    assert.equal(alpha.data.datasets[0].data.length,30);
    assert.equal(h.config.options.spanGaps,false);
    assert.equal(h.config.options.scales.y.max,undefined);
    assert.ok(alpha.data.datasets[0].data.some(value=>value===null));
    assert.ok(h.data.datasets[1].data.every(value=>value===0.5));
    elements.get('power-range-120').dispatch('click');
    assert.equal(h.data.datasets[0].data.length,120);
    assert.equal(elements.get('power-range-120').attributes['aria-pressed'],'true');
    elements.get('power-instrument').value='SOXX';
    elements.get('power-instrument').dispatch('change');
    assert.ok(elements.get('power-exponents-status').textContent.includes('STALE'));
    elements.get('power-instrument').value='NVDA';
    elements.get('power-instrument').dispatch('change');
    assert.ok(elements.get('power-exponents-status').textContent.includes('UNAVAILABLE'));
    assert.equal(elements.get('power-range-30').disabled,true);
    const risk=Chart.instances.find(chart=>chart.config.data.datasets[0].label==='Bubble Risk Score');
    const oldWindow=risk.data.labels.slice();
    elements.get('history-older').dispatch('click');
    assert.notDeepEqual(risk.data.labels,oldWindow);
    risk.options.onClick({},[{index:0}]);
    assert.ok(elements.get('status-title').textContent.startsWith('Historical'));
    const olderLabels=risk.data.labels.slice();
    elements.get('history-newer').dispatch('click');
    assert.notDeepEqual(risk.data.labels,olderLabels);
    elements.get('show-current').dispatch('click');
    assert.equal(elements.get('status-title').textContent,'Current Market Status');
    assert.ok(risk.data.labels[risk.data.labels.length-1].includes('Jan'));
  }else{
    assert.equal(Chart.instances.length,1);
    if(failDiagnostics)assert.ok(elements.get('power-exponents-status').textContent.includes('unavailable'));
    else assert.ok(elements.get('power-exponents-status').textContent.includes('not published'));
    assert.equal(elements.get('power-instrument').disabled,true);
    assert.equal(elements.get('power-range-30').disabled,true);
    elements.get('history-older').dispatch('click');
    assert.ok(Chart.instances[0].data.labels.length>0);
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
""".replace("__ARTIFACT__", json.dumps(artifact_json)).replace(
            "__HISTORY__", json.dumps(history_json)).replace(
                "__FAIL_DIAGNOSTICS__", "true" if fail_diagnostics else "false").replace(
                    "__SCRIPT__", json.dumps(self.dashboard_script))
        result = subprocess.run(["node", "-e", harness], text=True,
                                capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_populated_history_partial_values_and_editorial_navigation(self):
        point = {"date": "2026-05-20", "h": 0.57, "h_r_squared": 0.96,
                 "alpha": None, "alpha_k": 100, "alpha_x_min": 0.012,
                 "alpha_positive_count": 950, "alpha_sensitivity": {
                     "5%": {"alpha": 2.8, "k": 50, "x_min": 0.02},
                     "15%": {"alpha": 3.1, "k": 150, "x_min": 0.01}},
                 "h_delta_1": 0.01, "h_delta_5": -0.02,
                 "h_baseline_z": 1.1, "h_baseline_n": 30,
                 "h_scales": [8, 10, 12, 14, 17, 20],
                 "return_count": 1258}
        points = []
        for index in range(130):
            item = dict(point)
            item["date"] = (dt.date(2026, 1, 1) + dt.timedelta(days=index)).isoformat()
            item["h"] = None if index == 3 else point["h"]
            points.append(item)
        artifact = {"artifact_version": 1,
                    "settings": {"dfa_window": 252, "min_scale": 8,
                                 "max_scale": 63, "hill_window": 1000,
                                 "tail_fraction": 0.1},
                    "provider": {"name": power.SOURCE_NAME},
                    "instruments": {
                        "QQQ": {"status": "available", "last_session": "2026-05-20",
                                "source": power.SOURCE_NAME,
                                "price_adjustment": power.ADJUSTMENT_POLICY,
                                "retrieved_at_utc": "2026-05-20T22:00:00Z",
                                "history_type": "reconstructed", "points": points},
                        "SOXX": {"status": "stale", "status_message": "Feed timeout",
                                 "last_session": "2026-05-18", "points": [point]},
                        "NVDA": {"status": "unavailable", "status_message": "No feed",
                                 "points": []},
                        "SPY": {"status": "unavailable", "points": []}}}
        self.run_dashboard(artifact)

    def test_missing_diagnostic_artifact_does_not_break_editorial_history(self):
        self.run_dashboard(None)

    def test_feed_error_does_not_break_editorial_history(self):
        self.run_dashboard(None, fail_diagnostics=True)


if __name__ == "__main__":
    unittest.main()
