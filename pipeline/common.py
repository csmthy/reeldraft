"""Shared config, paths, and helpers for the pipeline."""
import csv
import gzip
import json
import os
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
CACHE = os.path.join(ROOT, "data", "cache")
DB_PATH = os.path.join(ROOT, "data", "index.db")
GAME_JSON = os.path.join(ROOT, "app", "static", "game_data.json")

# ---------------------------------------------------------------- config
def load_env():
    """Read KEY=VALUE lines from .env at repo root into a dict (env wins)."""
    cfg = {}
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    cfg.update({k: v for k, v in os.environ.items() if k in (
        "TMDB_API_KEY", "OMDB_API_KEY", "CONTACT_EMAIL")})
    return cfg

CFG = load_env()

# Pool / scoring knobs (see docs/DESIGN.md §6 Phase 0 and §7 open questions)
MIN_VOTES = int(CFG.get("MIN_VOTES", 25000))
MIN_YEAR = 1920
CPI_TARGET_YEAR = 2025
MIN_CELL_DEPTH = 8          # (decade, genre) wheel cells need this many films
WHEEL_DECADES = ["1930s", "1940s", "1950s", "1960s", "1970s",
                 "1980s", "1990s", "2000s", "2010s", "2020s"]

GENRES = ["Drama", "Comedy", "Action", "Horror", "Sci-Fi", "Thriller",
          "Crime", "Romance", "Animation", "Western", "Musical",
          "Documentary"]
# primaryGenre picks the *rarest* eligible genre first so thin cells get depth
GENRE_PRIORITY = ["Documentary", "Western", "Musical", "Animation", "Sci-Fi",
                  "Horror", "Romance", "Crime", "Thriller", "Action",
                  "Comedy", "Drama"]

PILLARS = ["commercial", "critics", "audience", "cinephile", "awards"]

# Scoring scheme (Connor, 2026-07-03): every pillar is a percentile rank
# across the WHOLE pool (box office CPI-adjusted to 2025 USD first). Flip to
# True to restore docs/DESIGN.md's original per-decade percentiles for A/B
# playtesting.
ERA_NORMALIZE = False

USER_AGENT = ("MovieIndexBuild/0.1 (one-time build step; contact: "
              + CFG.get("CONTACT_EMAIL", "set CONTACT_EMAIL") + ")")


def http_get(url, timeout=60, retries=3, sleep=2.0):
    last = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - retry any transport error
            last = e
            time.sleep(sleep)
    raise last


def http_get_json(url, **kw):
    return json.loads(http_get(url, **kw))


def tsv_rows(path):
    """Stream rows of an IMDb .tsv.gz as dicts."""
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
        for row in reader:
            yield row


def save_cache(name, obj):
    path = os.path.join(CACHE, name)
    with open(path + ".tmp", "w") as f:
        json.dump(obj, f)
    os.replace(path + ".tmp", path)
    print(f"[cache] wrote {name} ({os.path.getsize(path)/1e6:.1f} MB)")


def load_cache(name, default=None):
    path = os.path.join(CACHE, name)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def log(*a):
    print(*a, file=sys.stderr)
