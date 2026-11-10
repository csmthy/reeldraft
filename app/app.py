"""ReelDraft (working title) — Flask backend.

Serves: the game shell, daily seeded boards, result submission with
server-side rescoring, daily leaderboard, Letterboxd Fav-4 import,
and the Index (film pages / browse / methodology).

Run:  .venv/bin/python app/app.py   (http://127.0.0.1:5023)
"""
import datetime as dt
import hashlib
import json
import os
import random
import re
import sqlite3
import time
import urllib.request

from flask import Flask, g, jsonify, render_template, request

import scoring

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_JSON = os.path.join(ROOT, "app", "static", "game_data.json")
INDEX_DB = os.path.join(ROOT, "data", "index.db")
APP_DB = os.path.join(ROOT, "data", "app.db")

SITE_NAME = "ReelDraft"
INDEX_NAME = "The Reel Index"
SCORE_NAME = "Reel Score"
LAUNCH_DATE = dt.date(2026, 7, 2)
CONTACT = os.environ.get("CONTACT_EMAIL", "set CONTACT_EMAIL")
USER_AGENT = f"ReelDraft-Fav4/0.1 (one page per new user, cached; contact: {CONTACT})"
FAV4_CACHE_HOURS = 24

app = Flask(__name__)

# ------------------------------------------------------------- game data
_game = {"mtime": 0, "data": None, "slug_index": None}


def game_data():
    m = os.path.getmtime(GAME_JSON)
    if m != _game["mtime"]:
        with open(GAME_JSON) as f:
            _game["data"] = json.load(f)
        _game["mtime"] = m
        _game["slug_index"] = None
    return _game["data"]


def slugify(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s


def slug_index():
    """letterboxd slug -> film id (from scrape slugs + slugified titles)."""
    if _game["slug_index"] is None:
        idx = {}
        con = index_db()
        for tt, slug, title, year in con.execute(
                "SELECT tt, lb_slug, title, year FROM films WHERE complete=1"):
            if slug:
                idx.setdefault(slug, tt)
            t = slugify(title)
            idx.setdefault(t, tt)
            idx.setdefault(f"{t}-{year}", tt)
        _game["slug_index"] = idx
    return _game["slug_index"]


# ------------------------------------------------------------------- dbs
def index_db():
    if "index_db" not in g:
        g.index_db = sqlite3.connect(INDEX_DB)
        g.index_db.row_factory = sqlite3.Row
    return g.index_db


def app_db():
    if "app_db" not in g:
        first = not os.path.exists(APP_DB)
        g.app_db = sqlite3.connect(APP_DB)
        g.app_db.row_factory = sqlite3.Row
        if first:
            init_app_db(g.app_db)
    return g.app_db


def init_app_db(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY, date TEXT, client_id TEXT, handle TEXT,
        seats TEXT, used_respin INT, easy INT DEFAULT 0, score REAL,
        verdict TEXT, bonus REAL DEFAULT 0, final REAL, created_at REAL,
        UNIQUE(date, client_id));
    CREATE INDEX IF NOT EXISTS idx_results_date ON results(date, final DESC);
    CREATE TABLE IF NOT EXISTS fav4 (
        username TEXT PRIMARY KEY, fetched_at REAL, data TEXT);
    """)
    con.commit()


@app.teardown_appcontext
def close_dbs(_):
    for key in ("index_db", "app_db"):
        db = g.pop(key, None)
        if db:
            db.close()


# ------------------------------------------------------------ daily board
def board_for(date_str):
    """Deterministic daily board: 4 primary spins + 2 respin alternates.
    Each spin = (decade, genre) cell + 4 poster choices + 4 reroll choices
    (the same-cell lifeline); films distinct across the whole board."""
    data = game_data()
    rng = random.Random(hashlib.sha256(f"reeldraft:{date_str}".encode()).hexdigest())
    cells = sorted(data["cells"])
    picked_cells = rng.sample(cells, 6)
    used_films = set()
    spins = []
    for cell in picked_cells:
        members = [f for f in data["cells"][cell] if f not in used_films]
        picked = rng.sample(members, min(8, len(members)))
        used_films.update(picked)
        decade, genre = cell.split("|")
        spins.append({"decade": decade, "genre": genre,
                      "choices": picked[:4], "reroll": picked[4:8]})
    return {"spins": spins[:4], "alternates": spins[4:]}


def film_brief(fid):
    f = game_data()["films"][fid]
    # raw stats ride along for easy mode; normal mode simply never renders them
    return {"id": fid, "title": f["title"], "year": f["year"],
            "director": f["director"], "poster": f["poster"], "raw": f["raw"]}


def film_reveal(fid):
    f = game_data()["films"][fid]
    return {**film_brief(fid), "scores": f["scores"],
            "composite": f["composite"], "raw": f["raw"]}


def today():
    return dt.date.today().isoformat()


def day_number(date_str):
    return (dt.date.fromisoformat(date_str) - LAUNCH_DATE).days + 1


# ------------------------------------------------------------------ pages
@app.route("/")
def page_game():
    return render_template("game.html", site=SITE_NAME, index_name=INDEX_NAME)


@app.route("/browse")
def page_browse():
    q = (request.args.get("q") or "").strip()
    decade = request.args.get("decade") or ""
    genre = request.args.get("genre") or ""
    sql = "SELECT * FROM films WHERE complete = 1"
    args = []
    if q:
        sql += " AND title LIKE ?"
        args.append(f"%{q}%")
    if decade:
        sql += " AND decade = ?"
        args.append(decade)
    if genre:
        sql += " AND genres LIKE ?"
        args.append(f'%"{genre}"%')
    sql += " ORDER BY composite DESC LIMIT 250"
    films = index_db().execute(sql, args).fetchall()
    decades = [r[0] for r in index_db().execute(
        "SELECT DISTINCT decade FROM films ORDER BY decade")]
    return render_template("browse.html", site=SITE_NAME, index_name=INDEX_NAME,
                           score_name=SCORE_NAME, films=films, q=q,
                           decade=decade, genre=genre, decades=decades,
                           genres=sorted(json.loads(
                               '["Drama","Comedy","Action","Horror","Sci-Fi","Thriller",'
                               '"Crime","Romance","Animation","Western","Musical","Documentary"]')))


@app.route("/film/<tt>")
def page_film(tt):
    f = index_db().execute("SELECT * FROM films WHERE tt = ?", (tt,)).fetchone()
    if not f:
        return render_template("base.html", site=SITE_NAME,
                               index_name=INDEX_NAME), 404

    def money(v):
        return f"${v/1e9:.2f}B" if v >= 1e9 else f"${v/1e6:.0f}M"
    raw_texts = {
        "commercial": money(f["revenue_adj"]) + " adj." if f["revenue_adj"] else "no gross recorded",
        "critics": " · ".join(x for x in (
            f"RT {f['rt']}%" if f["rt"] is not None else "",
            f"MC {f['mc']}" if f["mc"] is not None else "") if x) or "no scores",
        "audience": f"IMDb {f['imdb_rating']}/10",
        "cinephile": f"LB {f['lb_rating']}/5" if f["lb_rating"] else "no rating yet",
        "awards": f"{f['noms']} noms, {f['wins']} wins",
    }
    pillars = [(p, scoring.PILLAR_LABELS[p], f["s_" + p], raw_texts[p])
               for p in scoring.PILLARS]
    rank = None
    if f["complete"]:
        pos = index_db().execute(
            "SELECT COUNT(*)+1 FROM films WHERE complete=1 AND composite > ?",
            (f["composite"],)).fetchone()[0]
        total = index_db().execute(
            "SELECT COUNT(*) FROM films WHERE complete=1").fetchone()[0]
        rank = (pos, total)
    return render_template("film.html", site=SITE_NAME, index_name=INDEX_NAME,
                           score_name=SCORE_NAME, f=f, pillars=pillars,
                           rank=rank, genres=json.loads(f["genres"]),
                           directors=json.loads(f["directors"]),
                           oscar_cats=json.loads(f["oscar_cats"] or "[]"))


@app.route("/methodology")
def page_methodology():
    n = index_db().execute("SELECT COUNT(*) FROM films").fetchone()[0]
    nc = index_db().execute("SELECT COUNT(*) FROM films WHERE complete=1").fetchone()[0]
    return render_template("methodology.html", site=SITE_NAME,
                           index_name=INDEX_NAME, score_name=SCORE_NAME,
                           n_films=n, n_complete=nc)


# -------------------------------------------------------------- game API
@app.route("/api/daily")
def api_daily():
    date = today()
    b = board_for(date)
    def brief_spin(s):
        return {**s, "choices": [film_brief(f) for f in s["choices"]],
                "reroll": [film_brief(f) for f in s["reroll"]]}
    return jsonify({
        "date": date, "day_number": day_number(date),
        "pillars": scoring.PILLARS,
        "spins": [brief_spin(s) for s in b["spins"]],
        "alternates": [brief_spin(s) for s in b["alternates"]],
    })


@app.route("/api/result", methods=["POST"])
def api_result():
    d = request.get_json(force=True)
    date = today()
    if d.get("date") != date:
        return jsonify({"error": "not today's board"}), 400
    client_id = (d.get("client_id") or "")[:64]
    handle = re.sub(r"[^\w .\-]", "", d.get("handle") or "anon")[:24] or "anon"
    seats = d.get("seats") or {}
    if not client_id:
        return jsonify({"error": "missing client_id"}), 400

    # validate seats: 4 films in 4 distinct seats, all from today's board,
    # each film from a distinct spin cell
    board = board_for(date)
    valid_cells = board["spins"] + (board["alternates"] if d.get("used_respin") else [])
    film_cell = {}
    for i, s in enumerate(valid_cells):
        for fid in s["choices"] + s["reroll"]:
            film_cell[fid] = i
    picks = {p: f for p, f in seats.items() if f}
    if (set(seats) - set(scoring.PILLARS)) or len(picks) != 4 \
            or len(set(picks.values())) != 4 \
            or any(f not in film_cell for f in picks.values()) \
            or len({film_cell[f] for f in picks.values()}) != 4:
        return jsonify({"error": "invalid slate for today's board"}), 400

    full_seats = {p: picks.get(p) for p in scoring.PILLARS}
    result = scoring.score_slate(full_seats, game_data()["films"])

    con = app_db()
    existing = con.execute(
        "SELECT * FROM results WHERE date=? AND client_id=?",
        (date, client_id)).fetchone()
    if not existing:
        con.execute(
            "INSERT INTO results (date, client_id, handle, seats, used_respin,"
            " easy, score, verdict, bonus, final, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,0,?,?)",
            (date, client_id, handle, json.dumps(full_seats),
             int(bool(d.get("used_respin"))), int(bool(d.get("easy"))),
             result["total"], result["verdict"], result["total"], time.time()))
        con.commit()

    rank, players = _rank(con, date, result["total"])
    return jsonify({
        **result,
        "films": {p: film_reveal(f) if f else None for p, f in full_seats.items()},
        "rank": rank, "players": players,
        "percentile": round(100 * (players - rank + 1) / players) if players else 100,
        "day_number": day_number(date),
    })


def _rank(con, date, score):
    players = con.execute("SELECT COUNT(*) FROM results WHERE date=?",
                          (date,)).fetchone()[0]
    better = con.execute("SELECT COUNT(*) FROM results WHERE date=? AND final>?",
                         (date, score)).fetchone()[0]
    return better + 1, players


@app.route("/api/leaderboard")
def api_leaderboard():
    date = request.args.get("date") or today()
    con = app_db()
    rows = con.execute(
        "SELECT handle, score, verdict, bonus, final, seats, easy FROM results"
        " WHERE date=? ORDER BY final DESC, created_at ASC LIMIT 50",
        (date,)).fetchall()
    players = con.execute("SELECT COUNT(*) FROM results WHERE date=?",
                          (date,)).fetchone()[0]
    films = game_data()["films"]
    out = []
    for r in rows:
        seats = json.loads(r["seats"])
        out.append({"handle": r["handle"], "score": r["score"],
                    "verdict": r["verdict"], "bonus": r["bonus"],
                    "final": r["final"], "easy": bool(r["easy"]),
                    "titles": [films[f]["title"] for f in seats.values() if f]})
    return jsonify({"date": date, "players": players, "top": out})


# ------------------------------------------------------------ Fav-4 import
FAVS_RE = re.compile(r'id="favourites".*?</section>', re.S)
SLUG_RE = re.compile(r'data-(?:film-|item-)?slug="([^"]+)"|href="/film/([^/"]+)/"')


def fetch_fav4(username):
    req = urllib.request.Request(f"https://letterboxd.com/{username}/",
                                 headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "replace")
    m = FAVS_RE.search(html)
    if not m:
        return []
    slugs = []
    for a, b in SLUG_RE.findall(m.group(0)):
        s = a or b
        if s and s not in slugs:
            slugs.append(s)
    return slugs[:4]


@app.route("/api/fav4/<username>")
def api_fav4(username):
    username = username.lower()
    if not re.fullmatch(r"[a-z0-9_]{2,15}", username):
        return jsonify({"error": "invalid username"}), 400
    con = app_db()
    row = con.execute("SELECT * FROM fav4 WHERE username=?", (username,)).fetchone()
    if row and time.time() - row["fetched_at"] < FAV4_CACHE_HOURS * 3600:
        return jsonify(json.loads(row["data"]))

    try:
        slugs = fetch_fav4(username)
    except urllib.error.HTTPError as e:
        code = 404 if e.code == 404 else 502
        return jsonify({"error": "profile not found" if code == 404
                        else "letterboxd unreachable"}), code
    except Exception:  # noqa: BLE001 - degrade gracefully (docs/DESIGN.md §4)
        return jsonify({"error": "letterboxd unreachable"}), 502
    if not slugs:
        return jsonify({"error": "no favorites found on profile"}), 404

    idx = slug_index()
    matched, unmatched = [], []
    for s in slugs:
        base = re.sub(r"-\d{4}$", "", s)
        fid = idx.get(s) or idx.get(base)
        (matched if fid else unmatched).append(fid or s)
    films = game_data()["films"]
    matched = [f for f in matched if f in films]
    if len(matched) < 2:
        return jsonify({"error": "too few of these favorites are in the pool",
                        "unmatched": unmatched}), 422

    seats, result = scoring.best_seating(matched, films)
    date = today()
    board_scores = [r["final"] for r in con.execute(
        "SELECT final FROM results WHERE date=?", (date,))]
    beat = sum(1 for s in board_scores if result["total"] > s)
    payload = {
        "username": username, **result,
        "films": {p: film_reveal(f) if f else None for p, f in seats.items()},
        "unmatched": unmatched,
        "today": {"players": len(board_scores), "would_beat": beat},
        "day_number": day_number(date),
    }
    con.execute("INSERT OR REPLACE INTO fav4 VALUES (?,?,?)",
                (username, time.time(), json.dumps(payload)))
    con.commit()
    return jsonify(payload)


@app.route("/api/fav4_leaderboard")
def api_fav4_leaderboard():
    con = app_db()
    rows = con.execute("SELECT username, data FROM fav4").fetchall()
    entries = []
    for r in rows:
        d = json.loads(r["data"])
        entries.append({"username": r["username"], "total": d["total"],
                        "verdict": d["verdict"],
                        "titles": [f["title"] for f in d["films"].values() if f]})
    entries.sort(key=lambda e: -e["total"])
    return jsonify({"top": entries[:50], "count": len(entries)})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5023)), debug=False)
