"""Run every pipeline stage in order (each stage is resumable/cached).

Usage: .venv/bin/python pipeline/run_all.py [--lb-limit N]
--lb-limit caps this run's Letterboxd fetches (stage 6 is the slow one;
it picks up where it left off on every run).
"""
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

STAGES = ["s01_pool.py", "s02_oscars.py", "s03_wikidata.py", "s04_tmdb.py",
          "s05_omdb.py", "s06_letterboxd.py", "s07_cpi.py", "s09_bom.py",
          "s08_scores.py"]

lb_args = []
if "--lb-limit" in sys.argv:
    lb_args = ["--limit", sys.argv[sys.argv.index("--lb-limit") + 1]]

for stage in STAGES:
    args = [PY, os.path.join(HERE, stage)]
    if stage.startswith("s06"):
        args += lb_args
    print(f"\n========== {stage} ==========")
    r = subprocess.run(args)
    if r.returncode != 0:
        sys.exit(f"{stage} failed ({r.returncode})")
print("\npipeline complete")
