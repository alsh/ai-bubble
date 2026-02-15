
import os
import json
import datetime
import yfinance as yf
import datetime
import yfinance as yf
import feedparser
import html
import re
import trafilatura
from urllib.parse import urlparse, parse_qs
from fake_useragent import UserAgent
from openai import OpenAI

# Configuration
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
DATA_FILE = "data/status_history.json"
RSS_FEED_URL = "https://www.bing.com/news/search?q=AI+bubble&format=rss&mkt=en-us"

def get_market_data():
    """Fetches market data for NVDA, MSFT, GOOGL and calculates volatility."""
    tickers = ["NVDA", "MSFT", "GOOGL"]
    data = {}
    
    print("Fetching stock data...")
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            # Fetch 5 days history
            hist = stock.history(period="5d")
            
            # Fetch fundamentals
            info = stock.info
            
            if not hist.empty:
                current_price = hist["Close"].iloc[-1]
                data[f"{ticker}_price"] = round(current_price, 2)
                
                # Fetch detailed metrics for NVDA as per PRD
                if ticker == "NVDA":
                    volatility = hist["Close"].std()
                    data[f"{ticker}_volatility"] = round(volatility, 2)
                    
                    # Fetch basic info
                    trailing_pe = info.get("trailingPE", "N/A")
                    forward_pe = info.get("forwardPE", "N/A")
                    revenue_growth = info.get("revenueGrowth", "N/A")
                    peg_ratio = info.get("pegRatio", "N/A")
                    earnings_growth = info.get("earningsGrowth", "N/A") # New: Fetch Earnings Growth

                    # Helper to safeguard float conversion
                    def safe_float(val):
                        try:
                            return float(val)
                        except (ValueError, TypeError):
                            return None

                    # Manual PEG Calculation Fallback
                    # PEG = P/E / (Earnings Growth Rate * 100)
                    if peg_ratio == "N/A" or peg_ratio is None:
                        pe_val = safe_float(trailing_pe)
                        eg_val = safe_float(earnings_growth)
                        
                        if pe_val is not None and eg_val is not None and eg_val != 0:
                            # earnings_growth is usually a decimal (e.g. 0.50 for 50%), so * 100
                            calculated_peg = pe_val / (eg_val * 100)
                            peg_ratio = round(calculated_peg, 2)
                            print(f"Calculated manual PEG: {peg_ratio} (P/E: {pe_val}, Growth: {eg_val})")
                        else:
                            print(f"Could not calculate PEG. P/E: {pe_val}, Growth: {eg_val}")

                    data[f"{ticker}_pe_ratio"] = trailing_pe
                    data[f"{ticker}_forward_pe"] = forward_pe
                    data[f"{ticker}_revenue_growth"] = revenue_growth
                    data[f"{ticker}_peg_ratio"] = peg_ratio
                    data[f"{ticker}_earnings_growth"] = earnings_growth

            else:
                print(f"Warning: No history found for {ticker}")
                
        except Exception as e:
            print(f"Error fetching {ticker}: {e}")
            
    return data

def extract_article_content(url):
    """Downloads and extracts main text from a URL using Trafilatura."""
    try:
        ua = UserAgent()
        # Trafilatura allows passing a config, but for simple user-agent rotation we can try downloading first with requests or letting trafilatura handle it if supports it.
        # Trafilatura specific way to fetch with custom headers:
        downloaded = trafilatura.fetch_url(url)
        # Note: Trafilatura's fetch_url uses a default user agent. To use our fake one, we might need requests.
        # But let's try the library's built-in robust fetch first, or override if needed.
        # Ideally: downloaded = trafilatura.fetch_url(url) is usually good.
        # To be strictly complying with PRD "Attempt 1... with random User-Agent":
        # We can use requests.
        import requests
        headers = {'User-Agent': ua.random}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
             downloaded = response.text
             text = trafilatura.extract(downloaded)
             if text:
                 return text
    except Exception as e:
        print(f"Error scraping {url}: {e}")
    return None

def get_news_headlines():
    """Fetches top 5 headlines with summary, source, date, and full content from Google News RSS."""
    print(f"Fetching news headlines from {RSS_FEED_URL}...")
    try:
        # Bing News blocks default python-requests/urllib UA, so we fetch with a browser UA first
        headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0'}
        import requests
        response = requests.get(RSS_FEED_URL, headers=headers, timeout=10)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        news_items = []
        for entry in feed.entries[:5]:
            title = entry.title
            # Extract summary (often in description), source, and date
            description = entry.get('description', '')
            summary = html.unescape(str(description))
            # Clean up summary (sometimes Google News adds "<ul>...</ul>" which is noisy)
            # Strip HTML tags
            summary = re.sub('<[^<]+?>', '', summary)

            # Handle source which might be a list or a dict depending on feedparser version/feed structure
            source_data = entry.get('source', {})
            if source_data is None:
                source_data = {}
            elif isinstance(source_data, list):
                source_data = source_data[0] if source_data else {}
            
            source = source_data.get('title', 'Unknown Source')
            published = entry.get('published', 'Unknown Date')
            link = str(entry.link)
            
            # Extract actual URL from Bing redirect if present
            try:
                parsed = urlparse(link)
                params = parse_qs(parsed.query)
                if 'url' in params:
                    link = params['url'][0]
            except Exception as e:
                print(f"Warning: Could not parse Bing link {link}: {e}")
            
            # Scrape content
            print(f"Scraping article: {title[:30]}...")
            content = extract_article_content(link)
            
            # Fallback to summary if scraping fails
            if not content:
                content = summary
            else:
                # Truncate content to avoid token limits (e.g. 3000 chars)
                content = content[:3000] + "..." if len(content) > 3000 else content

            news_items.append({
                "title": title,
                "summary": summary,
                "source": source,
                "published": published,
                "content": content
            })
        return news_items
    except Exception as e:
        print(f"Error fetching news: {e}")
        return []

def analyze_market_status(market_data, news_items):
    """Queries LLM to analyze the market status."""
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY environment variable is not set.")

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )

    prompt = f"""
    You are 'The Canary', a cynical, data-driven financial analyst tracking the AI Bubble.
    
    **The Bubble Algorithm:**
    1. **Efficiency Check:** Compare AI Revenue Growth to Capex signals (inferred from news). If companies are spending heavily but revenue growth is slowing (<10%), Score +20 risk.
    2. **Valuation Check:** If NVDA PEG Ratio > 2.5 OR Trailing P/E > 70, Score +15 risk.
    3. **Adoption Check:** Scan news for 'Pilot Purgatory'. If non-tech firms are pausing/canceling AI projects, Score +25 risk.
    4. **Hardware Signals:** If news mentions 'easing supply' or 'reduced lead times' for GPUs, Score +20 risk (signaling demand drop).

    **Task:** Analyze the provided metrics and news. Calculate the total Risk Score (0-100).
    * 0-30: GREEN (Stable/Early Growth)
    * 31-69: YELLOW (Caution/Leaking)
    * 70-100: RED (Burst Imminent)

    Market Data:
    {json.dumps(market_data, indent=2)}

    Recent News:
    {json.dumps(news_items, indent=2)}

    Analyze the provided stock metrics and news content.
    The 'content' field contains the scraped text of the article (or a summary if scraping failed).
    Pay close attention to specific details, contradictions, or expert quotes in the text that indicate a *shift* in sentiment.

    Return a valid JSON object with EXACTLY this structure:
    {{
      "status": "GREEN" | "YELLOW" | "RED",
      "score": <integer 0-100>,
      "reasoning": "<string description of how the score was calculated based on the algorithm>",
      "metrics": {{
         "market_sentiment": "<Bullish/Bearish/Neutral/Mixed>",
         "top_headline": "<most relevant headline>"
      }}
    }}
    """

    models_to_try = [
        "openai/gpt-5.1",
        "google/gemini-2.0-flash-thinking-exp:free",
        "google/gemini-2.0-flash-thinking-exp",
        "google/gemini-2.0-flash-exp:free",
        "google/gemini-2.0-flash-exp",
        "google/gemini-exp-1206:free",
        "google/gemini-exp-1206",
        "google/gemini-1.5-flash",
        "google/gemini-flash-1.5-8b",
        "google/gemini-flash-1.5",
        "meta-llama/llama-3.1-70b-instruct"
    ]

    print("Querying LLM...")
    for model in models_to_try:
        try:
            print(f"Attempting with model: {model}")
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a financial analyst."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )
            
            content = completion.choices[0].message.content
            if not content:
                print(f"Warning: Model {model} returned empty content.")
                continue
            return json.loads(content)
        except Exception as e:
            print(f"Error with model {model}: {e}")
            continue
            
    raise RuntimeError("All models failed to generate a response.")

def update_history(analysis_result):
    """Appends the new analysis to the history file."""
    # Add date
    entry = analysis_result.copy()
    entry["date"] = datetime.datetime.now().isoformat()
    
    # Load existing
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                history = json.load(f)
        except json.JSONDecodeError:
            history = []
    else:
        history = []
        
    history.append(entry)
    
    # Write back
    # Ensure directory exists (though we made it, good practice)
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    
    with open(DATA_FILE, "w") as f:
        json.dump(history, f, indent=2)
    
    print(f"Updated {DATA_FILE} with new entry.")

def main():
    try:
        # 1. Fetch Data
        market_data = get_market_data()
        news_items = get_news_headlines()
        
        # 2. Analyze
        analysis_result = analyze_market_status(market_data, news_items)
        
        # Merge raw market data into the saved metrics to ensure we capture daily price moves
        # even if the LLM doesn't explicitly return them in its strict schema.
        # Also map legacy keys to maintain schema compatibility.
        if "metrics" in analysis_result:
            metrics = analysis_result["metrics"]
            metrics.update(market_data)
            
            # Map legacy keys if they exist in market_data
            if "NVDA_pe_ratio" in market_data:
                metrics["nvda_pe"] = str(market_data["NVDA_pe_ratio"])
            if "NVDA_revenue_growth" in market_data:
                metrics["revenue_growth"] = str(market_data["NVDA_revenue_growth"])
            if "NVDA_peg_ratio" in market_data:
                metrics["peg_ratio"] = str(market_data["NVDA_peg_ratio"])
        
        # 3. Save
        update_history(analysis_result)
        
    except Exception as e:
        print(f"Fatal Error: {e}")
        exit(1)

if __name__ == "__main__":
    main()
