"""Korean research reports for the morning email: brokerage reports (via Naver Securities research)
and Bank of Korea publications (official RSS). Every fetch is best-effort: a failing source just
drops out instead of breaking the email.

Summaries are not generated (no paid APIs): they are the abstract the authors attach to the report,
trimmed to a few sentences.
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
SUMMARY_CHARS = 320
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


def _summary(raw):
    text = _text(raw or "")
    if not text or any(b in text for b in BOILERPLATE):
        return ""
    if len(text) <= SUMMARY_CHARS:
        return text
    cut = text[:SUMMARY_CHARS]
    end = max(cut.rfind(". "), cut.rfind("다. "), cut.rfind("함. "), cut.rfind("음. "))
    return (cut[:end + 1] if end > SUMMARY_CHARS // 2 else cut.rstrip()) + " …"


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
    """Per source, the `count` (default 1) unseen recent reports - most-read first, else newest. Cached per day."""
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
        pool.sort(key=lambda r: (r["reads"], r["date"]), reverse=True)
        for r in pool[:src.get("count", 1)]:
            seen.add(r["guid"])
            picks.append({"label": src["label"], "summary": _summary(r["raw"]), "date": str(r["date"]),
                          **{k: r[k] for k in ("guid", "title", "link", "by")}})
    state["reports_used"] = sorted(seen)[-500:]
    cache[str(day)] = picks
    for old in sorted(cache)[:-14]:  # keep two weeks of daily picks
        del cache[old]
    return picks


def render(picks):
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
        f"{'<div style=' + repr('font-size:13px;color:#4b5563;line-height:1.6') + '>' + escape(r['summary']) + '</div>' if r['summary'] else ''}"
        f"<div style='font-size:13px;margin-top:8px'><a style='{link}' href='{escape(r['link'])}'>리포트 보기 →</a></div></div>"
        for r in picks
    )
    return f"<div style='{head}'>KOREA REPORTS</div>{cards}"
