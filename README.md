# Bull vs Bear ⚖️

Two AI analysts debate a US stock using **only SEC filings and market data**, citing every number they use. A judge then scores both sides and gives a verdict.

![App screenshot](docs/app.png)

## How it works

1. **Data.** Annual figures (revenue, net income, operating income, cash flow, capex, cash, debt, equity) come from SEC EDGAR's XBRL company facts API. Recent 10-K, 10-Q and 8-K filings are linked. Price, valuation multiples and the 1-year chart come from Yahoo Finance via `yfinance`.
2. **Fact sheet.** The app works out growth, margins, free cash flow, leverage, ROE and price stats, then writes them up as numbered facts (`[F1]`, `[F2]`, ...).
3. **Debate.** Claude plays a bull and a bear analyst: openings, then rebuttals. Each must cite fact ids and may not invent numbers.
4. **Verdict.** A judge model scores each side on evidence, logic and rebuttal and returns structured JSON. The app also checks every citation against the fact sheet and flags any fact id that doesn't exist.

With no API key set, a rule-based engine builds the arguments from the same metrics, so the app still runs.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Optional: put these in `.streamlit/secrets.toml` (see the example file):

- `ANTHROPIC_API_KEY`: turns on the AI debate.
- `SEC_USER_AGENT`: your name and email, as the SEC asks of API users.

## Tests

```bash
pytest -q
```

18 offline tests cover EDGAR parsing (full-year 10-K values only, latest restatement wins, concept fallbacks), metrics, the fact sheet, citation checks, the verdict parser and both debate engines.

## Project layout

```
app.py                 Streamlit UI
bullbear/edgar.py      SEC EDGAR: ticker -> CIK, annual figures, filings
bullbear/market.py     yfinance snapshot and price stats
bullbear/factsheet.py  metrics and the numbered fact sheet
bullbear/debate.py     Claude debate + judge, rule-based fallback
tests/                 pytest suite
```

Educational project, not investment advice. Built by Aafan Khan.
