"""Stage 3: Wikidata enrichment — box office (P2142) and critic scores (P444,
qualified by reviewer: Rotten Tomatoes wd:Q105584, Metacritic wd:Q150248).

Free, CC0, no key. Box office has multiple statements (domestic/worldwide);
we take the max as worldwide gross (nominal USD). These are the fallback
sources; TMDB (revenue) and OMDb (RT/MC) override them when keys exist.
Output: cache/wikidata.json  {tt: {box_office, rt, mc}}
"""
import json
import re
import time
import urllib.parse
from common import http_get, load_cache, save_cache

BATCH = 350
ENDPOINT = "https://query.wikidata.org/sparql"

QUERY = """
SELECT ?imdb ?boxoffice ?rtScore ?mcScore WHERE {{
  VALUES ?imdb {{ {vals} }}
  ?film wdt:P345 ?imdb .
  OPTIONAL {{ ?film wdt:P2142 ?boxoffice . }}
  OPTIONAL {{ ?film p:P444 ?rs . ?rs pq:P447 wd:Q105584 . ?rs ps:P444 ?rtScore . }}
  OPTIONAL {{ ?film p:P444 ?ms . ?ms pq:P447 wd:Q150248 . ?ms ps:P444 ?mcScore . }}
}}
"""


def parse_pct(s):
    m = re.match(r"^(\d{1,3})\s*%$", s.strip())
    return int(m.group(1)) if m else None


def parse_mc(s):
    m = re.match(r"^(\d{1,3})\s*/\s*100$", s.strip())
    return int(m.group(1)) if m else None


def main():
    pool = load_cache("pool.json")
    out = load_cache("wikidata.json", {})
    todo = [tt for tt in pool if tt not in out]
    print(f"[s03] {len(todo)} films to query ({len(out)} cached)")

    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        vals = " ".join(f'"{t}"' for t in chunk)
        url = ENDPOINT + "?" + urllib.parse.urlencode(
            {"query": QUERY.format(vals=vals), "format": "json"})
        data = json.loads(http_get(url, timeout=120, retries=4, sleep=10))
        got = {}
        for b in data["results"]["bindings"]:
            tt = b["imdb"]["value"]
            d = got.setdefault(tt, {"box_office": None, "rt": None, "mc": None})
            if "boxoffice" in b:
                try:
                    v = float(b["boxoffice"]["value"])
                    d["box_office"] = max(d["box_office"] or 0, v)
                except ValueError:
                    pass
            if "rtScore" in b and d["rt"] is None:
                d["rt"] = parse_pct(b["rtScore"]["value"])
            if "mcScore" in b and d["mc"] is None:
                d["mc"] = parse_mc(b["mcScore"]["value"])
        for tt in chunk:
            out[tt] = got.get(tt, {"box_office": None, "rt": None, "mc": None})
        save_cache("wikidata.json", out)
        n_box = sum(1 for v in out.values() if v["box_office"])
        n_rt = sum(1 for v in out.values() if v["rt"] is not None)
        print(f"[s03] {min(i+BATCH, len(todo))}/{len(todo)}  "
              f"(box office: {n_box}, RT: {n_rt})")
        time.sleep(1.5)

    print("[s03] done")


if __name__ == "__main__":
    main()
