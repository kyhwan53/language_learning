"""Market snapshot + economic calendar for the morning email. Every fetch is best-effort:
a failing source just drops its block instead of breaking the email.

Sources (free, no API key):
  - US Treasury daily par yield curve (official CSV)
  - Frankfurter (ECB reference FX rates)
  - Forex Factory weekly calendar JSON (unofficial but widely used; High impact only, KST)
"""
import csv
import io
import json
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html import escape

KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "language-learning-queue/1.0"}
CAL_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CNY"}


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


def snapshot(day, cache=None):
    """Returns dict with optional keys: yields, fx, calendar. Never raises.
    `cache` is a dict persisted by the caller (used for the rate-limited calendar)."""
    data = {}
    cache = cache if cache is not None else {}
    for key, fn in (("yields", treasury_yields), ("fx", fx), ("calendar", lambda d: calendar(d, cache))):
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


def render(data):
    card = "background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:12px 16px;margin:0 0 10px"
    head = "font-size:12px;font-weight:700;letter-spacing:.06em;color:#6b7280;margin:16px 0 6px"
    parts = []
    rows_html = ""
    for key in ("yields", "fx"):
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
