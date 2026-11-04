"""Korean research reports for the morning email: brokerage reports (via Naver Securities research)
and Bank of Korea publications (official RSS). Every fetch is best-effort: a failing source just
drops out instead of breaking the email.

Summaries are not generated (no paid APIs): they are up to five lines picked from the abstract the
authors attach to the report - the lead sentence of each paragraph first, in the original order.
"""
import html
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from html import escape

UA = {"User-Agent": "Mozilla/5.0 (language-learning-queue/1.0)"}
NAVER_API = "https://stock.naver.com/api/stockSecurity/researches/v2/{}?size=30"
NAVER_PAGE = "https://stock.naver.com/research/{}/{}"
RECENT_DAYS = 3        # only reports written within this many days are candidates
SUMMARY_LINES = 5
LINE_CHARS = 110       # a longer sentence is cut at a clause boundary
MIN_LINE = 20          # shorter lines are headings like "Comment" or "증시 코멘트 및 대응 전략"
BOILERPLATE = ("자세한 내용은 첨부파일", "첨부파일을 참고")


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8-sig")


def _text(raw):
    """HTML (BOK feeds escape it twice) -> plain one-line text."""
    for _ in range(3):
        raw = html.unescape(raw)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>| ", " ", raw)).strip()
    return re.sub(r" ([.,])", r"\1", text)


def _clip(line):
    if len(line) <= LINE_CHARS:
        return line
    cut = line[:LINE_CHARS]
    end = max(cut.rfind(", "), cut.rfind(" "))
    return cut[:end if end > LINE_CHARS // 2 else LINE_CHARS].rstrip(" ,") + " …"


def _summary(raw):
    """Up to SUMMARY_LINES sentences: lead sentence of each paragraph, then second sentences, ... in source order."""
    for _ in range(3):
        raw = html.unescape(raw or "")
    paras = []
    for block in re.split(r"<br\s*/?>|</p>|</li>|\n", raw, flags=re.I):
        text = _text(block).lstrip("-·•▶■□○●* ").strip()
        text = re.sub(r"^(\d{1,2}|[가-하]|[①-⑩])[.)]?\s+", "", text)  # "1. ", "가. ", "① " numbering
        if len(text) < MIN_LINE or any(b in text for b in BOILERPLATE):
            continue
        sentences = [x.strip() for x in re.split(r"(?<=[.])\s+(?=\S)", text) if len(x.strip()) >= 10]
        if sentences:
            paras.append(sentences)
    picked, depth = [], 0
    while len(picked) < SUMMARY_LINES and any(len(p) > depth for p in paras):
        for i, p in enumerate(paras):
            if len(p) > depth and len(picked) < SUMMARY_LINES:
                picked.append((i, depth, p[depth]))
        depth += 1
    return [_clip(line) for _, _, line in sorted(picked)]


def _naver(category):
    out = []
    for it in json.loads(_get(NAVER_API.format(category))).get("items", []):
        out.append({
            "guid": f"naver:{category}:{it['nid']}",
            "title": (it.get("title") or "").strip(),
            "link": NAVER_PAGE.format(category, it["nid"]),
            "by": it.get("brokerName") or "",
            "date": date.fromisoformat(it["writeDate"]),
            "reads": int(it.get("readCount") or 0),
            "raw": it.get("content") or "",
        })
    return out


def _rss(url):
    out = []
    for item in ET.fromstring(_get(url)).find("channel").findall("item"):
        link = (item.findtext("link") or "").strip()
        pub = item.findtext("pubDate")
        if not link or not pub:
            continue
        out.append({
            "guid": item.findtext("guid") or link,
            "title": (item.findtext("title") or "").strip(),
            "link": link,
            "by": "",
            "date": parsedate_to_datetime(pub).date(),
            "reads": 0,
            "raw": item.findtext("description") or "",
        })
    return out


def pick(sources, day, state):
    """Per source, the `count` (default 1) unseen recent reports - titles with a `prefer` word first, then
    most-read, then newest. Cached per day."""
    cache = state.setdefault("reports", {})
    if str(day) in cache:
        return cache[str(day)]
    seen = set(state.setdefault("reports_used", []))
    since = day - timedelta(days=RECENT_DAYS)
    picks = []
    for src in sources:
        try:
            items = _naver(src["naver"]) if "naver" in src else _rss(src["rss"])
        except Exception as e:  # noqa: BLE001 - one dead source must not break the whole email
            print(f"  (report source {src['key']} failed: {e})")
            continue
        pool = [r for r in items if r["guid"] not in seen and since <= r["date"] <= day and r["title"]]
        prefer = src.get("prefer", [])
        newest = src.get("order") == "newest"
        pool.sort(key=lambda r: (any(w in r["title"] for w in prefer), r["date"] if newest else r["reads"],
                                 r["reads"] if newest else r["date"]), reverse=True)
        for r in pool[:src.get("count", 1)]:
            seen.add(r["guid"])
            picks.append({"label": src["label"], "slot": src.get("slot", ""), "summary": _summary(r["raw"]), "date": str(r["date"]),
                          **{k: r[k] for k in ("guid", "title", "link", "by")}})
    state["reports_used"] = sorted(seen)[-500:]
    cache[str(day)] = picks
    for old in sorted(cache)[:-14]:  # keep two weeks of daily picks
        del cache[old]
    return picks


def _bullets(lines):
    if isinstance(lines, str):  # picks cached before summaries became line lists
        lines = [lines] if lines else []
    if not lines:
        return ""
    items = "".join(f"<li style='margin:0 0 3px'>{escape(x)}</li>" for x in lines)
    return f"<ul style='font-size:13px;color:#4b5563;line-height:1.55;margin:6px 0 0;padding-left:18px'>{items}</ul>"


def render(picks, slot=""):
    """Cards for the picks in `slot` ("" = KOREA REPORTS, "overnight" = OVERNIGHT · US at the top of the global block)."""
    picks = [r for r in picks if r.get("slot", "") == slot]
    if not picks:
        return ""
    card = "background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:14px 16px;margin:0 0 10px"
    tag = "display:inline-block;font-size:11px;font-weight:600;color:#fff;background:#7c3aed;border-radius:4px;padding:2px 7px"
    head = "font-size:12px;font-weight:700;letter-spacing:.06em;color:#6b7280;margin:16px 0 6px"
    link = "color:#7c3aed;text-decoration:none"
    cards = "".join(
        f"<div style='{card}'><span style='{tag}'>{escape(r['label'])}</span>"
        f"<span style='font-size:12px;color:#6b7280;margin-left:6px'>{escape(' · '.join(x for x in (r['by'], r['date']) if x))}</span>"
        f"<div style='font-size:16px;font-weight:600;margin:8px 0 4px'>"
        f"<a style='color:#111;text-decoration:none' href='{escape(r['link'])}'>{escape(r['title'])}</a></div>"
        f"{_bullets(r['summary'])}"
        f"<div style='font-size:13px;margin-top:8px'><a style='{link}' href='{escape(r['link'])}'>리포트 보기 →</a></div></div>"
        for r in picks
    )
    return f"<div style='{head}'>{'OVERNIGHT · 밤사이 미국' if slot == 'overnight' else 'KOREA REPORTS'}</div>{cards}"
