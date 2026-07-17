# The Canary 🐦
**AI Market Monitor for the "AI Bubble"**

A serverless, zero-maintenance AI agent that tracks the health of the AI financial market. It runs daily on GitHub Actions, analyzes market data and news using an LLM, and publishes a risk score to a public dashboard.

## 🚀 Features
- **Zero Infrastructure**: Runs entirely on GitHub Actions and GitHub Pages.
- **AI Analyst**: Publishes a versioned editorial opinion about how fragile the AI investment boom is to a meaningful correction over the next 6–12 months. Confidence is the model's judgment; data quality is an independent collection measure.
- **Data-Driven**: Tracks volatility of major AI stocks (NVDA, MSFT, GOOGL) and global news sentiment.
- **Visual Dashboard**: Beautiful, dark-mode UI to visualize the "Risk Score" trend.

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
    This will generate a new entry in `data/status_history.json`. The default requested model is OpenRouter's `~openai/gpt-latest` alias: it means the newest eligible OpenAI GPT model selected by OpenRouter, not a fixed model name. Set `OPENROUTER_MODEL` to an exact slug for controlled testing or rollback. Each v2 entry records both requested and concrete resolved model identities and the `canary-opinion-v2` methodology.

    A score is an editorial opinion, not a calibrated probability or investment recommendation. Status is derived from score (0–30 GREEN, 31–69 YELLOW, 70–100 RED). Evidence quality is reported separately: articles published within the 48-hour freshness window count as fresh; missing collection inputs are marked degraded. A completely empty evidence packet is rejected.
3.  **View Dashboard**:
    Because of browser security (CORS), checking `index.html` directly from the file system won't work. Serve it locally:
    ```bash
    python -m http.server
    ```
    Then open [http://localhost:8000](http://localhost:8000) in your browser.

### 4. GitHub Deployment (Automated)
To enable the daily automatic updates:

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

Once the workflow finishes, your dashboard will be live at `https://<your-username>.github.io/ai-bubble/`.
