"""Stage 6: Letterboxd — gentle one-time BUILD-STEP scrape (docs/DESIGN.md §4).

The official API is closed to projects like this, so per the plan we fetch
public film pages once at build time, never as a live dependency:
  - letterboxd.com/imdb/<tt>/ redirects to the film page
  - JSON-LD on the page carries the weighted average rating + rating count
Politeness: honest User-Agent (common.USER_AGENT), ~1 request / DELAY sec,
resumable per-film cache, priority order = most-drafted-first (vote count),
films only fetched once ever. robots.txt allows /film/ pages for generic
agents (verified 2026-07-02).

Usage: s06_letterboxd.py [--limit N]
Output: cache/letterboxd/<tt>.json  {rating, count, slug} (or {} = miss)
"""
import json
import os
import re
import sys
import time
import urllib.request
from common import CACHE, USER_AGENT, load_cache

DELAY = 1.6
LB_DIR = os.path.join(CACHE, "letterboxd")

LD_RE = re.compile(
    r'<script type="application/ld\+json">\s*(?:/\*\s*<!\[CDATA\[\s*\*/)?'
    r'\s*(\{.*?\})\s*(?:/\*\s*\]\]>\s*\*/)?\s*</script>', re.S)


def fetch(tt):
    req = urllib.request.Request(
        f"https://letterboxd.com/imdb/{tt}/",
        headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "replace")
        slug_m = re.search(r"letterboxd\.com/film/([^/]+)/", r.geturl())
    m = LD_RE.search(html)
    if not m:
        return {}
    d = json.loads(m.group(1))
    agg = d.get("aggregateRating") or {}
    if not agg.get("ratingValue"):
        return {}
    return {"rating": float(agg["ratingValue"]),
            "count": int(agg.get("ratingCount") or 0),
            "slug": slug_m.group(1) if slug_m else None}


def priority_order(pool):
    """Most-likely-to-be-drafted first: films whose other pillars are already
    complete (so they can enter the offer pool), by vote count."""
    wd = load_cache("wikidata.json", {})
    tmdb = load_cache("tmdb.json", {}) or {}
    omdb = load_cache("omdb.json", {}) or {}

    def complete(tt):
        w, t, o = wd.get(tt) or {}, tmdb.get(tt) or {}, omdb.get(tt) or {}
        has_box = bool(t.get("revenue") or w.get("box_office"))
        has_crit = (o.get("rt") is not None or o.get("mc") is not None
                    or w.get("rt") is not None or w.get("mc") is not None)
        return has_box and has_crit

    tts = sorted(pool, key=lambda tt: -pool[tt]["imdb_votes"])
    return [t for t in tts if complete(t)] + [t for t in tts if not complete(t)]


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    os.makedirs(LB_DIR, exist_ok=True)
    pool = load_cache("pool.json")
    order = priority_order(pool)
    todo = [tt for tt in order if not os.path.exists(os.path.join(LB_DIR, tt + ".json"))]
    if limit:
        todo = todo[:limit]
    print(f"[s06] {len(todo)} films to fetch "
          f"({len(os.listdir(LB_DIR))} cached), delay {DELAY}s")

    for n, tt in enumerate(todo, 1):
        try:
            data = fetch(tt)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = {}
            elif e.code in (429, 503):
                print(f"[s06] {e.code} — backing off 60s")
                time.sleep(60)
                continue
            else:
                print(f"[s06] {tt}: HTTP {e.code} — skipping this run")
                time.sleep(DELAY)
                continue
        except Exception as e:  # noqa: BLE001
            print(f"[s06] {tt}: {e} — skipping this run")
            time.sleep(DELAY)
            continue
        with open(os.path.join(LB_DIR, tt + ".json"), "w") as f:
            json.dump(data, f)
        if n % 50 == 0:
            print(f"[s06] {n}/{len(todo)} ({pool[tt]['title']})")
        time.sleep(DELAY)
    print("[s06] done")


if __name__ == "__main__":
    main()
