"""Build today's listening queue, the personal podcast feed (docs/feed.xml) and the morning email.

Usage:
    python build_daily.py              # dry run: writes docs/feed.xml and out/email.html
    python build_daily.py --send       # also sends the email (needs GMAIL_USER / GMAIL_APP_PASSWORD)
    python build_daily.py --date 2026-10-12
"""
import argparse
import json
import os
import smtplib
import ssl
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import quote
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import format_datetime, parsedate_to_datetime
import re
from html import escape, unescape
from pathlib import Path

from sources import ARTICLES, ARTICLES_PER_DAY, BASE_URL, FEED_DAYS, MAX_MINUTES, RECIPIENT, SCHEDULE, SOURCES

ROOT = Path(__file__).parent
STATE = ROOT / "state.json"
DOCS = ROOT / "docs"
OUT = ROOT / "out"
ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"


def fetch_episodes(rss):
    req = urllib.request.Request(rss, headers={"User-Agent": "language-learning-queue/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        root = ET.fromstring(resp.read())
    eps = []
    for item in root.find("channel").findall("item"):
        enc = item.find("enclosure")
        if enc is None:
            continue
        pub = item.findtext("pubDate")
        eps.append({
            "guid": item.findtext("guid") or enc.get("url"),
            "title": (item.findtext("title") or "").strip(),
            "audio": enc.get("url"),
            "mime": enc.get("type") or "audio/mpeg",
            "page": item.findtext("link") or "",
            "minutes": parse_minutes(item.findtext(ITUNES + "duration")),
            "pub": parsedate_to_datetime(pub) if pub else None,
        })
    return eps


def parse_minutes(raw):
    if not raw:
        return None
    try:
        parts = [int(float(p)) for p in raw.split(":")]
    except ValueError:
        return None
    secs = 0
    for p in parts:
        secs = secs * 60 + p
    return round(secs / 60)


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"used": {}, "days": {}}


def pick(source, eps, used):
    pool = [e for e in eps if e["guid"] not in used]
    pool.sort(key=lambda e: e["pub"] or datetime.min.astimezone(), reverse=(source["mode"] == "newest"))
    return pool[0] if pool else None


def build_queue(day, state):
    if str(day) in state["days"]:  # idempotent: re-running the same day keeps the same queue
        return state["days"][str(day)]
    labels = {s["key"]: s for s in SOURCES}
    queue, total = [], 0
    for key in SCHEDULE[day.weekday()]:
        src = labels[key]
        used = set(state["used"].setdefault(key, []))
        ep = pick(src, fetch_episodes(src["rss"]), used)
        if ep is None:
            continue
        if total + (ep["minutes"] or 0) > MAX_MINUTES and queue:
            continue
        total += ep["minutes"] or 0
        state["used"][key].append(ep["guid"])
        queue.append({"key": key, "label": src["label"], **{k: ep[k] for k in ("guid", "title", "audio", "mime", "page", "minutes")}})
    state["days"][str(day)] = queue
    return queue


def write_feed(state, today):
    days = sorted(state["days"])[-FEED_DAYS:]
    ET.register_namespace("itunes", ITUNES[1:-1])
    rss = ET.Element("rss", version="2.0")
    ch = ET.SubElement(rss, "channel")
    ET.SubElement(ch, "title").text = "My Daily Language Queue"
    ET.SubElement(ch, "link").text = BASE_URL
    ET.SubElement(ch, "language").text = "en"
    ET.SubElement(ch, "description").text = "Personal daily listening queue (links to original podcasts)."
    for d in reversed(days):
        stamp = datetime.fromisoformat(d).astimezone()
        for i, ep in enumerate(state["days"][d]):
            it = ET.SubElement(ch, "item")
            ET.SubElement(it, "title").text = f"[{d[5:]} {i + 1}] {ep['label']} | {ep['title']}"
            ET.SubElement(it, "guid", isPermaLink="false").text = f"{d}:{ep['guid']}"
            ET.SubElement(it, "pubDate").text = format_datetime(stamp.replace(hour=6 - i if i < 6 else 0))
            ET.SubElement(it, "link").text = ep["page"] or BASE_URL
            ET.SubElement(it, "enclosure", url=ep["audio"], type=ep["mime"], length="0")
            if ep["minutes"]:
                ET.SubElement(it, ITUNES + "duration").text = str(ep["minutes"] * 60)
    DOCS.mkdir(exist_ok=True)
    ET.indent(rss)
    ET.ElementTree(rss).write(DOCS / "feed.xml", encoding="utf-8", xml_declaration=True)


def fetch_articles(rss):
    req = urllib.request.Request(rss, headers={"User-Agent": "language-learning-queue/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        root = ET.fromstring(resp.read())
    out = []
    for item in root.find("channel").findall("item"):
        link = (item.findtext("link") or "").strip()
        title = (item.findtext("title") or "").strip()
        if not link or not title:
            continue
        summary = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", item.findtext("description") or ""))).strip()
        pub = item.findtext("pubDate")
        out.append({
            "guid": item.findtext("guid") or link,
            "title": title,
            "link": link,
            "summary": summary[:240] + ("…" if len(summary) > 240 else ""),
            "pub": parsedate_to_datetime(pub) if pub else None,
        })
    return out


def build_articles(day, state):
    """Pick ARTICLES_PER_DAY unseen articles, rotating through the configured outlets."""
    cache = state.setdefault("articles", {})
    if str(day) in cache:
        return cache[str(day)]
    seen = set(state.setdefault("articles_used", []))
    picks = []
    n = len(ARTICLES)
    for j in range(min(ARTICLES_PER_DAY, n)):
        src = ARTICLES[(day.toordinal() * ARTICLES_PER_DAY + j) % n]
        try:
            pool = [a for a in fetch_articles(src["rss"]) if a["guid"] not in seen]
        except Exception as e:  # noqa: BLE001 - one dead outlet must not break the whole email
            print(f"  (article source {src['key']} failed: {e})")
            continue
        pool.sort(key=lambda a: a["pub"].timestamp() if a["pub"] else 0, reverse=True)
        if pool:
            a = pool[0]
            seen.add(a["guid"])
            picks.append({"label": src["label"], **{k: a[k] for k in ("guid", "title", "link", "summary")}})
    state["articles_used"] = sorted(seen)[-500:]
    cache[str(day)] = picks
    return picks


def render_email(queue, articles, day):
    total = sum(e["minutes"] or 0 for e in queue)
    card = "background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:14px 16px;margin:0 0 10px"
    tag = "display:inline-block;font-size:11px;font-weight:600;color:#fff;background:#2f6fed;border-radius:4px;padding:2px 7px"
    link = "color:#2f6fed;text-decoration:none"
    listen = "".join(
        f"<div style='{card}'><span style='{tag}'>{escape(e['label'])}</span>"
        f"<div style='font-size:16px;font-weight:600;margin:8px 0 4px'>{escape(e['title'])}</div>"
        f"<div style='font-size:13px;color:#6b7280'>{str(e['minutes']) + ' min' if e['minutes'] else 'length n/a'}</div>"
        f"<div style='font-size:13px;margin-top:8px'>"
        f"{'<a style=' + repr(link) + ' href=' + repr(escape(e['page'])) + '>Page &amp; transcript</a> &nbsp;|&nbsp; ' if e['page'] else ''}"
        f"<a style='{link}' href='https://music.youtube.com/search?q={quote(e['title'])}'>Open in YouTube Music</a></div></div>"
        for e in queue
    )
    read = "".join(
        f"<div style='{card}'><span style='{tag.replace('#2f6fed', '#0f9d58')}'>{escape(a['label'])}</span>"
        f"<div style='font-size:16px;font-weight:600;margin:8px 0 4px'>"
        f"<a style='color:#111;text-decoration:none' href='{escape(a['link'])}'>{escape(a['title'])}</a></div>"
        f"<div style='font-size:13px;color:#4b5563;line-height:1.5'>{escape(a['summary'])}</div>"
        f"<div style='font-size:13px;margin-top:8px'><a style='{link}' href='{escape(a['link'])}'>Read the article →</a></div></div>"
        for a in articles
    )
    return (
        "<div style='max-width:600px;margin:0 auto;background:#f4f6f8;padding:18px;"
        "font-family:Segoe UI,Arial,sans-serif;color:#111'>"
        f"<div style='font-size:20px;font-weight:700'>Daily Language Plan</div>"
        f"<div style='font-size:13px;color:#6b7280;margin:2px 0 16px'>{day} · listening about {total} min</div>"
        "<div style='font-size:12px;font-weight:700;letter-spacing:.06em;color:#6b7280;margin:0 0 6px'>LISTEN</div>"
        f"{listen}"
        "<div style='font-size:12px;font-weight:700;letter-spacing:.06em;color:#6b7280;margin:16px 0 6px'>READ</div>"
        f"{read or '<div style=color:#6b7280>No new articles today.</div>'}"
        "<div style='font-size:12px;color:#6b7280;margin-top:14px;line-height:1.5'>"
        "Tip: listen once without the transcript, then replay the hardest part. "
        "While reading, note 3 phrases you could reuse in a meeting or presentation.</div></div>"
    )


def send_email(html, day):
    user, pw = os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"]
    msg = EmailMessage()
    msg["Subject"] = f"Daily Listening {day}"
    msg["From"], msg["To"] = user, RECIPIENT or user
    msg.set_content("HTML email")
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(user, pw)
        s.send_message(msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--date", default=str(date.today()))
    args = ap.parse_args()
    day = date.fromisoformat(args.date)

    state = load_state()
    queue = build_queue(day, state)
    articles = build_articles(day, state)
    write_feed(state, day)
    html = render_email(queue, articles, day)
    OUT.mkdir(exist_ok=True)
    (OUT / "email.html").write_text(html, encoding="utf-8")
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.send:
        send_email(html, day)
    print(f"{day}: {len(queue)} items, {sum(e['minutes'] or 0 for e in queue)} min")
    for e in queue:
        print(f"  [{e['label']}] {e['title']} ({e['minutes']} min)")
    for a in articles:
        print(f"  [READ {a['label']}] {a['title']}")


if __name__ == "__main__":
    main()
