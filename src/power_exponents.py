"""Experimental daily-return scaling and tail diagnostics.

The estimators are descriptive. They do not detect a market crash or prove
long-range dependence, trader synchronization, or Pareto tails.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass
from zoneinfo import ZoneInfo

import numpy as np

METHOD_VERSION = "power-exponents-dfa1-hill-v2"
ARTIFACT_VERSION = 1
SOURCE_NAME = "Yahoo Finance via yfinance (unofficial provider client)"
ADJUSTMENT_POLICY = "yfinance history(auto_adjust=True, interval='1d', prepost=False, repair=False)"
INSTRUMENTS = ("QQQ", "SOXX", "NVDA", "SPY")
NEW_YORK = ZoneInfo("America/New_York")
MAX_PUBLISHED_POINTS = 120


@dataclass(frozen=True)
class MonitorConfig:
    dfa_window: int = 252
    min_scale: int = 8
    max_scale: int = 63
    num_scales: int = 12
    min_segments: int = 4
    min_valid_scales: int = 6
    hill_window: int = 1000
    tail_fraction: float = 0.10
    sensitivity_fractions: tuple[float, ...] = (0.05, 0.15)
    min_tail_observations: int = 50
    baseline_window: int = 30
    output_points: int = MAX_PUBLISHED_POINTS
    max_session_age_days: int = 7
    gap_warning_days: int = 7

    def __post_init__(self):
        if self.dfa_window <= 0 or self.hill_window <= 0:
            raise ValueError("return windows must be positive")
        if self.min_scale < 3 or self.max_scale < self.min_scale:
            raise ValueError("DFA scales must satisfy 3 <= min_scale <= max_scale")
        if self.num_scales < self.min_valid_scales or self.min_valid_scales < 2:
            raise ValueError("DFA requires enough configured and valid scales")
        if self.min_segments < 2:
            raise ValueError("min_segments must be at least 2")
        if not 0 < self.tail_fraction < 1:
            raise ValueError("tail_fraction must be between zero and one")
        if any(not 0 < value < 1 for value in self.sensitivity_fractions):
            raise ValueError("tail sensitivity fractions must be between zero and one")
        if self.min_tail_observations < 2 or self.baseline_window < 2:
            raise ValueError("tail and baseline minimums must be at least two")
        if self.output_points < 1:
            raise ValueError("output_points must be positive")

    @property
    def scales(self) -> tuple[int, ...]:
        values = np.rint(np.logspace(
            np.log10(self.min_scale), np.log10(self.max_scale),
            num=self.num_scales)).astype(int)
        values[0], values[-1] = self.min_scale, self.max_scale
        return tuple(int(value) for value in np.unique(values))


def _finite_vector(values, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} contains a non-finite value")
    return array


def _segment_residual_squares(segment: np.ndarray) -> float:
    """Return DFA-1 residual sum of squares for one (rows x columns) block."""
    width = segment.shape[1]
    x = np.arange(width, dtype=np.float64)
    x_centered = x - x.mean()
    x_var = float(np.dot(x_centered, x_centered))
    if x_var <= 0:
        return 0.0
    y_centered = segment - segment.mean(axis=1, keepdims=True)
    slopes = (y_centered @ x_centered) / x_var
    residual = y_centered - slopes[:, None] * x_centered[None, :]
    return float(np.sum(residual * residual))


def compute_dfa_scaling_law(
    returns,
    scales: tuple[int, ...] | list[int] | None = None,
    *,
    min_segments: int = 4,
    min_valid_scales: int = 6,
) -> dict:
    """Compute a finite-range DFA-1 slope and log-log R².

    Returns a JSON-ready mapping. The forward and reverse-origin partitions are
    combined as boxes when their origins differ; they overlap with each other
    but each partition is nonoverlapping internally. The returned R² describes
    only the chosen finite set of scales.
    """
    values = _finite_vector(returns, "returns")
    if min_segments < 2 or min_valid_scales < 2:
        raise ValueError("DFA minimum segment/scale counts are invalid")
    if values.size < 1:
        return {"h": None, "r_squared": None, "status": "insufficient_returns",
                "scales": [], "segment_counts": {}, "h_short": None,
                "h_long": None}
    if scales is None:
        config_scales = MonitorConfig().scales
    else:
        config_scales = tuple(sorted(set(int(scale) for scale in scales)))
    if any(scale < 3 for scale in config_scales):
        raise ValueError("DFA scales must be at least 3")

    profile = np.cumsum(values - float(values.mean()))
    usable_scales: list[int] = []
    fluctuations: list[float] = []
    segment_counts: dict[str, int] = {}
    n_total = values.size

    for tau in config_scales:
        n_segments = n_total // tau
        if n_segments < min_segments:
            continue
        block_size = n_segments * tau
        forward = profile[:block_size].reshape(n_segments, tau)
        residual_ss = _segment_residual_squares(forward)
        count = n_segments
        # A second partition starts at the right edge. If the first partition
        # already covers the full profile, it is the same partition and is not
        # counted twice.
        if block_size < n_total:
            backward = profile[n_total - block_size:].reshape(n_segments, tau)
            residual_ss += _segment_residual_squares(backward)
            count += n_segments
        fluctuation = math.sqrt(residual_ss / (count * tau)) if count else 0.0
        if not math.isfinite(fluctuation) or fluctuation <= 0:
            continue
        usable_scales.append(tau)
        fluctuations.append(fluctuation)
        segment_counts[str(tau)] = count

    scale_values = np.asarray(usable_scales, dtype=np.float64)
    fluctuation_values = np.asarray(fluctuations, dtype=np.float64)

    def subscale_slope(mask) -> float | None:
        sub_scales = scale_values[mask]
        sub_flucts = fluctuation_values[mask]
        if sub_scales.size < 3:
            return None
        slope = float(np.polyfit(np.log(sub_scales), np.log(sub_flucts), 1)[0])
        return slope if math.isfinite(slope) else None

    h_short = subscale_slope(scale_values <= 20)
    h_long = subscale_slope(scale_values > 20)

    if len(usable_scales) < min_valid_scales:
        return {"h": None, "r_squared": None, "status": "insufficient_valid_scales",
                "scales": usable_scales, "segment_counts": segment_counts,
                "h_short": h_short, "h_long": h_long}

    log_scales = np.log(np.asarray(usable_scales, dtype=np.float64))
    log_fluctuations = np.log(np.asarray(fluctuations, dtype=np.float64))
    centered_x = log_scales - log_scales.mean()
    total_x_ss = float(np.dot(centered_x, centered_x))
    total_y_ss = float(np.dot(log_fluctuations - log_fluctuations.mean(),
                              log_fluctuations - log_fluctuations.mean()))
    if total_x_ss <= 0 or total_y_ss <= 0:
        return {"h": None, "r_squared": None, "status": "degenerate_fit",
                "scales": usable_scales, "segment_counts": segment_counts,
                "h_short": h_short, "h_long": h_long}
    h = float(np.dot(centered_x, log_fluctuations - log_fluctuations.mean()) / total_x_ss)
    intercept = float(log_fluctuations.mean() - h * log_scales.mean())
    fitted = intercept + h * log_scales
    residual_ss = float(np.sum((log_fluctuations - fitted) ** 2))
    r_squared = float(1.0 - residual_ss / total_y_ss)
    if not math.isfinite(h) or not math.isfinite(r_squared):
        return {"h": None, "r_squared": None, "status": "non_finite_fit",
                "scales": usable_scales, "segment_counts": segment_counts,
                "h_short": h_short, "h_long": h_long}
    return {"h": h, "r_squared": r_squared, "status": "available",
            "scales": usable_scales, "segment_counts": segment_counts,
            "h_short": h_short, "h_long": h_long}


def hill_tail_estimate(
    returns,
    tail_fraction: float = 0.10,
    *,
    min_tail_observations: int = 50,
) -> dict:
    """Estimate the Pareto survival exponent using the standard Hill order statistic.

    The top k positive absolute returns are compared with the next lower order
    statistic X_(k+1): alpha = k / sum(log(X_(i) / X_(k+1))). This estimate is
    meaningful only if a Pareto-like tail and a defensible threshold apply.
    """
    values = _finite_vector(returns, "returns")
    if not 0 < tail_fraction < 1:
        raise ValueError("tail_fraction must be between zero and one")
    if min_tail_observations < 2:
        raise ValueError("min_tail_observations must be at least two")
    positive = np.sort(np.abs(values[values != 0.0]))
    positive_count = int(positive.size)
    proposed_k = max(min_tail_observations, int(positive_count * tail_fraction))
    if positive_count <= min_tail_observations or proposed_k >= positive_count:
        return {"alpha": None, "alpha_se": None, "k": None, "x_min": None,
                "positive_count": positive_count, "status": "insufficient_tail_observations"}
    k = proposed_k
    threshold = float(positive[-k - 1])
    exceedances = positive[-k:]
    if threshold <= 0 or not math.isfinite(threshold):
        return {"alpha": None, "alpha_se": None, "k": k, "x_min": threshold,
                "positive_count": positive_count, "status": "invalid_threshold"}
    log_excess = np.log(exceedances / threshold)
    denominator = float(np.sum(log_excess))
    if not math.isfinite(denominator) or denominator <= 0:
        return {"alpha": None, "alpha_se": None, "k": k, "x_min": threshold,
                "positive_count": positive_count, "status": "degenerate_tail"}
    alpha = float(k / denominator)
    if not math.isfinite(alpha):
        return {"alpha": None, "alpha_se": None, "k": k, "x_min": threshold,
                "positive_count": positive_count, "status": "non_finite_estimate"}
    alpha_se = float(alpha / math.sqrt(k))
    if not math.isfinite(alpha_se):
        alpha_se = None
    return {"alpha": alpha, "alpha_se": alpha_se, "k": k, "x_min": threshold,
            "positive_count": positive_count, "status": "available"}


def _session_label(value) -> str:
    """Use the vendor's daily session label without timezone date shifting."""
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if hasattr(value, "date"):
        date_value = value.date()
        if isinstance(date_value, dt.date):
            return date_value.isoformat()
    try:
        return np.datetime_as_string(np.datetime64(value, "D"), unit="D")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"invalid session date {value!r}") from exc


def _iso_utc(value: dt.datetime | None = None) -> str:
    value = value or dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _return_point(return_values: np.ndarray, dates: list[str], end: int,
                  config: MonitorConfig) -> dict:
    point = {"date": dates[end], "h": None, "h_r_squared": None,
             "h_status": "insufficient_returns", "h_scales": [],
             "h_segment_counts": {}, "h_short": None, "h_long": None,
             "h_abs": None, "h_abs_r_squared": None, "alpha": None,
             "alpha_se": None, "alpha_status": "insufficient_returns",
             "alpha_k": None, "alpha_x_min": None,
             "alpha_positive_count": 0, "alpha_sensitivity": {},
             "h_delta_1": None, "h_delta_5": None, "h_baseline_z": None,
             "h_baseline_n": 0, "return_count": end + 1}

    count = end + 1
    if count >= config.dfa_window:
        dfa = compute_dfa_scaling_law(
            return_values[count - config.dfa_window:count], config.scales,
            min_segments=config.min_segments,
            min_valid_scales=config.min_valid_scales,
        )
        point.update({"h": dfa["h"], "h_r_squared": dfa["r_squared"],
                      "h_status": dfa["status"], "h_scales": dfa["scales"],
                      "h_segment_counts": dfa["segment_counts"],
                      "h_short": dfa["h_short"], "h_long": dfa["h_long"]})
        dfa_abs = compute_dfa_scaling_law(
            np.abs(return_values[count - config.dfa_window:count]), config.scales,
            min_segments=config.min_segments,
            min_valid_scales=config.min_valid_scales,
        )
        point.update({"h_abs": dfa_abs["h"],
                      "h_abs_r_squared": dfa_abs["r_squared"]})
    if count >= config.hill_window:
        tail_window = return_values[count - config.hill_window:count]
        main = hill_tail_estimate(tail_window, config.tail_fraction,
                                  min_tail_observations=config.min_tail_observations)
        point.update({"alpha": main["alpha"], "alpha_se": main["alpha_se"],
                      "alpha_status": main["status"],
                      "alpha_k": main["k"], "alpha_x_min": main["x_min"],
                      "alpha_positive_count": main["positive_count"]})
        fractions = (0.05, *config.sensitivity_fractions, 0.15)
        # Preserve order while excluding duplicate fractions/the main estimate.
        fractions = tuple(dict.fromkeys(f for f in fractions
                                        if f != config.tail_fraction))
        point["alpha_sensitivity"] = {
            f"{fraction:.0%}": hill_tail_estimate(
                tail_window, fraction,
                min_tail_observations=config.min_tail_observations,
            ) for fraction in fractions
        }
    return point


def compute_indicator_points(session_dates, prices, config: MonitorConfig = MonitorConfig(),
                             *, output_points: int | None = None) -> list[dict]:
    """Compute causal observations from ordered positive adjusted daily closes."""
    labels = [_session_label(value) for value in session_dates]
    price_values = _finite_vector(prices, "prices")
    if len(labels) != price_values.size:
        raise ValueError("session date and price counts do not match")
    if any(not value > 0 for value in price_values):
        raise ValueError("prices must be positive")
    parsed_dates = [dt.date.fromisoformat(value) for value in labels]
    if any(right <= left for left, right in zip(parsed_dates, parsed_dates[1:])):
        raise ValueError("session dates must be unique and strictly increasing")
    if len(labels) < 2:
        return []
    returns = np.diff(np.log(price_values))
    return_dates = labels[1:]
    all_points: list[dict] = []
    h_history: list[tuple[int, float]] = []
    for end in range(returns.size):
        point = _return_point(returns, return_dates, end, config)
        h = point["h"]
        if h is not None:
            if h_history and h_history[-1][0] == end - 1:
                point["h_delta_1"] = float(h - h_history[-1][1])
            if len(h_history) >= 5 and h_history[-5][0] == end - 5:
                point["h_delta_5"] = float(h - h_history[-5][1])
            previous = h_history[-config.baseline_window:]
            has_consecutive_baseline = (
                len(previous) == config.baseline_window
                and previous[0][0] == end - config.baseline_window
                and previous[-1][0] == end - 1
            )
            if has_consecutive_baseline:
                baseline_values = [value for _index, value in previous]
                baseline_std = float(np.std(baseline_values, ddof=1))
                if baseline_std > 0 and math.isfinite(baseline_std):
                    point["h_baseline_z"] = float(
                        (h - float(np.mean(baseline_values))) / baseline_std)
                point["h_baseline_n"] = config.baseline_window
            h_history.append((end, h))
        all_points.append(point)
    limit = config.output_points if output_points is None else output_points
    if limit < 1:
        raise ValueError("output_points must be positive")
    return all_points[-limit:]


def _session_gap_warning(session_dates: list[str], gap_warning_days: int) -> str | None:
    for left, right in zip(session_dates, session_dates[1:]):
        if (dt.date.fromisoformat(right) - dt.date.fromisoformat(left)).days > gap_warning_days:
            return f"Input history has a gap over {gap_warning_days} calendar days: {left} to {right}."
    return None


def _unavailable_instrument(symbol: str, reason: str, now: dt.datetime) -> dict:
    return {"symbol": symbol, "status": "unavailable", "status_message": reason[:240],
            "source": SOURCE_NAME, "price_adjustment": ADJUSTMENT_POLICY,
            "history_type": "reconstructed", "retrieved_at_utc": None,
            "attempted_at_utc": _iso_utc(now),
            "last_session": None, "session_age_days": None, "gap_warning": None,
            "points": []}


def build_artifact(price_histories: dict[str, tuple[list, list]], *, now: dt.datetime | None = None,
                   failures: dict[str, str] | None = None,
                   previous: dict | None = None,
                   provider_version: str | None = None,
                   config: MonitorConfig = MonitorConfig()) -> dict:
    """Build independent instrument histories, retaining truthful stale history on failures."""
    now = now or dt.datetime.now(dt.timezone.utc)
    generated_at = _iso_utc(now)
    failures = failures or {}
    previous_instruments = (previous.get("instruments", {})
                            if isinstance(previous, dict) and isinstance(previous.get("instruments"), dict)
                            else {})
    settings = asdict(config)
    settings["scales"] = list(config.scales)
    instruments: dict[str, dict] = {}
    for symbol in INSTRUMENTS:
        if symbol not in price_histories:
            reason = failures.get(symbol, "No usable price history was returned.")
            old = previous_instruments.get(symbol)
            if isinstance(old, dict) and isinstance(old.get("points"), list):
                retained = copy.deepcopy(old)
                retained["points"] = retained["points"][-min(config.output_points, MAX_PUBLISHED_POINTS):]
                retained["status"] = "stale"
                retained["status_message"] = reason[:240]
                retained["stale_since_utc"] = generated_at
                instruments[symbol] = retained
            else:
                instruments[symbol] = _unavailable_instrument(symbol, reason, now)
            continue
        try:
            raw_dates, raw_prices = price_histories[symbol]
            labels = [_session_label(value) for value in raw_dates]
            values = _finite_vector(raw_prices, f"{symbol} prices")
            if len(labels) != values.size or len(labels) < 2:
                raise ValueError("insufficient daily prices")
            if any(not value > 0 for value in values):
                raise ValueError("daily closes must be positive")
            parsed = [dt.date.fromisoformat(value) for value in labels]
            if any(right <= left for left, right in zip(parsed, parsed[1:])):
                raise ValueError("daily session dates are duplicated or out of order")
            local_now = now.astimezone(NEW_YORK)
            local_date = local_now.date()
            before_daily_bar_complete = local_now.time() < dt.time(16, 15)
            completed = [(label, price) for label, price in zip(labels, values)
                         if dt.date.fromisoformat(label) < local_date or
                         (dt.date.fromisoformat(label) == local_date
                          and not before_daily_bar_complete)]
            labels = [item[0] for item in completed]
            values = np.asarray([item[1] for item in completed], dtype=np.float64)
            if len(labels) < 2:
                raise ValueError("no completed daily prices are available")
            last_session = dt.date.fromisoformat(labels[-1])
            age_days = max(0, (local_date - last_session).days)
            warning = _session_gap_warning(labels, config.gap_warning_days)
            points = compute_indicator_points(
                labels, values, config,
                output_points=min(config.output_points, MAX_PUBLISHED_POINTS))
            status = "stale" if age_days > config.max_session_age_days else "available"
            instruments[symbol] = {
                "symbol": symbol, "status": status,
                "status_message": ("Latest available daily bar is older than expected."
                                   if status == "stale" else None),
                "source": SOURCE_NAME, "price_adjustment": ADJUSTMENT_POLICY,
                "history_type": "reconstructed", "retrieved_at_utc": generated_at,
                "last_session": labels[-1], "session_age_days": age_days,
                "gap_warning": warning, "points": points,
            }
        except (TypeError, ValueError, OverflowError) as exc:
            reason = f"Invalid daily history: {exc}"
            old = previous_instruments.get(symbol)
            if isinstance(old, dict) and isinstance(old.get("points"), list):
                retained = copy.deepcopy(old)
                retained["points"] = retained["points"][-min(config.output_points, MAX_PUBLISHED_POINTS):]
                retained["status"] = "stale"
                retained["status_message"] = reason[:240]
                retained["stale_since_utc"] = generated_at
                instruments[symbol] = retained
            else:
                instruments[symbol] = _unavailable_instrument(symbol, reason, now)
    return {"artifact_version": ARTIFACT_VERSION,
            "methodology_version": METHOD_VERSION,
            "generated_at_utc": generated_at,
            "provider": {"name": SOURCE_NAME,
                         "client_version": provider_version or "unknown",
                         "adjustment": ADJUSTMENT_POLICY},
            "experimental_notice": ("Experimental descriptive diagnostics; not a crash forecast, "
                                    "trader-synchronization test, or investment advice."),
            "settings": settings, "instruments": instruments}


def _price_data_from_frame(frame) -> tuple[list[str], list[float]]:
    if frame is None or getattr(frame, "empty", True):
        raise ValueError("daily price history is empty")
    if "Close" not in frame.columns:
        raise ValueError("daily price history has no Close column")
    if getattr(frame.index, "has_duplicates", False):
        raise ValueError("daily price history contains duplicate sessions")
    ordered = frame.sort_index()
    labels = [_session_label(value) for value in ordered.index]
    values = _finite_vector(ordered["Close"].to_numpy(), "daily closes")
    if len(labels) != values.size:
        raise ValueError("daily session and close counts do not match")
    if any(not value > 0 for value in values):
        raise ValueError("daily closes must be positive")
    if any(right <= left for left, right in zip(labels, labels[1:])):
        raise ValueError("daily sessions are duplicated or out of order")
    return labels, values.tolist()


def fetch_adjusted_daily_prices(symbol: str, *, now: dt.datetime | None = None,
                                ticker_factory=None) -> tuple[list[str], list[float]]:
    """Fetch one symbol for the default-enabled daily diagnostics workflow."""
    if symbol not in INSTRUMENTS:
        raise ValueError(f"unsupported diagnostic instrument: {symbol}")
    if ticker_factory is None:
        import yfinance as yf
        ticker_factory = yf.Ticker
    ticker = ticker_factory(symbol)
    frame = ticker.history(period="5y", interval="1d", auto_adjust=True,
                           prepost=False, repair=False, timeout=20)
    labels, prices = _price_data_from_frame(frame)
    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        raise ValueError("collection time must include a timezone")
    local_now = current.astimezone(NEW_YORK)
    local_today = local_now.date()
    before_daily_bar_complete = local_now.time() < dt.time(16, 15)
    retained = [(label, price) for label, price in zip(labels, prices)
                if dt.date.fromisoformat(label) < local_today or
                (dt.date.fromisoformat(label) == local_today and not before_daily_bar_complete)]
    if not retained:
        raise ValueError("no completed daily sessions are available")
    return [item[0] for item in retained], [item[1] for item in retained]


def collect_price_histories(*, now: dt.datetime | None = None,
                            ticker_factory=None) -> tuple[dict[str, tuple[list[str], list[float]]], dict[str, str]]:
    """Fetch instruments independently; return successful prices and concise errors."""
    histories: dict[str, tuple[list[str], list[float]]] = {}
    failures: dict[str, str] = {}
    for symbol in INSTRUMENTS:
        try:
            histories[symbol] = fetch_adjusted_daily_prices(
                symbol, now=now, ticker_factory=ticker_factory)
        except Exception as exc:
            failures[symbol] = f"Price history unavailable: {type(exc).__name__}: {exc}"
    return histories, failures


def load_previous_artifact(path: str) -> dict | None:
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not isinstance(payload.get("instruments"), dict):
        raise ValueError("existing power-exponents artifact has an invalid shape")
    return payload


def write_artifact_atomic(path: str, artifact: dict) -> None:
    """Write strict JSON atomically in the destination directory."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(artifact, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def publish_power_exponents(path: str = "data/power_exponents.json", *,
                            now: dt.datetime | None = None,
                            ticker_factory=None,
                            config: MonitorConfig = MonitorConfig(),
                            enrich_artifact=None) -> dict:
    """Collect default-enabled diagnostics, isolate instrument failures, and publish stale history."""
    previous = load_previous_artifact(path)
    histories, failures = collect_price_histories(now=now, ticker_factory=ticker_factory)
    try:
        import yfinance as yf
        provider_version = getattr(yf, "__version__", "unknown")
    except ImportError:
        provider_version = "unavailable"
    artifact = build_artifact(histories, now=now, failures=failures,
                              previous=previous, provider_version=provider_version,
                              config=config)
    if enrich_artifact is not None:
        enrich_artifact(artifact)
    write_artifact_atomic(path, artifact)
    return artifact
