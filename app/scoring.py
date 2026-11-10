"""The scoring engine — one engine, two products (docs/DESIGN.md §3, §5).

Seat mechanic: 5 pillar seats, 4 films; each film scores its own pillar
value in the seat you gave it. Every EMPTY seat scores the slate's worst
number in that pillar (EMPTY_SEAT_RULE='worst_unseated'), so you choose
what to punt and misreads are punished. Alternative flat penalty kept as a
config for playtesting (open question #1).

Verdict tiers with weakest-link demotions calibrated on The Slate's
reference numbers (93/82/70/52, demote if any seat < 65 / < 55) —
open question #2 says retune on real distributions.

Mirrored in JS in app/static/game.js — keep the two in sync.
"""
from itertools import permutations

PILLARS = ["commercial", "critics", "audience", "cinephile", "awards"]
PILLAR_LABELS = {
    "commercial": "Commercial", "critics": "Critics", "audience": "Audience",
    "cinephile": "Cinephile", "awards": "Awards",
}

EMPTY_SEAT_RULE = "worst_unseated"   # or "flat"
FLAT_PENALTY = 35.0

TIERS = [                       # (min_total, min_seat_required, name)
    (93, 65, "Blockbuster"),
    (82, 55, "Smash Hit"),
    (70, 0, "Solid Opening"),
    (52, 0, "Underperformer"),
    (0, 0, "Flop"),
]


def score_slate(seats, films):
    """seats: {pillar: film_id or None}; films: {id: {"scores": {pillar: v}}}.
    Returns dict with per-seat scores, total, verdict, demotion flag."""
    drafted = [films[fid] for fid in seats.values() if fid]
    if not drafted:
        raise ValueError("empty slate")
    seat_scores = {}
    for pillar in PILLARS:
        fid = seats.get(pillar)
        if fid:
            seat_scores[pillar] = films[fid]["scores"][pillar]
        elif EMPTY_SEAT_RULE == "worst_unseated":
            seat_scores[pillar] = min(f["scores"][pillar] for f in drafted)
        else:
            seat_scores[pillar] = FLAT_PENALTY
    total = round(sum(seat_scores.values()) / len(PILLARS), 1)
    worst = min(seat_scores.values())
    verdict, demoted = None, False
    for min_total, min_seat, name in TIERS:
        if total >= min_total:
            if worst >= min_seat:
                verdict = name
                break
            demoted = True     # qualified on total but weakest link failed
        # fall through to next tier
    return {"seat_scores": {p: round(v, 1) for p, v in seat_scores.items()},
            "total": total, "verdict": verdict, "demoted": demoted,
            "worst_seat": round(worst, 1)}


def best_seating(film_ids, films):
    """Optimal assignment of up to 4 films to the 5 pillar seats (used by the
    Letterboxd Fav-4 import: flattering but honest)."""
    film_ids = [f for f in film_ids if f in films][:4]
    if not film_ids:
        return None
    best = None
    for perm in permutations(PILLARS, len(film_ids)):
        seats = {p: None for p in PILLARS}
        seats.update(dict(zip(perm, film_ids)))
        r = score_slate(seats, films)
        if best is None or r["total"] > best[1]["total"]:
            best = (seats, r)
    return best
