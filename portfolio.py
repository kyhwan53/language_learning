"""Buy candidates from the private portfolio_managing repo, shown only in the owner's copy of the email.

The workflow asks portfolio_managing to run in "candidates" mode and downloads its artifact to
portfolio_out/candidates.json. This repo is public, so nothing from that file is printed to the logs,
committed, or sent to EXTRA_RECIPIENTS.
"""
import json
from datetime import date, datetime
from html import escape
from pathlib import Path

FILE = Path(__file__).parent / "portfolio_out" / "candidates.json"


def load(day: date):
    """Today's candidates, or None when the file is missing, unreadable or older than a day."""
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
        made = datetime.strptime(d["generated"], "%Y-%m-%d %H:%M").date()
    except Exception:  # noqa: BLE001
        return None
    return d if (day - made).days <= 1 else None


def _pct(x, signed=True):
    return "–" if x is None else (f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%")


def _won(n):
    return f"{n / 1e4:,.0f}만" if n else "–"


def render(d) -> str:
    if not d:
        return ""
    head = "font-size:12px;font-weight:700;letter-spacing:.06em;color:#6b7280;margin:16px 0 6px"
    card = "background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:12px 16px;margin:0 0 10px"
    sub = "font-size:12px;color:#6b7280"
    rows = []
    for i, w in enumerate(d["items"], 1):
        px = f"${w['price']:,.2f}" if w["ccy"] == "USD" else f"{w['price']:,.0f}원"
        size = f"{_won(w['size'])}{' (절반)' if w.get('half') else ''}" + (f" ≈ {w['shares']}주" if w.get("shares") else "")
        extra = []
        if w.get("inst") and w["inst"].get("inst_amt") is not None:
            extra.append(f"기관 {w['inst'].get('inst_days', 20)}일 {w['inst']['inst_amt'] / 1e8:+,.0f}억")
        if w.get("d_earn") is not None and w["d_earn"] >= 0:
            extra.append(f"실적 D-{w['d_earn']}")
        rows.append(
            f"<tr><td style='padding:7px 8px 7px 0;vertical-align:top;color:#6b7280;font-weight:600'>{i}</td>"
            f"<td style='padding:7px 0;border-top:{'0' if i == 1 else '1px solid #eef0f2'}'>"
            f"<b>{escape(w['name'] or w['ticker'])}</b> <span style='{sub}'>{escape(w['ticker'])} · {escape(w.get('sector') or w.get('source') or '')}</span><br>"
            f"<span style='font-size:13px'>점수 <b>{w['score']:.2f}</b> · 6개월 {_pct(w['ret_6m'])} · 1개월 {_pct(w['ret_1m'])}"
            f" · 20일선 {_pct(w['vs_ma'])}</span><br>"
            f"<span style='{sub}'>{px} · 매수 {size} · 손절선까지 {_pct(1 / (1 + w['to_stop']) - 1 if w.get('to_stop') is not None else None)}"
            f" · ATR {_pct(w['atr_pct'], False)}{' · ' + ' · '.join(extra) if extra else ''}</span></td></tr>"
        )
    r = d.get("rules", {})
    note = (f"{escape(d['generated'])} 기준 · 매수 가능 {d['n_ok']}개 중 점수(6개월 수익률÷변동성) 상위 {len(d['items'])}개. "
            f"매도: 20일선+{(r.get('env_pct') or 0.1) * 100:.0f}% 돌파 시 1/3, 나머지 ATR×{r.get('atr_mult', 5):g} 손절. "
            f"<a style='color:#2f6fed;text-decoration:none' href='{escape(d.get('page', ''))}'>대시보드</a>")
    body = "".join(rows) if rows else "<tr><td style='color:#6b7280'>오늘은 매수 가능 후보가 없습니다.</td></tr>"
    return (f"<div style='{head}'>PORTFOLIO · 알파 매수 후보</div>"
            f"<div style='{card}'><table style='width:100%;border-collapse:collapse;font-size:14px'>{body}</table>"
            f"<div style='{sub};margin-top:8px;line-height:1.5'>{note}</div></div>")
