"""Loads and validates config.toml (the single place to edit sources and schedule)."""
import tomllib
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.toml"
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MODES = {"newest", "oldest"}


class ConfigError(SystemExit):
    pass


def load():
    with open(CONFIG_PATH, "rb") as f:
        cfg = tomllib.load(f)
    sources = cfg.get("source", [])
    keys = [s.get("key") for s in sources]
    for s in sources:
        missing = {"key", "label", "rss", "mode"} - s.keys()
        if missing:
            raise ConfigError(f"config.toml: source {s.get('key', '?')} missing {sorted(missing)}")
        if s["mode"] not in MODES:
            raise ConfigError(f"config.toml: source '{s['key']}' mode must be one of {sorted(MODES)}")
    if len(set(keys)) != len(keys):
        raise ConfigError("config.toml: duplicate source keys")
    schedule = cfg.get("schedule", {})
    for i, d in enumerate(DAYS):
        for k in schedule.get(d, []):
            if k not in keys:
                raise ConfigError(f"config.toml: schedule.{d} uses unknown source key '{k}' (defined: {keys})")
    st = cfg.get("settings", {})
    return {
        "sources": sources,
        "schedule": {i: schedule.get(d, []) for i, d in enumerate(DAYS)},  # Mon=0
        "max_minutes": st.get("max_minutes", 30),
        "feed_days": st.get("feed_days", 7),
        "recipient": st.get("recipient", ""),
        "base_url": st.get("base_url", ""),
    }


_cfg = load()
SOURCES = _cfg["sources"]
SCHEDULE = _cfg["schedule"]
MAX_MINUTES = _cfg["max_minutes"]
FEED_DAYS = _cfg["feed_days"]
RECIPIENT = _cfg["recipient"]
BASE_URL = _cfg["base_url"]
