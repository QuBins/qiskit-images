// QuBins admin page: client-side password gate + stats renderer.
//
// IMPORTANT: this is a speed bump, not security. The page and the
// stats.json it loads sit on a public GitHub Pages site. Anyone who
// knows the URL can fetch stats.json directly; the password only
// hides the rendered view. Treat the contents as non-sensitive.
//
// Auth flow: at deploy time the workflow substitutes the SHA-256
// hash of `<salt>:<password>` into ADMIN_HASH below (and the salt
// into ADMIN_SALT). The hash baked here is ALWAYS for a random,
// unguessable placeholder so a forgotten secret in CI doesn't grant
// anyone access — the page just stays locked until the secret is
// configured.

(() => {
  "use strict";

  // Replaced at deploy time by the pages.yml workflow. The defaults
  // below are intentionally unmatched so a misconfigured deploy
  // produces a locked page rather than an open one.
  const ADMIN_SALT = "__ADMIN_SALT__";
  const ADMIN_HASH = "__ADMIN_HASH__";
  const SESSION_KEY = "qubins-admin-unlocked";

  async function sha256Hex(s) {
    const bytes = new TextEncoder().encode(s);
    const hash = await crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(hash))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  }

  function setUnlocked(yes) {
    document.body.classList.toggle("locked", !yes);
    if (yes) {
      try { sessionStorage.setItem(SESSION_KEY, ADMIN_HASH); } catch (_) {}
      loadStats();
    } else {
      try { sessionStorage.removeItem(SESSION_KEY); } catch (_) {}
    }
  }

  async function tryUnlock(pw) {
    const got = await sha256Hex(`${ADMIN_SALT}:${pw}`);
    return got === ADMIN_HASH;
  }

  // Auto-unlock if the same hash is already remembered from this tab.
  // We compare on the hash (not the password), so refreshing the page
  // doesn't re-prompt.
  function maybeRestore() {
    try {
      if (sessionStorage.getItem(SESSION_KEY) === ADMIN_HASH && ADMIN_HASH !== "__ADMIN_HASH__") {
        setUnlocked(true);
      }
    } catch (_) {}
  }

  function wireGate() {
    const form = document.getElementById("gate-form");
    const pwField = document.getElementById("gate-pw");
    const err = document.getElementById("gate-error");
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      err.textContent = "";
      const ok = await tryUnlock(pwField.value);
      if (ok) {
        pwField.value = "";
        setUnlocked(true);
      } else {
        err.textContent = "Wrong password.";
      }
    });
    document.getElementById("lock-btn").addEventListener("click", () => {
      setUnlocked(false);
    });
  }

  // ---------------------------------------------------------------- render
  async function loadStats() {
    let data;
    try {
      const r = await fetch("stats.json", { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      data = await r.json();
    } catch (e) {
      document.getElementById("generated-at").textContent =
        `Failed to load stats.json: ${e.message}`;
      return;
    }
    renderStats(data);
  }

  function renderStats(data) {
    document.getElementById("generated-at").textContent =
      `Generated ${data.generated_at}`;

    const errBlock = document.getElementById("errors-block");
    errBlock.innerHTML = "";
    if (Array.isArray(data.errors) && data.errors.length) {
      const div = document.createElement("div");
      div.className = "errors";
      div.innerHTML = "<strong>Non-fatal issues during fetch:</strong>";
      const ul = document.createElement("ul");
      for (const msg of data.errors) {
        const li = document.createElement("li");
        li.textContent = msg;
        ul.appendChild(li);
      }
      div.appendChild(ul);
      errBlock.appendChild(div);
    }

    renderGhcr(data.ghcr);
    renderMybinder(data.mybinder);
  }

  function renderGhcr(g) {
    const cards = document.getElementById("ghcr-cards");
    const tbody = document.querySelector("#ghcr-tbl tbody");
    cards.innerHTML = "";
    tbody.innerHTML = "";
    if (!g) {
      cards.innerHTML = `<div class="stat-card"><div class="label">GHCR</div><div class="value">—</div><div class="sub">not available</div></div>`;
      return;
    }
    // GHCR doesn't expose pull counts for container packages
    // (download_count is always 0), so we surface publish freshness
    // instead — actual operational signal. "All N tags refreshed in
    // the last 24h" is what tells you the daily cron is healthy.
    cards.appendChild(card(
      "Tags published",
      g.total_tags.toLocaleString(),
      "multi-arch parent tags",
    ));
    if (g.latest_publish) {
      cards.appendChild(card(
        "Latest publish",
        formatRelative(g.latest_publish),
        new Date(g.latest_publish).toISOString().replace(/\.\d+Z$/, "Z"),
      ));
    }
    for (const row of g.by_tag) {
      const tr = document.createElement("tr");
      const td1 = document.createElement("td");
      const code = document.createElement("code");
      code.textContent = row.tag;
      td1.appendChild(code);
      const td2 = document.createElement("td");
      td2.className = "num";
      td2.textContent = formatRelative(row.updated_at);
      td2.title = row.updated_at;
      tr.append(td1, td2);
      tbody.appendChild(tr);
    }
  }

  function formatRelative(iso) {
    if (!iso) return "—";
    const then = Date.parse(iso);
    if (Number.isNaN(then)) return "—";
    const delta = Date.now() - then;
    const m = Math.floor(delta / 60000);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 48) return `${h}h ago`;
    const d = Math.floor(h / 24);
    return `${d}d ago`;
  }

  // mybinder is the interactive dashboard. Everything is driven by two
  // pieces of state — the selected window (1/7/30 days) and the selected
  // branch ("all" or one tag) — and re-derived from a single shared
  // branch×day matrix (`m.dates` + `m.series`) on every change, so no
  // re-fetch is needed to re-window or drill in. If an older stats.json
  // without the matrix is loaded we synthesize a one-series "all branches"
  // view from by_day so the charts still render.
  const MB_ALL = "__ALL__";

  function renderMybinder(m) {
    const cards = document.getElementById("mybinder-cards");
    const dayBody = document.querySelector("#mybinder-day-tbl tbody");
    const missingEl = document.getElementById("missing-days");
    const dailyChart = document.getElementById("mb-daily-chart");
    const branchChart = document.getElementById("mb-branch-chart");
    const dailyTitle = document.getElementById("mb-daily-title");
    const windowSeg = document.getElementById("mb-window");
    const branchSel = document.getElementById("mb-branch");

    cards.innerHTML = "";
    dayBody.innerHTML = "";
    missingEl.textContent = "";
    dailyChart.innerHTML = "";
    branchChart.innerHTML = "";
    if (!m) {
      cards.innerHTML = `<div class="stat-card"><div class="label">mybinder</div><div class="value">—</div><div class="sub">not available</div></div>`;
      return;
    }

    // Shared day axis + per-branch daily series, with a fallback for an
    // older stats.json that predates the matrix.
    const dates = (Array.isArray(m.dates) && m.dates.length)
      ? m.dates
      : (m.by_day || []).map((r) => r.date);
    const series = (Array.isArray(m.series) && m.series.length)
      ? m.series
      : [{ branch: null, total: m.total_launches || 0,
           daily: (m.by_day || []).map((r) => r.launches) }];

    // The archive lags a day or two, so the trailing dates often have no
    // data yet. Treat the window as ending at the last day we actually
    // have, not at "today" — otherwise the 1d view shows an empty day.
    const missing = new Set(m.days_missing || []);
    let dataEnd = dates.length;
    while (dataEnd > 0 && missing.has(dates[dataEnd - 1])) dataEnd--;

    // ---- interactive state
    let win = 30;
    let branch = MB_ALL;

    // Populate the branch selector once (every branch seen in the full
    // window, ordered by total launches as the generator emits them).
    branchSel.innerHTML = "";
    const optAll = document.createElement("option");
    optAll.value = MB_ALL;
    optAll.textContent = "All branches";
    branchSel.appendChild(optAll);
    for (const s of series) {
      if (!s.branch) continue;
      const o = document.createElement("option");
      o.value = s.branch;
      o.textContent = s.branch;
      branchSel.appendChild(o);
    }
    branchSel.disabled = series.length === 1 && !series[0].branch;

    // Use onclick/onchange (not addEventListener) so a re-render after a
    // lock/unlock cycle replaces handlers instead of stacking them.
    for (const btn of windowSeg.querySelectorAll("button")) {
      btn.onclick = () => {
        win = Number(btn.dataset.days);
        for (const b of windowSeg.querySelectorAll("button")) {
          b.classList.toggle("active", b === btn);
        }
        draw();
      };
    }
    branchSel.onchange = () => { branch = branchSel.value; draw(); };

    function draw() {
      const n = Math.min(win, dataEnd);
      const lo = dataEnd - n;
      const winDates = dates.slice(lo, dataEnd);

      // Daily totals for the selected branch (or the sum across all).
      const daily = winDates.map((_, i) => {
        const idx = lo + i;
        if (branch === MB_ALL) {
          return series.reduce((sum, s) => sum + (s.daily[idx] || 0), 0);
        }
        const s = series.find((x) => x.branch === branch);
        return s ? (s.daily[idx] || 0) : 0;
      });

      // Per-branch totals within the window (drives the bar chart).
      const branchTotals = series
        .filter((s) => s.branch)
        .map((s) => ({
          branch: s.branch,
          launches: s.daily.slice(lo, dataEnd).reduce((a, b) => a + b, 0),
        }))
        .filter((x) => x.launches > 0)
        .sort((a, b) => b.launches - a.launches || a.branch.localeCompare(b.branch));

      const total = daily.reduce((a, b) => a + b, 0);
      const branchLabel = branch === MB_ALL ? "all branches" : branch;

      // Cards
      cards.innerHTML = "";
      const span = winDates.length
        ? `${winDates[0]} → ${winDates[winDates.length - 1]}`
        : "no data";
      cards.appendChild(card(`Organic launches (${win}d)`,
        total.toLocaleString(), `${span} · ${branchLabel}`));
      const topB = branchTotals[0];
      if (topB) {
        cards.appendChild(card("Top branch", topB.branch,
          `${topB.launches.toLocaleString()} launches`));
      }
      // Our binder-warmup cron launches the target branches twice a day;
      // mybinder logs those too. They're stripped from the organic totals
      // above — surfaced here so the exclusion is visible, not silent.
      // (Window-independent: the generator reports it over its full window.)
      if (typeof m.warmup_launches_excluded === "number") {
        cards.appendChild(card("Warm-up excluded",
          m.warmup_launches_excluded.toLocaleString(),
          `binder-warmup cron, not counted (${m.window_days}d)`));
      }

      // Charts
      dailyTitle.textContent = `Daily launches · ${branchLabel}`;
      drawColumnChart(dailyChart, winDates, daily);
      drawBarChart(branchChart, branchTotals,
        branch === MB_ALL ? null : branch, (b) => {
          branch = (branch === b) ? MB_ALL : b;  // click again to clear
          branchSel.value = branch;
          draw();
        });

      // Day table (newest first), reflecting the same window + branch.
      dayBody.innerHTML = "";
      for (let i = winDates.length - 1; i >= 0; i--) {
        const tr = document.createElement("tr");
        const td1 = document.createElement("td");
        td1.textContent = winDates[i];
        const td2 = document.createElement("td");
        td2.className = "num";
        td2.textContent = daily[i].toLocaleString();
        tr.append(td1, td2);
        dayBody.appendChild(tr);
      }
    }

    if (m.days_missing && m.days_missing.length) {
      missingEl.textContent = `Days missing from archive (typically the most recent ${m.days_missing.length} day${m.days_missing.length === 1 ? "" : "s"}): ${m.days_missing.join(", ")}.`;
    }

    draw();
  }

  // ------------------------------------------------------------- SVG charts
  // Hand-rolled, dependency-free. Charts use a fixed viewBox and scale to
  // their container via `width:100%; height:auto` in CSS.
  const SVGNS = "http://www.w3.org/2000/svg";

  function svgEl(name, attrs) {
    const el = document.createElementNS(SVGNS, name);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    return el;
  }

  // Single shared tooltip, positioned at the cursor (viewport-fixed).
  function wireTip(node, text) {
    const tip = document.getElementById("chart-tooltip");
    if (!tip) return;
    node.addEventListener("mousemove", (e) => {
      tip.textContent = text;
      tip.hidden = false;
      tip.style.left = `${e.clientX}px`;
      tip.style.top = `${e.clientY}px`;
    });
    node.addEventListener("mouseleave", () => { tip.hidden = true; });
  }

  // Vertical column chart: one bar per day.
  function drawColumnChart(container, labels, values) {
    container.innerHTML = "";
    if (!labels.length) {
      container.innerHTML = `<p class="meta">No data in this window.</p>`;
      return;
    }
    const W = 720, H = 200, padL = 34, padR = 10, padT = 12, padB = 26;
    const plotW = W - padL - padR, plotH = H - padT - padB;
    const max = Math.max(1, ...values);
    const n = values.length;
    const slot = plotW / n;
    const barW = Math.max(1, Math.min(slot * 0.72, 44));
    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart-svg", role: "img" });

    // y axis: baseline + a max-value tick.
    svg.appendChild(svgEl("line", { class: "axis", x1: padL, y1: padT + plotH, x2: W - padR, y2: padT + plotH }));
    const yMax = svgEl("text", { class: "axis-label", x: padL - 6, y: padT + 4, "text-anchor": "end" });
    yMax.textContent = max.toLocaleString();
    svg.appendChild(yMax);
    const yZero = svgEl("text", { class: "axis-label", x: padL - 6, y: padT + plotH, "text-anchor": "end" });
    yZero.textContent = "0";
    svg.appendChild(yZero);

    // x labels: every bar when sparse, else ~8 evenly spaced ticks.
    const step = n <= 12 ? 1 : Math.ceil(n / 8);
    for (let i = 0; i < n; i++) {
      const v = values[i];
      const h = (v / max) * plotH;
      const x = padL + slot * i + (slot - barW) / 2;
      const y = padT + plotH - h;
      const rect = svgEl("rect", { class: "bar", x, y, width: barW, height: h, rx: 1 });
      rect.setAttribute("aria-label", `${labels[i]}: ${v}`);
      wireTip(rect, `${labels[i]} — ${v.toLocaleString()} launch${v === 1 ? "" : "es"}`);
      svg.appendChild(rect);
      if (i % step === 0 || i === n - 1) {
        const t = svgEl("text", { class: "axis-label", x: padL + slot * i + slot / 2, y: H - 8, "text-anchor": "middle" });
        t.textContent = (labels[i] || "").slice(5);  // MM-DD
        svg.appendChild(t);
      }
    }
    container.appendChild(svg);
  }

  // Horizontal bar chart: one row per branch, clickable to drill in.
  function drawBarChart(container, items, selected, onPick) {
    container.innerHTML = "";
    if (!items.length) {
      container.innerHTML = `<p class="meta">No launches in this window.</p>`;
      return;
    }
    const W = 720, labelW = 96, padR = 52, rowH = 22, gap = 8;
    const plotW = W - labelW - padR;
    const H = items.length * (rowH + gap);
    const max = Math.max(1, ...items.map((d) => d.launches));
    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart-svg", role: "img" });

    items.forEach((d, i) => {
      const y = i * (rowH + gap);
      const w = Math.max(2, (d.launches / max) * plotW);
      const dim = selected && d.branch !== selected;
      const g = svgEl("g", {
        class: `barrow${selected === d.branch ? " sel" : ""}`,
        tabindex: "0", role: "button",
        "aria-label": `${d.branch}: ${d.launches} launches`,
      });
      const label = svgEl("text", { class: "bar-label", x: labelW - 6, y: y + rowH * 0.72, "text-anchor": "end" });
      label.textContent = d.branch;
      const rect = svgEl("rect", { class: `bar${dim ? " dim" : ""}`, x: labelW, y, width: w, height: rowH, rx: 2 });
      const val = svgEl("text", { class: "bar-value", x: labelW + w + 6, y: y + rowH * 0.72 });
      val.textContent = d.launches.toLocaleString();
      g.append(label, rect, val);
      g.addEventListener("click", () => onPick(d.branch));
      g.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(d.branch); }
      });
      wireTip(rect, `${d.branch} — ${d.launches.toLocaleString()} launch${d.launches === 1 ? "" : "es"} · click to drill in`);
      svg.appendChild(g);
    });
    container.appendChild(svg);
  }

  function card(label, value, sub) {
    const d = document.createElement("div");
    d.className = "stat-card";
    const l = document.createElement("div"); l.className = "label"; l.textContent = label;
    const v = document.createElement("div"); v.className = "value"; v.textContent = value;
    const s = document.createElement("div"); s.className = "sub";   s.textContent = sub || "";
    d.append(l, v, s);
    return d;
  }

  // ----------------------------------------------------------------- boot
  wireGate();
  maybeRestore();
})();
