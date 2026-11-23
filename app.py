"""Bull vs Bear: two AI analysts debate a stock using SEC filings and market data, then a judge decides."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from bullbear import debate, edgar, factsheet, market

st.set_page_config(page_title="Bull vs Bear", page_icon="⚖️", layout="centered")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, button, input { font-family: 'Inter', sans-serif; }
#MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; }
.block-container { padding-top: 2.2rem; max-width: 820px; }
.bb-title { font-size: 2.2rem; line-height: 1.2; font-weight: 700; letter-spacing: -0.02em; margin-bottom: 0; }
.bb-title .bull { color: #1E7B4F; } .bb-title .bear { color: #B3392F; }
.bb-sub { color: #5B6675; margin: 0.2rem 0 1rem; }
.bb-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 0.6rem 0 1rem; }
.bb-stat { background: #F3F5F8; border-radius: 10px; padding: 10px 12px; }
.bb-stat .k { font-size: 0.75rem; color: #5B6675; text-transform: uppercase; letter-spacing: 0.04em; }
.bb-stat .v { font-size: 1.25rem; font-weight: 600; color: #1B2430; }
.bb-turn { border-radius: 12px; padding: 14px 16px; margin: 10px 0; border: 1px solid #E3E7ED; }
.bb-turn.bull { border-left: 5px solid #1E7B4F; background: #F2FAF5; }
.bb-turn.bear { border-left: 5px solid #B3392F; background: #FCF3F2; }
.bb-turn .who { font-weight: 600; font-size: 0.85rem; margin-bottom: 6px; }
.bb-turn.bull .who { color: #1E7B4F; } .bb-turn.bear .who { color: #B3392F; }
.bb-verdict { border-radius: 14px; padding: 18px; background: #1B2430; color: #fff; margin-top: 14px; }
.bb-verdict h3 { margin: 0 0 6px; color: #fff; }
.bb-verdict p { color: #D5DBE3; margin: 0.3rem 0; }
.bb-note { font-size: 0.8rem; color: #7A8594; }
@media (max-width: 640px) { .bb-stats { grid-template-columns: repeat(2, 1fr); } }
</style>
""", unsafe_allow_html=True)


def secret(name):
    try:
        return st.secrets.get(name)
    except Exception:
        return None


API_KEY = secret("ANTHROPIC_API_KEY")
SEC_UA = secret("SEC_USER_AGENT")


@st.cache_data(ttl=3600, show_spinner=False)
def get_company(ticker):
    return edgar.load_company(ticker, user_agent=SEC_UA)


@st.cache_data(ttl=900, show_spinner=False)
def get_market(ticker):
    return market.load_market(ticker)


def turn_html(t):
    body = t["text"].replace("<", "&lt;").replace("\n", "<br>")
    return f'<div class="bb-turn {t["side"]}"><div class="who">{t["label"]}</div>{body}</div>'


st.markdown('<div class="bb-title"><span class="bull">Bull</span> vs <span class="bear">Bear</span></div>',
            unsafe_allow_html=True)
st.markdown('<p class="bb-sub">Two AI analysts argue over a stock using only SEC filings and market data, '
            'citing every number. A judge picks the stronger case.</p>', unsafe_allow_html=True)

with st.form("pick"):
    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    ticker = c1.text_input("US stock ticker", value=st.session_state.get("ticker", "AAPL"),
                           placeholder="e.g. AAPL, NVDA, KO").strip().upper()
    go_btn = c2.form_submit_button("Analyse", type="primary", use_container_width=True)

if go_btn and ticker:
    st.session_state.ticker = ticker
    st.session_state.pop("result", None)

ticker = st.session_state.get("ticker")
if not ticker:
    st.stop()

with st.spinner(f"Pulling SEC filings and market data for {ticker}..."):
    try:
        co = get_company(ticker)
    except ValueError as e:
        st.error(str(e))
        st.stop()
    except Exception:
        st.error("Couldn't reach SEC EDGAR just now. Try again in a minute.")
        st.stop()
    snap, hist = get_market(ticker)

fin = co["financials"]
m = factsheet.metrics(fin)
facts = factsheet.build_facts(co["name"], ticker, fin, m, snap)
sheet = factsheet.facts_text(co["name"], ticker, facts)
valid = {i for i, _ in facts}

st.markdown(f"#### {co['name'].title()} · {ticker}")
pe = snap.get("forward_pe") or snap.get("trailing_pe")
stats = [
    ("Price", factsheet.num(snap.get("price"))), ("Market cap", factsheet.money(snap.get("market_cap"))),
    ("P/E", factsheet.num(pe, "x")), ("Revenue growth / yr", factsheet.pct(m["revenue_cagr"])),
    ("Net margin", factsheet.pct(m["net_margin"])), ("FCF margin", factsheet.pct(m["fcf_margin"])),
]
st.markdown('<div class="bb-stats">' + "".join(
    f'<div class="bb-stat"><div class="k">{k}</div><div class="v">{v}</div></div>' for k, v in stats) + "</div>",
    unsafe_allow_html=True)
if not snap.get("price"):
    st.caption("Market data from Yahoo Finance is unavailable right now; the debate uses SEC figures only.")

tab_debate, tab_fin, tab_facts, tab_filings = st.tabs(["Debate", "Financials", "Fact sheet", "Filings"])

with tab_debate:
    mode = "AI debate (Claude)" if API_KEY else "Rule-based debate (no API key set)"
    st.caption(f"Mode: {mode}. Not investment advice.")
    if st.button("Start the debate", type="primary", use_container_width=True):
        box = st.container()
        if API_KEY:
            try:
                with st.spinner("Analysts are arguing..."):
                    transcript, verdict = debate.run_ai_debate(
                        sheet, API_KEY, on_turn=lambda t: box.markdown(turn_html(t), unsafe_allow_html=True))
            except Exception:
                st.warning("The AI debate failed, so here's the rule-based version.")
                transcript, verdict = debate.run_rule_debate(m, snap, facts)
        else:
            transcript, verdict = debate.run_rule_debate(m, snap, facts)
        st.session_state.result = {"ticker": ticker, "transcript": transcript, "verdict": verdict}
        st.rerun()

    res = st.session_state.get("result")
    if res and res["ticker"] == ticker:
        for t in res["transcript"]:
            st.markdown(turn_html(t), unsafe_allow_html=True)
        v = res["verdict"]
        label = {"bull": "The bull wins", "bear": "The bear wins", "draw": "It's a draw"}[v["winner"]]
        st.markdown(
            f'<div class="bb-verdict"><h3>⚖️ {label} · {v.get("confidence", "–")}% confidence</h3>'
            f'<p>{v.get("summary", "")}</p>'
            f'<p><b>Best bull point:</b> {v.get("strongest_bull_point", "")}</p>'
            f'<p><b>Best bear point:</b> {v.get("strongest_bear_point", "")}</p>'
            f'<p><b>What would change it:</b> {v.get("what_would_change_the_verdict", "")}</p></div>',
            unsafe_allow_html=True)

        rows = []
        for side in ("bull", "bear"):
            sc = v.get("scores", {}).get(side, {})
            text = " ".join(t["text"] for t in res["transcript"] if t["side"] == side)
            cit = debate.citations(text, valid)
            rows.append({"Side": side.title(), "Evidence": sc.get("evidence"), "Logic": sc.get("logic"),
                         "Rebuttal": sc.get("rebuttal"), "Facts cited": len(cit["unique"]),
                         "Bad citations": len(cit["invalid"])})
        st.markdown("##### Scorecard")
        st.table(pd.DataFrame(rows).set_index("Side"))
        st.markdown('<p class="bb-note">"Bad citations" counts fact ids that don\'t exist on the fact sheet, '
                    'a quick check that the analysts aren\'t inventing numbers.</p>', unsafe_allow_html=True)

        md = f"# Bull vs Bear: {co['name']} ({ticker})\n\n" + "\n\n".join(
            f"## {t['label']}\n{t['text']}" for t in res["transcript"]) + \
            f"\n\n## Verdict\n{label} ({v.get('confidence')}% confidence). {v.get('summary', '')}\n\n---\n{sheet}\n"
        st.download_button("Download debate (.md)", md, file_name=f"bull_vs_bear_{ticker}.md")

with tab_fin:
    years = m["years"]
    if years:
        rev, ni = fin.get("revenue", {}), fin.get("net_income", {})
        fig = go.Figure()
        fig.add_bar(x=years, y=[rev.get(y, 0) / 1e9 for y in years], name="Revenue", marker_color="#1F4E79")
        fig.add_bar(x=years, y=[ni.get(y, 0) / 1e9 for y in years], name="Net income", marker_color="#7FA7CC")
        fig.update_layout(title="Revenue and net income ($bn, from 10-K filings)", barmode="group", height=340,
                          margin=dict(l=10, r=10, t=50, b=10), legend=dict(orientation="h", y=-0.15),
                          plot_bgcolor="white", xaxis=dict(type="category"))
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    else:
        st.info("No annual 10-K figures found in SEC's XBRL data for this company.")
    if hist is not None and not hist.empty:
        pf = go.Figure(go.Scatter(x=hist.index, y=hist["Close"], line=dict(color="#1F4E79", width=2)))
        pf.update_layout(title="Share price, last 12 months", height=300, margin=dict(l=10, r=10, t=50, b=10),
                         plot_bgcolor="white")
        st.plotly_chart(pf, use_container_width=True, config={"displayModeBar": False})

with tab_facts:
    st.caption("This is everything the analysts are allowed to use. Each line has an id they must cite.")
    for i, t in facts:
        st.markdown(f"**[{i}]** {t}")

with tab_filings:
    if co["filings"]:
        for f in co["filings"]:
            st.markdown(f"**{f['form']}** · {f['filed']} · [{f['description']}]({f['url']})")
    else:
        st.info("No recent filings found.")

st.markdown('<p class="bb-note">Data: SEC EDGAR XBRL company facts and Yahoo Finance via yfinance. '
            'Educational project, not investment advice.</p>', unsafe_allow_html=True)
