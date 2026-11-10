"""Stage 5: OMDb enrichment (KEY-GATED — set OMDB_API_KEY in .env).

RT critics % + Metacritic per IMDb ID. Free key = 1k req/day; the $1+/mo
patron tier (100k/day) covers the whole pool in one run (docs/DESIGN.md §4).
Overrides Wikidata values when present.
Output: cache/omdb.json  {tt: {rt, mc, box_office_domestic}}
"""
import time
import urllib.parse
from common import CFG, http_get_json, load_cache, save_cache


def main():
    key = CFG.get("OMDB_API_KEY")
    if not key:
        print("[s05] SKIPPED — no OMDB_API_KEY in .env (RT/Metacritic come "
              "from Wikidata fallback; add a key and rerun)")
        return
    pool = load_cache("pool.json")
    out = load_cache("omdb.json", {})
    todo = [tt for tt in pool if tt not in out]
    print(f"[s05] {len(todo)} films to fetch ({len(out)} cached)")

    for n, tt in enumerate(todo, 1):
        try:
            d = http_get_json("https://www.omdbapi.com/?" + urllib.parse.urlencode(
                {"apikey": key, "i": tt, "tomatoes": "true"}))
            rt = mc = None
            for r in d.get("Ratings", []):
                if r["Source"] == "Rotten Tomatoes":
                    rt = int(r["Value"].rstrip("%"))
                elif r["Source"] == "Metacritic":
                    mc = int(r["Value"].split("/")[0])
            box = d.get("BoxOffice", "N/A")
            box = int(box.replace("$", "").replace(",", "")) if box not in ("N/A", "", None) else None
            out[tt] = {"rt": rt, "mc": mc, "box_office_domestic": box}
        except Exception as e:  # noqa: BLE001
            print(f"[s05] {tt}: {e} — will retry next run")
        if n % 500 == 0 or n == len(todo):
            save_cache("omdb.json", out)
            print(f"[s05] {n}/{len(todo)}")
        time.sleep(0.05)
    save_cache("omdb.json", out)
    print("[s05] done")


if __name__ == "__main__":
    main()
