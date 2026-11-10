"""Stage 7: CPI table from the BLS public API (series CUUR0000SA0, annual
averages) -> multiplier per release year to constant 2025 USD.

BLS v1 API: no key, 10-year windows, 25 req/day — we need ~11 requests once,
then it's cached forever.
Output: cache/cpi.json  {year(str): multiplier_to_2025}
"""
import json
import time
import urllib.request
from common import CPI_TARGET_YEAR, MIN_YEAR, USER_AGENT, load_cache, save_cache

API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"


def fetch_window(start, end):
    body = json.dumps({"seriesid": ["CUUR0000SA0"], "startyear": str(start),
                       "endyear": str(end), "annualaverage": True}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Content-Type": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    out = {}
    for item in d["Results"]["series"][0]["data"]:
        if item["period"] == "M13" and item["value"] not in ("-", ""):
            out[int(item["year"])] = float(item["value"])
    return out


def main():
    cached = load_cache("cpi.json")
    if cached:
        print(f"[s07] cached ({len(cached)} years) — delete cache/cpi.json to refresh")
        return
    cpi = {}
    y = MIN_YEAR
    while y <= CPI_TARGET_YEAR:
        end = min(y + 9, CPI_TARGET_YEAR)
        cpi.update(fetch_window(y, end))
        print(f"[s07] {y}-{end} ok")
        y = end + 1
        time.sleep(1)
    base = cpi[CPI_TARGET_YEAR]
    mult = {str(y): round(base / v, 4) for y, v in sorted(cpi.items())}
    # future / missing years -> 1.0 at lookup time (see s08)
    save_cache("cpi.json", mult)
    print(f"[s07] {len(mult)} years; 1977 multiplier = {mult.get('1977')}")


if __name__ == "__main__":
    main()
