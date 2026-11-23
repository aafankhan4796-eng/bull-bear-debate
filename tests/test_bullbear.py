import json

import pandas as pd
import pytest

from bullbear import debate, edgar, factsheet, market


def fy(val, year, start=True, form="10-K", filed=None, months=12):
    row = {"val": val, "end": f"{year}-12-31", "fy": year, "fp": "FY", "form": form,
           "filed": filed or f"{year + 1}-02-15"}
    if start:
        sm = 13 - months
        row["start"] = f"{year if months < 12 else year}-{sm:02d}-01" if months < 12 else f"{year}-01-01"
    return row


FACTS = {"facts": {"us-gaap": {
    "Revenues": {"units": {"USD": [fy(100e9, 2021), fy(110e9, 2022), fy(121e9, 2023),
                                   fy(30e9, 2023, months=3),  # quarter inside a 10-K: must be ignored
                                   fy(999, 2023, form="10-Q")]}},
    "NetIncomeLoss": {"units": {"USD": [fy(10e9, 2021), fy(14e9, 2022), fy(18e9, 2023)]}},
    "OperatingIncomeLoss": {"units": {"USD": [fy(24e9, 2023)]}},
    "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [fy(25e9, 2023)]}},
    "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [fy(5e9, 2023)]}},
    "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [fy(40e9, 2023, start=False)]}},
    "LongTermDebtNoncurrent": {"units": {"USD": [fy(30e9, 2023, start=False)]}},
    "StockholdersEquity": {"units": {"USD": [fy(60e9, 2023, start=False)]}},
}}}

SNAP = {"price": 150.0, "market_cap": 2.4e12, "forward_pe": 40.0, "trailing_pe": 45.0, "return_1y": 0.3,
        "max_drawdown": -0.12, "volatility": 0.25, "week52_high": 160.0, "target_mean": 170.0,
        "recommendation": "buy", "currency": "USD"}


def test_ticker_lookup():
    data = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
    assert edgar.ticker_to_cik("aapl", data) == ("0000320193", "Apple Inc.")
    assert edgar.ticker_to_cik("ZZZZ", data) == (None, None)


def test_annual_series_ignores_quarters_and_10q():
    s = edgar.annual_series(FACTS, edgar.CONCEPTS["revenue"])
    assert s == {2021: 100e9, 2022: 110e9, 2023: 121e9}


def test_annual_series_prefers_latest_filing():
    f = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": [
        fy(5, 2023, filed="2024-02-01"), fy(6, 2023, filed="2025-02-01")]}}}}}
    assert edgar.annual_series(f, ["NetIncomeLoss"]) == {2023: 6}


def test_concept_fallback():
    f = {"facts": {"us-gaap": {"SalesRevenueNet": {"units": {"USD": [fy(7, 2020)]}}}}}
    assert edgar.annual_series(f, edgar.CONCEPTS["revenue"]) == {2020: 7}


def test_concepts_merge_when_company_switches_tags():
    # like Apple: old years under Revenues, new years under RevenueFromContract...
    f = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [fy(200, 2016), fy(210, 2017)]}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [fy(230, 2018), fy(260, 2019)]}},
    }}}
    assert edgar.annual_series(f, edgar.CONCEPTS["revenue"], years=3) == {2017: 210, 2018: 230, 2019: 260}


def test_fcf_margin_uses_same_year():
    fin = {"revenue": {2017: 100.0}, "operating_cash_flow": {2023: 50.0}, "capex": {2023: 10.0}}
    assert factsheet.metrics(fin)["fcf_margin"] is None


def test_recent_filings_links():
    subs = {"cik": "320193", "filings": {"recent": {
        "form": ["4", "10-K", "8-K"], "accessionNumber": ["a", "0000320193-24-000123", "x-y"],
        "filingDate": ["2024-11-02", "2024-11-01", "2024-10-30"], "primaryDocument": ["d", "aapl-10k.htm", "e.htm"],
        "primaryDocDescription": ["", "10-K", ""]}}}
    out = edgar.recent_filings(subs)
    assert [f["form"] for f in out] == ["10-K", "8-K"]
    assert out[0]["url"] == "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-10k.htm"


def test_metrics():
    m = factsheet.metrics(edgar.financials(FACTS))
    assert m["revenue_cagr"] == pytest.approx(0.10)
    assert m["revenue_yoy"] == pytest.approx(0.10)
    assert m["net_margin"] == pytest.approx(18 / 121)
    assert m["fcf_margin"] == pytest.approx(20 / 121)
    assert m["net_debt"] == pytest.approx(-10e9)
    assert m["roe"] == pytest.approx(0.3)


def test_formatting():
    assert factsheet.money(2.4e12) == "$2.4tn"
    assert factsheet.money(-10e9) == "-$10.0bn"
    assert factsheet.pct(None) == "n/a"
    assert factsheet.cagr({2020: -1, 2023: 5}) is None


def test_fact_sheet_ids():
    fin = edgar.financials(FACTS)
    facts = factsheet.build_facts("Apple", "AAPL", fin, factsheet.metrics(fin), SNAP)
    assert facts[0][0] == "F1" and len({i for i, _ in facts}) == len(facts)
    text = factsheet.facts_text("Apple", "AAPL", facts)
    assert "[F1]" in text and "net cash" in text and "40.0x" in text


def test_fact_sheet_without_market_data():
    fin = edgar.financials(FACTS)
    facts = factsheet.build_facts("Apple", "AAPL", fin, factsheet.metrics(fin), {})
    assert facts and not any("P/E" in t for _, t in facts)


def test_price_stats():
    h = pd.DataFrame({"Close": [100, 120, 90, 110] * 10})
    s = market.price_stats(h)
    assert s["return_1y"] == pytest.approx(0.10)
    assert s["max_drawdown"] == pytest.approx(-0.25)
    assert market.price_stats(pd.DataFrame()) == {}


def test_snapshot_price_fallback():
    assert market.snapshot_from_info({"regularMarketPrice": 9.5})["price"] == 9.5


def test_citations():
    c = debate.citations("Growth [F2] and margin [F3], again [F2], fake [F99].", {"F1", "F2", "F3"})
    assert c["count"] == 4 and c["unique"] == ["F2", "F3", "F99"] and c["invalid"] == ["F99"]


def test_parse_verdict():
    v = debate.parse_verdict('Sure: {"winner": "BULL", "confidence": 70, "scores": {}}')
    assert v["winner"] == "bull"
    assert debate.parse_verdict('{"winner": "maybe"}')["winner"] == "draw"
    with pytest.raises(ValueError):
        debate.parse_verdict("no json")


def test_rule_debate_cites_real_facts():
    fin = edgar.financials(FACTS)
    m = factsheet.metrics(fin)
    facts = factsheet.build_facts("Apple", "AAPL", fin, m, SNAP)
    transcript, verdict = debate.run_rule_debate(m, SNAP, facts)
    valid = {i for i, _ in facts}
    text = " ".join(t["text"] for t in transcript)
    assert debate.citations(text, valid)["invalid"] == []
    assert debate.citations(text, valid)["count"] >= 3
    assert verdict["winner"] in ("bull", "bear", "draw")
    assert "demanding" in text  # 40x forward P/E should trigger the valuation bear point


def test_rule_debate_handles_empty_data():
    transcript, verdict = debate.run_rule_debate(factsheet.metrics({}), {}, [])
    assert verdict["winner"] == "draw" and transcript


class FakeClient:
    def __init__(self):
        self.calls = []
        outer = self

        class Msgs:
            def create(self, **kw):
                outer.calls.append(kw)
                text = (json.dumps({"winner": "bear", "confidence": 60, "scores": {}, "summary": "ok"})
                        if "JSON only" in kw["system"] else f"Point [F1] #{len(outer.calls)}")

                class R:
                    content = [type("C", (), {"text": text})()]
                return R()
        self.messages = Msgs()


def test_ai_debate_flow():
    seen = []
    client = FakeClient()
    transcript, verdict = debate.run_ai_debate("[F1] x", "key", on_turn=seen.append, client=client)
    assert [t["label"] for t in transcript] == ["Bull · opening", "Bear · opening", "Bull · rebuttal", "Bear · rebuttal"]
    assert len(seen) == 4 and len(client.calls) == 5
    assert verdict["winner"] == "bear"
    assert "Point [F1] #2" in client.calls[2]["messages"][0]["content"]  # bull rebuts the bear's opening
