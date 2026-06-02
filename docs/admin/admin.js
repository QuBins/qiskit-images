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

  function renderMybinder(m) {
    const cards = document.getElementById("mybinder-cards");
    const branchBody = document.querySelector("#mybinder-branch-tbl tbody");
    const dayBody = document.querySelector("#mybinder-day-tbl tbody");
    const missingEl = document.getElementById("missing-days");
    cards.innerHTML = "";
    branchBody.innerHTML = "";
    dayBody.innerHTML = "";
    missingEl.textContent = "";
    if (!m) {
      cards.innerHTML = `<div class="stat-card"><div class="label">mybinder</div><div class="value">—</div><div class="sub">not available</div></div>`;
      return;
    }
    cards.appendChild(card(
      `Launches (${m.window_days}d)`,
      m.total_launches.toLocaleString(),
      `${m.window_start} → ${m.window_end}`,
    ));
    const top = m.by_branch[0];
    if (top) {
      cards.appendChild(card("Top branch", top.branch, `${top.launches.toLocaleString()} launches`));
    }
    for (const row of m.by_branch) {
      const tr = document.createElement("tr");
      const td1 = document.createElement("td");
      const code = document.createElement("code");
      code.textContent = row.branch;
      td1.appendChild(code);
      const td2 = document.createElement("td");
      td2.className = "num";
      td2.textContent = row.launches.toLocaleString();
      tr.append(td1, td2);
      branchBody.appendChild(tr);
    }
    for (const row of m.by_day) {
      const tr = document.createElement("tr");
      const td1 = document.createElement("td");
      td1.textContent = row.date;
      const td2 = document.createElement("td");
      td2.className = "num";
      td2.textContent = row.launches.toLocaleString();
      tr.append(td1, td2);
      dayBody.appendChild(tr);
    }
    if (m.days_missing && m.days_missing.length) {
      missingEl.textContent = `Days missing from archive (typically the most recent ${m.days_missing.length} day${m.days_missing.length === 1 ? "" : "s"}): ${m.days_missing.join(", ")}.`;
    }
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
