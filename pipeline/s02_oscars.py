"""Stage 2: Oscar nominations/wins per film from DLu/oscar_data (has IMDb IDs).

Raw awards metric per docs/DESIGN.md: noms + wins, where a win counts double
(i.e. each win adds one extra point on top of its nomination).
Output: cache/oscars.json  {tt: {"noms": n, "wins": w}}
"""
import csv
import os
from common import RAW, save_cache


def main():
    path = os.path.join(RAW, "oscars.csv")
    films = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            ids = (row.get("FilmId") or "").split("|")
            win = bool((row.get("Winner") or "").strip())
            cat = (row.get("CanonicalCategory") or row.get("Category") or "").title()
            year = row.get("Year") or ""
            for tt in ids:
                tt = tt.strip()
                if not tt.startswith("tt"):
                    continue
                d = films.setdefault(tt, {"noms": 0, "wins": 0, "cats": []})
                d["noms"] += 1
                if win:
                    d["wins"] += 1
                d["cats"].append({"c": cat, "y": year, "w": win})
    save_cache("oscars.json", films)
    print(f"[s02] {len(films)} films with Oscar history")


if __name__ == "__main__":
    main()
