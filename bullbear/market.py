"""Market data from Yahoo Finance via yfinance. Every call fails soft: missing data comes back as None."""

from typing import Optional

import pandas as pd

FIELDS = {
    "price": "currentPrice",
    "market_cap": "marketCap",
    "trailing_pe": "trailingPE",
    "forward_pe": "forwardPE",
    "ev_to_ebitda": "enterpriseToEbitda",
    "price_to_sales": "priceToSalesTrailing12Months",
    "dividend_yield": "dividendYield",
    "beta": "beta",
    "week52_high": "fiftyTwoWeekHigh",
    "week52_low": "fiftyTwoWeekLow",
    "target_mean": "targetMeanPrice",
    "recommendation": "recommendationKey",
    "sector": "sector",
    "industry": "industry",
    "currency": "currency",
}


def snapshot_from_info(info: dict) -> dict:
    snap = {k: info.get(v) for k, v in FIELDS.items()}
    if snap["price"] is None:
        snap["price"] = info.get("regularMarketPrice") or info.get("previousClose")
    return snap


def price_stats(history: pd.DataFrame) -> dict:
    """1-year return, max drawdown and annualised volatility from a daily Close series."""
    if history is None or history.empty or "Close" not in history:
        return {}
    close = history["Close"].dropna()
    if len(close) < 20:
        return {}
    rets = close.pct_change().dropna()
    drawdown = (close / close.cummax() - 1).min()
    return {
        "return_1y": float(close.iloc[-1] / close.iloc[0] - 1),
        "max_drawdown": float(drawdown),
        "volatility": float(rets.std() * (252 ** 0.5)),
    }


def load_market(ticker: str) -> tuple[dict, Optional[pd.DataFrame]]:
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        try:
            info = t.info or {}
        except Exception:
            info = {}
        try:
            hist = t.history(period="1y", auto_adjust=True)
        except Exception:
            hist = None
        snap = snapshot_from_info(info)
        snap.update(price_stats(hist))
        return snap, hist
    except Exception:
        return {}, None
