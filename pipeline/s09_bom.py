"""Stage 9: Box Office Mojo gap-filler (docs/DESIGN.md §3: "The Numbers/BOM for gaps").

Only fetches films that STILL lack revenue after TMDB + Wikidata. BOM title
pages are keyed by IMDb ID (boxofficemojo.com/title/<tt>/) so joins are
exact. robots.txt allows /title/ for generic agents (verified 2026-07-03).
Same politeness rules as the Letterboxd stage: honest UA, ~1 req/1.2s,
resumable per-film cache. Old films often have no BOM data — cached as {}.

Usage: s09_bom.py [--limit N]
Output: cache/bom/<tt>.json  {worldwide, domestic} (or {} = no data)
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from common import CACHE, USER_AGENT, load_cache

DELAY = 1.2
BOM_DIR = os.path.join(CACHE, "bom")

MONEY_RE = re.compile(
    r'<span>(Domestic|International|Worldwide)[^<]*</span>.*?class="money">\$([0-9,]+)',
    re.S)


def fetch(tt):
    req = urllib.request.Request(
        f"https://www.boxofficemojo.com/title/{tt}/",
        headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "replace")
    out = {}
    for label, amount in MONEY_RE.findall(html):
        out[label.lower()] = int(amount.replace(",", ""))
    if not out.get("worldwide") and not out.get("domestic"):
        return {}
    return {"worldwide": out.get("worldwide"), "domestic": out.get("domestic")}


def missing_revenue():
    """Films with no revenue from TMDB or Wikidata, candidates first
    (has critics data -> can become offer-pool complete)."""
    pool = load_cache("pool.json")
    wd = load_cache("wikidata.json", {})
    tmdb = load_cache("tmdb.json", {}) or {}
    omdb = load_cache("omdb.json", {}) or {}

    def has_rev(tt):
        t, w = tmdb.get(tt) or {}, wd.get(tt) or {}
        return bool(t.get("revenue") or w.get("box_office"))

    def has_crit(tt):
        w, o = wd.get(tt) or {}, omdb.get(tt) or {}
        return any(v is not None for v in
                   (o.get("rt"), o.get("mc"), w.get("rt"), w.get("mc")))

    tts = sorted((t for t in pool if not has_rev(t)),
                 key=lambda t: (not has_crit(t), -pool[t]["imdb_votes"]))
    return pool, tts


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    os.makedirs(BOM_DIR, exist_ok=True)
    pool, order = missing_revenue()
    todo = [tt for tt in order
            if not os.path.exists(os.path.join(BOM_DIR, tt + ".json"))]
    if limit:
        todo = todo[:limit]
    print(f"[s09] {len(todo)} films missing revenue to try "
          f"({len(os.listdir(BOM_DIR))} cached), delay {DELAY}s")

    hits = 0
    for n, tt in enumerate(todo, 1):
        try:
            data = fetch(tt)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = {}
            elif e.code in (429, 503):
                print(f"[s09] {e.code} — backing off 60s")
                time.sleep(60)
                continue
            else:
                print(f"[s09] {tt}: HTTP {e.code} — skipping this run")
                time.sleep(DELAY)
                continue
        except Exception as e:  # noqa: BLE001
            print(f"[s09] {tt}: {e} — skipping this run")
            time.sleep(DELAY)
            continue
        with open(os.path.join(BOM_DIR, tt + ".json"), "w") as f:
            json.dump(data, f)
        hits += bool(data)
        if n % 100 == 0:
            print(f"[s09] {n}/{len(todo)}, {hits} hits ({pool[tt]['title']})")
        time.sleep(DELAY)
    print(f"[s09] done — {hits} films gained box office this run")


if __name__ == "__main__":
    main()
