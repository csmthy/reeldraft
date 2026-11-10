"""Build the static, serverless demo of ReelDraft for GitHub Pages.

Renders the Flask templates once, rewrites links to work under a sub-path, and adds
app/static/demo.js, which answers the game's API calls in the browser. Needs the built data
(data/index.db and app/static/game_data.json), so run the pipeline first.

    python tools/build_demo.py                 # writes ./site for https://<user>.github.io/reeldraft/
    python tools/build_demo.py --base /x/      # different sub-path
"""

import argparse
import json
import pathlib
import re
import shutil
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import app as reeldraft  # noqa: E402

STATIC = ROOT / "app" / "static"
FILM_FIELDS = (
    "tt title year decade primary_genre genres directors runtime poster imdb_rating imdb_votes "
    "lb_rating lb_count lb_slug rt mc revenue revenue_adj budget noms wins oscar_cats tmdb_id "
    "s_commercial s_critics s_audience s_cinephile s_awards composite"
).split()
DEMO_NOTE = (
    "<p><b>Demo build.</b> This copy runs entirely in your browser, so the daily leaderboard "
    "and Letterboxd import are switched off.</p>"
)


def films_json():
    con = sqlite3.connect(ROOT / "data" / "index.db")
    con.row_factory = sqlite3.Row
    rows = con.execute(
        f"SELECT {', '.join(FILM_FIELDS)} FROM films WHERE complete = 1 ORDER BY composite DESC"
    ).fetchall()
    out = []
    for r in rows:
        f = dict(r)
        for key in ("genres", "directors", "oscar_cats"):
            f[key] = json.loads(f[key] or "[]")
        out.append(f)
    return out


def rewrite(html, base):
    html = html.replace(
        '<meta charset="utf-8">', f'<meta charset="utf-8">\n<base href="{base}">', 1
    )
    html = re.sub(r'href="/film/(tt\d+)"', r'href="film/?id=\1"', html)
    for old, new in (
        ('href="/static/', 'href="static/'),
        ('src="/static/', 'src="static/'),
        ('href="/browse"', 'href="browse/"'),
        ('action="/browse"', 'action="browse/"'),
        ('href="/methodology"', 'href="methodology/"'),
        ('href="/"', 'href="./"'),
    ):
        html = html.replace(old, new)
    # demo layer loads before any page script
    html = html.replace("<header", '<script src="static/demo.js"></script>\n<header', 1)
    html = html.replace("</footer>", DEMO_NOTE + "</footer>", 1) if "</footer>" in html else html
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="/reeldraft/")
    ap.add_argument("--out", default=str(ROOT / "site"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "static").mkdir(parents=True)

    for name in ("game.js", "demo.js", "game_data.json"):
        shutil.copy(STATIC / name, out / "static" / name)
    shutil.copytree(STATIC / "fonts", out / "static" / "fonts")
    css = (STATIC / "style.css").read_text()
    (out / "static" / "style.css").write_text(css.replace('url("/static/fonts/', 'url("fonts/'))
    (out / "static" / "films.json").write_text(json.dumps(films_json(), separators=(",", ":")))

    client = reeldraft.app.test_client()

    def page(url, dest, transform=None):
        html = client.get(url).get_data(as_text=True)
        if transform:
            html = transform(html)
        path = out / dest
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rewrite(html, args.base))

    page("/", "index.html")
    page("/browse", "browse/index.html")
    page("/methodology", "methodology/index.html")
    # one film page, filled in by demo.js from ?id=
    shell = lambda html: re.sub(  # noqa: E731
        r'<main class="page">.*?</main>',
        '<main class="page"><div id="film-root"></div></main>',
        html,
        flags=re.S,
    )
    top = films_json()[0]["tt"]
    page(f"/film/{top}", "film/index.html", shell)
    page("/film/not-a-film", "404.html")
    (out / ".nojekyll").write_text("")
    print(f"built {out} for {args.base}")


if __name__ == "__main__":
    main()
