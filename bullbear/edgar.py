"""SEC EDGAR: ticker -> CIK, annual figures from XBRL company facts, and recent filings.

The SEC asks every client to send a User-Agent with a name and contact address and to stay
under 10 requests a second. Set SEC_USER_AGENT (env var or Streamlit secret) to your own.
"""

import os
from typing import Optional

import requests

DEFAULT_UA = "bull-bear-debate research demo (github.com/aafankhan4796-eng/bull-bear-debate)"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# First concept that has data wins (companies tag the same idea differently).
CONCEPTS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss"],
    "operating_income": ["OperatingIncomeLoss"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "equity": ["StockholdersEquity"],
}


def _get(url: str, user_agent: Optional[str] = None) -> dict:
    ua = user_agent or os.getenv("SEC_USER_AGENT") or DEFAULT_UA
    r = requests.get(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}, timeout=20)
    r.raise_for_status()
    return r.json()


def ticker_to_cik(ticker: str, tickers_json: Optional[dict] = None, user_agent: Optional[str] = None):
    """Returns (cik as 10-digit string, company name) or (None, None)."""
    data = tickers_json if tickers_json is not None else _get(TICKERS_URL, user_agent)
    t = ticker.strip().upper()
    for row in data.values():
        if str(row.get("ticker", "")).upper() == t:
            return str(row["cik_str"]).zfill(10), row.get("title", t)
    return None, None


def annual_series(facts: dict, concept_names: list[str], years: int = 5) -> dict[int, float]:
    """{fiscal_year: value} from 10-K full-year figures, latest filing per year, newest `years` years."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for name in concept_names:
        units = gaap.get(name, {}).get("units", {})
        rows = units.get("USD") or next(iter(units.values()), [])
        best: dict[int, tuple] = {}
        for r in rows:
            if r.get("form") not in ("10-K", "10-K/A", "20-F") or r.get("fp") != "FY":
                continue
            end = r.get("end", "")
            start = r.get("start")
            # flow items carry a start date; keep only ~12-month periods
            if start and not _is_full_year(start, end):
                continue
            year = int(end[:4]) if end else r.get("fy")
            key = (r.get("filed", ""), end)
            if year not in best or key > best[year][0]:
                best[year] = (key, float(r["val"]))
        if best:
            ys = sorted(best)[-years:]
            return {y: best[y][1] for y in ys}
    return {}


def _is_full_year(start: str, end: str) -> bool:
    try:
        sy, sm = int(start[:4]), int(start[5:7])
        ey, em = int(end[:4]), int(end[5:7])
    except (ValueError, IndexError):
        return True
    months = (ey - sy) * 12 + (em - sm)
    return 11 <= months <= 13


def financials(facts: dict, years: int = 5) -> dict[str, dict[int, float]]:
    return {k: annual_series(facts, v, years) for k, v in CONCEPTS.items()}


def recent_filings(submissions: dict, forms=("10-K", "10-Q", "8-K"), limit: int = 8) -> list[dict]:
    recent = submissions.get("filings", {}).get("recent", {})
    cik = str(submissions.get("cik", "")).lstrip("0")
    out = []
    for i, form in enumerate(recent.get("form", [])):
        if form not in forms:
            continue
        acc = recent["accessionNumber"][i]
        doc = recent.get("primaryDocument", [""] * (i + 1))[i]
        out.append({
            "form": form,
            "filed": recent["filingDate"][i],
            "description": (recent.get("primaryDocDescription") or [""] * (i + 1))[i] or form,
            "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}",
        })
        if len(out) >= limit:
            break
    return out


def load_company(ticker: str, user_agent: Optional[str] = None) -> dict:
    """Everything the app needs from EDGAR for one ticker. Raises ValueError for unknown tickers."""
    cik, name = ticker_to_cik(ticker, user_agent=user_agent)
    if not cik:
        raise ValueError(f"{ticker.upper()} isn't in SEC's ticker list (US-listed companies only).")
    facts = _get(FACTS_URL.format(cik=cik), user_agent)
    subs = _get(SUBMISSIONS_URL.format(cik=cik), user_agent)
    return {"cik": cik, "name": name, "financials": financials(facts), "filings": recent_filings(subs)}
