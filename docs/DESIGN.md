# ReelDraft: design document

_The original design document, written before the build (July 2026). Some details changed during implementation; the README describes what shipped._

---

## 1. Vision (one paragraph)

A two-layer product. **Layer 1 (long-term asset): The Index** — a site that aggregates
every major film rating system (IMDb, Rotten Tomatoes, Metacritic, Letterboxd, box
office, Oscars) into one era-normalized composite score per film, with a per-film
detail page showing the breakdown. **Layer 2 (the funnel): The Game** — a daily,
seeded, draft-based movie game (in the style of 82-0.com but for movies) where players
draft 4 films off a spinner and are scored by the Index's engine. The game drives
traffic; the Index is the durable value. One data pipeline powers both.

Core product goals, in Connor's words:
- A draft-based game people replay over and over chasing a higher score, with a
  shareable social card showing their performance.
- A daily version where everyone plays the same seed, with a leaderboard of the day's
  best performances.
- **Reward deep movie knowledge above all else.** Knowing deep cuts, deep cast lists,
  and film history must be a win condition, not a flex.
- Letterboxd "Four Favorites" import: enter a username, get your actual Fav 4 scored,
  with its own shareable card. (Committed feature — the onboarding hook.)
- Inflation-adjusted box office everywhere (constant 2025 dollars). Seeing Star Wars
  as ~$4.1B instead of ~$700M makes older films desirable instead of trap picks and
  teaches film history. Generalized principle: **no era is ever a dead zone** — every
  pillar is percentile-ranked within its decade where fame/money compounds over time.

---

## 2. Competitive research (done — key findings)

### 82-0.com (NBA, the original viral hit)
- Spin a wheel → get (team, decade) → pick 1 of 4 all-time players. 5 rounds = starting
  five. One team-skip and one era-skip.
- Sim: PPG/RPB/APG/BLK/STL combined into a "Strength Rating," run through a season sim.
  **Each category is gated — one glaring weakness caps the record** regardless of the
  rest. (This weakest-link idea is central to our design.)
- "HoopIQ" mode hides all stats (draft from memory). For us, hidden stats are the
  DEFAULT, not a hard mode.
- Went viral via NBA players/teams playing it publicly. ESPN story:
  https://www.espn.com/nba/story/_/id/48976391/82-0-viral-game-tyrese-haliburton-milwaukee-bucks-trey-murphy

### 250-0.com (Call of Duty) — where the genre evolved
- Role constraints (2 ARs + 2 SMGs, off-role penalty), chemistry bonus for real-life
  teammates, legacy multiplier, map-by-map simulated bracket, daily streaks, daily
  challenge with a "twist," head-to-head multiplayer, shareable result images.

### The Slate (tastemakerclub.com/slate) — the direct movie predecessor. FULLY REVERSE-ENGINEERED
Its entire database + scoring engine ships in the client JS bundle (Next.js). Facts:
- **Pool: exactly 2,353 films**, IDs are `tmdb-<id>`, decades 1950s–2020s, 12 genres:
  Drama, Comedy, Action, Horror, Sci-Fi, Thriller, Crime, Romance, Animation, Western,
  Musical, Documentary.
- Per film: title, year, director, decade, primaryGenre, eligibleGenres[], TMDB poster
  URL (`image.tmdb.org/t/p/w342/...`), and 5 raw metrics:
  - `boxOffice` — worldwide gross **inflation-adjusted to 2025 dollars**
  - `critics` — Rotten Tomatoes critics score
  - `audience` — IMDb user rating
  - `reach` — IMDb vote count
  - `awards` — Oscar nominations + wins, **a win counts double**
- **Scoring**: each metric → percentile rank within the pool (binary search over the
  sorted metric array), × 20 → 0–20 points per film per dimension. Draft 5 films →
  each dimension total is out of 100 → final score = mean of the 5 dimension totals.
- **Era normalization**: `boxOffice` and `reach` are percentile-ranked **within the
  film's own decade**; critics/audience/awards rank across the whole pool.
- **Verdict tiers**: ≥93 Blockbuster, ≥82 Smash Hit, ≥70 Solid Opening,
  ≥52 Underperformer, else Flop. **Weakest-link demotions**: can't be Blockbuster if
  any dimension total < 65; can't be Blockbuster or Smash Hit if any < 55.
- Spinner: two slot-machine reels (decade, genre); only (decade, genre) combos with
  at least N qualifying films are eligible.
- **Its weaknesses (our openings)**: all stats visible during draft (so it's spreadsheet
  optimization, zero knowledge required); no simulation/theater; no daily seed or
  leaderboard; no people-level data (directors are display-only); shallow 2,353-film
  pool; no rarity/anti-meta mechanic.

### CineNerdle / Cine2Nerdle (cinenerdle2.app) — the knowledge-rewarding benchmark
- **Daily puzzle**: 4×4 Connections-style grid; 16 tiles (actors, character names,
  quotes, plot details, soundtrack), 15 swaps to arrange rows/columns into movies, plus
  a hidden 5th answer threaded through the others.
- **Battle (viral on TikTok, ranked ladder + tournaments)**: turn-based movie-linking
  duel on a chess clock. Name a movie connected to the previous one by shared
  actor/director/writer/cinematographer. Constraints that make deep knowledge win:
  each movie usable once per match; **each person usable as a link max 3 times**
  (kills Samuel L. Jackson/Marvel spam); 3 pre-game bans per player; lifelines (skip,
  extra time, reveal cast list).
- Lesson: CineNerdle rewards *connection* knowledge (the actor/film graph — which is
  IMDb principals data). The Slate rewards nothing. Our game rewards *evaluation*
  knowledge (knowing films' metric fingerprints) at launch, and can add connection
  knowledge later (declared links, see §6 v2 drawer).
- Anti-meta lesson: Battle needed the "3 uses per person" rule; our equivalent is the
  rarity bonus (meta picks are never optimal).

### Other movie draft games found (all shallow, none daily/knowledge-based)
- moviedrafter.com, boxrt.com, fantasyboxofficegame.com (fantasy-sports-style, friends
  leagues, upcoming releases — different niche, not competitors to a daily game).

### Design laws distilled from all of the above
1. The score must have a weakest link (balance is the strategy).
2. Losses/results must be specific and named (specificity is the shareability).
3. Hidden information is what converts an optimization puzzle into a knowledge game.
4. Anti-meta pressure (rarity) keeps a daily game from being solved.

---

## 3. Layer 1 — The Index (score aggregation engine)

Every film gets five **pillar scores** (0–100) plus a headline **composite**:

| Pillar | Inputs | Source |
|---|---|---|
| **Commercial** | Worldwide gross in constant 2025 USD (CPI-adjusted). Budget-aware profitability later. | TMDB budget/revenue; The Numbers/BOM for gaps; CPI table |
| **Critics** | RT critics % + Metacritic score | OMDb bulk pull |
| **Audience** | IMDb rating (+ RT audience score if available) | IMDb dumps; OMDb |
| **Cinephile** | Letterboxd weighted avg rating + fans-per-watch ratio | Letterboxd scrape / Kaggle bootstrap |
| **Awards/Legacy** | Oscar noms + wins (win ×2). Extensible: Globes, Cannes/Venice/Berlin, guild awards, National Film Registry. | DLu/oscar_data (has IMDb IDs) |

Methodology decisions:
- ~~**Percentile-based, era-normalized within decade** for every pillar (extends The
  Slate's approach, which only era-normalized boxOffice/reach). Rationale: votes, fame,
  and dollars all compound over time; a 1950s film must be able to win any pillar.~~
  **AMENDED 2026-07-03 (Connor): no decade normalization** — it introduces more
  problems than it fixes. Every pillar is a percentile rank across the WHOLE pool
  (box office CPI-adjusted to 2025 USD before ranking). The Godfather's audience
  score should reflect being ~top-3 on IMDb ever, not its rank within the 1970s.
  The per-decade scheme stays behind `ERA_NORMALIZE` in `pipeline/common.py` for
  A/B playtesting.
- Composite = mean of pillars for v1. Intra-pillar weights (RT vs Metacritic etc.):
  start with percentile-of-the-simple-average; publish the methodology on the site and
  evolve it publicly (methodology page is content/SEO in itself).
- The five pillars ARE the game's scoring dimensions. One engine, two products.
- Per-film page: composite, five-pillar "fingerprint" radar/bars, raw numbers from each
  source, adjusted vs nominal box office, awards list. (Same pattern as kintara's
  property detail pages.) These pages are the SEO surface ("is X actually good").
- Prior art (differentiation): TSPDT (critic-list aggregation), Flickmetrix
  (IMDb/RT/Metacritic/Letterboxd browsing filter). Nobody does era-fair percentile
  composite + fingerprint + attached game.
- The disagreement between pillars is a feature — IMDb canon (Shawshank, Nolan) vs
  Letterboxd canon vs RT critics. Films like Forrest Gump (top-15 IMDb, huge gross,
  ~75% RT) have lopsided fingerprints, and that lopsidedness is exactly what the game
  tests (see seat mechanic).

---

## 4. Data sources (researched, with terms)

| Source | What we take | Access / terms |
|---|---|---|
| **IMDb non-commercial datasets** — https://datasets.imdbws.com/ (docs: https://developer.imdb.com/non-commercial-datasets/) | title.basics (year/runtime/genres), title.ratings (avg rating + numVotes), title.principals (full cast/crew — the people graph), title.crew, name.basics | Free daily TSV dumps. **Non-commercial license.** |
| **TMDB API** — https://developer.themoviedb.org/ | Posters/backdrops/headshots (the ONLY clean legal image source — The Slate uses it too), budget & revenue, credits, keywords, release dates, daily ID export files for bulk sync | Free non-commercial **with attribution required**. Commercial use needs a license from TMDB — relevant if the site ever monetizes. Rate limit ~40 req/10s. |
| **OMDb** — http://www.omdbapi.com/ | RT critics %, Metacritic, box office (domestic), per IMDb ID | Free 1k req/day; **$1+/mo patron = 100k/day** → a one-time bulk pull over the whole pool is trivial. |
| **Oscars** — https://github.com/DLu/oscar_data | Every nomination 1927→present **with IMDb IDs** (clean joins). Alt: Kaggle `unanimad/the-oscar-award`; official DB at awardsdatabase.oscars.org | Free. |
| **Letterboxd** | Weighted avg rating, ★ histogram, watched/like/list/fan counts per film. Letterboxd is TMDB-ID based → joins are trivial. | **Official API is closed to us** (request-only; policy explicitly excludes data-analysis/personal projects — https://letterboxd.com/api-beta/). Plan: bootstrap from Kaggle, gentle one-time scrape of public film pages for our curated pool as a BUILD STEP (never a live dependency). Do not use Letterboxd branding. Kaggle bootstraps: `gsimonx37/letterboxd` (full films dump), `freeth/letterboxd-film-ratings` (18M ratings from 11k top users), `sahilislam007/letterbox-movie-classification-dataset` (watches/likes/list counts). |
| **Inflation** | Annual CPI table (BLS) → multiplier per release year → constant 2025 USD | Public data, one small table. |
| Kaggle merged sets | `ggtejas/tmdb-imdb-merged-movies-dataset` for bootstrapping; Golden Globes + Razzies datasets exist on Kaggle for later | Free. |

Fav-4 import: scrape the public profile page (`letterboxd.com/<user>/`) for the four
favorites at request time; cache aggressively; degrade gracefully if markup changes.
Gray-area scraping — keep volume tiny (one page per new user), identify honestly.

Licensing summary: IMDb dumps + TMDB free tier are both non-commercial → fine for a
free viral site with attribution; revisit if monetizing (TMDB commercial license).

---

## 5. Layer 2 — The Game (locked design)

### Daily loop (~4–5 min, same seed for everyone)

1. **DRAFT — 4 picks.** 4 spins; each spin = two slot-machine reels (decade + genre)
   landing on an eligible combo, then 4 poster choices from that cell.
   **No stats shown** on choice cards — poster, title, year, director only. Knowing the
   fingerprints IS the game. One re-spin token per day (skip mechanic, tunable).
2. **SEAT — 5 pillar seats, only 4 films.** Assign each film to exactly one pillar
   seat; the film scores that pillar's number for the team. **The empty seat scores
   the slate's worst unseated pillar** (alt: flat penalty — tune in playtesting). So
   you choose which pillar to punt, and misreads are punished: seat Forrest Gump in
   Critics and its ~75% RT torches you; seat it in Audience or Commercial and it's a
   monster. This is The Slate's weakest-link dynamic converted from hidden gotcha into
   placement skill.
3. **SCORE + REVEAL.** Full fingerprints revealed per film (all pillars, adjusted
   dollars, raw source numbers), seat scores, composite, verdict tier with
   weakest-link demotion (thresholds to tune; Slate's 93/82/70/52 with <65/<55
   demotions is the calibration reference). Each revealed film links to its Index page
   (game → Index funnel).
4. **LEADERBOARD + SHARE.** Daily leaderboard (best scores of the day), your
   percentile, streak counter. Share card: **four posters in a row** (the Letterboxd
   Fav-4 visual format) + seat assignments + score + percentile + emoji grid. No
   spoilers of the day's spins in the share text.
5. **RARITY BONUS (post-close).** After the daily closes, picks that few players made
   AND that scored well earn a bonus. Anti-meta insurance: the obvious pick is never
   the optimal pick; deep cuts are a win condition. Requires storing pick counts
   server-side (cheap).

### Decisions made
- **One attempt per daily.** Retries on a fixed seed = brute-forcing the reveal; the
  leaderboard must measure knowledge, not grinding. Soft-enforce via localStorage at
  launch; accounts later if it grows. The grind demand is absorbed by:
- **Endless mode** (replayable): same engine, unlimited runs, random seeds, personal
  best, no leaderboard. This is the "play over and over for a higher score" outlet;
  the daily stays sacred.
- **4 picks, not 5**: keeps Fav-4 symmetry (imports comparable to dailies), and
  5-seats/4-films punting is more strategic than film-per-pillar.
- **Hidden stats by default** (not a hard mode).
- All money displayed in constant 2025 dollars, everywhere, always.

### Letterboxd Fav-4 import (committed onboarding hook)
- Enter username → scrape public four favorites → auto-seat optimally (flattering but
  honest) → score through the identical engine.
- Output: dedicated shareable card (four posters, composite, weakest pillar,
  "your Fav 4 would have gone X on today's board").
- Imported Fav-4s get their own all-time leaderboard → its own share loop.
- Perfect first-session flow: judge my taste → oh, I can draft better than my own
  favorites? → plays daily.

### Daily twist (nice-to-have, not core)
One rule mutation per day ("Critics count double — Cannes week," "no films after
1999," "all four genres must differ"). Tie twists to release-date anniversaries
(data already in TMDB) — writes the content calendar for free. Connor rates this
"cool, not life-changing" — ship after core.

### v2 drawer (discussed, deliberately deferred)
- **Call your shot**: on any spin, instead of the 4 offered posters, TYPE any film
  matching the (decade, genre) cell (validated vs DB). Open-answer knowledge reward
  with a rarity multiplier and flop risk. Nobody in the genre has this. Strong v2
  candidate.
- **Declared links**: optionally declare connections between drafted films (shared
  actor / composer / cinematographer, verified vs IMDb principals) for multipliers;
  wrong declaration = penalty. Imports Cine2Nerdle Battle's cast-list skill into the
  draft. Deeper crew links pay more than shallow actor links.
- Head-to-head record vs the field: score each player's slate dimension-by-dimension
  against every other daily player (win 3+ of 5 pillars = matchup win) → a REAL W-L
  record ("11,204–312 — top 2.7%"). Discussed as the honest replacement for a fake
  simulation; parked because plain leaderboard is enough for launch. Note: Connor is
  skeptical of simulation theater generally — anything sim-like must be grounded in
  real data or real opponents.
- Cinephile hard mode (posters only, no titles), Razzie mode (draft the worst slate —
  Kaggle has Razzie data), weekly "festival" cumulative leaderboard, head-to-head live
  drafting.

---

## 6. Architecture & build order

Stack (Connor's comfort zone, mirrors kintara): **Python ETL → single SQLite file →
Flask backend (tiny API) + embedded/static frontend.** The game itself can be fully
client-side off a static JSON bundle derived from SQLite; the backend exists for:
daily seed distribution, score submission, leaderboard, rarity tallies, Fav-4 import
proxy, share-card PNG rendering.

### Phase 0 — Data pipeline (FIRST; it is both products)
1. Download IMDb TSVs; filter to movies, `numVotes >= threshold` (start ~25k votes,
   tune), join ratings + crew + principals.
2. TMDB: match by IMDb ID (TMDB find-by-external-id endpoint or daily ID export),
   pull poster path, budget, revenue, genres, release date.
3. OMDb bulk pull (patron tier) over the pool → RT critics, Metacritic.
4. Oscars: join DLu/oscar_data by IMDb ID → noms, wins.
5. Letterboxd: Kaggle bootstrap joined by TMDB ID; targeted gentle scrape for gaps.
6. CPI adjust all dollars → 2025 USD.
7. Compute per-decade percentiles per pillar + composite. Emit SQLite + game JSON.
8. **Validation gates**: pool ≥ ~5–10k films; every (decade × genre) wheel cell has
   enough depth (≥ ~8 films) or the cell is excluded from the wheel; spot-check
   fingerprints (Forrest Gump critics ≈ 75, Paddington 2 critics ≈ 99, Star Wars
   adjusted ≈ $4B+).

### Phase 1 — Game MVP
Daily seeded draft (seeded PRNG from date), seat assignment UI, scoring + reveal,
localStorage one-attempt, Flask endpoints: `GET /daily`, `POST /result`,
`GET /leaderboard`. Endless mode is the same code with a random seed and no POST.

### Phase 2 — Social layer
Share cards (server-rendered PNG: 4 posters, seats, score, percentile, emoji grid),
streaks, rarity bonus job at daily close, Letterboxd Fav-4 import + its card +
all-time imported leaderboard.

### Phase 3 — The Index
Film detail pages (fingerprint breakdown, raw sources, adjusted dollars, awards),
browse/rank/search views, methodology page. Reveal screens link here from day one
even if pages are minimal.

### Phase 4 — v2 drawer
Call your shot → declared links → daily twists → H2H record vs field, in roughly
that order of value.

---

## 7. Open questions (for the next session)

1. Empty-seat rule: worst-unseated-pillar vs flat penalty vs "empty seat scores 0" —
   needs playtesting against real fingerprints once the pipeline exists.
2. Verdict thresholds + rarity bonus formula — calibrate on real pool distributions.
3. Pool size vs. draftability tension: a 10k pool makes call-your-shot great but may
   make the 4 offered posters too obscure; possibly two tiers (offer-pool ~4k famous
   films, full pool valid for typed picks later).
4. Name/branding — unclaimed. Score name for the Index composite also unnamed.
   (Avoid Letterboxd trademarks; "Fav 4" phrasing is fine as a cultural reference.)
5. Intra-pillar weights (RT vs Metacritic; IMDb vs RT-audience; Letterboxd rating vs
   fans-per-watch) — v1 uses simple averages before percentiling.
6. Identity for leaderboard: anonymous handle vs lightweight accounts.
7. Whether Documentary/Western/Musical have enough depth per decade to stay on the
   wheel (The Slate includes them; verify with our pool).

## 8. Key reference links

- 82-0: https://www.82-0.com/ · ESPN writeup: https://www.espn.com/nba/story/_/id/48976391/82-0-viral-game-tyrese-haliburton-milwaukee-bucks-trey-murphy
- 250-0: https://250-0.com/
- The Slate: https://www.tastemakerclub.com/slate (DB + engine in client bundle —
  re-derivable any time by fetching its Next.js chunks and grepping for `"boxOffice"`)
- CineNerdle: https://www.cinenerdle.app/ · Battle: https://www.cinenerdle2.app/battle
  · rules: https://www.cinenerdle2.app/how-to-play?mode=battle
- IMDb datasets: https://developer.imdb.com/non-commercial-datasets/ · files at
  https://datasets.imdbws.com/
- TMDB API: https://developer.themoviedb.org/docs/getting-started
- OMDb: http://www.omdbapi.com/
- Oscar data (IMDb IDs): https://github.com/DLu/oscar_data
- Letterboxd API policy: https://letterboxd.com/api-beta/
- Letterboxd Kaggle sets: https://www.kaggle.com/datasets/gsimonx37/letterboxd ·
  https://www.kaggle.com/datasets/freeth/letterboxd-film-ratings ·
  https://www.kaggle.com/datasets/sahilislam007/letterbox-movie-classification-dataset
- Adjacent games (not direct competitors): moviedrafter.com, boxrt.com,
  fantasyboxofficegame.com
