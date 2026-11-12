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
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse
from typing import Any

np: Any = None
try:
    import numpy as np
except ImportError:  # Keep contract-only validation importable without optional collection deps.
    pass

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
try:
    from openai import OpenAI
except ImportError:  # Keep offline validation and persistence tests runnable without the SDK.
    class OpenAI:  # type: ignore[no-redef]
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("openai package is required for LLM requests")

power_exponents: Any = None
try:
    import power_exponents as power_exponents
except ImportError:  # Experimental diagnostics require NumPy and are optional to the agent.
    pass

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
DATA_DIR = "data/status_history"
LEGACY_DATA_FILE = "data/status_history.json"
RSS_FEED_URLS = (
    "https://www.bing.com/news/search?q=%22AI+bubble%22+OR+%22AI+valuation%22&format=rss&mkt=en-us",
    "https://www.bing.com/news/search?q=%22AI+capex%22+OR+%22AI+data+center%22+spending&format=rss&mkt=en-us",
    "https://www.bing.com/news/search?q=enterprise+AI+adoption+revenue+ROI&format=rss&mkt=en-us",
)
RSS_FEED_URL = RSS_FEED_URLS[0]
SCHEMA_VERSION = 2
METHODOLOGY_VERSION = "canary-opinion-v3"
DEFAULT_MODEL = "~openai/gpt-latest"
MODEL_OVERRIDE_ENV = "OPENROUTER_MODEL"
MODEL_RETRY_ATTEMPTS = 3
MAX_OUTPUT_TOKENS = 2_000
ARTICLE_FRESHNESS_HOURS = 48
MAX_NEWS_ITEMS = 6
MAX_ARTICLE_CHARS = 2_500
POWER_EXPONENTS_PATH = "data/power_exponents.json"
CONFIDENCE_VALUES = {"LOW", "MEDIUM", "HIGH"}
SENTIMENT_VALUES = {"BEARISH", "CAUTIOUS", "MIXED", "CONSTRUCTIVE", "EUPHORIC"}


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
    """Fetch one-month peer snapshots and normalize scale-free market metrics."""
    tickers = ["NVDA", "MSFT", "GOOGL"]
    data = {}
    print("Fetching stock data...")
    for ticker in tickers:
        info = {}
        try:
            stock = yf.Ticker(ticker)
            try:
                info = stock.info or {}
            except Exception as exc:
                print(f"Warning: No fundamentals found for {ticker}: {exc}")
            try:
                hist = stock.history(period="1mo", interval="1d", auto_adjust=True)
            except TypeError:
                # Keep minimal test doubles and older clients usable.
                hist = stock.history(period="1mo")

            try:
                if getattr(hist, "empty", False):
                    raw_closes = []
                else:
                    close_series = hist["Close"]
                    tolist = getattr(close_series, "tolist", None)
                    to_numpy = getattr(close_series, "to_numpy", None)
                    raw_closes: Any
                    if callable(tolist):
                        raw_closes = tolist()
                    elif callable(to_numpy):
                        raw_closes = list(to_numpy())
                    elif hasattr(close_series, "iloc"):
                        # Minimal Series stubs sometimes expose only `.iloc[-1]`.
                        raw_closes = [close_series.iloc[-1]]
                    else:
                        try:
                            raw_closes = list(close_series)
                        except TypeError:
                            raw_closes = [close_series]
                closes = [value for raw in raw_closes
                          if (value := _as_finite_float(raw)) is not None and value > 0]
            except Exception as exc:
                print(f"Warning: No usable history found for {ticker}: {exc}")
                closes = []

            if closes:
                data[f"{ticker}_price"] = round(closes[-1], 2)
            else:
                print(f"Warning: No finite positive close found for {ticker}")

            if len(closes) >= 6:
                data[f"{ticker}_5d_return_pct"] = round((closes[-1] / closes[-6] - 1.0) * 100.0, 2)
            else:
                data[f"{ticker}_5d_return_pct"] = "N/A"
            if len(closes) >= 21:
                data[f"{ticker}_20d_return_pct"] = round((closes[-1] / closes[-21] - 1.0) * 100.0, 2)
            else:
                data[f"{ticker}_20d_return_pct"] = "N/A"

            if len(closes) >= 21:
                volatility_closes = closes[-21:]
            elif len(closes) >= 6:
                volatility_closes = closes
            else:
                volatility_closes = None
            volatility = None
            if volatility_closes is not None:
                log_returns = np.diff(np.log(np.asarray(volatility_closes, dtype=float)))
                if len(log_returns) >= 2:
                    candidate = float(np.std(log_returns, ddof=1) * math.sqrt(252) * 100.0)
                    if math.isfinite(candidate) and candidate >= 0:
                        volatility = round(candidate, 2)
            data[f"{ticker}_realized_vol_20d_pct"] = volatility if volatility is not None else "N/A"

        except Exception as exc:
            print(f"Error fetching {ticker}: {exc}")
            data.setdefault(f"{ticker}_5d_return_pct", "N/A")
            data.setdefault(f"{ticker}_20d_return_pct", "N/A")
            data.setdefault(f"{ticker}_realized_vol_20d_pct", "N/A")

        if not isinstance(info, dict):
            info = {}
        pe = _as_finite_float(info.get("trailingPE"))
        growth = _as_finite_float(info.get("earningsGrowth"))
        peg = _normalise_metric(info.get("pegRatio", "N/A"))
        if peg == "N/A" and pe is not None and pe > 0 and growth is not None and growth > 0:
            calculated_peg = pe / (growth * 100.0)
            if _is_finite_number(calculated_peg):
                peg = round(float(calculated_peg), 2)
        data[f"{ticker}_pe_ratio"] = _normalise_metric(info.get("trailingPE", "N/A"))
        data[f"{ticker}_forward_pe"] = _normalise_metric(info.get("forwardPE", "N/A"))
        data[f"{ticker}_revenue_growth"] = _normalise_metric(info.get("revenueGrowth", "N/A"))
        data[f"{ticker}_peg_ratio"] = peg
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


def _entry_value(entry, key, default=None):
    """Read one feedparser-like field from either a mapping or a simple stub."""
    if isinstance(entry, dict):
        return entry.get(key, default)
    return getattr(entry, key, default)


def _unwrap_article_url(url):
    """Unwrap Bing redirects and return a canonical URL plus its hostname."""
    candidate = str(url or "").strip()
    for _ in range(3):
        parsed = urlparse(candidate)
        params = parse_qs(parsed.query)
        redirected = next((value for key, values in params.items()
                           if key.lower() == "url" for value in values if value.strip()), None)
        if not redirected or redirected == candidate:
            break
        candidate = redirected.strip()
    parsed = urlparse(candidate)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError:
        port = None
    netloc = hostname
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{hostname}:{port}"
    tracking_keys = {
        "cvid", "fbclid", "gclid", "mc_cid", "mc_eid", "ocid", "ref", "referrer",
        "source", "utm_campaign", "utm_content", "utm_medium", "utm_source", "utm_term",
    }
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if key.lower() not in tracking_keys and not key.lower().startswith("utm_")]
    normalized = urlunparse((scheme, netloc, parsed.path or ("/" if netloc else ""),
                             parsed.params, urlencode(sorted(query)), ""))
    return normalized, hostname


def _normalized_news_title(title):
    """Normalize a headline for deduplication and return an optional publisher suffix."""
    collapsed = " ".join(str(title or "").split())
    comparable, separator, publisher = collapsed.rpartition(" - ")
    if separator and publisher.strip():
        comparable = comparable.strip()
        publisher = publisher.strip()
    else:
        comparable, publisher = collapsed, ""
    return comparable.lower(), publisher


def _news_source(entry, hostname, title_publisher):
    source = _entry_value(entry, "source", {}) or {}
    if isinstance(source, list):
        source = source[0] if source else {}
    source_title = _entry_value(source, "title", "") if source else ""
    if isinstance(source_title, str) and source_title.strip() and source_title.strip().lower() != "unknown source":
        return source_title.strip()
    bing_source = _entry_value(entry, "news_source", "")
    if (isinstance(bing_source, str) and bing_source.strip()
            and bing_source.strip().lower() != "unknown source"):
        return bing_source.strip()
    if title_publisher and title_publisher.lower() != "unknown source":
        return title_publisher
    return hostname.removeprefix("www.") if hostname else "Unknown Source"


def _news_candidate(entry, query_topic, feed_index):
    raw_title = _entry_value(entry, "title", "")
    title = str(raw_title or "")
    normalized_title, title_publisher = _normalized_news_title(title)
    raw_link = _entry_value(entry, "link", "")
    link, hostname = _unwrap_article_url(raw_link)
    raw_description = (_entry_value(entry, "description", "")
                       or _entry_value(entry, "summary", ""))
    description = html.unescape(str(raw_description or ""))
    summary = re.sub(r"<[^<]+?>", "", description).strip()
    published = _entry_value(entry, "published", "") or _entry_value(entry, "updated", "")
    parsed_published = _parse_published(published)
    now = datetime.datetime.now(datetime.timezone.utc)
    fresh = (parsed_published is not None and datetime.timedelta(0) <= now - parsed_published
             <= datetime.timedelta(hours=ARTICLE_FRESHNESS_HOURS))
    timestamp = parsed_published.timestamp() if fresh and parsed_published is not None else 0.0
    return {
        "title": title,
        "normalized_title": normalized_title,
        "url": link,
        "url_domain": hostname.removeprefix("www."),
        "summary": summary,
        "source": _news_source(entry, hostname, title_publisher),
        "published": published if isinstance(published, str) else "",
        "query_topic": query_topic,
        "feed_index": feed_index,
        "fresh": fresh,
        "timestamp": timestamp,
    }


def get_news_headlines():
    """Collect balanced, deduplicated RSS evidence and scrape only selected articles."""
    if feedparser is None:
        print("Error fetching news: feedparser is required for news collection")
        return []
    try:
        import requests
    except ImportError:
        print("Error fetching news: requests is required for news collection")
        return []

    topics = ("valuation_bubble", "capex_infrastructure", "enterprise_adoption_roi")
    query_candidates = []
    for query_topic, feed_url in zip(topics, RSS_FEED_URLS):
        print(f"Fetching news headlines for {query_topic}...")
        try:
            response = requests.get(feed_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
        except Exception as exc:
            print(f"Error fetching news for {query_topic}: {exc}")
            continue

        candidates = [_news_candidate(entry, query_topic, index)
                      for index, entry in enumerate(getattr(feed, "entries", []))]
        query_candidates.append((query_topic, candidates))

    selected = []
    seen_urls = set()
    seen_titles = set()
    for _query_topic, candidates in query_candidates:
        fresh_candidates = sorted(
            (candidate for candidate in candidates if candidate["fresh"]),
            key=lambda item: (-item["timestamp"], item["feed_index"]))
        topic_count = 0
        for candidate in fresh_candidates:
            url_key = candidate["url"]
            title_key = candidate["normalized_title"]
            if ((url_key and url_key in seen_urls) or (title_key and title_key in seen_titles)):
                continue
            if len(selected) >= MAX_NEWS_ITEMS:
                break
            if url_key:
                seen_urls.add(url_key)
            if title_key:
                seen_titles.add(title_key)
            selected.append(candidate)
            topic_count += 1
            if topic_count >= 2:
                break

    if not selected:
        for _query_topic, candidates in query_candidates:
            for candidate in candidates:
                url_key = candidate["url"]
                title_key = candidate["normalized_title"]
                if ((url_key and url_key in seen_urls) or (title_key and title_key in seen_titles)):
                    continue
                if len(selected) >= MAX_NEWS_ITEMS:
                    break
                if url_key:
                    seen_urls.add(url_key)
                if title_key:
                    seen_titles.add(title_key)
                selected.append(candidate)
                break

    items = []
    for candidate in selected[:MAX_NEWS_ITEMS]:
        content = (extract_article_content(candidate["url"]) if candidate["url"] else None)
        content = content or candidate["summary"]
        items.append({
            "title": candidate["title"],
            "summary": candidate["summary"],
            "source": candidate["source"],
            "published": candidate["published"],
            "content": content[:MAX_ARTICLE_CHARS],
            "query_topic": candidate["query_topic"],
            "url_domain": candidate["url_domain"],
        })
    return items


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


def validate_opinion(payload, *, require_sentiment=False):
    """Validate model-authored fields and return a normalized opinion."""
    if not isinstance(payload, dict):
        raise ValueError("model response must be an object")
    required = ("score", "confidence", "thesis", "reasoning", "risk_factors",
                "stabilizing_factors", "change_explanation")
    missing = [name for name in required if name not in payload]
    if require_sentiment and "market_sentiment" not in payload:
        missing.append("market_sentiment")
    if missing:
        raise ValueError("missing required fields: " + ", ".join(missing))
    score_status(payload["score"])
    if payload["confidence"] not in CONFIDENCE_VALUES:
        raise ValueError("confidence must be LOW, MEDIUM, or HIGH")
    result = {"score": payload["score"], "confidence": payload["confidence"]}
    if "market_sentiment" in payload:
        sentiment = payload["market_sentiment"]
        if not isinstance(sentiment, str) or sentiment not in SENTIMENT_VALUES:
            raise ValueError("market_sentiment must be BEARISH, CAUTIOUS, MIXED, CONSTRUCTIVE, or EUPHORIC")
        result["market_sentiment"] = sentiment
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


EDITORIAL_SYSTEM_INSTRUCTIONS = """You are The Canary, an independent editorial financial analyst.

CORE QUESTION AND SCOPE
Assess the structural fragility of the AI investment boom to a meaningful equity
correction (a sector drawdown of at least 20%) or material AI-infrastructure
capital-expenditure deceleration over the next 6–12 months. The integer score is
an editorial fragility index from 0 to 100, not a calibrated probability, forecast,
or investment advice.

CALIBRATED FRAGILITY SCORE BANDS
- 0–30 GREEN — Low fragility / Sustainable expansion: valuation multiples are
  supported by realized cash flows and broad end-user ROI; financing is mostly
  internal cash flow; capex and adoption grow together without circular vendor
  financing or acute concentration stress.
- 31–50 YELLOW — Moderate fragility / Watchful growth: real adoption and strong
  supplier earnings coexist with elevated expectations, capex ahead of verified
  downstream monetization, or concentration that magnifies macro/guidance shocks.
- 51–69 YELLOW — Elevated fragility / Selective repricing risk: major infrastructure
  commitments conflict with unverified buyer ROI, external/vendor financing is
  increasing, or localized selloffs/multiple compression appear, while core
  hyperscaler demand and earnings still restrain an imminent systemic bust.
- 70–85 RED — High fragility / Correction-prone: stretched valuations or aggressive
  forward assumptions combine with circular/debt-heavy financing, buyer ROI
  disappointments, inventory/lead-time softening, or credit/equity contagion.
- 86–100 RED — Extreme fragility / Acute bust conditions: active capex cancellations,
  funding freezes, demand air-pockets, or broad earnings/guidance breakdowns occur
  alongside crowded leverage.

CALIBRATED ANALYTICAL CONFIDENCE
Confidence measures how strongly the supplied evidence supports the analysis; it is
not a data-completeness rating (the application reports data_quality separately).
- HIGH: NVDA/MSFT/GOOGL fundamentals and multiple independent, recent news sources
  directly corroborate evidence across most lenses: valuation, capex financing,
  downstream adoption, and hardware demand.
- MEDIUM: peer fundamentals and recent news support a directional synthesis, though
  some lenses (such as private-startup financing or enterprise ROI) rely on indirect
  indicators.
- LOW: fundamentals are mostly N/A, news is missing/stale/redundant or non-factual,
  or primary signals sharply contradict each other on material facts. Do not default
  to LOW merely because daily public snapshots lack proprietary enterprise surveys;
  judge confidence relative to public daily market/news monitoring.

MARKET SENTIMENT (DISTINCT FROM FRAGILITY)
Choose the prevailing tone of observed price action and news framing: BEARISH means
broadly negative/downbeat; CAUTIOUS means risk-focused or defensive; MIXED means
materially conflicting positive and negative signals; CONSTRUCTIVE means broadly
supportive, improving tone; EUPHORIC means exuberant or unusually optimistic tone.
Sentiment describes the market's tone, not The Canary's fragility assessment: for
example, EUPHORIC sentiment can coexist with a high fragility score.

MARKET DATA FIELD AND UNIT DICTIONARY
For each of NVDA, MSFT, and GOOGL:
- *_price: latest adjusted daily close in USD.
- *_5d_return_pct and *_20d_return_pct: trailing 5-session and 20-session returns
  in percent (for example, -4.25 means -4.25%). N/A means unavailable.
- *_realized_vol_20d_pct: annualized standard deviation of daily log returns in
  percent, std * sqrt(252) * 100, using up to 20 sessions when available.
- *_pe_ratio and *_forward_pe: trailing and forward price/earnings multiples from
  the Yahoo Finance snapshot; N/A means unavailable.
- *_revenue_growth: decimal year-over-year quarterly revenue growth (0.852 means
  +85.2%).
- *_peg_ratio: provider PEG, or trailing P/E divided by year-over-year earnings
  growth in percentage points when both are positive.

NEWS PROVENANCE
News is selected from three balanced Bing RSS searches: AI valuation/bubble,
AI capex/data-center spending, and enterprise AI adoption/revenue/ROI. Each item
includes query_topic and url_domain for provenance; extracted article content is
truncated to 2,500 characters. Different outlets can syndicate the same story, so
headline/source counts may overlap and should not automatically be treated as
independent corroboration.

ANTI-ANCHORING AND INTERNAL CONSISTENCY
First derive today's score and thesis independently from today's market_data and
news_items using the score rubric. Only afterward use prior_context (prior_score,
prior_thesis, recent_scores) to explain why today's independent assessment moved or
stayed near the prior score in change_explanation. Reconcile score band, thesis,
risk_factors, and stabilizing_factors: do not pair RED (70+) with a mild thesis or
GREEN/YELLOW (0–69) with a claim of an imminent systemic bust. Consider valuation,
investment efficiency/financing, adoption, hardware demand, concentration, price
action, and both risk and stabilizing evidence; do not use fixed additive weights.

OUTPUT CONTRACT
Return exactly one JSON object and no surrounding prose, with exactly these
model-authored fields: score (integer 0–100), confidence (LOW/MEDIUM/HIGH),
market_sentiment (BEARISH/CAUTIOUS/MIXED/CONSTRUCTIVE/EUPHORIC), thesis (non-empty
string), reasoning (non-empty string), risk_factors (non-empty array of strings),
stabilizing_factors (non-empty array of strings), and change_explanation (non-empty
string). Do not emit status or application metadata.
"""


def _prompt(market_data, news_items, context):
    context_text = json.dumps(context, ensure_ascii=False, allow_nan=False)
    return f"""Analyze the evidence below for The Canary's 6–12 month AI-boom fragility assessment.

Use valuation, investment efficiency and financing, adoption/ROI, hardware demand,
concentration, price behavior, and stabilizing evidence. Form today's score and thesis
from today's evidence first; consult prior_context only afterward for change_explanation.
Keep the score band consistent with the thesis, risks, and stabilizing factors.

Today's market_data: {json.dumps(market_data, ensure_ascii=False, allow_nan=False)}
Today's news_items (query_topic/url_domain indicate provenance; syndication may overlap):
{json.dumps(news_items, ensure_ascii=False, allow_nan=False)}
Prior context (for change explanation only): {context_text}

Return JSON only, with exactly this model-authored schema:
{{"score": integer 0-100, "confidence": "LOW"|"MEDIUM"|"HIGH",
"market_sentiment": "BEARISH"|"CAUTIOUS"|"MIXED"|"CONSTRUCTIVE"|"EUPHORIC",
"thesis": non-empty string, "reasoning": non-empty string,
"risk_factors": non-empty array of strings,
"stabilizing_factors": non-empty array of strings,
"change_explanation": non-empty string}}"""


def analyze_market_status(market_data, news_items, history=None):
    """Request and validate one opinion, retrying only the same requested model."""
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY environment variable is not set.")
    history = [] if history is None else history
    model = requested_model()
    client: Any = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY, timeout=60.0)
    prompt = _prompt(market_data, news_items, prior_context(history))
    last_error = None
    for attempt in range(MODEL_RETRY_ATTEMPTS):
        try:
            print(f"Querying LLM ({model}), attempt {attempt + 1}/{MODEL_RETRY_ATTEMPTS}...")
            completion = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": EDITORIAL_SYSTEM_INSTRUCTIONS},
                          {"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=MAX_OUTPUT_TOKENS,
            )
            resolved = getattr(completion, "model", None)
            if not isinstance(resolved, str) or not resolved.strip():
                raise ValueError("completion.model is missing; resolved model identity is required")
            choice = completion.choices[0]
            if getattr(choice, "finish_reason", None) != "stop":
                finish_reason = getattr(choice, "finish_reason", None)
                raise ValueError(f"opinion response did not finish normally: {finish_reason!r}")
            content = choice.message.content
            opinion = validate_opinion(
                json.loads(content, parse_constant=_reject_non_standard_json_constant),
                require_sentiment=True)
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
    metrics["market_sentiment"] = (validated.get("market_sentiment") or
                                    opinion.get("market_sentiment", metrics.get("market_sentiment", "Unavailable")))
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


POWER_INTERPRETATION_VERSION = "power-exponents-interpretation-v2"
POWER_INTERPRETATION_MAX_WORDS = 180
POWER_INTERPRETATION_MAX_CHARS = 2_400
_POWER_INTERPRETATION_SIGNAL_FIELDS = (
    "date", "h", "h_r_squared", "h_status", "h_short", "h_long", "h_abs",
    "h_abs_r_squared", "h_delta_1", "h_delta_5", "h_baseline_z", "alpha",
    "alpha_se", "alpha_status", "alpha_k", "alpha_x_min",
)
POWER_INTERPRETATION_INSTRUCTIONS = """Explain experimental market diagnostics to a general reader.
Use only the supplied computed data for this one instrument. Do not use news,
external knowledge of recent events, other instruments, or an editorial score.
Write 90–150 words in clear, short sentences, in at most three short paragraphs.
Return plain JSON with one field: {"explanation": "plain text"}. No Markdown or HTML.
Explain the latest DFA H relative to the ideal independent finite-variance
returns reference H=0.5, and R² as fit quality over the supplied scales only.
When h_r_squared < 0.85, or h_short (scales 8–20) and h_long (scales 25–63)
diverge materially, say the single straight-line exponent fits poorly across
scales 8–63; this may reflect crossover or a transient volatility shift, not one
clean scaling law. Describe h_abs (DFA-1 of |r_t|) as a volatility-clustering
contrast: signed returns may sit near 0.5 while return magnitudes show stronger
persistence; this is descriptive, not tradable predictability.
Describe the 1/5-observation H changes and prior-only standardized deviation
when available; overlapping windows make this deviation NOT a significance test.
Explain Hill alpha: lower estimates suggest heavier fitted absolute-return tails,
higher estimates suggest thinner fitted tails, conditional on a suitable tail model.
Use the actual separate DFA/Hill window lengths, tail count k, x_min (absolute
log-return units; multiply by 100 only when describing percent log returns),
alpha_se (alpha / sqrt(k), an idealized i.i.d. reference standard error), and
5%/15% cutoff sensitivity when useful. alpha_se understates uncertainty under
dependent returns, and cutoff sensitivity is NOT a confidence interval. An
unchanged alpha on consecutive days is normal if new returns do not enter the
top k extremes of the 1,000-return (~4-year) window; these order-statistic plateaus
are not evidence that the market is static.
Briefly describe the supplied recent H/alpha trajectory using dates and values.
Distinguish null/unavailable estimates from zero; do not invent missing results.
Do not call rounded H=0.500 an exact or proven memoryless random walk.
Do not claim persistence, mean reversion, clean Brownian scaling, finite/infinite
market variance, structural breaks, trader herding, or market safety is established.
No crash forecasts, probabilities, danger/herding thresholds, phase-transition
warnings, trading advice, or claims that high R² confirms a regime.
Do not infer specific daily moves or causes of Hill steps from exponent history:
rolling-window entry/exit and threshold changes can both affect the estimate.
Keep the explanation at or below 180 words and 2,400 characters. End with a brief
reminder that these are uncertain descriptive estimates, not a crash forecast.
Do not give an all-clear or claim extreme events are absent.
"""


def _compact_recent_point(point):
    """Project historical diagnostics to their signal fields, excluding repeated detail."""
    if not isinstance(point, dict):
        return point
    return {key: point[key] for key in _POWER_INTERPRETATION_SIGNAL_FIELDS if key in point}


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
        "latest": points[-1], "recent_points": [_compact_recent_point(point) for point in points],
    }
    model = requested_model()
    # No retry loop: at most one extra request per eligible instrument per run.
    client: Any = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY,
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
    if len(explanation) > POWER_INTERPRETATION_MAX_CHARS or len(explanation.split()) > POWER_INTERPRETATION_MAX_WORDS:
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
