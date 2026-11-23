"""Bull vs bear debate over a numbered fact sheet, then a judge's verdict.

With an Anthropic API key, Claude plays both analysts and the judge. Without one, a rule-based
engine builds the arguments from the same metrics so the app still works.
"""

import json
import os
import re
from typing import Callable, Optional

DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
CITE = re.compile(r"\[(F\d+)\]")

RULES = (
    "Use ONLY the fact sheet. Cite every number with its id in square brackets, e.g. [F3]. "
    "Do not invent figures, news, products or management quotes. If a fact is missing, say so. "
    "Write plain English for a smart non-specialist. Max 150 words."
)
ROLES = {
    "bull": "You are a sharp equity analyst arguing the BULL case (buy) for this stock.",
    "bear": "You are a sharp equity analyst arguing the BEAR case (sell/avoid) for this stock.",
}


def citations(text: str, valid_ids: set[str]) -> dict:
    found = CITE.findall(text or "")
    return {"count": len(found), "unique": sorted(set(found), key=lambda x: int(x[1:])),
            "invalid": sorted({f for f in found if f not in valid_ids})}


def _client(api_key: Optional[str]):
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def _ask(client, system: str, prompt: str, max_tokens: int = 450) -> str:
    msg = client.messages.create(model=DEFAULT_MODEL, max_tokens=max_tokens, system=system,
                                 messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text.strip()


def judge_prompt(sheet: str, transcript: list[dict]) -> str:
    debate = "\n\n".join(f"{t['label']}:\n{t['text']}" for t in transcript)
    return (
        f"{sheet}\n\nDEBATE\n{debate}\n\n"
        "You are the judge: a neutral portfolio manager. Score each side 1-10 on evidence (accurate, cited facts), "
        "logic and rebuttal. Penalise claims not supported by the fact sheet. Reply with JSON only:\n"
        '{"winner": "bull"|"bear"|"draw", "confidence": 0-100, '
        '"scores": {"bull": {"evidence": n, "logic": n, "rebuttal": n}, "bear": {"evidence": n, "logic": n, "rebuttal": n}}, '
        '"strongest_bull_point": "...", "strongest_bear_point": "...", '
        '"what_would_change_the_verdict": "...", "summary": "2-3 sentences"}'
    )


def parse_verdict(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("judge did not return JSON")
    v = json.loads(m.group(0))
    v["winner"] = str(v.get("winner", "draw")).lower()
    if v["winner"] not in ("bull", "bear", "draw"):
        v["winner"] = "draw"
    return v


def run_ai_debate(sheet: str, api_key: str, on_turn: Optional[Callable[[dict], None]] = None,
                  client=None) -> tuple[list[dict], dict]:
    client = client or _client(api_key)
    transcript: list[dict] = []

    def turn(side: str, label: str, prompt: str):
        text = _ask(client, f"{ROLES[side]} {RULES}", prompt)
        t = {"side": side, "label": label, "text": text}
        transcript.append(t)
        if on_turn:
            on_turn(t)

    turn("bull", "Bull · opening", f"{sheet}\n\nGive your opening: the 3 strongest reasons to own this stock, as bullets.")
    turn("bear", "Bear · opening", f"{sheet}\n\nGive your opening: the 3 strongest reasons to avoid this stock, as bullets.")
    turn("bull", "Bull · rebuttal",
         f"{sheet}\n\nThe bear said:\n{transcript[1]['text']}\n\nRebut their two weakest points, then restate your thesis in one line.")
    turn("bear", "Bear · rebuttal",
         f"{sheet}\n\nThe bull said:\n{transcript[0]['text']}\n\nAnd rebutted:\n{transcript[2]['text']}\n\n"
         "Rebut their two weakest points, then restate your thesis in one line.")
    verdict = parse_verdict(_ask(client, "You are a fair, numerate judge. Output JSON only.",
                                 judge_prompt(sheet, transcript), max_tokens=700))
    return transcript, verdict


# ---------------------------------------------------------------- offline, rule-based fallback

def _points(m: dict, s: dict, ids: dict) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """(weight, text) arguments for each side. ids maps metric key -> fact id."""
    bull, bear = [], []

    def c(key):
        return f" [{ids[key]}]" if key in ids else ""

    g = m.get("revenue_cagr")
    if g is not None:
        (bull if g >= 0.08 else bear if g < 0.03 else bull).append(
            (3 if g >= 0.15 or g < 0 else 2,
             f"Revenue has compounded at {g * 100:.1f}% a year{c('revenue_cagr')}." if g >= 0.03
             else f"Growth is thin: revenue compounded at only {g * 100:.1f}% a year{c('revenue_cagr')}."))
    nm, nm0 = m.get("net_margin"), m.get("net_margin_first")
    if nm is not None:
        if nm >= 0.15:
            bull.append((3, f"Highly profitable: {nm * 100:.1f}% net margin{c('net_margin')}."))
        elif nm < 0.05:
            bear.append((3, f"Profitability is weak at a {nm * 100:.1f}% net margin{c('net_margin')}."))
        if nm0 is not None and abs(nm - nm0) >= 0.03:
            (bull if nm > nm0 else bear).append(
                (2, f"Margins have {'expanded' if nm > nm0 else 'shrunk'} from {nm0 * 100:.1f}% to {nm * 100:.1f}%{c('net_margin')}."))
    fm = m.get("fcf_margin")
    if fm is not None:
        if fm >= 0.10:
            bull.append((2, f"Strong cash generation: free cash flow is {fm * 100:.1f}% of revenue{c('fcf')}."))
        elif fm < 0.02:
            bear.append((2, f"Little free cash flow: {fm * 100:.1f}% of revenue{c('fcf')}."))
    nd = m.get("net_debt_to_ocf")
    if m.get("net_debt") is not None:
        if m["net_debt"] < 0:
            bull.append((2, f"Balance sheet holds net cash{c('net_debt')}."))
        elif nd is not None and nd > 3:
            bear.append((3, f"Leverage is high: net debt is {nd:.1f}x operating cash flow{c('net_debt')}."))
    pe = s.get("forward_pe") or s.get("trailing_pe")
    if pe is not None:
        if pe > 35:
            bear.append((3, f"Valuation is demanding at about {pe:.0f}x earnings{c('pe')}, so little room for error."))
        elif 0 < pe < 15:
            bull.append((2, f"Valuation looks undemanding at about {pe:.0f}x earnings{c('pe')}."))
    r = s.get("return_1y")
    if r is not None:
        if r > 0.25:
            bull.append((1, f"Momentum: the shares are up {r * 100:.0f}% over the year{c('return_1y')}."))
            bear.append((1, f"After a {r * 100:.0f}% run in a year{c('return_1y')}, a lot of good news may be priced in."))
        elif r < -0.15:
            bear.append((2, f"The market is losing faith: shares are down {abs(r) * 100:.0f}% over the year{c('return_1y')}."))
            bull.append((1, f"A {abs(r) * 100:.0f}% fall over the year{c('return_1y')} may already price in the bad news."))
    if s.get("target_mean") and s.get("price"):
        up = s["target_mean"] / s["price"] - 1
        if up > 0.10:
            bull.append((1, f"Analysts' average target implies {up * 100:.0f}% upside{c('target')}."))
        elif up < 0:
            bear.append((1, f"The share price is already above analysts' average target{c('target')}."))
    return sorted(bull, reverse=True), sorted(bear, reverse=True)


FACT_KEYS = [  # metric key -> phrase that identifies its fact line
    ("revenue_cagr", "compound annual growth"), ("net_margin", "Net profit margin"), ("fcf", "Free cash flow"),
    ("net_debt", "Long-term debt minus cash"), ("pe", "P/E:"), ("return_1y", "over the last year"),
    ("target", "analyst target"),
]


def fact_ids(facts: list[tuple[str, str]]) -> dict:
    out = {}
    for key, phrase in FACT_KEYS:
        for fid, text in facts:
            if phrase in text:
                out[key] = fid
                break
    return out


def run_rule_debate(m: dict, snap: dict, facts: list[tuple[str, str]]) -> tuple[list[dict], dict]:
    bull, bear = _points(m, snap or {}, fact_ids(facts))

    def bullets(pts):
        return "\n".join(f"- {t}" for _, t in pts[:3]) or "- Not enough data to argue this side."

    transcript = [
        {"side": "bull", "label": "Bull · opening", "text": bullets(bull)},
        {"side": "bear", "label": "Bear · opening", "text": bullets(bear)},
    ]
    if bear:
        transcript.append({"side": "bull", "label": "Bull · rebuttal",
                           "text": f"The bear's case leans on one point: {bear[0][1][0].lower() + bear[0][1][1:]} "
                                   f"That matters less than the business quality above."})
    if bull:
        transcript.append({"side": "bear", "label": "Bear · rebuttal",
                           "text": f"The bull's best point is fair: {bull[0][1][0].lower() + bull[0][1][1:]} "
                                   f"But the risks above are not priced for."})
    bs, rs = sum(w for w, _ in bull), sum(w for w, _ in bear)
    total = bs + rs or 1
    winner = "draw" if abs(bs - rs) <= 1 else ("bull" if bs > rs else "bear")

    def score(x):
        return max(1, min(10, round(3 + 7 * x / total)))

    verdict = {
        "winner": winner, "confidence": int(50 + 50 * abs(bs - rs) / total),
        "scores": {"bull": {"evidence": score(bs), "logic": score(bs), "rebuttal": score(bs)},
                   "bear": {"evidence": score(rs), "logic": score(rs), "rebuttal": score(rs)}},
        "strongest_bull_point": bull[0][1] if bull else "n/a",
        "strongest_bear_point": bear[0][1] if bear else "n/a",
        "what_would_change_the_verdict": "A clear change in growth, margins or valuation versus the figures above.",
        "summary": f"Rule-based scoring weighs {len(bull)} bull and {len(bear)} bear signals "
                   f"({bs} vs {rs} points). Add an Anthropic API key for a full AI debate.",
    }
    return transcript, verdict
