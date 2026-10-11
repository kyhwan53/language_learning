"""Manage sources in config.toml without hand-editing.

    python manage.py list                               # sources + weekly schedule
    python manage.py check                              # verify every feed is alive, show latest episode
    python manage.py preview <rss-url>                  # test a candidate feed before adding
    python manage.py add <key> "<label>" <rss-url> [--mode newest|oldest]
    python manage.py remove <key>                       # also drops it from the schedule
    python manage.py schedule <mon..sun> key1,key2,...  # e.g. schedule mon biz,sci,jp
After any change run `check`; the next build_daily.py run picks it up (today's queue is kept if already built).
"""
import re
import sys
from pathlib import Path

import sources
from build_daily import fetch_episodes

CFG = sources.CONFIG_PATH


def _text():
    return CFG.read_text(encoding="utf-8")


def _save(text):
    old = _text()
    CFG.write_text(text, encoding="utf-8")
    try:
        sources.load()  # validate the edit
    except BaseException:
        CFG.write_text(old, encoding="utf-8")  # never leave a broken config behind
        raise


def cmd_list():
    for s in sources.SOURCES:
        print(f"{s['key']:8} {s['label']:14} {s['mode']:7} {s['rss']}")
    print()
    for i, d in enumerate(sources.DAYS):
        print(f"{d}: {', '.join(sources.SCHEDULE[i])}")


def summarize(rss):
    eps = fetch_episodes(rss)
    newest = max(eps, key=lambda e: e["pub"].timestamp() if e["pub"] else 0)
    mins = [e["minutes"] for e in eps[:10] if e["minutes"]]
    avg = f"avg ~{sum(mins) // len(mins)} min" if mins else "no duration info"
    return f"{len(eps)} episodes, {avg}; latest: {newest['title'][:60]}"


def cmd_check():
    bad = 0
    for s in sources.SOURCES:
        try:
            print(f"OK   {s['key']:8} {summarize(s['rss'])}")
        except Exception as e:  # noqa: BLE001 - report any failure per feed
            bad += 1
            print(f"FAIL {s['key']:8} {e}")
    sys.exit(1 if bad else 0)


def cmd_add(key, label, rss, mode="newest"):
    if not re.fullmatch(r"[A-Za-z0-9_]+", key):
        sys.exit("key must be letters/digits/underscore")
    if key in [s["key"] for s in sources.SOURCES]:
        sys.exit(f"key '{key}' already exists")
    print("testing feed:", summarize(rss))
    block = f'[[source]]\nkey = "{key}"\nlabel = "{label}"\nrss = "{rss}"\nmode = "{mode}"\n\n'
    text = _text()
    marker = "# --- 읽기용"
    if marker not in text:
        sys.exit("config.toml: schedule marker not found; add the block by hand")
    _save(text.replace(marker, block + marker, 1))
    print(f"added '{key}'. Put it in the schedule: python manage.py schedule mon {key},jp")


def cmd_remove(key):
    if key not in [s["key"] for s in sources.SOURCES]:
        sys.exit(f"unknown key '{key}'")
    text = re.sub(rf'\[\[source\]\]\nkey = "{re.escape(key)}"\n.*?\n\n', "", _text(), flags=re.S)

    def drop(m):
        keys = [k for k in re.findall(r'"([^"]+)"', m.group(2)) if k != key]
        return m.group(1) + "[" + ", ".join(f'"{k}"' for k in keys) + "]"

    text = re.sub(r"(?m)^((?:mon|tue|wed|thu|fri|sat|sun) = )(\[.*?\])", drop, text)
    _save(text)
    print(f"removed '{key}' (also from schedule)")


def cmd_schedule(day, keys):
    if day not in sources.DAYS:
        sys.exit(f"day must be one of {sources.DAYS}")
    new = "[" + ", ".join(f'"{k.strip()}"' for k in keys.split(",") if k.strip()) + "]"
    text, n = re.subn(rf"(?m)^{day} = \[.*?\]", f"{day} = {new}", _text())
    if n != 1:
        sys.exit(f"could not find '{day}' line in config.toml")
    _save(text)
    print(f"{day}: {new}")


def main(argv):
    if not argv:
        print(__doc__)
        return
    cmd, args = argv[0], argv[1:]
    if cmd == "list":
        cmd_list()
    elif cmd == "check":
        cmd_check()
    elif cmd == "preview" and len(args) == 1:
        print(summarize(args[0]))
    elif cmd == "add" and len(args) >= 3:
        mode = args[args.index("--mode") + 1] if "--mode" in args else "newest"
        cmd_add(args[0], args[1], args[2], mode)
    elif cmd == "remove" and len(args) == 1:
        cmd_remove(args[0])
    elif cmd == "schedule" and len(args) == 2:
        cmd_schedule(*args)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
