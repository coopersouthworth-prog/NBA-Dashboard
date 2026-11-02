"""Pull NBA headlines from RSS feeds.

Feeds are downloaded with a normal browser User-Agent, because some news sites
refuse requests that look like bots, especially from cloud servers like
GitHub Actions. Each source's result is logged, and the command fails loudly
if every source comes back empty, so a broken feed shows up as a red run on
the Actions tab instead of silently doing nothing.
"""
import calendar
import re
from datetime import datetime, timezone

import feedparser
import requests

from config import HEADLINE_FEEDS
from db import fetch_value, get_conn, upsert

TAG_RE = re.compile(r"<[^>]+>")
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
}


def _to_iso(struct_time):
    if not struct_time:
        return None
    return datetime.fromtimestamp(calendar.timegm(struct_time), tz=timezone.utc).isoformat()


def _fetch_feed(source, url):
    """Download and parse one feed. Returns its entries, or [] with a logged reason."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
    except requests.RequestException as e:
        print(f"[headlines] {source}: request failed ({e.__class__.__name__}: {e})")
        return []
    if resp.status_code != 200:
        print(f"[headlines] {source}: HTTP {resp.status_code} from {url}")
        return []
    feed = feedparser.parse(resp.content)
    if not feed.entries:
        reason = getattr(feed, "bozo_exception", "no items in feed")
        print(f"[headlines] {source}: 0 entries ({reason})")
        return []
    print(f"[headlines] {source}: {len(feed.entries)} entries")
    return feed.entries


def fetch_headlines():
    now = datetime.now(timezone.utc).isoformat()
    items, seen = [], set()
    for source, url in HEADLINE_FEEDS.items():
        for e in _fetch_feed(source, url):
            link, title = e.get("link"), e.get("title")
            if not link or not title or link in seen:
                continue
            seen.add(link)
            items.append({
                "title": title.strip(),
                "link": link,
                "summary": TAG_RE.sub("", e.get("summary", "")).strip() or None,
                "source": source,
                "published_at": _to_iso(e.get("published_parsed") or e.get("updated_parsed")),
                "fetched_at": now,
            })
    return items


def update_headlines():
    items = fetch_headlines()
    if not items:
        raise SystemExit("[headlines] every feed came back empty; see the lines above")
    with get_conn() as conn:
        before = fetch_value(conn, "SELECT COUNT(*) FROM headlines")
        upsert(conn, "headlines", items, keys=["link"], update=False)  # skip ones we have
        added = fetch_value(conn, "SELECT COUNT(*) FROM headlines") - before
    print(f"[headlines] {added} new of {len(items)} fetched")
    return items
