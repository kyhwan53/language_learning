"""Market snapshot + economic calendar for the morning email. Every fetch is best-effort:
a failing source just drops its block instead of breaking the email.

Sources (free, no API key):
  - US Treasury daily par yield curve (official CSV)
  - Frankfurter (ECB reference FX rates)
  - Forex Factory weekly calendar JSON (unofficial but widely used; High impact only, KST)
  - Naver Securities mobile JSON (unofficial): KOSPI, KOSDAQ, Korea 3Y government bond, world indices, commodities
  - New York Fed Markets API (official): effective fed funds rate and target range
  - Bank of Korea monetary policy RSS (official): latest base rate decision
  - CNBC Economy RSS and Federal Reserve monetary policy press RSS: headlines (title + link only)
"""
import csv
import io
import json
import re
import time
import xml.etree.ElementTree as ET
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import escape, unescape

KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "language-learning-queue/1.0"}
CAL_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CNY"}
WORLD = [(".INX", "S&P 500"), (".IXIC", "나스닥"), (".DJI", "다우"), (".STOXX50E", "유로스톡스 50"),
         (".N225", "니케이 225"), (".SSEC", "상해종합"), (".HSI", "항셍")]
COMMODITIES = [("energy", "CLcv1", "WTI"), ("energy", "LCOcv1", "브렌트유"), ("metals", "GCcv1", "금"),
               ("metals", "HGcv1", "구리 (경기 선행)")]
BOK_POLICY_RSS = "https://www.bok.or.kr/portal/bbs/P0000559/news.rss?menuNo=200690"
HEADLINE_FEEDS = [("CNBC", "https://www.cnbc.com/id/20910258/device/rss/rss.html", 3, 2),  # (label, rss, max items, max age days)
                  ("Fed 공식 발표", "https://www.federalreserve.gov/feeds/press_monetary.xml", 2, 7)]


def _get(url, timeout=30, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read().decode("utf-8-sig")
        except urllib.error.HTTPError as e:
            if e.code == 429 or i == tries - 1:  # rate limited: retrying right away only makes it worse
                raise
        except Exception:  # noqa: BLE001 - timeouts / resets are worth a retry
            if i == tries - 1:
                raise
        time.sleep(3 * (i + 1))


def treasury_yields(day):
    rows = []
    for year in (day.year, day.year - 1):  # fall back to last year right after New Year
        url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
               f"daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv")
        rows = list(csv.DictReader(io.StringIO(_get(url))))
        if len(rows) >= 2:
            break
    if len(rows) < 2:
        return None
    cur, prev = rows[0], rows[1]  # newest first
    out = []
    for tenor in ("2 Yr", "10 Yr", "30 Yr"):
        c, p = float(cur[tenor]), float(prev[tenor])
        out.append((f"US {tenor.replace(' Yr', 'Y')}", f"{c:.2f}%", (c - p) * 100, "bp"))
    spread = float(cur["10 Yr"]) - float(cur["2 Yr"])
    pspread = float(prev["10 Yr"]) - float(prev["2 Yr"])
    out.append(("10Y-2Y spread", f"{spread * 100:+.0f}bp", (spread - pspread) * 100, "bp"))
    return cur["Date"], out


def fx(day):
    url = f"https://api.frankfurter.dev/v1/{day - timedelta(days=10)}..{day}?base=USD&symbols=KRW,JPY,EUR"
    rates = json.loads(_get(url))["rates"]
    dates = sorted(rates)
    if len(dates) < 2:
        return None
    cur, prev = rates[dates[-1]], rates[dates[-2]]
    out = []
    for sym, name, fmt in (("KRW", "USD/KRW", "{:,.1f}"), ("JPY", "USD/JPY", "{:.2f}"), ("EUR", "USD/EUR", "{:.4f}")):
        pct = (cur[sym] / prev[sym] - 1) * 100
        out.append((name, fmt.format(cur[sym]), pct, "%"))
    return dates[-1], out


def korea(day):
    out, asof = [], None
    for code, name in (("KOSPI", "KOSPI"), ("KOSDAQ", "KOSDAQ")):
        it = json.loads(_get(f"https://m.stock.naver.com/api/index/{code}/basic"))
        asof = asof or it["localTradedAt"][:10]
        out.append((name, it["closePrice"], float(it["fluctuationsRatio"]), "%"))
    bond = json.loads(_get("https://m.stock.naver.com/front-api/marketIndex/productDetail?category=bond&reutersCode=KR3YT=RR"))["result"]
    out.append(("KR 3Y", f"{float(bond['closePrice']):.2f}%", float(bond["fluctuations"]) * 100, "bp"))
    return asof, out


def _rows(fetch, items):
    """One row per item; a failing item is skipped so the rest of the table still shows."""
    out, asof = [], None
    for item in items:
        try:
            name, value, pct, traded = fetch(*item)
        except Exception as e:  # noqa: BLE001
            print(f"  (indicator {item[-1]} failed: {e})")
            continue
        asof = asof or traded[:10]
        out.append((name, value, pct, "%"))
    if not out:
        raise RuntimeError("all items failed")
    return asof, out


def _index(code, name):
    it = json.loads(_get(f"https://api.stock.naver.com/index/{code}/basic"))
    return name, it["closePrice"], float(it["fluctuationsRatio"]), it["localTradedAt"]


def world(day):
    return _rows(_index, WORLD)


def commodities(day):
    def one(cat, code, name):
        it = json.loads(_get(f"https://m.stock.naver.com/front-api/marketIndex/productDetail?category={cat}&reutersCode={code}"))["result"]
        return name, "$" + it["closePrice"], float(it["fluctuationsRatio"]), it["localTradedAt"]
    asof, rows = _rows(one, COMMODITIES)
    try:
        rows.append(_index(".VIX", "VIX (공포 지수)")[:3] + ("%",))
    except Exception as e:  # noqa: BLE001
        print(f"  (indicator VIX failed: {e})")
    return asof, rows


def _bok_rate():
    """Latest base rate from the BOK policy RSS: '기준금리를 현재의 3.00% 수준에서 유지' or '... 3.00%에서 2.75%로 인하'."""
    for item in ET.fromstring(_get(BOK_POLICY_RSS)).find("channel").findall("item"):
        title = item.findtext("title") or ""
        if not title.startswith("통화정책방향"):
            continue
        text = item.findtext("description") or ""
        for _ in range(3):
            text = unescape(text)
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))
        m = re.search(r"기준금리를[^.]*?([\d.]+)\s*%[^.]*?(?:([\d.]+)\s*%\s*로|유지)", text)
        if m:
            return {"rate": f"{m.group(2) or m.group(1)}%", "decision": title.removeprefix("통화정책방향").strip("() ")}
        return None
    return None


def central_banks(day, meetings=None):
    """Fed target range + EFFR (NY Fed) and the BOK base rate from its latest decision; next meetings from config."""
    meetings = meetings or {}
    out = {}
    try:
        r = json.loads(_get("https://markets.newyorkfed.org/api/rates/unsecured/effr/last/1.json"))["refRates"][0]
        out["fed"] = {"range": f"{r['targetRateFrom']:.2f}–{r['targetRateTo']:.2f}%", "effr": f"{r['percentRate']:.2f}%",
                      "asof": r["effectiveDate"]}
    except Exception as e:  # noqa: BLE001
        print(f"  (fed rate failed: {e})")
    try:
        if bok := _bok_rate():
            out["bok"] = bok
    except Exception as e:  # noqa: BLE001
        print(f"  (bok rate failed: {e})")
    for key, dates in (("fed", meetings.get("fomc", [])), ("bok", meetings.get("bok", []))):
        nxt = next((d for d in sorted(dates) if date.fromisoformat(d) >= day), None)
        if key in out and nxt:
            out[key]["next"] = nxt
    if not out:
        raise RuntimeError("no central bank data")
    return out


def headlines(day):
    out = []
    for label, url, n, max_age in HEADLINE_FEEDS:
        try:
            items = ET.fromstring(_get(url)).find("channel").findall("item")
        except Exception as e:  # noqa: BLE001
            print(f"  (headlines {label} failed: {e})")
            continue
        kept = 0
        for it in items:
            pub = it.findtext("pubDate")
            if pub and parsedate_to_datetime(pub).astimezone(KST).date() < day - timedelta(days=max_age):
                continue
            title, link = (it.findtext("title") or "").strip(), (it.findtext("link") or "").strip()
            if title and link and kept < n:
                out.append((label, title, link))
                kept += 1
    return out


def _calendar_items(day, cache):
    """Fetch the weekly calendar; this host rate-limits hard (429), so fall back to the last
    successful copy kept in `cache` (persisted in state.json) while it still covers `day`."""
    try:
        items = json.loads(_get("https://nfs.faireconomy.media/ff_calendar_thisweek.json"))
        cache["items"] = items
        return items
    except Exception as e:  # noqa: BLE001
        items = cache.get("items") or []
        dates = [datetime.fromisoformat(i["date"]).astimezone(KST).date() for i in items]
        if dates and min(dates) <= day <= max(dates):
            print(f"  (calendar fetch failed: {e}; using cached copy)")
            return items
        raise


def calendar(day, cache=None, days=3):
    items = _calendar_items(day, cache if cache is not None else {})
    start = datetime(day.year, day.month, day.day, tzinfo=KST)
    end = start + timedelta(days=days)
    out = []
    for it in items:
        if it.get("impact") != "High" or it.get("country") not in CAL_CURRENCIES:
            continue
        when = datetime.fromisoformat(it["date"]).astimezone(KST)
        if start <= when < end:
            out.append((when, it))
    out.sort(key=lambda x: x[0])
    return out


def snapshot(day, cache=None, meetings=None):
    """Returns dict with optional keys: yields, fx, calendar. Never raises.
    `cache` is a dict persisted by the caller (used for the rate-limited calendar)."""
    data = {}
    cache = cache if cache is not None else {}
    for key, fn in (("korea", korea), ("yields", treasury_yields), ("fx", fx), ("world", world), ("commodities", commodities),
                    ("banks", lambda d: central_banks(d, meetings)), ("headlines", headlines), ("calendar", lambda d: calendar(d, cache))):
        try:
            data[key] = fn(day)
        except Exception as e:  # noqa: BLE001 - best effort per block
            print(f"  (indicator {key} failed: {e})")
    return data


def _arrow(delta, unit):
    if abs(delta) < (0.05 if unit == "%" else 0.5):
        return "<span style='color:#6b7280'>–</span>"
    color = "#d93025" if delta > 0 else "#1a73e8"  # up red, down blue (KR convention)
    sign = "▲" if delta > 0 else "▼"
    val = f"{abs(delta):.2f}%" if unit == "%" else f"{abs(delta):.0f}bp"
    return f"<span style='color:{color}'>{sign} {val}</span>"


def _md(d):
    return f"{int(d[5:7])}/{int(d[8:10])}"


def render_global(data, overnight_html=""):
    """Overnight US recap, world indices, commodities & risk, central banks, economy headlines."""
    card = "background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:12px 16px;margin:0 0 10px"
    head = "font-size:12px;font-weight:700;letter-spacing:.06em;color:#6b7280;margin:16px 0 6px"
    parts = [overnight_html]
    for key, title in (("world", "WORLD MARKETS"), ("commodities", "COMMODITIES & RISK")):
        if data.get(key):
            asof, rows = data[key]
            body = "".join(
                f"<tr><td style='padding:3px 0'>{escape(n)}</td><td style='text-align:right;font-weight:600'>{escape(v)}</td>"
                f"<td style='text-align:right;padding-left:12px;font-size:13px'>{_arrow(d, u)}</td></tr>"
                for n, v, d, u in rows
            )
            parts.append(f"<div style='{head}'>{title}</div><div style='{card}'><table style='width:100%;font-size:14px'>{body}"
                         f"<tr><td colspan=3 style='font-size:11px;color:#9ca3af'>latest close, local time (as of {escape(asof)})</td></tr></table></div>")
    banks = data.get("banks") or {}
    cells = []
    if "fed" in banks:
        f = banks["fed"]
        cells.append(("미 연준 목표 금리", f["range"], f"실효금리 {f['effr']} ({_md(f['asof'])})"
                      + (f"<br>다음 FOMC 결정 {_md(f['next'])} (한국은 다음 날 새벽)" if f.get("next") else "")))
    if "bok" in banks:
        b = banks["bok"]
        cells.append(("한국은행 기준금리", b["rate"], f"최근 결정 {escape(b['decision'])}"
                      + (f"<br>다음 회의 {_md(b['next'])}" if b.get("next") else "")))
    if cells:
        tds = "".join(f"<td style='vertical-align:top;padding:4px 10px 4px 0;width:50%'><div style='font-size:12px;color:#6b7280'>{escape(t)}</div>"
                      f"<div style='font-size:18px;font-weight:700'>{escape(v)}</div><div style='font-size:12px;color:#6b7280'>{sub}</div></td>"
                      for t, v, sub in cells)
        parts.append(f"<div style='{head}'>CENTRAL BANKS</div><div style='{card}'><table style='width:100%'><tr>{tds}</tr></table></div>")
    if data.get("headlines"):
        lis = "".join(f"<li style='margin:0 0 5px'><a style='color:#111;text-decoration:none' href='{escape(link)}'>{escape(t)}</a>"
                      f" <span style='color:#6b7280;font-size:12px'>· {escape(label)}</span></li>" for label, t, link in data["headlines"])
        parts.append(f"<div style='{head}'>GLOBAL ECONOMY HEADLINES</div><div style='{card}'>"
                     f"<ul style='margin:0;padding-left:18px;font-size:13.5px;line-height:1.5'>{lis}</ul></div>")
    return "".join(parts)


def render(data):
    card = "background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:12px 16px;margin:0 0 10px"
    head = "font-size:12px;font-weight:700;letter-spacing:.06em;color:#6b7280;margin:16px 0 6px"
    parts = []
    rows_html = ""
    for key in ("korea", "yields", "fx"):
        if data.get(key):
            asof, rows = data[key]
            rows_html += "".join(
                f"<tr><td style='padding:3px 0'>{escape(n)}</td><td style='text-align:right;font-weight:600'>{escape(v)}</td>"
                f"<td style='text-align:right;padding-left:12px;font-size:13px'>{_arrow(d, u)}</td></tr>"
                for n, v, d, u in rows
            ) + f"<tr><td colspan=3 style='font-size:11px;color:#9ca3af;padding-bottom:6px'>as of {escape(asof)}</td></tr>"
    if rows_html:
        parts.append(f"<div style='{head}'>MARKETS</div><div style='{card}'><table style='width:100%;font-size:14px'>{rows_html}</table></div>")
    cal = data.get("calendar")
    if cal is not None:
        if cal:
            lines = "".join(
                f"<tr><td style='padding:3px 8px 3px 0;white-space:nowrap;color:#6b7280'>{w:%m/%d %H:%M}</td>"
                f"<td style='padding:3px 8px 3px 0'><b>{escape(it['country'])}</b></td>"
                f"<td style='padding:3px 0'>{escape(it['title'])}"
                f"{'<br><span style=font-size:12px;color:#6b7280>forecast ' + escape(it['forecast']) + ' · prev ' + escape(it['previous']) + '</span>' if it.get('forecast') or it.get('previous') else ''}</td></tr>"
                for w, it in cal
            )
        else:
            lines = "<tr><td style='color:#6b7280'>No high-impact releases in the next 3 days.</td></tr>"
        parts.append(f"<div style='{head}'>CALENDAR · next 3 days, KST, high impact</div>"
                     f"<div style='{card}'><table style='font-size:14px'>{lines}</table></div>")
    return "".join(parts)
