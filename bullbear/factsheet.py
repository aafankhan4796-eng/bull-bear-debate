"""Turns raw EDGAR + market data into derived metrics and a numbered fact sheet.

Each fact gets an id (F1, F2, ...) so the debaters can cite it and the judge can check them.
"""

from typing import Optional


def _latest(series: dict) -> Optional[float]:
    return series[max(series)] if series else None


def _ratio(a, b) -> Optional[float]:
    if a is None or b in (None, 0):
        return None
    return a / b


def cagr(series: dict) -> Optional[float]:
    if len(series) < 2:
        return None
    ys = sorted(series)
    first, last, n = series[ys[0]], series[ys[-1]], ys[-1] - ys[0]
    if first <= 0 or last <= 0 or n <= 0:
        return None
    return (last / first) ** (1 / n) - 1


def yoy(series: dict) -> Optional[float]:
    if len(series) < 2:
        return None
    ys = sorted(series)
    prev, last = series[ys[-2]], series[ys[-1]]
    return (last - prev) / abs(prev) if prev else None


def metrics(fin: dict) -> dict:
    rev, ni, oi = fin.get("revenue", {}), fin.get("net_income", {}), fin.get("operating_income", {})
    ocf, capex = fin.get("operating_cash_flow", {}), fin.get("capex", {})
    fcf = {y: ocf[y] - capex.get(y, 0) for y in ocf}
    margin = {y: ni[y] / rev[y] for y in ni if rev.get(y)}
    op_margin = {y: oi[y] / rev[y] for y in oi if rev.get(y)}
    debt, cash = _latest(fin.get("long_term_debt", {})), _latest(fin.get("cash", {}))
    net_debt = (debt or 0) - (cash or 0) if (debt is not None or cash is not None) else None
    return {
        "revenue_latest": _latest(rev),
        "revenue_cagr": cagr(rev),
        "revenue_yoy": yoy(rev),
        "net_margin": _latest(margin),
        "net_margin_first": margin[min(margin)] if margin else None,
        "op_margin": _latest(op_margin),
        "fcf_latest": _latest(fcf),
        "fcf_margin": _ratio(_latest(fcf), _latest(rev)),
        "net_debt": net_debt,
        "net_debt_to_ocf": _ratio(net_debt, _latest(ocf)),
        "roe": _ratio(_latest(ni), _latest(fin.get("equity", {}))),
        "years": sorted(rev) if rev else [],
    }


def money(x: Optional[float]) -> str:
    if x is None:
        return "n/a"
    sign, x = ("-" if x < 0 else ""), abs(x)
    for div, unit in ((1e12, "tn"), (1e9, "bn"), (1e6, "m")):
        if x >= div:
            return f"{sign}${x / div:,.1f}{unit}"
    return f"{sign}${x:,.0f}"


def pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def num(x: Optional[float], suffix: str = "") -> str:
    return "n/a" if x is None else f"{x:,.1f}{suffix}"


def build_facts(name: str, ticker: str, fin: dict, m: dict, snap: dict) -> list[tuple[str, str]]:
    """[(id, text)] using only figures that exist."""
    lines: list[str] = []
    yrs = m.get("years") or []
    span = f"FY{yrs[0]}–FY{yrs[-1]}" if len(yrs) > 1 else ""
    if m["revenue_latest"] is not None:
        lines.append(f"Revenue in the latest fiscal year (10-K): {money(m['revenue_latest'])}.")
    if m["revenue_cagr"] is not None:
        lines.append(f"Revenue compound annual growth {span}: {pct(m['revenue_cagr'])}.")
    if m["revenue_yoy"] is not None:
        lines.append(f"Revenue growth in the latest year: {pct(m['revenue_yoy'])}.")
    if m["net_margin"] is not None:
        first = f" (was {pct(m['net_margin_first'])} in FY{yrs[0]})" if m["net_margin_first"] is not None and yrs else ""
        lines.append(f"Net profit margin, latest year: {pct(m['net_margin'])}{first}.")
    if m["op_margin"] is not None:
        lines.append(f"Operating margin, latest year: {pct(m['op_margin'])}.")
    if m["fcf_latest"] is not None:
        lines.append(f"Free cash flow (operating cash flow minus capex), latest year: {money(m['fcf_latest'])}"
                     f" = {pct(m['fcf_margin'])} of revenue.")
    if m["net_debt"] is not None:
        what = "net cash" if m["net_debt"] < 0 else "net debt"
        lines.append(f"Long-term debt minus cash: {money(m['net_debt'])} ({what}); "
                     f"{num(m['net_debt_to_ocf'], 'x')} operating cash flow.")
    if m["roe"] is not None:
        lines.append(f"Return on equity, latest year: {pct(m['roe'])}.")
    s = snap or {}
    if s.get("price") is not None:
        lines.append(f"Share price: {num(s['price'])} {s.get('currency') or ''}; market cap {money(s.get('market_cap'))}.".replace("  ", " "))
    if s.get("trailing_pe") is not None or s.get("forward_pe") is not None:
        lines.append(f"P/E: trailing {num(s.get('trailing_pe'), 'x')}, forward {num(s.get('forward_pe'), 'x')}.")
    if s.get("ev_to_ebitda") is not None:
        lines.append(f"EV/EBITDA: {num(s['ev_to_ebitda'], 'x')}; price/sales {num(s.get('price_to_sales'), 'x')}.")
    if s.get("return_1y") is not None:
        lines.append(f"Share price over the last year: {pct(s['return_1y'])}; max drawdown {pct(s['max_drawdown'])}; "
                     f"volatility {pct(s['volatility'])} a year.")
    if s.get("week52_high") is not None and s.get("price") is not None:
        lines.append(f"Price is {pct(s['price'] / s['week52_high'] - 1)} vs the 52-week high of {num(s['week52_high'])}.")
    if s.get("target_mean") is not None and s.get("price") is not None:
        lines.append(f"Average analyst target {num(s['target_mean'])} ({pct(s['target_mean'] / s['price'] - 1)} vs price); "
                     f"consensus '{s.get('recommendation') or 'n/a'}'.")
    if s.get("beta") is not None:
        lines.append(f"Beta: {num(s['beta'])}.")
    if s.get("sector"):
        lines.append(f"Sector: {s['sector']} / {s.get('industry') or 'n/a'}.")
    return [(f"F{i + 1}", t) for i, t in enumerate(lines)]


def facts_text(name: str, ticker: str, facts: list[tuple[str, str]]) -> str:
    return f"FACT SHEET — {name} ({ticker.upper()})\n" + "\n".join(f"[{i}] {t}" for i, t in facts)
