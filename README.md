# The Canary 🐦
**AI Market Monitor for the "AI Bubble"**

A serverless AI agent that tracks the health of the AI financial market. It runs daily on GitHub Actions, analyzes market data and news using an LLM, and publishes an editorial risk score to a public dashboard. An optional experimental Power exponents panel graphs market-return diagnostics separately from that score.

## 🚀 Features
- **Zero Infrastructure**: Runs entirely on GitHub Actions and GitHub Pages.
- **AI Analyst**: Publishes a versioned editorial opinion about how fragile the AI investment boom is to a meaningful correction over the next 6–12 months. Confidence is the model's judgment; data quality is an independent collection measure.
- **Data-Driven**: Tracks volatility of major AI stocks (NVDA, MSFT, GOOGL) and global news sentiment.
- **Visual Dashboard**: Dark-mode UI with a historical editorial risk-score graph.
- **Interactive History**: The score graph shows 30 points at a time. Use **Older** and **Newer** to browse all history. Select a point to view its opinion and metrics, or select **Show current data** to return to the latest entry.
- **Experimental power exponents**: Optional, separate H and tail-alpha graphs for QQQ, SOXX, NVDA, and SPY. These are descriptive research diagnostics, not crash forecasts, and do not change the editorial score.

## 🛠️ Setup & Deployment

### 1. Fork & Clone
Fork this repository to your GitHub account and clone it locally.

### 2. Get an API Key
You need an API key from [OpenRouter](https://openrouter.ai/) to access the LLM.

### 3. Local Usage
1.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
2.  **Run the Agent**:
    ```bash
    export OPENROUTER_API_KEY="your_key_here"
    python src/agent.py
    ```
    This adds a new entry to the file for the current UTC month: `data/status_history/YYYY-MM.json`. If `data/status_history.json` exists, the agent moves its records into monthly files on its next run. The small `data/status_history/index.json` file lists the months for the dashboard. Agent writes bounded derived diagnostics to `data/power_exponents.json` without publishing raw prices. Review [the methodology and data-use limits](docs/power-exponents.md) before enabling it.

    The default requested model is OpenRouter's `~openai/gpt-latest` alias: it means the newest eligible OpenAI GPT model selected by OpenRouter, not a fixed model name. Set `OPENROUTER_MODEL` to an exact slug for controlled testing or rollback. Each v2 entry records both requested and concrete resolved model identities and the `canary-opinion-v2` methodology.

    A score is an editorial opinion, not a calibrated probability or investment recommendation. Status is derived from score (0–30 GREEN, 31–69 YELLOW, 70–100 RED). Evidence quality is reported separately: articles published within the 48-hour freshness window count as fresh; missing collection inputs are marked degraded. A completely empty evidence packet is rejected. Power-exponent diagnostics remain outside the LLM prompt and score. The underlying Yahoo Finance/yfinance feed is unofficial; enabling publication requires the operator to verify applicable provider and exchange terms.
3.  **View Dashboard**:
    Because of browser security (CORS), checking `index.html` directly from the file system won't work. Serve it locally:
    ```bash
    python -m http.server
    ```
    Then open [http://localhost:8000](http://localhost:8000) in your browser.

### Run Tests
The test suite uses Python's built-in `unittest` framework:
```bash
python -m unittest discover -s tests -v
```
In VS Code, select the project's Python environment and use **Python: Configure Tests** to select **unittest** with `tests` as the test directory if the Test Explorer has not already discovered the tests.

### 4. GitHub Deployment (Automated)
To enable daily automatic updates, follow these steps. The workflow runs at 22:00 UTC, after the US regular equity close in both standard and daylight-saving time:

1.  **Add Secret**:
    - Go to your repo **Settings** -> **Secrets and variables** -> **Actions**.
    - Click **New repository secret**.
    - Name: `OPENROUTER_API_KEY`
    - Value: `sk-or-v1-...` (your actual key).

2.  **Enable GitHub Pages**:
    - Go to **Settings** -> **Pages**.
    - Under **Build and deployment** -> **Source**, select **Deploy from a branch**.
    - Select **Branch**: `main`, **Folder**: `/(root)`.
    - Click **Save**.

3.  **Permissions** (Important!):
    - Go to **Settings** -> **Actions** -> **General**.
    - Scroll to **Workflow permissions**.
    - Select **Read and write permissions**.
    - Click **Save**.

4.  **Test It**:
    - Go to the **Actions** tab.
    - Select "Daily Market Check".
    - Click **Run workflow**.

Once the workflow finishes, your dashboard will be live at `https://<your-username>.github.io/ai-bubble/`. The indicator graphs load independently and show an unavailable message until an artifact has been published. The daily agent schedule also requires an `OPENROUTER_API_KEY`; enabling market diagnostics does not bypass the opinion run.
