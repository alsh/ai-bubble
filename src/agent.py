
import os
import json
import datetime
import yfinance as yf
import feedparser
from openai import OpenAI

# Configuration
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
DATA_FILE = "data/status_history.json"
RSS_FEED_URL = "https://news.google.com/rss/search?q=AI+adoption+OR+AI+bubble+when:1d&hl=en-US&gl=US&ceid=US:en"

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
            
            if not hist.empty:
                current_price = hist["Close"].iloc[-1]
                data[f"{ticker}_price"] = round(current_price, 2)
                
                # Calculate volatility (std dev of prices) for NVDA specifically as per PRD example
                if ticker == "NVDA":
                    volatility = hist["Close"].std()
                    data[f"{ticker}_volatility"] = round(volatility, 2)
            else:
                print(f"Warning: No history found for {ticker}")
                
        except Exception as e:
            print(f"Error fetching {ticker}: {e}")
            
    return data

def get_news_headlines():
    """Fetches top 5 headlines from Google News RSS."""
    print("Fetching news headlines...")
    try:
        feed = feedparser.parse(RSS_FEED_URL)
        headlines = []
        for entry in feed.entries[:5]:
            title = entry.title
            # Basic cleanup if needed, often title is sufficient
            headlines.append(title)
        return headlines
    except Exception as e:
        print(f"Error fetching news: {e}")
        return []

def analyze_market_status(market_data, headlines):
    """Queries LLM to analyze the market status."""
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY environment variable is not set.")

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )

    prompt = f"""
    You are a cynical, data-driven financial analyst tracking the AI bubble.

    Market Data:
    {json.dumps(market_data, indent=2)}

    Recent News Headlines:
    {json.dumps(headlines, indent=2)}

    Analyze the provided stock metrics and news headlines.
    Determine the market status (GREEN, YELLOW, or RED) and a risk score (0-100).
    Provide a concise reasoning string explaining the decision.

    Return a valid JSON object with EXACTLY this structure:
    {{
      "status": "GREEN" | "YELLOW" | "RED",
      "score": <integer 0-100>,
      "reasoning": "<string description>",
      "metrics": {{
         ... <include relevant metrics from input> ...
         "market_sentiment": "<Bullish/Bearish/Neutral/Mixed>",
         "top_headline": "<most relevant headline>"
      }}
    }}
    """

    models_to_try = [
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
    entry["date"] = datetime.date.today().isoformat()
    
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
        headlines = get_news_headlines()
        
        # 2. Analyze
        analysis_result = analyze_market_status(market_data, headlines)
        
        # 3. Save
        update_history(analysis_result)
        
    except Exception as e:
        print(f"Fatal Error: {e}")
        exit(1)

if __name__ == "__main__":
    main()
