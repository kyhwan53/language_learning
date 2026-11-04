"""Daily study cards (business English phrase, Japanese kana + travel phrase) and the Sunday weekly recap.

Cards come from content/*.toml and advance one step per calendar day from CARDS_START, so every run on
the same day shows the same card and nothing needs to be stored.
"""
import re
import tomllib
from datetime import date, timedelta
from html import escape
from pathlib import Path
from urllib.parse import quote

from indicators import COMMODITIES, WORLD
from sources import CARDS_START

CONTENT = Path(__file__).parent / "content"
KANA_PER_DAY = 3

with open(CONTENT / "business_english.toml", "rb") as f:
    PHRASES = tomllib.load(f)["phrase"]
with open(CONTENT / "japanese.toml", "rb") as f:
    _jp = tomllib.load(f)
KANA = [("히라가나", k, r) for k, r in _jp["hiragana"]] + [("가타카나", k, r) for k, r in _jp["katakana"]]
JP_PHRASES = _jp["phrase"]

HEAD = "font-size:12px;font-weight:700;letter-spacing:.06em;color:#6b7280;margin:16px 0 6px"
CARD = "background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:14px 16px;margin:0 0 10px"
LINK = "text-decoration:none;font-size:13px"


def _n(day):
    return max((day - date.fromisoformat(CARDS_START)).days, 0)


def english(day):
    return PHRASES[_n(day) % len(PHRASES)]


def kana(day):
    start = _n(day) * KANA_PER_DAY % len(KANA)
    return [KANA[(start + i) % len(KANA)] for i in range(KANA_PER_DAY)]


def japanese(day):
    return {"kana": kana(day), "phrase": JP_PHRASES[_n(day) % len(JP_PHRASES)]}


def _youglish(en):
    # Search text: drop "(...)", "...", leading "to " and end punctuation so YouGlish finds real clips.
    q = re.sub(r"\(.*?\)|\.\.\.|…|[?.!]$", "", en).strip()
    q = re.sub(r"^to ", "", q).strip(" ,")
    return f"https://youglish.com/pronounce/{quote(q)}/english"


def _translate(jp):
    return f"https://translate.google.com/?sl=ja&tl=ko&op=translate&text={quote(jp)}"


def render_english(p):
    return (
        f"<div style='{HEAD}'>BUSINESS ENGLISH · 오늘의 표현</div><div style='{CARD}'>"
        f"<div style='font-size:17px;font-weight:700'>{escape(p['en'])}</div>"
        f"<div style='font-size:14px;color:#374151;margin:2px 0 8px'>{escape(p['ko'])}</div>"
        f"<div style='font-size:14px;font-style:italic;color:#4b5563;border-left:3px solid #e3e6ea;padding-left:10px'>{escape(p['ex'])}</div>"
        f"<div style='margin-top:8px'><a style='{LINK};color:#2f6fed' href='{escape(_youglish(p['en']))}'>▶ 실제 영상 속 발음 듣기 (YouGlish)</a></div>"
        "<div style='font-size:12px;color:#6b7280;margin-top:6px'>오늘 회의나 메일에서 한 번 써 보세요.</div></div>"
    )


def render_japanese(card, day):
    review = kana(day - timedelta(days=1)) if _n(day) > 0 else []
    big = "".join(
        f"<td style='text-align:center;padding:4px 14px 0 0'><div style='font-size:30px;line-height:1.2'>{escape(k)}</div>"
        f"<div style='font-size:13px;color:#6b7280'>{escape(r)}</div></td>"
        for _, k, r in card["kana"]
    )
    p = card["phrase"]
    return (
        f"<div style='{HEAD}'>JAPANESE · 0단계 ({escape(card['kana'][0][0])})</div><div style='{CARD}'>"
        f"<table style='border-collapse:collapse'><tr>{big}</tr></table>"
        + (f"<div style='font-size:12px;color:#6b7280;margin-top:4px'>어제 글자 복습: "
           f"{escape(' '.join(k for _, k, _ in review))}</div>" if review else "")
        + f"<div style='border-top:1px solid #eef0f2;margin-top:10px;padding-top:10px'>"
        f"<div style='font-size:12px;color:#6b7280'>여행 표현</div>"
        f"<div style='font-size:17px;font-weight:600'>{escape(p['jp'])}</div>"
        f"<div style='font-size:13px;color:#4b5563'>{escape(p['ro'])} · {escape(p['ko'])}</div>"
        f"<div style='margin-top:6px'><a style='{LINK};color:#c2410c' href='{escape(_translate(p['jp']))}'>▶ 발음 듣기 (Google 번역의 스피커 버튼)</a></div>"
        "</div></div>"
    )


def _num(v):
    return float(re.sub(r"[^\d.\-]", "", v))


def _change(first, last):
    """Week change between two stored value strings: rates in bp, spreads in bp, levels in %."""
    a, b = _num(first), _num(last)
    if last.endswith("bp"):
        return f"{b - a:+.0f}bp"
    if last.endswith("%"):
        return f"{(b - a) * 100:+.0f}bp"
    return f"{(b / a - 1) * 100:+.2f}%"


GLOBAL_NAMES = {n for _, n in WORLD} | {c[-1] for c in COMMODITIES} | {"VIX (공포 지수)"}


def _bar(name, first, last):
    pct = (_num(last) / _num(first) - 1) * 100
    w = min(abs(pct) / 5 * 50, 50)  # +-5% fills half the track
    color = "#d93025" if pct >= 0 else "#1a73e8"
    side = "left:50%" if pct >= 0 else f"left:{50 - w:.1f}%"
    return (f"<tr><td style='padding:2px 8px 2px 0;white-space:nowrap'>{escape(name)}</td>"
            f"<td style='width:55%'><div style='position:relative;height:8px;background:#f1f3f5;border-radius:2px'>"
            f"<div style='position:absolute;top:0;{side};width:{w:.1f}%;height:8px;background:{color};border-radius:2px'></div></div></td>"
            f"<td style='text-align:right;padding-left:8px;color:{color};white-space:nowrap'>{pct:+.1f}%</td></tr>")


def render_weekly(state, day):
    """Sunday recap of the last 7 days (day-6 .. day): market moves, articles, reports, phrases, kana."""
    days = [str(day - timedelta(days=i)) for i in range(6, -1, -1)]
    sub = "font-size:13px;font-weight:700;margin:12px 0 4px"
    li = "margin:0 0 3px"
    parts = []

    hist = state.get("markets_history", {})
    seen = [hist[d] for d in days if d in hist]
    if len(seen) >= 2:
        first = {n: next(h[n] for h in seen if n in h) for n in seen[-1]}
        bars = [n for n in seen[-1] if n in GLOBAL_NAMES]
        if bars:
            parts.append(f"<div style='{sub}'>세계 증시·원자재 주간 등락</div>"
                         f"<table style='width:100%;font-size:12.5px;border-collapse:collapse'>{''.join(_bar(n, first[n], seen[-1][n]) for n in bars)}</table>")
        rows = "".join(
            f"<tr><td style='padding:2px 0'>{escape(n)}</td><td style='text-align:right'>{escape(seen[-1][n])}</td>"
            f"<td style='text-align:right;padding-left:12px;color:#6b7280'>{escape(_change(first[n], seen[-1][n]))}</td></tr>"
            for n in seen[-1] if n not in GLOBAL_NAMES
        )
        if rows:
            parts.append(f"<div style='{sub}'>국내·금리·환율 주간 변화</div><table style='width:100%;font-size:13px'>{rows}</table>")

    def links(key):
        items = [x for d in days for x in state.get(key, {}).get(d, [])]
        return "".join(f"<li style='{li}'><a style='color:#111' href='{escape(x['link'])}'>{escape(x['title'])}</a>"
                       f" <span style='color:#6b7280'>· {escape(x['label'])}</span></li>" for x in items)

    for key, title in (("articles", "이번 주 기사"), ("reports", "이번 주 리포트")):
        if html := links(key):
            parts.append(f"<div style='{sub}'>{title}</div><ul style='font-size:13px;margin:0;padding-left:18px'>{html}</ul>")

    start = max(day - timedelta(days=6), date.fromisoformat(CARDS_START))
    week = [start + timedelta(days=i) for i in range((day - start).days + 1)]
    if week:
        en = "".join(f"<li style='{li}'><b>{escape(english(d)['en'])}</b> — {escape(english(d)['ko'])}</li>" for d in week)
        jp = " ".join(f"{k}({r})" for d in week for _, k, r in kana(d))
        parts.append(f"<div style='{sub}'>이번 주 업무 영어</div><ul style='font-size:13px;margin:0;padding-left:18px'>{en}</ul>")
        parts.append(f"<div style='{sub}'>이번 주 일본어 글자</div><div style='font-size:15px'>{escape(jp)}</div>")

    if not parts:
        return ""
    return (f"<div style='{HEAD}'>WEEKLY · 한 주 정리 ({escape(days[0][5:])} ~ {escape(days[-1][5:])})</div>"
            f"<div style='{CARD};border-color:#c7d2fe;background:#f8f9ff'>{''.join(parts)}</div>")
