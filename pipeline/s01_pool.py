"""Stage 1: build the film pool from the IMDb non-commercial dumps.

Movies only, numVotes >= MIN_VOTES, year >= MIN_YEAR, at least one of the 12
game genres. Joins ratings + crew(directors) + name.basics(director names).
Output: cache/pool.json  {tt: {title, year, decade, genres, primary_genre,
directors, imdb_rating, imdb_votes}}
"""
import os
from common import (RAW, CACHE, GENRES, GENRE_PRIORITY, MIN_VOTES, MIN_YEAR,
                    tsv_rows, save_cache)

GENRE_SET = set(GENRES)


def main():
    print(f"[s01] filtering ratings (numVotes >= {MIN_VOTES}) ...")
    ratings = {}
    for r in tsv_rows(os.path.join(RAW, "title.ratings.tsv.gz")):
        try:
            votes = int(r["numVotes"])
        except ValueError:
            continue
        if votes >= MIN_VOTES:
            ratings[r["tconst"]] = (float(r["averageRating"]), votes)
    print(f"[s01] {len(ratings)} titles pass the vote threshold")

    print("[s01] scanning title.basics for movies ...")
    pool = {}
    for r in tsv_rows(os.path.join(RAW, "title.basics.tsv.gz")):
        tt = r["tconst"]
        if tt not in ratings or r["titleType"] != "movie":
            continue
        try:
            year = int(r["startYear"])
        except ValueError:
            continue
        if year < MIN_YEAR:
            continue
        genres = [g for g in (r["genres"] or "").split(",") if g in GENRE_SET]
        if not genres:
            continue
        primary = next(g for g in GENRE_PRIORITY if g in genres)
        rating, votes = ratings[tt]
        pool[tt] = {
            "title": r["primaryTitle"],
            "year": year,
            "decade": f"{year // 10 * 10}s",
            "genres": genres,
            "primary_genre": primary,
            "runtime": int(r["runtimeMinutes"]) if r["runtimeMinutes"].isdigit() else None,
            "imdb_rating": rating,
            "imdb_votes": votes,
            "directors": [],
        }
    print(f"[s01] pool: {len(pool)} movies")

    print("[s01] joining directors from title.crew ...")
    want_names = set()
    dir_ids = {}
    for r in tsv_rows(os.path.join(RAW, "title.crew.tsv.gz")):
        tt = r["tconst"]
        if tt in pool and r["directors"] != r"\N":
            ids = r["directors"].split(",")[:2]
            dir_ids[tt] = ids
            want_names.update(ids)

    print(f"[s01] resolving {len(want_names)} director names ...")
    names = {}
    for r in tsv_rows(os.path.join(RAW, "name.basics.tsv.gz")):
        if r["nconst"] in want_names:
            names[r["nconst"]] = r["primaryName"]

    for tt, ids in dir_ids.items():
        pool[tt]["directors"] = [names[n] for n in ids if n in names]

    save_cache("pool.json", pool)
    by_dec = {}
    for f in pool.values():
        by_dec[f["decade"]] = by_dec.get(f["decade"], 0) + 1
    print("[s01] by decade:", dict(sorted(by_dec.items())))


if __name__ == "__main__":
    main()
