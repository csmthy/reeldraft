/* Static demo layer for GitHub Pages (built by tools/build_demo.py).
 *
 * The real app is a Flask server. In the demo there is no server, so this file answers the
 * game's API calls in the browser from the same data files:
 *   /api/daily        today's board, seeded from the date so everyone gets the same one
 *   /api/result       scored with the same engine the server uses (mirrored in game.js)
 *   /api/leaderboard  switched off (needs shared storage)
 *   /api/fav4/...     switched off (needs a server to read Letterboxd)
 * It also renders the Index (browse) and film pages from static/films.json.
 */
(() => {
  window.RD_DEMO = true;
  const LAUNCH = "2026-07-02";
  const PILLARS = ["commercial", "critics", "audience", "cinephile", "awards"];
  const LABELS = { commercial: "Commercial", critics: "Critics", audience: "Audience",
    cinephile: "Cinephile", awards: "Awards" };
  const json = (body, status = 200) => new Response(JSON.stringify(body),
    { status, headers: { "Content-Type": "application/json" } });
  const esc = (s) => String(s).replace(/[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (n) => Number(n).toLocaleString("en-US");

  let gameData = null, films = null;
  const loadGame = async () => gameData ||= await (await realFetch("static/game_data.json")).json();
  const loadFilms = async () => films ||= await (await realFetch("static/films.json")).json();

  /* ---------- deterministic daily board ---------- */
  function hash(str) {                      // cyrb53
    let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
    for (let i = 0; i < str.length; i++) {
      const ch = str.charCodeAt(i);
      h1 = Math.imul(h1 ^ ch, 2654435761); h2 = Math.imul(h2 ^ ch, 1597334677);
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return (h2 >>> 0) * 4294967296 + (h1 >>> 0);
  }
  function rng(seed) {                      // mulberry32
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function sample(list, k, rand) {          // like Python's random.sample
    const pool = list.slice(), out = [];
    for (let i = 0; i < Math.min(k, pool.length); i++) {
      const j = i + Math.floor(rand() * (pool.length - i));
      [pool[i], pool[j]] = [pool[j], pool[i]];
      out.push(pool[i]);
    }
    return out;
  }
  const localDate = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };
  const dayNumber = (date) => Math.round((Date.parse(date) - Date.parse(LAUNCH)) / 864e5) + 1;

  function boardFor(date, data) {
    const rand = rng(hash("reeldraft:" + date));
    const cells = Object.keys(data.cells).sort();
    const used = new Set(), spins = [];
    for (const cell of sample(cells, 6, rand)) {
      const members = data.cells[cell].filter((f) => !used.has(f));
      const picked = sample(members, 8, rand);
      picked.forEach((f) => used.add(f));
      const [decade, genre] = cell.split("|");
      spins.push({ decade, genre, choices: picked.slice(0, 4), reroll: picked.slice(4, 8) });
    }
    return { spins: spins.slice(0, 4), alternates: spins.slice(4) };
  }
  const brief = (data, id) => {
    const f = data.films[id];
    return { id, title: f.title, year: f.year, director: f.director, poster: f.poster, raw: f.raw };
  };
  const reveal = (data, id) => ({ ...brief(data, id), scores: data.films[id].scores,
    composite: data.films[id].composite });

  /* ---------- API shim ---------- */
  const realFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = typeof input === "string" ? input : input.url;
    if (url === "/static/game_data.json") return realFetch("static/game_data.json", init);
    if (url === "/api/daily") {
      const data = await loadGame(), date = localDate(), b = boardFor(date, data);
      const spin = (s) => ({ ...s, choices: s.choices.map((f) => brief(data, f)),
        reroll: s.reroll.map((f) => brief(data, f)) });
      return json({ date, day_number: dayNumber(date), pillars: PILLARS,
        spins: b.spins.map(spin), alternates: b.alternates.map(spin) });
    }
    if (url === "/api/result") {
      const data = await loadGame(), body = JSON.parse(init.body);
      const res = window.scoreSlate(body.seats, data.films);   // same engine as the server
      res.films = {};
      for (const p of PILLARS) res.films[p] = body.seats[p] ? reveal(data, body.seats[p]) : null;
      return json({ ...res, rank: null, players: 0, demo: true, day_number: dayNumber(body.date) });
    }
    if (url.startsWith("/api/leaderboard")) return json({ date: localDate(), players: 0, top: [], demo: true });
    if (url.startsWith("/api/fav4_leaderboard")) return json({ top: [], count: 0, demo: true });
    if (url.startsWith("/api/fav4/")) return json({ error: "demo" }, 503);
    return realFetch(input, init);
  };

  /* ---------- shared bits for the Index pages ---------- */
  const art = (f) => `<div class="art"><span class="noart">${esc(f.title)}</span>${f.poster
    ? `<img src="${esc(f.poster)}" alt="" loading="lazy" decoding="async" onerror="this.remove()">` : ""}</div>`;
  const filmHref = (tt) => `film/?id=${tt}`;
  const money = (v) => v >= 1e9 ? `$${(v / 1e9).toFixed(2)}B` : `$${Math.round(v / 1e6)}M`;

  /* ---------- browse ---------- */
  function rowHtml(f, i) {
    const spark = PILLARS.map((k) => `<i style="--c:var(--${k});--v:${f["s_" + k] ?? 0}"></i>`).join("");
    const title = PILLARS.map((k) => `${LABELS[k]} ${f["s_" + k]}`).join(" · ");
    return `<div class="row${i < 3 ? " top3" : ""}">
      <span class="rk">${i + 1}</span>${art(f)}
      <div class="row-title"><a href="${filmHref(f.tt)}">${esc(f.title)}</a>
        <div class="meta"><span>${f.year}</span><span>${esc(f.primary_genre)}</span>${f.runtime ? `<span>${f.runtime} min</span>` : ""}</div></div>
      <div class="spark" title="${title}">${spark}</div>
      <span class="score">${f.composite}</span></div>`;
  }
  async function browse(form) {
    const all = await loadFilms();
    const params = new URLSearchParams(location.search);
    const set = (name) => { const el = form.elements[name]; if (params.has(name)) el.value = params.get(name); };
    ["q", "decade", "genre"].forEach(set);
    const render = () => {
      const q = form.elements.q.value.trim().toLowerCase(), decade = form.elements.decade.value,
        genre = form.elements.genre.value;
      const hits = all.filter((f) => (!q || f.title.toLowerCase().includes(q))
        && (!decade || f.decade === decade) && (!genre || f.genres.includes(genre))).slice(0, 250);
      const qs = new URLSearchParams(Object.entries({ q, decade, genre }).filter(([, v]) => v)).toString();
      history.replaceState(null, "", location.pathname + (qs ? "?" + qs : ""));
      const count = document.querySelector(".result-count"), list = document.querySelector(".list");
      const empty = document.querySelector(".empty-state");
      const filtered = q || decade || genre;
      if (count) count.textContent = filtered
        ? `${hits.length}${hits.length === 250 ? "+" : ""} ${hits.length === 1 ? "film" : "films"} matching`
        : `Top ${hits.length} films by Reel Score`;
      if (list) list.innerHTML = hits.map(rowHtml).join("");
      if (count) count.hidden = !hits.length;
      if (list) list.hidden = !hits.length;
      if (empty) empty.hidden = !!hits.length;
    };
    form.addEventListener("submit", (e) => { e.preventDefault(); render(); });
    form.elements.q.addEventListener("input", render);
    render();
  }

  /* ---------- film page ---------- */
  async function film(root) {
    const all = await loadFilms();
    const id = new URLSearchParams(location.search).get("id");
    const f = all.find((x) => x.tt === id);
    if (!f) {
      root.innerHTML = `<section class="lost"><p class="kicker">Not in the pool</p>
        <h1 class="display">This reel is empty.</h1><p class="muted">That film isn't in the Index.</p>
        <p class="lost-actions"><a class="btn btn-primary" href="browse/">Browse the Index</a>
        <a class="btn btn-ghost" href="./">Play today's board</a></p></section>`;
      return;
    }
    document.title = `${f.title} (${f.year}) · The Reel Index`;
    const rank = all.filter((x) => x.composite > f.composite).length + 1;
    const raw = {
      commercial: f.revenue_adj ? money(f.revenue_adj) + " adj." : "no gross recorded",
      critics: [f.rt != null ? `RT ${f.rt}%` : "", f.mc != null ? `MC ${f.mc}` : ""].filter(Boolean).join(" · ") || "no scores",
      audience: `IMDb ${f.imdb_rating}/10`,
      cinephile: f.lb_rating ? `LB ${f.lb_rating}/5` : "no rating yet",
      awards: `${f.noms} noms, ${f.wins} wins`,
    };
    const oscars = (f.oscar_cats || []).slice().sort((a, b) => b.w - a.w);
    const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
    root.innerHTML = `
<section class="film-hero">
  ${f.poster ? `<div class="backdrop" style="background-image:url('${esc(f.poster)}')"></div>` : ""}
  <div class="film-head">
    <div class="art"><span class="noart">${esc(f.title)}</span>${f.poster ? `<img src="${esc(f.poster)}" alt="${esc(f.title)} poster" onerror="this.remove()">` : ""}</div>
    <div>
      <a class="kicker" href="browse/">The Reel Index</a>
      <h1 class="film-title">${esc(f.title)}<small>${f.year}</small></h1>
      <p class="film-by">Directed by <b>${esc(f.directors.join(", "))}</b></p>
      <div class="tags">${f.genres.map((g) => `<span class="tag">${esc(g)}</span>`).join("")}${f.runtime ? `<span class="tag">${f.runtime} min</span>` : ""}<span class="tag">${f.decade}</span></div>
      <div class="film-score">
        <div class="score-badge"><b>${f.composite}</b><span><strong>Reel Score</strong>#${fmt(rank)} of ${fmt(all.length)} films</span></div>
        <div class="ext">
          <a href="https://www.imdb.com/title/${f.tt}/" target="_blank" rel="noopener">IMDb<svg aria-hidden="true"><use href="#i-out"/></svg></a>
          ${f.tmdb_id ? `<a href="https://www.themoviedb.org/movie/${f.tmdb_id}" target="_blank" rel="noopener">TMDB<svg aria-hidden="true"><use href="#i-out"/></svg></a>` : ""}
          ${f.lb_slug ? `<a href="https://letterboxd.com/film/${esc(f.lb_slug)}/" target="_blank" rel="noopener">Letterboxd<svg aria-hidden="true"><use href="#i-out"/></svg></a>` : ""}
        </div>
      </div>
    </div>
  </div>
</section>
<section class="panel">
  <div class="panel-head"><h2>Fingerprint</h2><p>Percentile across the whole pool: 99 beats 99% of films on that pillar.</p></div>
  <div class="fp">${PILLARS.map((k) => `
    <div class="fp-row" style="--c:var(--${k})">
      <span class="lab"><svg aria-hidden="true"><use href="#i-${k}"/></svg>${LABELS[k]}</span>
      <span class="rawv">${raw[k]}</span>
      <span class="track"><span class="fill" data-w="${f["s_" + k] ?? 0}"></span></span>
      <span class="val">${f["s_" + k] ?? "—"}</span>
    </div>`).join("")}</div>
</section>
<div class="grid2">
  <section class="panel"><div class="panel-head"><h2>Ratings</h2></div><div class="stat-list">
    <div class="stat"><span>Rotten Tomatoes</span><b>${f.rt != null ? f.rt + "%" : "—"}</b></div>
    <div class="stat"><span>Metacritic</span><b>${f.mc != null ? `${f.mc}<small>out of 100</small>` : "—"}</b></div>
    <div class="stat"><span>IMDb</span><b>${f.imdb_rating}<small>${fmt(f.imdb_votes)} votes</small></b></div>
    <div class="stat"><span>Letterboxd</span><b>${f.lb_rating || "—"}${f.lb_count ? `<small>${fmt(f.lb_count)} ratings</small>` : ""}</b></div>
  </div></section>
  <section class="panel"><div class="panel-head"><h2>Box office</h2></div><div class="stat-list">
    <div class="stat"><span>Worldwide gross<small>in 2025 dollars</small></span><b>${f.revenue_adj ? "$" + fmt(Math.round(f.revenue_adj)) : "Not recorded"}</b></div>
    <div class="stat"><span>Worldwide gross<small>in ${f.year} dollars</small></span><b>${f.revenue ? "$" + fmt(Math.round(f.revenue)) : "Not recorded"}</b></div>
    ${f.budget ? `<div class="stat"><span>Budget<small>in ${f.year} dollars</small></span><b>$${fmt(Math.round(f.budget))}</b></div>` : ""}
  </div></section>
</div>
<section class="panel">
  <div class="panel-head"><h2>Academy Awards</h2><p>${plural(f.noms, "nomination")} · ${plural(f.wins, "win")}</p></div>
  ${oscars.length ? `<div class="oscars">${oscars.map((c) => `<div class="oscar${c.w ? " won" : ""}"><svg aria-hidden="true"><use href="#i-awards"/></svg>${esc(c.c)}<small>${c.w ? "Won" : "Nominated"}</small></div>`).join("")}</div>`
    : `<p class="muted" style="margin:0">No Academy Award nominations.</p>`}
</section>`;
    const fills = root.querySelectorAll(".fp .fill");
    requestAnimationFrame(() => requestAnimationFrame(() => fills.forEach((el) => { el.style.width = el.dataset.w + "%"; })));
  }

  document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("filters");
    if (form) browse(form);
    const root = document.getElementById("film-root");
    if (root) film(root);
  });
})();
