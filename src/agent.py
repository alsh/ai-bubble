"""The Canary daily editorial opinion agent.

The persisted file deliberately remains a plain JSON array: GitHub Actions runs this
module once a day and GitHub Pages serves the resulting file directly.
"""
import datetime
import html
import json
import os
import re
import tempfile
from email.utils import parsedate_to_datetime
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

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
DATA_FILE = "data/status_history.json"
RSS_FEED_URL = "https://www.bing.com/news/search?q=AI+bubble&format=rss&mkt=en-us"
SCHEMA_VERSION = 2
METHODOLOGY_VERSION = "canary-opinion-v2"
DEFAULT_MODEL = "~openai/gpt-latest"
MODEL_OVERRIDE_ENV = "OPENROUTER_MODEL"
MODEL_RETRY_ATTEMPTS = 3
ARTICLE_FRESHNESS_HOURS = 48
CONFIDENCE_VALUES = {"LOW", "MEDIUM", "HIGH"}


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
            data[f"{ticker}_price"] = round(float(hist["Close"].iloc[-1]), 2)
            if ticker == "NVDA":
                data["NVDA_volatility"] = round(float(hist["Close"].std()), 2)
                data["NVDA_pe_ratio"] = info.get("trailingPE", "N/A")
                data["NVDA_forward_pe"] = info.get("forwardPE", "N/A")
                data["NVDA_revenue_growth"] = info.get("revenueGrowth", "N/A")
                peg = info.get("pegRatio", "N/A")
                if peg in (None, "N/A"):
                    try:
                        pe = float(info.get("trailingPE"))
                        growth = float(info.get("earningsGrowth"))
                        peg = round(pe / (growth * 100), 2) if growth else "N/A"
                    except (TypeError, ValueError, ZeroDivisionError):
                        peg = "N/A"
                data["NVDA_peg_ratio"] = peg
        except Exception as exc:
            print(f"Error fetching {ticker}: {exc}")
    return data


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
    context_text = json.dumps(context, ensure_ascii=False)
    return f"""You are The Canary, an independent editorial financial analyst.

Question: how fragile is the AI investment boom to a meaningful correction within the next 6–12 months?
Use these analytical lenses, without fixed additive weights: valuation; investment efficiency and
financing; adoption; hardware demand; concentration; price behavior; and stabilizing evidence.
Weigh balanced evidence holistically. Reconcile the integer score with the thesis. Reassess
independently rather than anchoring on the prior opinion. Explain material movement from it.
This is an editorial opinion, not a probability or investment recommendation.

Prior compact context (scores are context only): {context_text}
Market evidence: {json.dumps(market_data, ensure_ascii=False)}
News evidence: {json.dumps(news_items, ensure_ascii=False)}

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
    market_complete = all(isinstance(market_data.get(key), (int, float)) for key in required_prices)
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
    usable_market = isinstance(market_data, dict) and any(isinstance(value, (int, float)) and not isinstance(value, bool)
                                                          for value in market_data.values())
    usable_news = isinstance(news_items, list) and any(
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
    if news_items:
        metrics["top_headline"] = news_items[0].get("title", "")
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
    return entry


def load_history(path=DATA_FILE):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        history = json.load(handle)
    if not isinstance(history, list):
        raise ValueError("history must be a JSON array")
    return history


def update_history(entry, path=DATA_FILE):
    """Append using same-directory atomic replacement; never reset corrupt history."""
    history = load_history(path)
    if not isinstance(entry, dict):
        raise ValueError("entry must be an object")
    history.append(entry)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".status_history.", suffix=".tmp", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(history, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    print(f"Updated {path} with new entry.")


def main():
    market_data = get_market_data()
    news_items = get_news_headlines()
    history = load_history(DATA_FILE)
    usable_market = isinstance(market_data, dict) and any(isinstance(value, (int, float)) and not isinstance(value, bool)
                                                          for value in market_data.values())
    usable_news = isinstance(news_items, list) and any(
        isinstance(item, dict) and any(isinstance(item.get(key), str) and item.get(key).strip()
                                       for key in ("title", "summary", "content"))
        for item in news_items)
    if not usable_market and not usable_news:
        raise ValueError("evidence packet is entirely empty")
    opinion = analyze_market_status(market_data, news_items, history)
    entry = build_version2_entry(opinion, market_data, news_items, history)
    update_history(entry, DATA_FILE)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Fatal Error: {exc}")
        raise SystemExit(1)
