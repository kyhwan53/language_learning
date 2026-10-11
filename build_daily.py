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
from html import escape
from pathlib import Path

from sources import BASE_URL, FEED_DAYS, MAX_MINUTES, RECIPIENT, SCHEDULE, SOURCES

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


def render_email(queue, day):
    total = sum(e["minutes"] or 0 for e in queue)
    rows = "".join(
        f"<tr><td style='padding:8px'><b>{escape(e['label'])}</b></td>"
        f"<td style='padding:8px'><a href='{escape(e['audio'])}'>{escape(e['title'])}</a>"
        f"{' · ' + str(e['minutes']) + ' min' if e['minutes'] else ''}"
        f"{' · <a href=' + repr(escape(e['page'])) + '>page/transcript</a>' if e['page'] else ''}"
        f" · <a href='https://music.youtube.com/search?q={quote(e['title'])}'>YouTube Music</a></td></tr>"
        for e in queue
    )
    return (
        f"<h2>Today's listening ({day}) — about {total} min</h2>"
        f"<table>{rows}</table>"
        "<p>Tip: listen once without the transcript, then re-listen the hardest part. "
        "Episodes are also queued in your podcast app via the personal feed.</p>"
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
    write_feed(state, day)
    html = render_email(queue, day)
    OUT.mkdir(exist_ok=True)
    (OUT / "email.html").write_text(html, encoding="utf-8")
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.send:
        send_email(html, day)
    print(f"{day}: {len(queue)} items, {sum(e['minutes'] or 0 for e in queue)} min")
    for e in queue:
        print(f"  [{e['label']}] {e['title']} ({e['minutes']} min)")


if __name__ == "__main__":
    main()
