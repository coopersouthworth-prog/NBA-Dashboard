"""Pull NBA headlines from RSS feeds."""
import calendar
import re
from datetime import datetime, timezone

import feedparser

from config import HEADLINE_FEEDS
from db import fetch_value, get_conn, upsert

TAG_RE = re.compile(r"<[^>]+>")


def _to_iso(struct_time):
    if not struct_time:
        return None
    return datetime.fromtimestamp(calendar.timegm(struct_time), tz=timezone.utc).isoformat()


def fetch_headlines():
    now = datetime.now(timezone.utc).isoformat()
    items = []
    for source, url in HEADLINE_FEEDS.items():
        feed = feedparser.parse(url)
        if not feed.entries:
            print(f"[headlines] warning: no entries from {source} ({url})")
            continue
        for e in feed.entries:
            if not e.get("link") or not e.get("title"):
                continue
            items.append({
                "title": e.title.strip(),
                "link": e.link,
                "summary": TAG_RE.sub("", e.get("summary", "")).strip() or None,
                "source": source,
                "published_at": _to_iso(e.get("published_parsed")),
                "fetched_at": now,
            })
    return items


def update_headlines():
    items = fetch_headlines()
    with get_conn() as conn:
        before = fetch_value(conn, "SELECT COUNT(*) FROM headlines")
        upsert(conn, "headlines", items, keys=["link"], update=False)  # skip ones we have
        added = fetch_value(conn, "SELECT COUNT(*) FROM headlines") - before
    print(f"[headlines] {added} new of {len(items)} fetched")
    return items
