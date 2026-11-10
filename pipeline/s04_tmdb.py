"""Stage 4: TMDB enrichment (needs TMDB_API_KEY in .env).

Pulls poster path, budget, revenue, TMDB id — one request per film via
/movie/{imdb_id} (TMDB resolves IMDb IDs natively). TMDB free tier is
non-commercial WITH ATTRIBUTION (see docs/DESIGN.md §4); the site footer carries
the attribution. 4 workers ≈ 15 req/s, well under TMDB's ~50/s guidance.
Output: cache/tmdb.json  {tt: {tmdb_id, poster, budget, revenue} | null}
"""
import json
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from common import CFG, USER_AGENT, load_cache, save_cache

IMG = "https://image.tmdb.org/t/p/w342"
WORKERS = 4


def fetch(tt, key):
    url = f"https://api.themoviedb.org/3/movie/{tt}?api_key={key}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            det = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None          # not a movie on TMDB
        raise
    return {
        "tmdb_id": det["id"],
        "poster": IMG + det["poster_path"] if det.get("poster_path") else None,
        "budget": det.get("budget") or None,
        "revenue": det.get("revenue") or None,
    }


def main():
    key = CFG.get("TMDB_API_KEY")
    if not key:
        print("[s04] SKIPPED — no TMDB_API_KEY in .env (posters/budget/revenue "
              "will come from fallbacks; add a free key and rerun)")
        return
    pool = load_cache("pool.json")
    out = load_cache("tmdb.json", {})
    todo = [tt for tt in pool if tt not in out]
    print(f"[s04] {len(todo)} films to fetch ({len(out)} cached), "
          f"{WORKERS} workers")
    lock = threading.Lock()
    done = [0]

    def work(tt):
        try:
            res = fetch(tt, key)
        except Exception as e:  # noqa: BLE001
            print(f"[s04] {tt}: {e} — will retry next run")
            return
        with lock:
            out[tt] = res
            done[0] += 1
            if done[0] % 500 == 0:
                save_cache("tmdb.json", out)
                print(f"[s04] {done[0]}/{len(todo)}")

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(work, todo))
    save_cache("tmdb.json", out)
    n_rev = sum(1 for v in out.values() if v and v.get("revenue"))
    n_pos = sum(1 for v in out.values() if v and v.get("poster"))
    print(f"[s04] done — revenue for {n_rev}, posters for {n_pos} "
          f"of {len(out)} films")


if __name__ == "__main__":
    main()
