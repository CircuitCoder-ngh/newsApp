"""Command line: python -m pipeline {run,build,check-feeds,inspect}."""

import argparse
import json
import logging
import sys
from datetime import timedelta
from pathlib import Path

from . import config


def cmd_run(args) -> int:
    from .run import run

    record = run(args.data, args.cache, args.feeds)
    print(json.dumps(record, indent=1))
    return 0


def cmd_build(args) -> int:
    from .site.build import build

    pages = build(args.data, args.out, args.feeds)
    print(f"wrote {pages} pages to {args.out}")
    return 0


def cmd_check_feeds(args) -> int:
    from .fetch import fetch_all, load_feeds, new_articles
    from .normalize import now_utc

    feeds = load_feeds(args.feeds)
    results = fetch_all(feeds, {})
    now = now_utc()
    bad = 0
    for r in results:
        kept = len(new_articles([r], set(), now))
        status = "FAIL" if r.error else "ok"
        bad += bool(r.error)
        print(f"{status:4} {r.feed.outlet[:24]:24} {r.feed.topic:8} items={len(r.items):3} kept={kept:3}  "
              f"{r.error or ''}  {r.feed.url}")
    print(f"\n{len(results) - bad}/{len(results)} feeds ok")
    return 1 if bad else 0


def cmd_inspect(args) -> int:
    from .normalize import from_iso, now_utc
    from .store import DataStore

    store = DataStore(args.data)
    events, stories = store.load_events(), store.load_stories()
    cutoff = now_utc() - timedelta(hours=args.hours)
    shown = [s for s in stories.values() if from_iso(s.last_seen) >= cutoff and s.outlet_count >= args.min_outlets]
    shown.sort(key=lambda s: (-s.outlet_count, s.last_seen))
    for s in shown:
        print(f"\n■ {s.title}  [{s.outlet_count} outlets, {len(s.event_ids)} events]  {' · '.join(s.keywords)}  ({s.id})")
        for eid in s.event_ids:
            e = events.get(eid)
            if e is None:
                continue
            print(f"  ● {e.first_seen[5:16]} [{len(e.outlets)}] {e.headline}")
            if args.articles:
                for a in e.articles:
                    print(f"      - {a.outlet}: {a.title}")
    print(f"\n{len(shown)} stories (of {len(stories)} active) updated in the last {args.hours}h "
          f"with ≥{args.min_outlets} outlets")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pipeline")
    parser.add_argument("--data", type=Path, default=config.DEFAULT_DATA_DIR, help="data directory")
    parser.add_argument("--feeds", type=Path, default=config.FEEDS_FILE, help="feeds.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="fetch feeds and update the data directory")
    p.add_argument("--cache", type=Path, default=config.DEFAULT_CACHE_DIR, help="model and embedding cache")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("build", help="render the static site")
    p.add_argument("--out", type=Path, default=config.DEFAULT_SITE_DIR)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("check-feeds", help="fetch every feed once and report")
    p.set_defaults(func=cmd_check_feeds)

    p = sub.add_parser("inspect", help="print recent stories and events for tuning")
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--min-outlets", type=int, default=2)
    p.add_argument("--articles", action="store_true", help="also list every article")
    p.set_defaults(func=cmd_inspect)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
