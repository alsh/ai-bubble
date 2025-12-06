# Product Requirements Document (PRD): "The Canary"

**Version:** 1.0
**Type:** Serverless AI Agent & Dashboard
**Tech Stack:** Python, GitHub Actions, GitHub Pages, OpenRouter API

---

## 1. Project Overview

**Objective:** Build an autonomous, zero-maintenance market monitor that tracks the health of the "AI Financial Bubble." The system runs once daily to fetch financial data and news, uses an LLM to analyze market sentiment and stability, and publishes the results to a public dashboard.

**Core Philosophy:** "Zero Infrastructure, Zero Maintenance."

* **No Backend Server:** We use GitHub Actions as the runtime.
* **No Database:** We use the Git repository itself as the database.
* **No Hosting Cost:** We use GitHub Pages for the frontend.

---

## 2. System Architecture

The system follows a "Git-as-Backend" architecture pattern.

### Components

1.  **The Scheduler (GitHub Actions):** A workflow defined in `.github/workflows/daily.yml` that triggers automatically at market close (21:00 UTC).

2.  **The Agent (`src/agent.py`):** A Python script that performs the "Check-Think-Save" loop.

3.  **The Database (`data/status_history.json`):** A flat JSON file stored in the repository containing the historical record of daily checks.

4.  **The Dashboard (`index.html`):** A static HTML file hosted on GitHub Pages that fetches the raw JSON content to render the UI.

---

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
      "nvda_volatility": 45.2,
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

---

## 4. Functional Requirements (Backend)

### 4.1 The Agent Script (`src/agent.py`)

**Dependency Constraints:**
* `yfinance` (v0.2.50+ for stable API access)
* `feedparser` (v6.0.11+ for RSS parsing)
* `trafilatura` (For scraping full article content)
* `requests` (for HTTP requests)
* `openai` (v1.57+ configured for OpenRouter)

**Logic Flow:**

1.  **Fetch Market Data:**
    * Use `yfinance` to get the closing price of `NVDA` (Nvidia), `MSFT` (Microsoft), and `GOOGL` (Google).
    * Calculate **Volatility** (Standard Deviation of the last 5 days' closing prices).

2.  **Fetch News Data:**
    * Use `feedparser` to scrape the Google News RSS feed.
    * **Query:** `https://news.google.com/rss/search?q=AI+adoption+OR+AI+bubble+when:1d&hl=en-US&gl=US&ceid=US:en`
    * Extract the top 5 headlines.
    * **Full Content Scraping:** For each headline, extract the URL and use `trafilatura` to scrape the article body text (truncated to ~2000 chars) to provide deep context.

3.  **Intelligence (LLM Analysis):**
    * **API Provider:** OpenRouter
    * **Base URL:** `https://openrouter.ai/api/v1`
    * **API Provider:** OpenRouter
    * **Base URL:** `https://openrouter.ai/api/v1`
    * **Model:** Prioritize `openai/gpt-5.1` or `google/gemini-2.0-flash-thinking-exp` for deep reasoning capability.
    * **System Prompt:** "You are a cynical, data-driven financial analyst tracking the *AI Bubble*. Your goal is to assess the risk of this bubble *bursting*. Analyze the provided stock metrics and *full news article content*. Look for specific contradictions or signs of hype fatigue."

4.  **Persistence:**
    * Load the existing `data/status_history.json`.
    * Append the new entry.
    * Save the file back to disk.

### 4.2 The Workflow (`.github/workflows/daily.yml`)

**Triggers:**
* **Schedule:** Cron `0 21 * * *` (Runs daily at 9 PM UTC).
* **Manual:** `workflow_dispatch` (Allows manual trigger for testing).

**Job Steps:**
1.  Checkout repository.
2.  Install Python 3.10.
3.  Install dependencies (`pip install -r requirements.txt`).
4.  Run `python src/agent.py`.
    * **Env Var:** Inject `OPENROUTER_API_KEY` from repository secrets.
5.  Commit and Push changes:
    * Config user as "AI Agent".
    * Commit message: "Daily Update: [Date]".

---

## 5. Functional Requirements (Frontend)

### 5.1 The Dashboard (`index.html`)

**Constraints:** Single HTML file. No build step. Use CDN for all libraries.

**Libraries:**
* **Tailwind CSS:** `<script src="https://cdn.tailwindcss.com"></script>`
* **Chart.js:** `<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>`

**UI Logic:**
1.  **Data Fetching:** On load, fetch `data/status_history.json`.
2.  **Current Status Card:**
    * Display the **Latest Status** (GREEN, YELLOW, RED).
    * **Dynamic Styling:**
        * Red: `bg-red-500` (Text: "CRITICAL WARNING")
        * Yellow: `bg-yellow-500` (Text: "CAUTION")
        * Green: `bg-green-500` (Text: "STABLE")
3.  **Trend Graph:**
    * Render a Line Chart showing the `score` (Y-axis) over the `date` (X-axis) for the last 30 entries.
4.  **Reasoning Section:**
    * Display the `reasoning` text block from the latest entry to explain *why* the status is what it is.

---

## 6. Implementation Prompt for AI Coding Agent

*Copy and paste the text below into your AI coding tool (Cursor/Windsurf/Copilot) to generate the project.*

> "Act as a Senior Python Developer and DevOps Engineer. I need to scaffold a serverless repository for 'The Canary', an AI Market Monitor.
>
> 1.  **Setup Structure**: Create folders `src/`, `data/`, and `.github/workflows/`. Create an empty `data/status_history.json` initialized with `[]`.
> 2.  **Dependencies**: Create `requirements.txt` with `yfinance`, `feedparser`, `openai`, `pandas`.
> 3.  **The Agent (`src/agent.py`)**:
>     * Use `os.environ.get("OPENROUTER_API_KEY")` for authentication.
>     * Initialize the `openai.OpenAI` client with `base_url="https://openrouter.ai/api/v1"`.
>     * Fetch NVDA/MSFT prices (using yfinance) and Google News RSS (using feedparser).
>     * Send this data to the model `google/gemini-flash-1.5`. Ask it to return a JSON with keys: `status` (GREEN/YELLOW/RED), `score` (0-100), `reasoning` (string), and `metrics` (dict).
>     * Append this result to `data/status_history.json`.
> 4.  **The Workflow (`.github/workflows/daily.yml`)**:
>     * Schedule it for 21:00 UTC daily.
>     * Include steps to install python, install requirements, run the script, and commit the changes back to the repo.
> 5.  **The Dashboard (`index.html`)**:
>     * Create a clean, dark-mode UI using Tailwind CSS via CDN.
>     * Fetch the JSON file and display the latest status, score, and reasoning.
>     * Use Chart.js to plot the history of the 'score'."

---

## 7. Success Metrics

* **Reliability:** The GitHub Action runs successfully 7/7 days a week.
* **Cost Efficiency:** Monthly OpenRouter costs stay below $0.10.
* **Latency:** The Dashboard loads and renders data in < 1 second.

## 8. Non-Functional Requirements

* **Security:** API Keys must **never** be hardcoded. They must only be accessed via `os.environ`.
* **Error Handling:** If the LLM API fails or returns malformed JSON, the script must exit with an error code and **not** corrupt the `status_history.json` file.
