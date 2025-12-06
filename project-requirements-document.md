# Product Requirements Document (PRD): "The Canary"

**Version:** 1.2
**Type:** Serverless AI Agent & Dashboard
**Tech Stack:** Python, GitHub Actions, GitHub Pages, OpenRouter API

## 1. Project Overview

**Objective:** Build an autonomous, zero-maintenance market monitor that tracks the health of the "AI Financial Bubble." The system runs once daily to fetch financial data and news, uses an LLM to analyze market sentiment and stability, and publishes the results to a public dashboard.

**Core Philosophy:** "Zero Infrastructure, Zero Maintenance."

* **No Backend Server:** We use GitHub Actions as the runtime.
* **No Database:** We use the Git repository itself as the database.
* **No Hosting Cost:** We use GitHub Pages for the frontend.

## 2. System Architecture

The system follows a "Git-as-Backend" architecture pattern.

### Components

1. **The Scheduler (GitHub Actions):** A workflow defined in `.github/workflows/daily.yml` that triggers automatically at market close (21:00 UTC).

2. **The Agent (`src/agent.py`):** A Python script that performs the "Check-Think-Save" loop.

3. **The Database (`data/status_history.json`):** A flat JSON file stored in the repository containing the historical record of daily checks.

4. **The Dashboard (`index.html`):** A static HTML file hosted on GitHub Pages that fetches the raw JSON content to render the UI.

## 3. Data Structures

### 3.1 The Database (`data/status_history.json`)

The agent must append a new object to this array daily. The frontend relies on this specific schema.

```json
[
  {
    "date": "2025-12-05T10:30:00.000",
    "status": "YELLOW",
    "score": 65,
    "reasoning": "Nvidia volatility is high (45.2) and news sentiment is mixed due to stalled pilots.",
    "metrics": {
      "nvda_price": 145.20,
      "nvda_pe_ratio": 65.4,
      "nvda_revenue_growth": 0.12,
      "market_sentiment": "Bearish",
      "top_headline": "Global banks pause AI rollout"
    }
  }
]
```

**Schema Notes:**

* `status`: Enum ["GREEN", "YELLOW", "RED"]
* `score`: Integer 0-100 (0 = Safe, 100 = Crash Imminent)
* `date`: ISO 8601 Timestamp (e.g., `2025-12-05T10:30:00`)

## 4. Functional Requirements (Backend)

### 4.1 The Agent Script (`src/agent.py`)

**Dependency Constraints:**

* `yfinance` (v0.2.50+ for stable API access)
* `feedparser` (v6.0.11+ for RSS parsing)
* `trafilatura` (For scraping full article content)
* `fake-useragent` (CRITICAL: To rotate headers and avoid 403 blocks)
* `requests` (for HTTP requests)
* `openai` (v1.57+ configured for OpenRouter)

**Logic Flow:**

1. **Fetch Market Data (Fundamentals):**

   * **Tickers:** `NVDA` (Hardware Bellwether), `MSFT` (Software/Capex Proxy), `GOOGL` (Model Competitor).
   * **Technicals:** Closing Price, Volatility (StdDev of last 5 days).
   * **Fundamentals (via `ticker.info`):**
     * `trailingPE`: Price-to-Earnings Ratio.
     * `forwardPE`: Expected future valuation.
     * `revenueGrowth`: YoY Revenue Growth.
     * `pegRatio`: Price/Earnings-to-Growth (Key for bubble detection; >2.0 often signals overvaluation).

2. **Fetch News Data (The Hybrid Mining Strategy):**

   * **Source:** Google News RSS.
   * **Query:** `https://news.google.com/rss/search?q=AI+adoption+OR+AI+bubble+when:1d&hl=en-US&gl=US&ceid=US:en`
   * **Extraction Logic (Robustness):**
     * Iterate through Top 5 headlines.
     * **Attempt 1 (Deep Dive):** Use `trafilatura.fetch_url(url)` with a random `User-Agent` header to scrape the full body.
     * **Fallback (Safety Net):** If scraping fails (returns None, 403, or empty string), default to using the RSS `description` field.
     * **Token Optimization:** Truncate all scraped text to 3,000 characters max per article to prevent context window overflow.

3. **Intelligence (LLM Analysis):**

   * **API Provider:** OpenRouter
   * **Base URL:** `https://openrouter.ai/api/v1`
   * **Model:** Prioritize `openai/gpt-5.1` or `google/gemini-2.0-flash-thinking-exp`.
   * **System Prompt:**

     > "You are 'The Canary', a cynical, data-driven financial analyst tracking the AI Bubble.
     > **The Bubble Algorithm:**
     > 1. **Efficiency Check:** Compare AI Revenue Growth to Capex signals (inferred from news). If companies are spending heavily but revenue growth is slowing (<10%), Score +20 risk.
     > 2. **Valuation Check:** If NVDA PEG Ratio > 2.5 OR Trailing P/E > 70, Score +15 risk.
     > 3. **Adoption Check:** Scan news for 'Pilot Purgatory'. If non-tech firms are pausing/canceling AI projects, Score +25 risk.
     > 4. **Hardware Signals:** If news mentions 'easing supply' or 'reduced lead times' for GPUs, Score +20 risk (signaling demand drop).
     >
     > **Task:** Analyze the provided metrics and news. Calculate the total Risk Score (0-100).
     > * 0-30: GREEN (Stable/Early Growth)
     > * 31-69: YELLOW (Caution/Leaking)
     > * 70-100: RED (Burst Imminent)
     >
     > Output valid JSON only."

4. **Persistence:**

   * Load the existing `data/status_history.json`.
   * Append the new entry.
   * Save the file back to disk.

### 4.2 The Workflow (`.github/workflows/daily.yml`)

**Triggers:**

* **Schedule:** Cron `0 21 * * *` (Runs daily at 9 PM UTC).
* **Manual:** `workflow_dispatch` (Allows manual trigger for testing).

**Job Steps:**

1. Checkout repository.
2. Install Python 3.10.
3. Install dependencies (`pip install -r requirements.txt`).
4. Run `python src/agent.py`.
   * **Env Var:** Inject `OPENROUTER_API_KEY` from repository secrets.
5. Commit and Push changes:
   * Config user as "AI Agent".
   * Commit message: "Daily Update: [Date]".

## 5. Functional Requirements (Frontend)

### 5.1 The Dashboard (`index.html`)

**Constraints:** Single HTML file. No build step. Use CDN for all libraries.

**Libraries:**

* **Tailwind CSS:** `<script src="https://cdn.tailwindcss.com"></script>`
* **Chart.js:** `<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>`

**UI Logic:**

1. **Data Fetching:** On load, fetch `data/status_history.json`.

2. **Current Status Card:**
   * Display the **Latest Status** (GREEN, YELLOW, RED).
   * **Dynamic Styling:**
     * Red: `bg-red-500` (Text: "CRITICAL WARNING")
     * Yellow: `bg-yellow-500` (Text: "CAUTION")
     * Green: `bg-green-500` (Text: "STABLE")

3. **Trend Graph:**
   * Render a Line Chart showing the `score` (Y-axis) over the `date` (X-axis) for the last 30 entries.

4. **Reasoning Section:**
   * Display the `reasoning` text block from the latest entry.

5. **Metrics Grid:**
   * Display a small grid showing `NVDA P/E`, `Revenue Growth`, and `Market Sentiment` pulled from the latest JSON entry.

## 6. Implementation Prompt for AI Coding Agent

*Copy and paste the text below into your AI coding tool (Cursor/Windsurf/Copilot) to generate the project.*

> "Act as a Senior Python Developer and DevOps Engineer. I need to scaffold a serverless repository for 'The Canary', an AI Market Monitor.
>
> 1. **Setup Structure**: Create folders `src/`, `data/`, and `.github/workflows/`. Create an empty `data/status_history.json` initialized with `[]`.
>
> 2. **Dependencies**: Create `requirements.txt` with `yfinance`, `feedparser`, `trafilatura`, `fake-useragent`, `openai`, `pandas`.
>
> 3. **The Agent (`src/agent.py`)**:
>    * Use `os.environ.get("OPENROUTER_API_KEY")` for authentication.
>    * Initialize `openai.OpenAI` client with `base_url="https://openrouter.ai/api/v1"`.
>    * **Market Data:** Fetch `trailingPE`, `revenueGrowth`, `pegRatio`, and `currentPrice` for NVDA/MSFT using `yfinance`.
>    * **News Data:** Fetch Google News RSS. Iterate top 5 items. TRY to scrape full content with `trafilatura` (using random user-agent). IF scraping fails/returns empty, fallback to RSS `summary`. Limit content to 3000 chars.
>    * **Analysis:** Send this to `google/gemini-2.0-flash-thinking-exp`. Use the 'Bubble Algorithm' system prompt defined in the PRD (Efficiency, Valuation, Adoption, Hardware checks) to output a JSON with `status`, `score`, and `reasoning`.
>    * Append this result to `data/status_history.json`.
>
> 4. **The Workflow (`.github/workflows/daily.yml`)**:
>    * Schedule it for 21:00 UTC daily.
>    * Include steps to install python, install requirements, run the script, and commit the changes back to the repo.
>
> 5. **The Dashboard (`index.html`)**:
>    * Create a clean, dark-mode UI using Tailwind CSS via CDN.
>    * Fetch the JSON file. Display the Status Card, the Reasoning text, and a metrics grid (P/E, Growth).
>    * Use Chart.js to plot the history of the 'score'."

## 7. Success Metrics

* **Reliability:** The GitHub Action runs successfully 7/7 days a week.
* **Cost Efficiency:** Monthly OpenRouter costs stay below $0.10.
* **Latency:** The Dashboard loads and renders data in < 1 second.

## 8. Non-Functional Requirements

* **Security:** API Keys must **never** be hardcoded. They must only be accessed via `os.environ`.
* **Error Handling:** If the LLM API fails or returns malformed JSON, the script must exit with an error code and **not** corrupt the `status_history.json` file.
