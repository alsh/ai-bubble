"""The Canary daily editorial opinion agent.

History is stored in monthly JSON arrays with a small month index. The static
dashboard serves these files directly; the agent migrates legacy single-file
history when it runs.
"""
import datetime
import html
import json
import math
import os
import re
import tempfile
from email.utils import parsedate_to_datetime
from numbers import Real
from urllib.parse import parse_qs, urlparse

try:
    import feedparser
except ImportError:  # Optional for contract-only local tests.
    feedparser = None
try:
    import trafilatura
except ImportError:  # Optional until article scraping is invoked.
    trafilatura = None
try:
    import yfinance as yf
except ImportError:  # Keep validation helpers importable without collection deps.
    class _MissingYFinance:
        def Ticker(self, *_args, **_kwargs):
            raise RuntimeError("yfinance is required for market collection")
    yf = _MissingYFinance()
try:
    from fake_useragent import UserAgent
except ImportError:
    class UserAgent:
        random = "Mozilla/5.0"
from openai import OpenAI

import power_exponents

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
DATA_DIR = "data/status_history"
LEGACY_DATA_FILE = "data/status_history.json"
RSS_FEED_URL = "https://www.bing.com/news/search?q=AI+bubble&format=rss&mkt=en-us"
SCHEMA_VERSION = 2
METHODOLOGY_VERSION = "canary-opinion-v2"
DEFAULT_MODEL = "~openai/gpt-latest"
MODEL_OVERRIDE_ENV = "OPENROUTER_MODEL"
MODEL_RETRY_ATTEMPTS = 3
MAX_OUTPUT_TOKENS = 2_000
ARTICLE_FRESHNESS_HOURS = 48
POWER_EXPONENTS_PATH = "data/power_exponents.json"
CONFIDENCE_VALUES = {"LOW", "MEDIUM", "HIGH"}


def _is_finite_number(value):
    """Return whether value is a JSON-safe finite real number."""
    if isinstance(value, bool) or not isinstance(value, Real):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _as_finite_float(value):
    """Convert a numeric value to a finite built-in float, or return None."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _normalise_metric(value):
    """Keep optional market metrics JSON-safe while preserving useful text."""
    if isinstance(value, str):
        value = value.strip()
        if not value or value.lower() in {"nan", "+nan", "-nan", "inf", "+inf", "-inf",
                                           "infinity", "+infinity", "-infinity"}:
            return "N/A"
        return value
    number = _as_finite_float(value)
    return number if number is not None else "N/A"


def _clean_market_data(market_data):
    """Replace non-JSON numeric values before evidence reaches the prompt or file."""
    if not isinstance(market_data, dict):
        return {}
    cleaned = {}
    for key, value in market_data.items():
        if not isinstance(key, str):
            continue
        cleaned[key] = _normalise_metric(value)
    return cleaned


class _NonStandardJSONConstantError(ValueError):
    """Signals a recoverable JavaScript-only numeric literal in history."""
def _reject_non_standard_json_constant(value):
    """Reject JavaScript-only numeric constants accepted by Python's JSON parser."""
    raise _NonStandardJSONConstantError(f"non-standard JSON constant {value!r} is not permitted")

def _recover_non_standard_json_constant(value):
    """Convert legacy non-standard numeric literals to JSON null while repairing history."""
    return None


def get_market_data():
    """Fetch market snapshots. Missing individual tickers are retained as degradation."""
    tickers = ["NVDA", "MSFT", "GOOGL"]
    data = {}
    print("Fetching stock data...")
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="5d")
            info = stock.info or {}
            if hist.empty:
                print(f"Warning: No history found for {ticker}")
                continue
            price = _as_finite_float(hist["Close"].iloc[-1])
            if price is None:
                print(f"Warning: Non-finite closing price for {ticker}")
                continue
            data[f"{ticker}_price"] = round(price, 2)
            if ticker == "NVDA":
                volatility = _as_finite_float(hist["Close"].std())
                if volatility is not None:
                    data["NVDA_volatility"] = round(volatility, 2)
                data["NVDA_pe_ratio"] = _normalise_metric(info.get("trailingPE", "N/A"))
                data["NVDA_forward_pe"] = _normalise_metric(info.get("forwardPE", "N/A"))
                data["NVDA_revenue_growth"] = _normalise_metric(info.get("revenueGrowth", "N/A"))
                peg = _normalise_metric(info.get("pegRatio", "N/A"))
                if peg == "N/A":
                    pe = _as_finite_float(info.get("trailingPE"))
                    growth = _as_finite_float(info.get("earningsGrowth"))
                    if pe is not None and growth not in (None, 0):
                        try:
                            calculated_peg = pe / (growth * 100)
                        except (OverflowError, ZeroDivisionError):
                            calculated_peg = None
                        if _is_finite_number(calculated_peg):
                            peg = round(calculated_peg, 2)
                data["NVDA_peg_ratio"] = peg
        except Exception as exc:
            print(f"Error fetching {ticker}: {exc}")
    return _clean_market_data(data)


def extract_article_content(url):
    """Download and extract article text, returning None when unavailable."""
    try:
        ua = UserAgent()
        import requests
        response = requests.get(url, headers={"User-Agent": ua.random}, timeout=10)
        if response.status_code == 200:
            text = trafilatura.extract(response.text) if trafilatura else None
            if text:
                return text
    except Exception as exc:
        print(f"Error scraping {url}: {exc}")
    return None


def get_news_headlines():
    """Fetch up to five RSS items and use article text with an RSS fallback."""
    print(f"Fetching news headlines from {RSS_FEED_URL}...")
    try:
        import requests
        response = requests.get(RSS_FEED_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        response.raise_for_status()
        if feedparser is None:
            raise RuntimeError("feedparser is required for news collection")
        feed = feedparser.parse(response.content)
        items = []
        for entry in feed.entries[:5]:
            raw_title = entry.get("title", None)
            if not isinstance(raw_title, str):
                raw_title = getattr(entry, "title", "")
            title = str(raw_title)
            raw_description = entry.get("description", "")
            description = html.unescape(str(raw_description))
            summary = re.sub(r"<[^<]+?>", "", description)
            source = entry.get("source", {}) or {}
            if isinstance(source, list):
                source = source[0] if source else {}
            raw_link = entry.get("link", None)
            if not isinstance(raw_link, str):
                raw_link = getattr(entry, "link", "")
            link = str(raw_link)
            try:
                params = parse_qs(urlparse(link).query)
                link = params.get("url", [link])[0]
            except Exception:
                pass
            content = extract_article_content(link) or summary
            items.append({
                "title": title,
                "summary": summary,
                "source": source.get("title", "Unknown Source") if isinstance(source, dict) else "Unknown Source",
                "published": entry.get("published", entry.get("updated", "")),
                "content": content[:3000],
            })
        return items
    except Exception as exc:
        print(f"Error fetching news: {exc}")
        return []


def requested_model():
    """Return the configured slug, or OpenRouter's current OpenAI alias."""
    return os.environ.get(MODEL_OVERRIDE_ENV) or DEFAULT_MODEL


def score_status(score):
    """Derive presentation status; the model never supplies this field."""
    if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 100:
        raise ValueError("score must be an integer from 0 through 100")
    return "GREEN" if score <= 30 else "YELLOW" if score <= 69 else "RED"


def _nonempty_string(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def validate_opinion(payload):
    """Validate only model-authored v2 fields and return a normalized copy."""
    if not isinstance(payload, dict):
        raise ValueError("model response must be an object")
    required = ("score", "confidence", "thesis", "reasoning", "risk_factors",
                "stabilizing_factors", "change_explanation")
    missing = [name for name in required if name not in payload]
    if missing:
        raise ValueError("missing required fields: " + ", ".join(missing))
    score_status(payload["score"])
    if payload["confidence"] not in CONFIDENCE_VALUES:
        raise ValueError("confidence must be LOW, MEDIUM, or HIGH")
    result = {"score": payload["score"], "confidence": payload["confidence"]}
    for field in ("thesis", "reasoning", "change_explanation"):
        result[field] = _nonempty_string(payload[field], field)
    for field in ("risk_factors", "stabilizing_factors"):
        values = payload[field]
        if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError(f"{field} must be a non-empty list of strings")
        result[field] = [v.strip() for v in values]
    return result


def valid_history_entries(history):
    """Return entries with a valid numeric score, without rewriting their values."""
    if not isinstance(history, list):
        raise ValueError("history must be a JSON array")
    return [entry for entry in history if isinstance(entry, dict) and isinstance(entry.get("score"), int)
            and not isinstance(entry.get("score"), bool) and 0 <= entry["score"] <= 100]


def prior_context(history):
    entries = valid_history_entries(history)
    if not entries:
        return {"baseline": True, "prior_score": None, "prior_thesis": None, "recent_scores": []}
    latest = entries[-1]
    return {
        "baseline": False,
        "prior_score": latest["score"],
        "prior_thesis": latest.get("thesis", ""),
        "recent_scores": [entry["score"] for entry in entries[-7:]],
    }


def _prompt(market_data, news_items, context):
    context_text = json.dumps(context, ensure_ascii=False, allow_nan=False)
    return f"""You are The Canary, an independent editorial financial analyst.

Question: how fragile is the AI investment boom to a meaningful correction within the next 6–12 months?
Use these analytical lenses, without fixed additive weights: valuation; investment efficiency and
financing; adoption; hardware demand; concentration; price behavior; and stabilizing evidence.
Weigh balanced evidence holistically. Reconcile the integer score with the thesis. Reassess
independently rather than anchoring on the prior opinion. Explain material movement from it.
This is an editorial opinion, not a probability or investment recommendation.

Prior compact context (scores are context only): {context_text}
Market evidence: {json.dumps(market_data, ensure_ascii=False, allow_nan=False)}
News evidence: {json.dumps(news_items, ensure_ascii=False, allow_nan=False)}

Return JSON only with exactly these model-authored fields:
{{"score": integer 0-100, "confidence": "LOW"|"MEDIUM"|"HIGH",
"thesis": non-empty concise string, "reasoning": non-empty string,
"risk_factors": non-empty array of strings, "stabilizing_factors": non-empty array of strings,
"change_explanation": non-empty string}}"""


def analyze_market_status(market_data, news_items, history=None):
    """Request and validate one opinion, retrying only the same requested model."""
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY environment variable is not set.")
    history = [] if history is None else history
    model = requested_model()
    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
    prompt = _prompt(market_data, news_items, prior_context(history))
    last_error = None
    for attempt in range(MODEL_RETRY_ATTEMPTS):
        try:
            print(f"Querying LLM ({model}), attempt {attempt + 1}/{MODEL_RETRY_ATTEMPTS}...")
            completion = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": "You are a careful financial analyst."}, {"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=MAX_OUTPUT_TOKENS,
            )
            resolved = getattr(completion, "model", None)
            if not isinstance(resolved, str) or not resolved.strip():
                raise ValueError("completion.model is missing; resolved model identity is required")
            content = completion.choices[0].message.content
            opinion = validate_opinion(json.loads(content))
            opinion["_requested_model"] = model
            opinion["_resolved_model"] = resolved.strip()
            return opinion
        except Exception as exc:
            last_error = exc
            print(f"Error querying {model}: {exc}")
    raise RuntimeError(f"All {MODEL_RETRY_ATTEMPTS} attempts failed for {model}: {last_error}")


def _parse_published(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
    return parsed.replace(tzinfo=datetime.timezone.utc) if parsed.tzinfo is None else parsed.astimezone(datetime.timezone.utc)


def data_quality(market_data, news_items, now=None):
    """Compute observed evidence quality independently of model score/confidence.

    Articles published within 48 hours are fresh; unknown publication dates are not fresh.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    required_prices = [f"{ticker}_price" for ticker in ("NVDA", "MSFT", "GOOGL")]
    market_complete = isinstance(market_data, dict) and all(_is_finite_number(market_data.get(key))
                                                   for key in required_prices)
    fetched = len(news_items) if isinstance(news_items, list) else 0
    fresh = 0
    for item in news_items if isinstance(news_items, list) else []:
        published = _parse_published(item.get("published")) if isinstance(item, dict) else None
        if published and datetime.timedelta(0) <= now - published <= datetime.timedelta(hours=ARTICLE_FRESHNESS_HOURS):
            fresh += 1
    state = "complete" if market_complete and fresh > 0 else "degraded"
    return {"state": state, "market_data_complete": market_complete,
            "fetched_articles": fetched, "fresh_articles": fresh,
            "freshness_window_hours": ARTICLE_FRESHNESS_HOURS}


def build_version2_entry(opinion, market_data, news_items, history, now=None):
    """Combine validated model fields with application-owned metadata."""
    validated = validate_opinion(opinion)
    market_data = _clean_market_data(market_data)
    news_items = news_items if isinstance(news_items, list) else []
    usable_market = any(_is_finite_number(value) for value in market_data.values())
    usable_news = any(
        isinstance(item, dict) and any(isinstance(item.get(key), str) and item.get(key).strip()
                                       for key in ("title", "summary", "content"))
        for item in news_items)
    if not usable_market and not usable_news:
        raise ValueError("evidence packet is entirely empty")
    now = now or datetime.datetime.now(datetime.timezone.utc)
    context = prior_context(history)
    previous = context["prior_score"]
    metrics = dict(market_data)
    metrics["market_sentiment"] = opinion.get("market_sentiment", metrics.get("market_sentiment", "Unavailable"))
    first_article = next((item for item in news_items if isinstance(item, dict)), None)
    if first_article is not None:
        headline = first_article.get("title")
        metrics["top_headline"] = headline.strip() if isinstance(headline, str) and headline.strip() else "Unavailable"
    entry = {
        "schema_version": SCHEMA_VERSION,
        "methodology_version": METHODOLOGY_VERSION,
        "date": now.astimezone(datetime.timezone.utc).isoformat(),
        "score": validated["score"],
        "status": score_status(validated["score"]),
        "confidence": validated["confidence"],
        "thesis": validated["thesis"],
        "reasoning": validated["reasoning"],
        "risk_factors": validated["risk_factors"],
        "stabilizing_factors": validated["stabilizing_factors"],
        "change": {"previous_score": previous, "delta": validated["score"] - previous if previous is not None else None,
                   "explanation": validated["change_explanation"]},
        "data_quality": data_quality(market_data, news_items, now),
        "model": {"requested": opinion.get("_requested_model", requested_model()),
                  "resolved": opinion.get("_resolved_model", "")},
        "metrics": metrics,
    }
    if not isinstance(entry["model"]["resolved"], str) or not entry["model"]["resolved"].strip():
        raise ValueError("resolved model identity is required")
    # Legacy-compatible aliases deliberately remain present in new records.
    entry["metrics"].setdefault("nvda_pe", str(market_data.get("NVDA_pe_ratio", "N/A")))
    entry["metrics"].setdefault("revenue_growth", str(market_data.get("NVDA_revenue_growth", "N/A")))
    entry["metrics"].setdefault("peg_ratio", str(market_data.get("NVDA_peg_ratio", "N/A")))
    # Fail before persistence rather than creating a browser-invalid JSON artifact.
    json.dumps(entry, ensure_ascii=False, allow_nan=False)
    return entry


def _read_history_file(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        try:
            history = json.load(handle, parse_constant=_reject_non_standard_json_constant)
        except _NonStandardJSONConstantError:
            handle.seek(0)
            history = json.load(handle, parse_constant=_recover_non_standard_json_constant)
            print(f"Warning: repaired non-standard numeric values in {path}")
    if not isinstance(history, list):
        raise ValueError("history must be a JSON array")
    return history


def _history_month(entry, index=None):
    if not isinstance(entry, dict):
        raise ValueError(f"history entry {index} must be an object with a date")
    value = entry.get("date")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"history entry {index} has no valid date")
    try:
        parsed = datetime.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"history entry {index} has invalid date {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    else:
        parsed = parsed.astimezone(datetime.timezone.utc)
    return parsed.strftime("%Y-%m")


def _history_months(directory):
    if not os.path.isdir(directory):
        return []
    return sorted(name[:-5] for name in os.listdir(directory)
                  if re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])\.json", name))


def _load_partitioned_history(directory):
    history = []
    for month in _history_months(directory):
        history.extend(_read_history_file(os.path.join(directory, f"{month}.json")))
    return history


def _write_json_atomic(path, payload):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _write_month_index(directory):
    _write_json_atomic(os.path.join(directory, "index.json"), {"months": _history_months(directory)})


def _legacy_path_for(directory):
    directory = os.path.normpath(directory)
    return os.path.join(os.path.dirname(directory), os.path.basename(directory) + ".json")


def migrate_legacy_history(storage_dir=DATA_DIR, legacy_file=LEGACY_DATA_FILE):
    """Move the old array into month files, then remove its source file."""
    if not os.path.isfile(legacy_file):
        return False
    history = _read_history_file(legacy_file)
    groups = {}
    for index, entry in enumerate(history):
        groups.setdefault(_history_month(entry, index), []).append(entry)

    parent = os.path.dirname(os.path.normpath(storage_dir)) or "."
    os.makedirs(parent, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".status_history.migration.", dir=parent)
    try:
        for month, entries in groups.items():
            _write_json_atomic(os.path.join(staging, f"{month}.json"), entries)
        _write_month_index(staging)

        if os.path.isdir(storage_dir) and not os.listdir(storage_dir):
            os.rmdir(storage_dir)
        if os.path.exists(storage_dir):
            if not os.path.isdir(storage_dir):
                raise ValueError(f"monthly history path is not a directory: {storage_dir}")
            existing = {month: _read_history_file(os.path.join(storage_dir, f"{month}.json"))
                        for month in _history_months(storage_dir)}
            if existing != groups:
                raise ValueError("legacy and monthly history both exist with different data; migration stopped")
            _write_month_index(storage_dir)
        else:
            os.replace(staging, storage_dir)
            staging = None

        os.unlink(legacy_file)
        print(f"Migrated {len(history)} history entries from {legacy_file} to {storage_dir}.")
        return True
    finally:
        if staging and os.path.isdir(staging):
            for name in os.listdir(staging):
                os.unlink(os.path.join(staging, name))
            os.rmdir(staging)


def load_history(path=DATA_DIR):
    """Load a legacy array or all month files; migrate the default legacy store once."""
    if os.path.isfile(path) or str(path).endswith(".json"):
        return _read_history_file(path)
    legacy_file = _legacy_path_for(path)
    if os.path.isfile(legacy_file):
        migrate_legacy_history(path, legacy_file)
    return _load_partitioned_history(path)


def update_history(entry, path=DATA_DIR):
    """Append atomically to one month file and refresh its small month index."""
    if not isinstance(entry, dict):
        raise ValueError("entry must be an object")
    if not os.path.isdir(path) and str(path).endswith(".json"):
        history = load_history(path)
        history.append(entry)
        _write_json_atomic(path, history)
        print(f"Updated {path} with new entry.")
        return

    legacy_file = _legacy_path_for(path)
    if os.path.isfile(legacy_file):
        migrate_legacy_history(path, legacy_file)
    month = _history_month(entry)
    os.makedirs(path, exist_ok=True)
    month_path = os.path.join(path, f"{month}.json")
    history = _read_history_file(month_path)
    history.append(entry)
    _write_json_atomic(month_path, history)
    _write_month_index(path)
    print(f"Updated {month_path} with new entry.")


POWER_INTERPRETATION_VERSION = "power-exponents-interpretation-v1"
POWER_INTERPRETATION_MAX_WORDS = 180
POWER_INTERPRETATION_INSTRUCTIONS = """Explain experimental market diagnostics to a general reader.
Use only the supplied computed data for this one instrument. Do not use news,
external knowledge of recent events, other instruments, or an editorial score.
Write 90–150 words in clear, short sentences, in at most three short paragraphs.
Return JSON with one field: {"explanation": "plain text"}. No Markdown or HTML.
Explain the latest DFA H relative to the ideal independent finite-variance
returns reference H=0.5, and R² as fit quality over the supplied scales only.
Describe the 1/5-observation H changes and prior-only standardized deviation
when available; overlapping windows make this deviation NOT a significance test.
Explain Hill alpha: lower estimates suggest heavier fitted absolute-return tails,
higher estimates suggest thinner fitted tails, conditional on a suitable tail model.
Use the actual separate DFA/Hill window lengths, tail count k, x_min (absolute
log-return units; multiply by 100 only when describing percent log returns),
and cutoff sensitivity when useful. Sensitivity is NOT a confidence interval.
Briefly describe the supplied recent H/alpha trajectory using dates and values.
Distinguish null/unavailable estimates from zero; do not invent missing results.
Do not call rounded H=0.500 an exact or proven memoryless random walk.
Do not claim persistence, mean reversion, clean Brownian scaling, finite/infinite
market variance, structural breaks, trader herding, or market safety is established.
No crash predictions, probabilities, danger/herding thresholds, phase-transition
warnings, trading advice, or claims that high R² confirms a regime.
Do not infer specific daily moves or causes of Hill steps from exponent history:
rolling-window entry/exit and threshold changes can both affect the estimate.
End with a brief reminder that these are uncertain descriptive estimates, not a
crash forecast. Do not give an all-clear or claim extreme events are absent.
"""


def explain_power_exponents(artifact, symbol, instrument):
    """Make one bounded, separate model request using derived diagnostics only."""
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY environment variable is not set.")
    points = instrument["points"][-30:]
    evidence = {
        "symbol": symbol, "session_date": instrument["last_session"],
        "methodology_version": artifact.get("methodology_version"),
        "settings": artifact.get("settings", {}),
        "history_type": instrument.get("history_type"),
        "gap_warning": instrument.get("gap_warning"),
        "latest": points[-1], "recent_points": points,
    }
    model = requested_model()
    # No retry loop: at most one extra request per eligible instrument per run.
    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY,
                    timeout=60.0, max_retries=0)
    completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": POWER_INTERPRETATION_INSTRUCTIONS},
                  {"role": "user", "content": json.dumps(evidence, allow_nan=False)}],
        response_format={"type": "json_object"}, max_tokens=1_200,
    )
    choice = completion.choices[0]
    if choice.finish_reason != "stop":
        raise ValueError("interpretation response did not finish normally")
    payload = json.loads(choice.message.content,
                         parse_constant=_reject_non_standard_json_constant)
    if not isinstance(payload, dict):
        raise ValueError("interpretation response must be an object")
    explanation = _nonempty_string(payload.get("explanation"), "explanation")
    if len(explanation) > 2400 or len(explanation.split()) > POWER_INTERPRETATION_MAX_WORDS:
        raise ValueError("interpretation response is too long")
    resolved = _nonempty_string(getattr(completion, "model", None), "resolved model")
    return {
        "status": "available", "text": explanation,
        "session_date": instrument["last_session"],
        "history_start": points[0]["date"], "history_end": points[-1]["date"],
        "observation_count": len(points),
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "methodology_version": POWER_INTERPRETATION_VERSION,
        "estimator_version": artifact.get("methodology_version"),
        "requested_model": model, "resolved_model": resolved,
    }


def add_power_exponent_interpretations(artifact):
    """Isolate instrument failures; never relabel retained stale text as current."""
    for symbol in power_exponents.INSTRUMENTS:
        instrument = artifact.get("instruments", {}).get(symbol)
        if not isinstance(instrument, dict) or instrument.get("status") != "available":
            continue
        points = instrument.get("points", [])
        if (not points or points[-1].get("date") != instrument.get("last_session")
                or not any(_is_finite_number(points[-1].get(key)) for key in ("h", "alpha"))):
            instrument["interpretation"] = {"status": "unavailable"}
            continue
        try:
            instrument["interpretation"] = explain_power_exponents(artifact, symbol, instrument)
        except Exception:
            # Do not publish provider errors, response bodies, or an old session's text.
            print(f"Warning: power-exponent interpretation unavailable for {symbol}.")
            instrument["interpretation"] = {"status": "unavailable"}


def update_power_exponent_diagnostics():
    """Publish optional diagnostics without making them a requirement for the opinion run."""
    try:
        artifact = power_exponents.publish_power_exponents(
            POWER_EXPONENTS_PATH, enrich_artifact=add_power_exponent_interpretations)
        print("Published experimental power-exponent history through "
              f"{artifact['generated_at_utc']}.")
        return True
    except Exception as exc:
        print(f"Warning: power-exponent collection/publication failed: {exc}")
        return False


def main():
    history = load_history()
    market_data = _clean_market_data(get_market_data())
    news_items = get_news_headlines()
    usable_market = any(_is_finite_number(value) for value in market_data.values())
    usable_news = isinstance(news_items, list) and any(
        isinstance(item, dict) and any(isinstance(item.get(key), str) and item.get(key).strip()
                                       for key in ("title", "summary", "content"))
        for item in news_items)
    if not usable_market and not usable_news:
        raise ValueError("evidence packet is entirely empty")
    opinion = analyze_market_status(market_data, news_items, history)
    entry = build_version2_entry(opinion, market_data, news_items, history)
    update_history(entry)
    update_power_exponent_diagnostics()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Fatal Error: {exc}")
        raise SystemExit(1)
