"""Stage 8: merge all sources, compute pillar scores + composite, run
validation gates, emit data/index.db and app/static/game_data.json.

Methodology (amended by Connor 2026-07-03; original per-decade scheme kept
behind common.ERA_NORMALIZE for playtesting):
- five pillars: commercial, critics, audience, cinephile, awards
- EVERY pillar = percentile rank across the WHOLE pool (strict-less fraction
  x 100; ties sit at the bottom of their band, a 0-nomination film scores 0
  on awards). Raw inputs: CPI-adjusted worldwide gross / RT+MC average /
  IMDb rating / Letterboxd weighted average / noms+wins (win counts double)
- source priority: TMDB revenue > Wikidata box office > BOM; OMDb > Wikidata
- composite = mean of available pillars; the game offer pool only takes
  films with all five ("complete fingerprints")
"""
import bisect
import json
import os
import sqlite3
from common import (CACHE, DB_PATH, GAME_JSON, GENRES, MIN_CELL_DEPTH,
                    PILLARS, WHEEL_DECADES, load_cache)

LB_DIR = os.path.join(CACHE, "letterboxd")
BOM_DIR = os.path.join(CACHE, "bom")


def load_letterboxd():
    out = {}
    if not os.path.isdir(LB_DIR):
        return out
    for fn in os.listdir(LB_DIR):
        if fn.endswith(".json"):
            with open(os.path.join(LB_DIR, fn)) as f:
                d = json.load(f)
            if d.get("rating"):
                out[fn[:-5]] = d
    return out


def load_bom():
    out = {}
    if not os.path.isdir(BOM_DIR):
        return out
    for fn in os.listdir(BOM_DIR):
        if fn.endswith(".json"):
            with open(os.path.join(BOM_DIR, fn)) as f:
                d = json.load(f)
            if d.get("worldwide") or d.get("domestic"):
                out[fn[:-5]] = d
    return out


def merge():
    pool = load_cache("pool.json")
    wd = load_cache("wikidata.json", {})
    tmdb = load_cache("tmdb.json", {}) or {}
    omdb = load_cache("omdb.json", {}) or {}
    oscars = load_cache("oscars.json", {})
    cpi = load_cache("cpi.json", {})
    lb = load_letterboxd()
    bom = load_bom()

    films = {}
    for tt, p in pool.items():
        w = wd.get(tt) or {}
        t = tmdb.get(tt) or {}
        o = omdb.get(tt) or {}
        l = lb.get(tt) or {}
        a = oscars.get(tt) or {"noms": 0, "wins": 0, "cats": []}

        b = bom.get(tt) or {}
        revenue = (t.get("revenue") or w.get("box_office")
                   or b.get("worldwide") or b.get("domestic"))
        mult = float(cpi.get(str(p["year"]), 1.0))
        rt = o.get("rt") if o.get("rt") is not None else w.get("rt")
        mc = o.get("mc") if o.get("mc") is not None else w.get("mc")
        crit_parts = [v for v in (rt, mc) if v is not None]

        f = dict(p)
        f.update({
            "tt": tt,
            "poster": t.get("poster"),
            "tmdb_id": t.get("tmdb_id"),
            "budget": t.get("budget"),
            "revenue": revenue,
            "revenue_adj": round(revenue * mult) if revenue else None,
            "rt": rt, "mc": mc,
            "lb_rating": l.get("rating"), "lb_count": l.get("count"),
            "lb_slug": l.get("slug"),
            "noms": a["noms"], "wins": a["wins"],
            "oscar_cats": a.get("cats", []),
            # raw pillar inputs
            "raw_commercial": (revenue * mult) if revenue else None,
            "raw_critics": sum(crit_parts) / len(crit_parts) if crit_parts else None,
            "raw_audience": p["imdb_rating"],
            "raw_cinephile": l.get("rating"),
            "raw_awards": a["noms"] + a["wins"],  # win counts double
        })
        films[tt] = f
    return films


def percentile_scores(films):
    """Every pillar is a percentile rank (strict-less fraction x 100) across
    the WHOLE POOL (Connor, 2026-07-03: The Godfather's audience score should
    reflect being ~top-3 on IMDb ever, not its rank within the 1970s).
    ERA_NORMALIZE=True groups by decade instead, for A/B playtesting."""
    from common import ERA_NORMALIZE
    groups = {}
    for f in films.values():
        key = f["decade"] if ERA_NORMALIZE else "all"
        groups.setdefault(key, []).append(f)

    for group in groups.values():
        for pillar in PILLARS:
            key = "raw_" + pillar
            vals = sorted(f[key] for f in group if f[key] is not None)
            n = len(vals)
            for f in group:
                v = f[key]
                if v is None or n < 2:
                    f["s_" + pillar] = None
                else:
                    f["s_" + pillar] = round(bisect.bisect_left(vals, v) / n * 100, 1)

    for f in films.values():
        scores = [f["s_" + p] for p in PILLARS if f["s_" + p] is not None]
        f["composite"] = round(sum(scores) / len(scores), 1) if scores else None
        f["complete"] = all(f["s_" + p] is not None for p in PILLARS)


def build_cells(films):
    complete = [f for f in films.values() if f["complete"]]
    cells = {}
    for dec in WHEEL_DECADES:
        for g in GENRES:
            members = [f["tt"] for f in complete
                       if f["decade"] == dec and g in f["genres"]]
            if len(members) >= MIN_CELL_DEPTH:
                cells[f"{dec}|{g}"] = members
    return cells, complete


def emit_sqlite(films):
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE films (
        tt TEXT PRIMARY KEY, title TEXT, year INT, decade TEXT,
        primary_genre TEXT, genres TEXT, directors TEXT, runtime INT,
        poster TEXT, imdb_rating REAL, imdb_votes INT,
        lb_rating REAL, lb_count INT, lb_slug TEXT,
        rt INT, mc INT, revenue REAL, revenue_adj REAL, budget REAL,
        noms INT, wins INT, oscar_cats TEXT, tmdb_id INT,
        s_commercial REAL, s_critics REAL, s_audience REAL,
        s_cinephile REAL, s_awards REAL, composite REAL, complete INT)""")
    con.executemany(
        "INSERT INTO films VALUES (" + ",".join("?" * 30) + ")",
        [(f["tt"], f["title"], f["year"], f["decade"], f["primary_genre"],
          json.dumps(f["genres"]), json.dumps(f["directors"]), f["runtime"],
          f["poster"], f["imdb_rating"], f["imdb_votes"],
          f["lb_rating"], f["lb_count"], f["lb_slug"],
          f["rt"], f["mc"], f["revenue"], f["revenue_adj"], f["budget"],
          f["noms"], f["wins"], json.dumps(f["oscar_cats"]), f.get("tmdb_id"),
          f["s_commercial"], f["s_critics"], f["s_audience"],
          f["s_cinephile"], f["s_awards"], f["composite"], int(f["complete"]))
         for f in films.values()])
    con.execute("CREATE INDEX idx_films_complete ON films(complete)")
    con.execute("CREATE INDEX idx_films_composite ON films(composite)")
    con.commit()
    con.close()
    print(f"[s08] wrote {DB_PATH} ({len(films)} films)")


def emit_game_json(films, cells, complete):
    game_films = {}
    for f in complete:
        game_films[f["tt"]] = {
            "id": f["tt"], "title": f["title"], "year": f["year"],
            "decade": f["decade"], "genres": f["genres"],
            "director": ", ".join(f["directors"]),
            "poster": f["poster"],
            "scores": {p: f["s_" + p] for p in PILLARS},
            "composite": f["composite"],
            "raw": {
                "revenue": f["revenue"], "revenue_adj": f["revenue_adj"],
                "rt": f["rt"], "mc": f["mc"],
                "imdb_rating": f["imdb_rating"], "imdb_votes": f["imdb_votes"],
                "lb_rating": f["lb_rating"], "lb_count": f["lb_count"],
                "noms": f["noms"], "wins": f["wins"],
            },
        }
    payload = {"pillars": PILLARS, "films": game_films, "cells": cells}
    os.makedirs(os.path.dirname(GAME_JSON), exist_ok=True)
    with open(GAME_JSON, "w") as f:
        json.dump(payload, f)
    print(f"[s08] wrote {GAME_JSON} "
          f"({len(game_films)} offer-pool films, {len(cells)} wheel cells, "
          f"{os.path.getsize(GAME_JSON)/1e6:.1f} MB)")


def validate(films, cells, complete):
    print("\n[s08] ===== VALIDATION GATES (docs/DESIGN.md §6 Phase 0.8) =====")
    n = len(films)
    print(f"pool size: {n} " + ("OK (>=5k)" if n >= 5000 else "!! below 5k target"))
    print(f"complete fingerprints (offer pool): {len(complete)}")
    print(f"wheel cells with depth >= {MIN_CELL_DEPTH}: {len(cells)} "
          f"of {len(WHEEL_DECADES) * len(GENRES)} possible")
    per_dec = {}
    for c in cells:
        per_dec[c.split("|")[0]] = per_dec.get(c.split("|")[0], 0) + 1
    print("cells per decade:", dict(sorted(per_dec.items())))

    def spot(tt, name):
        f = films.get(tt)
        if not f:
            print(f"  {name}: NOT IN POOL")
            return
        adj = f"${f['revenue_adj']/1e9:.2f}B" if f["revenue_adj"] else "n/a"
        print(f"  {name}: rt={f['rt']} mc={f['mc']} imdb={f['imdb_rating']} "
              f"lb={f['lb_rating']} adj={adj} "
              f"noms={f['noms']} wins={f['wins']} complete={f['complete']}")
    print("spot checks:")
    spot("tt0109830", "Forrest Gump (expect rt~75)")
    spot("tt5462602", "Paddington 2 (expect rt~99)")
    spot("tt0076759", "Star Wars (expect adj ~$4B)")
    spot("tt0111161", "Shawshank")
    print("=====================================================\n")


def main():
    films = merge()
    percentile_scores(films)
    cells, complete = build_cells(films)
    emit_sqlite(films)
    emit_game_json(films, cells, complete)
    validate(films, cells, complete)


if __name__ == "__main__":
    main()
