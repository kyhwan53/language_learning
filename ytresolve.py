"""Resolve a podcast episode to its YouTube video (best effort, no API key).

Searches YouTube, reads the first results from the page's embedded JSON, and only accepts a
video that clearly is the same episode - otherwise returns None so the caller can fall back to
a plain search link. A wrong video is worse than no link, so matching is strict:
  * numbered series ("#3 ...") match on the same number + same show, or
  * the titles share (almost) all words AND the video was uploaded around the episode's release date
    (or, when the release date is unknown, the titles are nearly identical).
Never raises.
"""
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Cookie": "CONSENT=YES+1",
}
STOP = {"the", "a", "an", "of", "to", "and", "in", "on", "for", "is", "are", "how", "why", "what", "with", "your", "you"}
UNIT_DAYS = {"second": 0, "minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30, "year": 365}


def _tokens(text):
    return {t for t in re.findall(r"[\w']+", text.lower()) if t not in STOP and len(t) > 1}


def _age_days(text):
    m = re.search(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago", text or "")
    return int(m.group(1)) * UNIT_DAYS[m.group(2)] if m else None


def _results(query):
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query) + "&hl=en"
    html = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read().decode("utf-8", "replace")
    m = re.search(r"var ytInitialData = ", html)
    if not m:
        return []
    data, _ = json.JSONDecoder().raw_decode(html[m.end():])
    found = []

    def walk(o):
        if isinstance(o, dict):
            v = o.get("videoRenderer")
            if v and "videoId" in v:
                title = "".join(r.get("text", "") for r in v.get("title", {}).get("runs", []))
                owner = "".join(r.get("text", "") for r in v.get("ownerText", {}).get("runs", []))
                age = _age_days(v.get("publishedTimeText", {}).get("simpleText", ""))
                found.append((v["videoId"], title, owner, age))
            for x in o.values():
                walk(x)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(data)
    return found[:8]


def _accept(show, title, ep_age, vid_title, owner, vid_age):
    n_ep = re.search(r"#\s*(\d+)", title)
    n_vid = re.search(r"#\s*(\d+)", vid_title)
    if n_ep and n_vid:  # numbered series: same number + same show is decisive (titles are often translated)
        return n_ep.group(1) == n_vid.group(1) and bool(_tokens(show) & (_tokens(vid_title) | _tokens(owner)))
    a, b = _tokens(title), _tokens(vid_title)
    if not a or not b:
        return False
    jaccard = len(a & b) / len(a | b)
    if ep_age is not None and vid_age is not None:
        return jaccard >= 0.7 and abs(vid_age - ep_age) <= max(45, 0.25 * ep_age)
    return jaccard >= 0.9  # no dates to compare: demand an essentially identical title


def find_video(show, title, pub=None):
    """Return (video_id, video_title) for a confident match, else None. `pub` = episode release (aware datetime)."""
    try:
        results = _results(f"{show} {title}"[:150].strip())
    except Exception as e:  # noqa: BLE001 - YouTube may block/consent-wall datacenter IPs
        print(f"  (youtube lookup failed: {e})")
        return None
    ep_age = (datetime.now(timezone.utc) - pub).days if pub else None
    for vid, vt, owner, vid_age in results:
        if _accept(show, title, ep_age, vt, owner, vid_age):
            return vid, vt
    return None
