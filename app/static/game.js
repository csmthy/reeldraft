/* ReelDraft client. Daily mode is server-authoritative (board from
 * /api/daily, scoring via POST /api/result). Endless mode runs fully
 * client-side off game_data.json with the mirrored engine below —
 * keep it in sync with app/scoring.py. */
"use strict";

const PILLARS = ["commercial", "critics", "audience", "cinephile", "awards"];
const PILLAR_LABELS = { commercial: "Commercial", critics: "Critics",
  audience: "Audience", cinephile: "Cinephile", awards: "Awards" };
const PILLAR_DESC = { commercial: "Box office in 2025 dollars",
  critics: "Rotten Tomatoes and Metacritic", audience: "IMDb rating",
  cinephile: "Letterboxd rating", awards: "Oscar nominations and wins" };
const TIERS = [[93, 65, "Blockbuster"], [82, 55, "Smash Hit"],
  [70, 0, "Solid Opening"], [52, 0, "Underperformer"], [0, 0, "Flop"]];
const TIER_CLASS = { "Blockbuster": "tier-blockbuster", "Smash Hit": "tier-smash",
  "Solid Opening": "tier-solid", "Underperformer": "tier-under", "Flop": "tier-flop" };

/* ---------------- state ---------------- */
const S = {
  mode: "daily", daily: null, gameData: null, easy: false,
  spins: [], spinIdx: 0, picks: [], respinLeft: 1, rerollLeft: 1, altIdx: 0,
  seats: {}, armedFilm: null, result: null, usedRespin: false,
  showOptimal: false, spinToken: 0, busy: false,
};

const $ = (id) => document.getElementById(id);
const todayStr = () => new Date().toISOString().slice(0, 10);
const reduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const finePointer = matchMedia("(hover: hover) and (pointer: fine)");
const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const esc = (s) => String(s).replace(/[&<>"]/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function clientId() {
  let id = localStorage.getItem("rd_client_id");
  if (!id) {
    id = Array.from(crypto.getRandomValues(new Uint8Array(16)),
      b => b.toString(16).padStart(2, "0")).join("");
    localStorage.setItem("rd_client_id", id);
  }
  return id;
}

function show(id) {
  document.querySelectorAll("#game .screen").forEach(s => s.classList.remove("active"));
  $(id).classList.add("active");
  window.scrollTo({ top: 0, behavior: "auto" });
}

let toastTimer = 0;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2000);
}

/* ---------------- engine mirror (see app/scoring.py) ---------------- */
function scoreSlate(seats, films) {
  const drafted = Object.values(seats).filter(Boolean).map(f => films[f]);
  const seatScores = {};
  for (const p of PILLARS) {
    const fid = seats[p];
    seatScores[p] = fid ? films[fid].scores[p]
      : Math.min(...drafted.map(f => f.scores[p]));
  }
  const total = Math.round(
    Object.values(seatScores).reduce((a, b) => a + b, 0) / PILLARS.length * 10) / 10;
  const worst = Math.min(...Object.values(seatScores));
  let verdict = "Flop", demoted = false;
  for (const [minTotal, minSeat, name] of TIERS) {
    if (total >= minTotal) {
      if (worst >= minSeat) { verdict = name; break; }
      demoted = true;
    }
  }
  return { seat_scores: seatScores, total, verdict, demoted, worst_seat: worst };
}

function permutations(arr, k) {
  if (k === 0) return [[]];
  const out = [];
  arr.forEach((x, i) => {
    for (const rest of permutations(arr.slice(0, i).concat(arr.slice(i + 1)), k - 1))
      out.push([x, ...rest]);
  });
  return out;
}

/* Best possible assignment of these films to the 5 seats. */
function bestSeating(filmIds, films) {
  let best = null;
  for (const perm of permutations(PILLARS, filmIds.length)) {
    const seats = {};
    PILLARS.forEach(p => { seats[p] = null; });
    perm.forEach((p, i) => { seats[p] = filmIds[i]; });
    const res = scoreSlate(seats, films);
    if (!best || res.total > best.res.total) best = { seats, res };
  }
  return best;
}

const bestPillarOf = (film) =>
  PILLARS.reduce((a, b) => film.scores[a] >= film.scores[b] ? a : b);

/* ---------------- poster art ---------------- */
const fmtMoney = (v) => v == null ? "—" :
  "$" + (v >= 1e9 ? (v / 1e9).toFixed(2) + "B" : Math.round(v / 1e6) + "M");

function art(f) {
  // the title card sits underneath; a poster that fails to load removes itself
  return `<div class="art"><span class="noart">${esc(f.title)}</span>${f.poster
    ? `<img src="${esc(f.poster)}" alt="" loading="lazy" decoding="async" onerror="this.remove()">` : ""}</div>`;
}

function statsBlock(f) {
  if (!f.raw) return "";
  const r = f.raw;
  return `<div class="stats">
    <span>Gross <b>${fmtMoney(r.revenue_adj)}</b></span><span>RT <b>${r.rt ?? "—"}%</b></span>
    <span>IMDb <b>${r.imdb_rating}</b></span><span>MC <b>${r.mc ?? "—"}</b></span>
    <span>LB <b>${r.lb_rating ?? "—"}</b></span><span>Oscars <b>${r.noms}/${r.wins}</b></span>
  </div>`;
}

/* ---------------- intro ---------------- */
async function init() {
  $("handle").value = localStorage.getItem("rd_handle") || "";
  $("easyMode").checked = localStorage.getItem("rd_easy") === "1";
  const streak = JSON.parse(localStorage.getItem("rd_streak") || "null");
  if (streak && streak.count > 1) {
    $("introStreak").hidden = false;
    $("introStreak").querySelector("span").textContent = `${streak.count}-day streak`;
  }
  try {
    const r = await fetch("/api/daily");
    S.daily = await r.json();
    const d = new Date(S.daily.date + "T12:00:00");
    $("introDay").textContent = `Daily #${S.daily.day_number} · ` +
      d.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
    const played = localStorage.getItem("rd_played_" + S.daily.date);
    if (played) $("btnDaily").textContent = "See today's result";
  } catch {
    $("introDay").textContent = "Offline · endless mode only";
    $("btnDaily").disabled = true;
  }
}

$("btnDaily").onclick = () => {
  if (!S.daily) return;
  const played = localStorage.getItem("rd_played_" + S.daily.date);
  if (played) { S.result = JSON.parse(played); S.mode = "daily"; renderReveal(); return; }
  startDraft("daily");
};
$("btnEndless").onclick = () => startDraft("endless");
$("btnEndless2").onclick = () => startDraft("endless");
$("easyMode").onchange = () =>
  localStorage.setItem("rd_easy", $("easyMode").checked ? "1" : "0");
$("handle").addEventListener("keydown", (e) => { if (e.key === "Enter") $("btnDaily").click(); });

async function loadGameData() {
  if (!S.gameData) {
    const r = await fetch("/static/game_data.json");
    S.gameData = await r.json();
  }
  return S.gameData;
}

/* ---------------- draft ---------------- */
function randomBoard(data) {
  const cells = Object.keys(data.cells);
  const spins = [], used = new Set(), usedCells = new Set();
  while (spins.length < 4) {
    const cell = cells[Math.floor(Math.random() * cells.length)];
    if (usedCells.has(cell)) continue;
    usedCells.add(cell);
    const members = data.cells[cell].filter(f => !used.has(f));
    if (members.length < 4) continue;
    const choices = [];
    while (choices.length < 4) {
      const f = members[Math.floor(Math.random() * members.length)];
      if (!choices.includes(f)) choices.push(f);
    }
    choices.forEach(f => used.add(f));
    const [decade, genre] = cell.split("|");
    spins.push({ decade, genre, cell, choices: choices.map(f => briefOf(data, f)) });
  }
  return spins;
}
const briefOf = (data, fid) => {
  const f = data.films[fid];
  return { id: fid, title: f.title, year: f.year, director: f.director,
    poster: f.poster, raw: f.raw };
};

async function startDraft(mode) {
  S.mode = mode; S.spinIdx = 0; S.picks = []; S.seats = {};
  S.respinLeft = 1; S.rerollLeft = 1; S.altIdx = 0; S.usedRespin = false;
  S.armedFilm = null; S.showOptimal = false; S.busy = false;
  S.easy = $("easyMode").checked;
  const h = $("handle").value.trim();
  if (h) localStorage.setItem("rd_handle", h);
  if (mode === "daily") {
    S.spins = S.daily.spins.map(s => ({ ...s }));
  } else {
    const data = await loadGameData();
    S.spins = randomBoard(data);
  }
  show("scr-draft");
  runSpin();
}

const DECADES = ["1930s","1940s","1950s","1960s","1970s","1980s","1990s","2000s","2010s","2020s"];
const GENRES = ["Drama","Comedy","Action","Horror","Sci-Fi","Thriller","Crime",
  "Romance","Animation","Western","Musical","Documentary"];

function renderTray() {
  const tray = $("tray");
  tray.innerHTML = "";
  for (let i = 0; i < 4; i++) {
    const slot = document.createElement("div");
    const f = S.picks[i];
    slot.className = "tray-slot" + (f ? " filled" : i === S.picks.length ? " current" : "");
    slot.innerHTML = f ? art(f) : String(i + 1);
    if (f) slot.title = `${f.title} (${f.year})`;
    tray.appendChild(slot);
  }
}

/* Slot-machine reel: scroll a strip of random values and land on the answer. */
function spinReel(strip, pool, final, ms) {
  const reel = strip.closest(".reel");
  reel.classList.remove("landed");
  const items = [];
  for (let i = 0; i < 14; i++) items.push(pool[Math.floor(Math.random() * pool.length)]);
  items.push(final);
  strip.innerHTML = items.map(v => `<div class="reel-item">${esc(v)}</div>`).join("");
  strip.style.transition = "none";
  strip.style.transform = "translateY(0)";
  const h = strip.firstElementChild.offsetHeight;
  if (reduceMotion() || ms === 0) {
    strip.style.transform = `translateY(${-(items.length - 1) * h}px)`;
    reel.classList.add("landed");
    return;
  }
  void strip.offsetHeight;
  strip.style.transition = `transform ${ms}ms cubic-bezier(.15,.85,.25,1.04)`;
  strip.style.transform = `translateY(${-(items.length - 1) * h}px)`;
  setTimeout(() => reel.classList.add("landed"), ms);
}

function runSpin() {
  const spin = S.spins[S.spinIdx];
  const token = ++S.spinToken;
  $("spinCount").textContent = `Pick ${S.spinIdx + 1} of 4`;
  $("easyFlag").hidden = !S.easy;
  $("choices").innerHTML = "";
  $("choices").classList.remove("picking");
  $("btnRespin").hidden = S.respinLeft <= 0;
  $("btnReroll").hidden = true;
  renderTray();
  const fast = reduceMotion();
  spinReel($("reelDecade"), DECADES, spin.decade, fast ? 0 : 900);
  spinReel($("reelGenre"), GENRES, spin.genre, fast ? 0 : 1250);
  setTimeout(() => { if (token === S.spinToken) renderChoices(spin); }, fast ? 0 : 1300);
}

function attachTilt(card) {
  const a = card.querySelector(".art");
  card.addEventListener("pointermove", (e) => {
    if (!finePointer.matches || reduceMotion()) return;
    const r = a.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
    a.style.setProperty("--ry", `${(x - .5) * 12}deg`);
    a.style.setProperty("--rx", `${(.5 - y) * 10}deg`);
    a.style.setProperty("--gx", `${x * 100}%`);
    a.style.setProperty("--gy", `${y * 100}%`);
  });
  card.addEventListener("pointerleave", () => {
    a.style.setProperty("--ry", "0deg");
    a.style.setProperty("--rx", "0deg");
  });
}

function renderChoices(spin) {
  const box = $("choices");
  box.innerHTML = "";
  box.classList.remove("picking");
  $("btnReroll").hidden = S.rerollLeft <= 0;
  spin.choices.forEach((f, i) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "card choice";
    card.style.setProperty("--i", i);
    card.setAttribute("aria-label", `Draft ${f.title} (${f.year})`);
    card.innerHTML = `<div class="art-wrap">${art(f)}</div>
      <div class="cap"><div class="t">${esc(f.title)}</div>
      <div class="y"><b>${f.year}</b>${f.director ? " · " + esc(f.director) : ""}</div>
      ${S.easy ? statsBlock(f) : ""}</div>`;
    const a = card.querySelector(".art");
    a.insertAdjacentHTML("beforeend", `<span class="glare"></span><span class="draft-pill">${icon("arrow")}Draft</span>`);
    attachTilt(card);
    card.onclick = () => pick(f, card);
    box.appendChild(card);
  });
}

function pick(f, card) {
  if (S.busy) return;
  S.busy = true;
  S.picks.push(f);
  card.classList.add("picked");
  $("choices").classList.add("picking");
  renderTray();
  setTimeout(() => {
    S.busy = false;
    S.spinIdx++;
    if (S.spinIdx < 4) runSpin(); else startSeating();
  }, reduceMotion() ? 0 : 420);
}

$("btnRespin").onclick = async () => {
  if (S.respinLeft <= 0 || S.busy) return;
  S.respinLeft--; S.usedRespin = true;
  if (S.mode === "daily") {
    S.spins[S.spinIdx] = S.daily.alternates[S.altIdx++];
  } else {
    const data = await loadGameData();
    S.spins[S.spinIdx] = randomBoard(data)[0];
  }
  runSpin();
};

/* Lifeline: 4 new films from the SAME (decade, genre) wheel. */
$("btnReroll").onclick = async () => {
  if (S.rerollLeft <= 0 || S.busy) return;
  const spin = S.spins[S.spinIdx];
  if (S.mode === "daily") {
    if (!spin.reroll || !spin.reroll.length) { toast("No reroll available"); return; }
    spin.choices = spin.reroll;
    spin.reroll = [];
  } else {
    const data = await loadGameData();
    const seen = new Set([...spin.choices.map(f => f.id), ...S.picks.map(f => f.id)]);
    const fresh = data.cells[spin.cell].filter(f => !seen.has(f));
    if (fresh.length < 4) { toast("Not enough films left in this wheel"); return; }
    const picks = [];
    while (picks.length < 4) {
      const f = fresh[Math.floor(Math.random() * fresh.length)];
      if (!picks.includes(f)) picks.push(f);
    }
    spin.choices = picks.map(f => briefOf(data, f));
  }
  S.rerollLeft--;
  renderChoices(spin);
  toast("Four new films from the same wheel");
};

/* ---------------- seating ---------------- */
function startSeating() {
  show("scr-seat");
  const hand = $("hand");
  hand.innerHTML = "";
  for (const f of S.picks) {
    /* A div, not a button: Firefox and Safari won't drag a <button>. */
    const tile = document.createElement("div");
    tile.setAttribute("role", "button");
    tile.tabIndex = 0;
    tile.className = "film-tile"; tile.id = "chip-" + f.id;
    tile.draggable = true;
    tile.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); tile.click(); }
    });
    tile.innerHTML = `${art(f)}<span class="ft"><b>${esc(f.title)}</b><span>${f.year}</span></span>`;
    tile.onclick = () => {
      if (S.armedFilm && S.armedFilm.id === f.id) { disarm(); return; }
      arm(f);
    };
    tile.addEventListener("dragstart", (e) => {
      arm(f);
      tile.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", f.id);
    });
    tile.addEventListener("dragend", () => tile.classList.remove("dragging"));
    hand.appendChild(tile);
  }
  const grid = $("seats");
  grid.innerHTML = "";
  for (const p of PILLARS) {
    const seat = document.createElement("button");
    seat.type = "button";
    seat.className = "seat"; seat.id = "seat-" + p;
    seat.style.setProperty("--c", `var(--${p})`);
    seat.onclick = (e) => seatClick(p, seat, e);
    seat.addEventListener("dragover", (e) => { e.preventDefault(); seat.classList.add("over"); });
    seat.addEventListener("dragleave", () => seat.classList.remove("over"));
    seat.addEventListener("drop", (e) => { e.preventDefault(); seat.classList.remove("over"); seatClick(p, seat); });
    grid.appendChild(seat);
    redrawSeat(p);
  }
  updateLockIn();
}

function arm(f) {
  document.querySelectorAll(".film-tile").forEach(c => c.classList.remove("armed"));
  $("chip-" + f.id).classList.add("armed");
  S.armedFilm = f;
  document.querySelectorAll(".seat").forEach(s => s.classList.add("can-drop"));
  updateLockIn();
}
function disarm() {
  S.armedFilm = null;
  document.querySelectorAll(".film-tile").forEach(c => c.classList.remove("armed"));
  document.querySelectorAll(".seat").forEach(s => s.classList.remove("can-drop"));
  updateLockIn();
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && S.armedFilm) disarm();
});

function seatClick(pillar, seatEl) {
  const current = S.seats[pillar];
  if (S.armedFilm) {
    for (const [pl, f] of Object.entries(S.seats))
      if (f && f.id === S.armedFilm.id) { delete S.seats[pl]; redrawSeat(pl); }
    if (current) $("chip-" + current.id).classList.remove("used");
    S.seats[pillar] = S.armedFilm;
    $("chip-" + S.armedFilm.id).classList.add("used");
    disarm();
  } else if (current) {
    $("chip-" + current.id).classList.remove("used");
    delete S.seats[pillar];
  }
  redrawSeat(pillar);
  updateLockIn();
}

function redrawSeat(pillar) {
  const seat = $("seat-" + pillar);
  const f = S.seats[pillar];
  seat.classList.toggle("filled", !!f);
  seat.setAttribute("aria-label", f
    ? `${PILLAR_LABELS[pillar]} seat: ${f.title}. Activate to remove.`
    : `${PILLAR_LABELS[pillar]} seat, empty`);
  seat.innerHTML = `<span class="seat-head">${icon(pillar)}${PILLAR_LABELS[pillar]}</span>
    <span class="seat-desc">${PILLAR_DESC[pillar]}</span>
    <span class="seat-body">${f
      ? `<span class="seat-film">${art(f)}<b>${esc(f.title)}</b><span>${f.year}</span></span>`
      : `<span class="seat-empty"><b>Empty</b><span>Drop a film here</span></span>`}</span>
    ${f ? `<span class="seat-x">${icon("close")}</span>` : ""}`;
}

function updateLockIn() {
  const n = Object.values(S.seats).filter(Boolean).length;
  $("btnLockIn").disabled = n !== 4;
  const punt = PILLARS.find(p => !S.seats[p]);
  document.querySelectorAll(".seat").forEach(s =>
    s.classList.toggle("punt-preview", n === 4 && s.id === "seat-" + punt));
  const hint = $("seatHint");
  if (n === 4) hint.innerHTML = `Punting <b>${PILLAR_LABELS[punt]}</b>. Ready when you are.`;
  else if (S.armedFilm) hint.innerHTML = `Pick a seat for <b>${esc(S.armedFilm.title)}</b>`;
  else hint.innerHTML = n ? `<b>${n} of 4</b> seated` : "Choose a film, then a seat";
}

$("btnLockIn").onclick = async () => {
  const btn = $("btnLockIn");
  const seatIds = {};
  for (const p of PILLARS) seatIds[p] = S.seats[p] ? S.seats[p].id : null;
  if (S.mode === "daily") {
    btn.disabled = true; btn.textContent = "Scoring…";
    let res;
    try {
      const r = await fetch("/api/result", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          date: S.daily.date, client_id: clientId(),
          handle: $("handle").value.trim() || "anon",
          seats: seatIds, used_respin: S.usedRespin, easy: S.easy,
        }),
      });
      res = await r.json();
    } catch { res = { error: "Couldn't reach the server. Try again." }; }
    btn.textContent = "Lock it in";
    if (res.error) { btn.disabled = false; toast(res.error); return; }
    S.result = res;
    localStorage.setItem("rd_played_" + S.daily.date, JSON.stringify(res));
    $("btnDaily").textContent = "See today's result";
    bumpStreak();
  } else {
    const data = await loadGameData();
    const res = scoreSlate(seatIds, data.films);
    res.films = {};
    for (const p of PILLARS)
      res.films[p] = seatIds[p] ? {
        ...briefOf(data, seatIds[p]),
        scores: data.films[seatIds[p]].scores,
        composite: data.films[seatIds[p]].composite,
      } : null;
    const best = parseFloat(localStorage.getItem("rd_best_endless") || "0");
    if (res.total > best) localStorage.setItem("rd_best_endless", String(res.total));
    res.endlessBest = Math.max(best, res.total);
    res.newBest = res.total > best;
    S.result = res;
  }
  renderReveal();
};

function bumpStreak() {
  const today = todayStr();
  const s = JSON.parse(localStorage.getItem("rd_streak") || "null") || { last: "", count: 0 };
  if (s.last === today) return;
  const y = new Date(); y.setDate(y.getDate() - 1);
  s.count = (s.last === y.toISOString().slice(0, 10)) ? s.count + 1 : 1;
  s.last = today;
  localStorage.setItem("rd_streak", JSON.stringify(s));
}

/* ---------------- reveal ---------------- */
const scoreEmoji = (v) => v >= 85 ? "🟩" : v >= 70 ? "🟨" : v >= 55 ? "🟧" : v >= 40 ? "🟥" : "⬛";
const scoreColor = (v) => v >= 85 ? "var(--great)" : v >= 70 ? "var(--ok)" : v >= 55 ? "var(--meh)" : v >= 40 ? "var(--bad)" : "var(--dead)";
const scoreClass = (v) => v >= 85 ? "sc-great" : v >= 70 ? "sc-ok" : v >= 55 ? "sc-meh" : "sc-bad";

function emojiGrid(res) {
  return PILLARS.map(p => scoreEmoji(res.seat_scores[p])).join("");
}

/* films map + your seat ids, straight from the reveal payload */
function revealContext() {
  const res = S.result;
  const films = {}, yourSeats = {};
  for (const p of PILLARS) {
    const f = res.films[p];
    yourSeats[p] = f ? f.id : null;
    if (f) films[f.id] = f;
  }
  return { films, yourSeats, ids: Object.keys(films) };
}

function renderReveal() {
  const res = S.result;
  show("scr-reveal");
  $("revealHead").textContent = S.mode === "daily"
    ? `Daily #${res.day_number}` : "Endless run";
  animateScore(res.total);
  const stamp = $("revealVerdict");
  stamp.textContent = res.verdict;
  stamp.className = "stamp " + (TIER_CLASS[res.verdict] || "");
  setTimeout(() => stamp.classList.add("slam"), reduceMotion() ? 0 : 1350);
  $("revealDemoted").hidden = !res.demoted;
  $("revealDemoted").textContent = res.demoted
    ? `Demoted: your weakest seat scored ${res.worst_seat}` : "";
  $("revealRank").innerHTML = S.mode === "daily"
    ? `<b>#${res.rank}</b> of ${res.players} today`
    : (res.newBest ? `<b>New personal best</b>` : `Personal best <b>${res.endlessBest}</b>`);
  $("emojiGrid").innerHTML = PILLARS.map((p, i) =>
    `<i style="--tc:${scoreColor(res.seat_scores[p])};--i:${i}" title="${PILLAR_LABELS[p]} ${res.seat_scores[p]}"></i>`).join("");
  $("btnBoard").hidden = S.mode !== "daily";
  $("btnAgain").hidden = S.mode !== "endless";
  $("btnAgain").onclick = () => startDraft("endless");

  renderResultGrid();
  renderFilmDetails();
}

/* The 5-seat verdict grid: your placement vs the optimal one. */
function renderResultGrid() {
  const res = S.result;
  const { films, yourSeats, ids } = revealContext();
  const optimal = bestSeating(ids, films);
  const shown = S.showOptimal ? optimal.seats : yourSeats;
  const shownScores = S.showOptimal ? optimal.res.seat_scores : res.seat_scores;

  const grid = $("resultGrid");
  grid.innerHTML = "";
  PILLARS.forEach((p, i) => {
    const fid = shown[p];
    const f = fid ? films[fid] : null;
    const v = shownScores[p];
    let placement;
    if (!f) {
      placement = `<span class="place punt">Empty · lowest on slate</span>`;
    } else if (S.showOptimal) {
      placement = `<span class="place good">Optimal seat</span>`;
    } else if (optimal.seats[p] === fid) {
      placement = `<span class="place good">✓ Right call</span>`;
    } else {
      const wanted = PILLARS.find(q => optimal.seats[q] === fid);
      placement = wanted
        ? `<span class="place bad">Better at ${PILLAR_LABELS[wanted]} (${f.scores[wanted]})</span>`
        : `<span class="place bad">Best lineup benches it</span>`;
    }
    const card = document.createElement("div");
    card.className = "rseat";
    card.style.setProperty("--c", `var(--${p})`);
    card.style.setProperty("--i", i);
    card.innerHTML = `<span class="seat-head">${icon(p)}${PILLAR_LABELS[p]}</span>
      <div class="ring ${scoreClass(v)}"><b>${v}</b></div>
      <div class="rt">${f ? esc(f.title) : "Punted"}</div>
      ${placement}`;
    grid.appendChild(card);
    const ring = card.querySelector(".ring");
    requestAnimationFrame(() => requestAnimationFrame(() => ring.style.setProperty("--v", v)));
  });

  const note = $("optimalNote");
  const pct = Math.round(res.total / optimal.res.total * 100);
  const label = $("btnOptimal").querySelector("span");
  if (S.showOptimal) {
    note.hidden = false;
    note.innerHTML = `Best possible lineup with these four: <b>${optimal.res.total} · ${optimal.res.verdict}</b>.
      You scored ${res.total}, ${pct}% of the ceiling.`;
    label.textContent = "Show my lineup";
  } else {
    note.hidden = res.total < optimal.res.total;
    if (res.total >= optimal.res.total)
      note.innerHTML = `<b>Perfect seating.</b> No arrangement of these four films scores higher.`;
    label.textContent = "Show best lineup";
  }
}

$("btnOptimal").onclick = () => {
  S.showOptimal = !S.showOptimal;
  renderResultGrid();
};

/* Per-film fingerprints with the seated pillar highlighted and the film's
 * best pillar starred. */
function renderFilmDetails() {
  const res = S.result;
  const box = $("revealFilms");
  box.innerHTML = `<div class="prints-head"><h2>The fingerprints</h2><span>${icon("star").replace("<svg", '<svg style="width:13px;height:13px;color:var(--bulb);vertical-align:-2px"')} marks each film's strongest pillar</span></div>`;
  for (const p of PILLARS) {
    const f = res.films[p];
    const row = document.createElement("article");
    row.style.setProperty("--c", `var(--${p})`);
    if (f) {
      row.className = "print";
      const bestP = bestPillarOf(f);
      const bars = PILLARS.map(q => `
        <div class="bar${q === p ? " here" : ""}" style="--c:var(--${q})">
          <span class="lab">${icon(q)}${PILLAR_LABELS[q]}${q === bestP ? icon("star").replace("<svg", '<svg class="best"') : ""}</span>
          <span class="track"><span class="fill" data-w="${f.scores[q]}"></span></span>
          <span class="val">${f.scores[q]}</span>
        </div>`).join("");
      const r = f.raw || {};
      row.innerHTML = `<a href="/film/${f.id}" tabindex="-1" aria-hidden="true">${art(f)}</a>
        <div>
          <div class="print-top">
            <h3><a href="/film/${f.id}">${esc(f.title)}</a><small>${f.year}</small></h3>
            <span class="seat-chip">${icon(p)}${PILLAR_LABELS[p]} seat · <b>${res.seat_scores[p]}</b></span>
          </div>
          <div class="bars">${bars}</div>
          <div class="raw">
            <span>Gross <b>${fmtMoney(r.revenue_adj)}</b></span><span>RT <b>${r.rt ?? "—"}%</b></span>
            <span>MC <b>${r.mc ?? "—"}</b></span><span>IMDb <b>${r.imdb_rating}</b></span>
            <span>LB <b>${r.lb_rating ?? "—"}</b></span><span>Oscars <b>${r.noms} noms · ${r.wins} wins</b></span>
          </div>
        </div>`;
    } else {
      row.className = "print punted";
      row.innerHTML = `<div><span class="seat-chip">${icon(p)}${PILLAR_LABELS[p]} seat · punted</span>
        <p>The empty seat took your slate's lowest ${PILLAR_LABELS[p]} number: <b>${res.seat_scores[p]}</b></p></div>`;
    }
    box.appendChild(row);
  }
  const prints = [...box.querySelectorAll(".print")];
  const grow = (pr) => pr.querySelectorAll(".fill").forEach(el => { el.style.width = el.dataset.w + "%"; });
  if (!("IntersectionObserver" in window) || reduceMotion()) { prints.forEach(grow); return; }
  /* Fill bars as each film scrolls into view; anything already scrolled past fills too. */
  const io = new IntersectionObserver((entries) => {
    if (!entries.some(e => e.isIntersecting)) return;
    for (const pr of prints) if (pr.getBoundingClientRect().top < innerHeight * .9) { grow(pr); io.unobserve(pr); }
  }, { threshold: .25 });
  prints.forEach(pr => io.observe(pr));
}

function animateScore(target) {
  const el = $("revealScore");
  if (reduceMotion()) { el.textContent = target.toFixed(1); return; }
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / 1400);
    el.textContent = (target * (1 - Math.pow(1 - k, 3))).toFixed(1);
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/* ---------------- share ---------------- */
$("btnShare").onclick = () => {
  const res = S.result;
  const lines = [
    S.mode === "daily"
      ? `🎬 ${window.SITE_NAME} #${res.day_number} — ${res.total} ${res.verdict.toUpperCase()}`
      : `🎬 ${window.SITE_NAME} endless — ${res.total} ${res.verdict.toUpperCase()}`,
    emojiGrid(res),
  ];
  if (S.mode === "daily" && res.players) lines.push(`#${res.rank} of ${res.players}`);
  const streak = JSON.parse(localStorage.getItem("rd_streak") || "null");
  if (streak && streak.count > 1) lines.push(`🔥 ${streak.count}-day streak`);
  navigator.clipboard.writeText(lines.join("\n"))
    .then(() => toast("Copied to clipboard"))
    .catch(() => toast("Couldn't copy. Your browser blocked the clipboard."));
};

const CARD = { house: "#1a0e12", panel: "#2a171d", screen: "#f6ead8", dust: "#b39b93",
  bulb: "#ffb53b", bulbHi: "#ffcb6e", great: "#5fcf8b", ok: "#f4cf5d", meh: "#ff9a45", bad: "#ff5d58", dead: "#4a3036",
  commercial: "#5fcf8b", critics: "#ff6b57", audience: "#5ab6ff", cinephile: "#b79eff", awards: "#f4cf5d" };
const TIER_COLOR = { "Blockbuster": CARD.bulbHi, "Smash Hit": CARD.great, "Solid Opening": CARD.audience,
  "Underperformer": CARD.meh, "Flop": CARD.bad };
const BODY_FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';

$("btnCard").onclick = async () => {
  const res = S.result;
  const cv = $("shareCanvas"), ctx = cv.getContext("2d");
  try { await document.fonts.load('900 100px "Marquee"'); } catch {}
  const W = 1200, H = 630;
  ctx.fillStyle = CARD.house; ctx.fillRect(0, 0, W, H);
  const glow = ctx.createRadialGradient(300, 0, 20, 300, 0, 620);
  glow.addColorStop(0, "rgba(255,181,59,.20)"); glow.addColorStop(1, "rgba(255,181,59,0)");
  ctx.fillStyle = glow; ctx.fillRect(0, 0, W, H);
  // marquee bulbs along the top and bottom edges
  for (let x = 24; x < W; x += 24) {
    for (const y of [16, H - 16]) {
      ctx.fillStyle = (x / 24) % 2 ? "rgba(255,203,110,.95)" : "rgba(255,203,110,.35)";
      ctx.beginPath(); ctx.arc(x, y, 3.2, 0, 7); ctx.fill();
    }
  }
  // brand
  ctx.fillStyle = CARD.bulb; ctx.beginPath(); ctx.arc(66, 78, 20, 0, 7); ctx.fill();
  ctx.fillStyle = CARD.house;
  [[66, 67], [66, 89], [55, 78], [77, 78]].forEach(([x, y]) => { ctx.beginPath(); ctx.arc(x, y, 4.6, 0, 7); ctx.fill(); });
  ctx.fillStyle = CARD.screen; ctx.font = '800 44px "Marquee", Impact, sans-serif';
  ctx.textBaseline = "middle";
  ctx.fillText(window.SITE_NAME.toUpperCase() + (S.mode === "daily" ? ` #${res.day_number}` : " ENDLESS"), 100, 80);
  ctx.textBaseline = "alphabetic";
  // score + verdict
  ctx.fillStyle = CARD.screen; ctx.font = '900 190px "Marquee", Impact, sans-serif';
  ctx.fillText(String(res.total), 44, 300);
  const vc = TIER_COLOR[res.verdict] || CARD.great;
  ctx.font = '900 58px "Marquee", Impact, sans-serif';
  const vw = ctx.measureText(res.verdict.toUpperCase()).width;
  ctx.save(); ctx.translate(50, 330); ctx.rotate(-0.05);
  ctx.strokeStyle = vc; ctx.lineWidth = 5; roundRect(ctx, 0, 0, vw + 36, 74, 10); ctx.stroke();
  ctx.fillStyle = vc; ctx.fillText(res.verdict.toUpperCase(), 18, 59); ctx.restore();
  // tiles
  PILLARS.forEach((p, i) => {
    const v = res.seat_scores[p];
    ctx.fillStyle = v >= 85 ? CARD.great : v >= 70 ? CARD.ok : v >= 55 ? CARD.meh : v >= 40 ? CARD.bad : CARD.dead;
    roundRect(ctx, 50 + i * 46, 450, 36, 36, 7); ctx.fill();
  });
  ctx.fillStyle = CARD.dust; ctx.font = `600 22px ${BODY_FONT}`;
  if (S.mode === "daily" && res.players) ctx.fillText(`#${res.rank} of ${res.players} today`, 50, 540);
  // posters
  const seated = PILLARS.filter(p => res.films[p]);
  const pw = 146, ph = 219, gap = 18, x0 = W - 44 - seated.length * pw - (seated.length - 1) * gap;
  const imgs = await Promise.all(seated.map(p => loadImage(res.films[p].poster)));
  seated.forEach((p, i) => drawPoster(ctx, imgs[i], x0 + i * (pw + gap), 140, pw, ph));
  seated.forEach((p, i) => {
    const x = x0 + i * (pw + gap);
    ctx.fillStyle = CARD[p]; roundRect(ctx, x, 140 + ph + 14, pw, 4, 2); ctx.fill();
    ctx.fillStyle = CARD[p]; ctx.font = '800 22px "Marquee", Impact, sans-serif';
    ctx.fillText(`${PILLAR_LABELS[p].toUpperCase()} ${res.seat_scores[p]}`, x, 140 + ph + 46);
    ctx.fillStyle = CARD.screen; ctx.font = `600 17px ${BODY_FONT}`;
    wrapText(ctx, res.films[p].title, x, 140 + ph + 72, pw, 2);
  });
  cv.toBlob((b) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(b);
    a.download = `${window.SITE_NAME.toLowerCase()}-${todayStr()}.png`;
    a.click();
  });
  toast("Card downloaded");
};

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}
function loadImage(src) {
  return new Promise((resolve) => {
    if (!src) return resolve(null);
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}
function drawPoster(ctx, img, x, y, w, h) {
  ctx.save(); roundRect(ctx, x, y, w, h, 10); ctx.clip();
  const g = ctx.createLinearGradient(x, y, x + w, y + h);
  g.addColorStop(0, "#3a222a"); g.addColorStop(1, "#24141a");
  ctx.fillStyle = g; ctx.fillRect(x, y, w, h);
  if (img) { try { ctx.drawImage(img, x, y, w, h); } catch {} }
  ctx.restore();
}
function wrapText(ctx, text, x, y, maxW, maxLines = 3) {
  const words = String(text).split(" ");
  let line = "", yy = y, lines = 0;
  for (const w of words) {
    if (ctx.measureText(line + w).width > maxW && line) {
      if (++lines === maxLines) { ctx.fillText(line.trim().replace(/.$/, "…"), x, yy); return; }
      ctx.fillText(line.trim(), x, yy); line = w + " "; yy += 22;
    } else line += w + " ";
  }
  ctx.fillText(line.trim(), x, yy);
}

/* ---------------- leaderboard ---------------- */
$("btnBoard").onclick = renderBoard;
$("btnBackReveal").onclick = () => S.result ? renderReveal() : show("scr-intro");

const posBadge = (i) => `<span class="pos${i < 3 ? " p" + (i + 1) : ""}">${i + 1}</span>`;

async function renderBoard() {
  show("scr-board");
  $("btnBackReveal").hidden = !S.result;
  const r = await fetch("/api/leaderboard");
  const d = await r.json();
  const date = new Date(d.date + "T12:00:00").toLocaleDateString("en-US", { month: "long", day: "numeric" });
  $("boardMeta").textContent = `${date} · ${d.players} ${d.players === 1 ? "player" : "players"}`;
  $("lbTable").innerHTML = d.top.length
    ? `<thead><tr><th></th><th>Player</th><th class="films">Slate</th><th>Verdict</th><th class="num hide-sm">Bonus</th><th class="num">Final</th></tr></thead><tbody>` +
      d.top.map((e, i) => `<tr><td>${posBadge(i)}</td>
        <td class="who">${esc(e.handle)}${e.easy ? '<span class="easy-mark" title="Played in easy mode">Easy</span>' : ""}</td>
        <td class="films">${e.titles.map(esc).join(" · ")}</td>
        <td><span class="vpill">${esc(e.verdict)}</span></td>
        <td class="num hide-sm">${e.bonus ? `<span class="bonus">+${e.bonus}</span>` : ""}</td>
        <td class="num final">${e.final}</td></tr>`).join("") + "</tbody>"
    : `<tbody><tr><td class="board-empty">Nobody has played today's board yet.</td></tr></tbody>`;
  const r2 = await fetch("/api/fav4_leaderboard");
  const d2 = await r2.json();
  $("fav4Table").innerHTML = d2.top.length
    ? `<thead><tr><th></th><th>Letterboxd user</th><th class="films">Fav 4</th><th>Verdict</th><th class="num">Score</th></tr></thead><tbody>` +
      d2.top.map((e, i) => `<tr><td>${posBadge(i)}</td>
        <td class="who">${esc(e.username)}</td>
        <td class="films">${e.titles.map(esc).join(" · ")}</td>
        <td><span class="vpill">${esc(e.verdict)}</span></td>
        <td class="num final">${e.total}</td></tr>`).join("") + "</tbody>"
    : `<tbody><tr><td class="board-empty">No Fav 4s scored yet.</td></tr></tbody>`;
}

/* ---------------- fav4 import ---------------- */
$("fav4Form").onsubmit = async (e) => {
  e.preventDefault();
  const u = $("fav4User").value.trim().toLowerCase();
  if (!u) { $("fav4User").focus(); return; }
  const btn = $("btnFav4");
  btn.disabled = true; btn.textContent = "Scoring…";
  $("fav4Out").innerHTML = "";
  let d;
  try {
    const r = await fetch("/api/fav4/" + encodeURIComponent(u));
    d = await r.json();
  } catch { d = { error: "Couldn't reach the server." }; }
  btn.disabled = false; btn.textContent = "Score it";
  if (d.error) {
    const msg = { "invalid username": "That isn't a valid Letterboxd username.",
      "profile not found": "No Letterboxd profile with that name.",
      "letterboxd unreachable": "Letterboxd didn't respond. Try again in a minute.",
      "no favorites found on profile": "That profile has no favorite films set.",
      "too few of these favorites are in the pool": "Too few of those favorites are in the film pool to score." }[d.error] || d.error;
    $("fav4Out").innerHTML = `<p class="fav4-msg err">${esc(msg)}</p>`;
    return;
  }
  const films = PILLARS.filter(p => d.films[p]).map(p => d.films[p]);
  $("fav4Out").innerHTML = `<div class="fav4-result">
      <div class="fav4-score"><b>${d.total}</b><span>${esc(d.verdict)}</span></div>
      <div class="fav4-posters">${films.map(f => `<a href="/film/${f.id}" title="${esc(f.title)} (${f.year})">${art(f)}</a>`).join("")}</div>
      <p class="fav4-note">${esc(u)}'s Fav 4 would beat ${d.today.would_beat} of ${d.today.players} players on today's board.
      ${d.unmatched.length ? `Not in the pool: ${d.unmatched.map(esc).join(", ")}.` : ""}</p>
    </div>`;
};

init();
