// QuBins package lists: renders docs/packages/<tag>.json (written by
// .github/scripts/build-pages-data.py at deploy time) for ?tag=<tag>.
(function () {
  "use strict";
  const params = new URLSearchParams(location.search);
  const tagSel = document.getElementById("pk-tag");
  const archSel = document.getElementById("pk-arch");
  const filter = document.getElementById("pk-filter");
  const meta = document.getElementById("pk-meta");
  const historyEl = document.getElementById("pk-history");
  const listEl = document.getElementById("pk-list");
  let data = null;

  const el = (name, text) => {
    const e = document.createElement(name);
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const day = (iso) => (iso || "").slice(0, 10);

  function renderList() {
    listEl.innerHTML = "";
    const arch = data && (data[archSel.value] || data.amd64);
    if (!arch) return;
    const q = filter.value.trim().toLowerCase();
    for (const kind of ["python", "apt"]) {
      for (const [name, version] of Object.entries(arch[kind] || {})) {
        if (q && !name.toLowerCase().includes(q)) continue;
        const tr = el("tr");
        tr.append(el("td", name), el("td", kind === "python" ? "pip" : "apt"), el("td", version));
        listEl.appendChild(tr);
      }
    }
  }

  function renderHistory() {
    historyEl.innerHTML = "";
    const history = (data && data.history) || [];
    if (!history.length) {
      historyEl.appendChild(el("p", "No version changes recorded yet. The history starts with the first nightly that changes a package after package lists were introduced."));
      historyEl.firstChild.className = "notes";
      return;
    }
    for (const h of history) {
      const box = el("div");
      box.className = "pk-change";
      box.appendChild(el("h3", `${day(h.date)}: ${h.changes.length} package${h.changes.length === 1 ? "" : "s"}`));
      const ul = el("ul");
      for (const c of h.changes) {
        const li = el("li");
        const what = c.from === null ? `added ${c.to}` : c.to === null ? `removed (was ${c.from})` : `${c.from} → ${c.to}`;
        li.append(el("code", c.name), ` (${c.kind === "python" ? "pip" : "apt"}): ${what}`);
        ul.appendChild(li);
      }
      box.appendChild(ul);
      historyEl.appendChild(box);
    }
  }

  function load(tag) {
    historyEl.innerHTML = '<p class="notes">Loading…</p>';
    listEl.innerHTML = "";
    meta.textContent = "";
    fetch(`${encodeURIComponent(tag)}.json`, { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => {
        data = d;
        const hasArm = Boolean(d.arm64);
        archSel.disabled = !hasArm;
        if (!hasArm) archSel.value = "amd64";
        meta.textContent = `qiskit ${d.qiskit_patch || "?"}, built ${day(d.updated_at)}, image ${d.digest.slice(0, 19)}…`;
        renderHistory();
        renderList();
      })
      .catch(() => {
        data = null;
        historyEl.innerHTML = "";
        historyEl.appendChild(el("p", `No package list for ${tag} yet. It appears after the image's next nightly build.`));
      });
  }

  fetch("../versions.json", { cache: "no-cache" })
    .then((r) => r.json())
    .then((v) => {
      const tags = v.images.filter((i) => i.packages).map((i) => i.binder_tag);
      const all = tags.length ? tags : v.images.map((i) => i.binder_tag);
      for (const t of all) {
        const o = el("option", t);
        o.value = t;
        tagSel.appendChild(o);
      }
      const want = params.get("tag");
      tagSel.value = all.includes(want) ? want : (all.find((t) => t === `${v.latest_qiskit}-xl`) || all[0]);
      load(tagSel.value);
    });

  tagSel.addEventListener("change", () => {
    params.set("tag", tagSel.value);
    history.replaceState(null, "", `?${params}`);
    load(tagSel.value);
  });
  archSel.addEventListener("change", renderList);
  filter.addEventListener("input", renderList);
})();
