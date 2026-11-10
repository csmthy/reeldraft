"""Rarity bonus job — run once after a daily closes (docs/DESIGN.md §5 step 5).

Picks that few players made AND that scored well earn a bonus, so the
obvious pick is never the optimal pick. For each seated film with a seat
score >= RARITY_MIN_SCORE:  bonus += (1 - pick_share) * RARITY_WEIGHT.
final = score + bonus (leaderboard sorts by final).

Usage:  .venv/bin/python app/jobs_rarity.py [YYYY-MM-DD]   (default: yesterday)
Cron:   5 0 * * *  cd <repo> && .venv/bin/python app/jobs_rarity.py
"""
import datetime as dt
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DB = os.path.join(ROOT, "data", "app.db")
GAME_JSON = os.path.join(ROOT, "app", "static", "game_data.json")

RARITY_MIN_SCORE = 70.0   # only good picks earn rarity (tunable)
RARITY_WEIGHT = 3.0       # max bonus per film (tunable)


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else (
        dt.date.today() - dt.timedelta(days=1)).isoformat()
    with open(GAME_JSON) as f:
        films = json.load(f)["films"]
    con = sqlite3.connect(APP_DB)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT id, seats, score FROM results WHERE date=?",
                       (date,)).fetchall()
    n = len(rows)
    if not n:
        print(f"[rarity] no results for {date}")
        return

    counts = {}
    for r in rows:
        for fid in json.loads(r["seats"]).values():
            if fid:
                counts[fid] = counts.get(fid, 0) + 1

    for r in rows:
        bonus = 0.0
        for pillar, fid in json.loads(r["seats"]).items():
            if fid and films[fid]["scores"][pillar] >= RARITY_MIN_SCORE:
                bonus += (1 - counts[fid] / n) * RARITY_WEIGHT
        bonus = round(bonus, 2)
        con.execute("UPDATE results SET bonus=?, final=? WHERE id=?",
                    (bonus, round(r["score"] + bonus, 2), r["id"]))
    con.commit()
    print(f"[rarity] {date}: {n} results updated "
          f"(max bonus {max((r[0] for r in con.execute('SELECT bonus FROM results WHERE date=?', (date,))), default=0)})")


if __name__ == "__main__":
    main()
