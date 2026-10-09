// QuBins launch redirector.
//
// Reads query params, builds the appropriate mybinder URL using the
// same encoding logic as the landing page generator, and redirects.
// Supported params:
//   image=<tag>            (default: latest-xl)
//   repo=<github url>      repo loader (nbgitpuller)
//   branch=<ref>           optional, repo loader only
//   path=<subpath>         optional, repo loader only
//   ui=rise                repo loader only, needs path: land in the
//                          jupyterlab-rise standalone presenter (the whole
//                          tab is the slideshow) instead of JupyterLab
//   ui=rise-classic        repo loader only, needs path: land in the
//                          *classic* Notebook frontend + classic RISE
//                          (renders interactive ipywidgets in slides).
//                          Requires a rise-capable image (e.g. 2.1-xl-rise).
//   file=<raw url>         single-file loader (jupyterlab-open-url-parameter)
//
// Precedence: `file` wins over `repo`; if neither, bare image launch.
//
// We use location.replace() so the redirector doesn't pollute the
// user's history. The destination URL is also rendered into the
// fallback section in case the redirect fails or the user wants to
// inspect it.

(() => {
  "use strict";
  const REPO = "QuBins/qiskit-images";
  const params = new URLSearchParams(location.search);

  // `image` lands in the path of the mybinder URL we navigate to.
  // A fixed `https://mybinder.org/...` prefix and the hardcoded REPO
  // mean URL parsing keeps the host pinned to mybinder.org regardless
  // of the value — but we still constrain it to the real tag shape so
  // the invariant doesn't depend on subtle URL-parser reasoning and a
  // future refactor can't turn this into an open redirect. Anything
  // off-shape falls back to the safe default.
  const TAG_RE = /^[a-z0-9][a-z0-9._-]{0,40}$/;
  let image = (params.get("image") || "latest-xl").trim();
  if (!TAG_RE.test(image)) image = "latest-xl";
  const repo   = params.get("repo");
  const branch = params.get("branch");
  const path   = params.get("path");
  const file   = params.get("file");
  let ui       = params.get("ui");

  // small images ship neither nbgitpuller + git (repo loader) nor
  // jupyterlab-open-url-parameter (file loader), so a repo or file
  // launch on one opens a Lab that can't load anything. Older
  // generator versions produced such links, so upgrade them to the
  // same minor's xl (snapshot tags keep their date suffix: every
  // flavor is snapshotted on the same day) and say so on the page.
  let note = "";
  if ((repo || file) && /-small(-\d{8})?$/.test(image)) {
    const upgraded = image.replace(/-small(-\d{8})?$/, "-xl$1");
    note = `${image} can't load notebooks from a repo or URL, so this opens ${upgraded} instead.`;
    image = upgraded;
  }
  // Classic RISE only ships in the -rise flavor. Every xl/xxl has
  // jupyterlab-rise, so fall back to that presenter elsewhere.
  if (ui === "rise-classic" && !/-rise(-\d{8})?$/.test(image)) ui = "rise";

  let url;
  if (file) {
    const inner = `lab?fromURL=${encodeURIComponent(file)}`;
    url = `https://mybinder.org/v2/gh/${REPO}/${image}?urlpath=${encodeURIComponent(inner)}`;
  } else if (repo) {
    let repoName = "repo";
    try {
      const u = new URL(repo);
      const parts = u.pathname.replace(/\.git$/, "").split("/").filter(Boolean);
      repoName = parts[parts.length - 1] || "repo";
    } catch (_) { /* fall back to default repoName */ }
    const inner = new URLSearchParams();
    inner.set("repo", repo);
    if (branch) inner.set("branch", branch);
    // Both rise presenters need a concrete notebook; without a path,
    // fall back to the Lab file browser as before.
    //   ui=rise         -> jupyterlab-rise (Lab-based standalone presenter)
    //   ui=rise-classic -> classic Notebook frontend + classic RISE
    inner.set("urlpath",
      ui === "rise" && path ? `rise/${repoName}/${path}`
        : ui === "rise-classic" && path ? `nbclassic/notebooks/${repoName}/${path}`
        : path ? `lab/tree/${repoName}/${path}`
        : `lab/tree/${repoName}`);
    const innerEncoded = encodeURIComponent("git-pull?" + inner.toString());
    url = `https://mybinder.org/v2/gh/${REPO}/${image}?urlpath=${innerEncoded}`;
  } else {
    url = `https://mybinder.org/v2/gh/${REPO}/${image}`;
  }

  // Belt-and-braces: never wire a navigation sink to anything whose
  // origin isn't mybinder.org. With the inputs above this can't fail,
  // but asserting it here means any future change that weakens the
  // construction degrades to the safe default instead of silently
  // becoming an open redirect.
  try {
    if (new URL(url).origin !== "https://mybinder.org") {
      url = `https://mybinder.org/v2/gh/${REPO}/latest-xl`;
    }
  } catch (_) {
    url = `https://mybinder.org/v2/gh/${REPO}/latest-xl`;
  }

  // Reveal fallback first (in case the redirect is blocked) and only
  // then trigger location.replace. If a browser strips the redirect
  // (rare), the link is already wired.
  if (note) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = note;
    document.getElementById("status").appendChild(p);
  }
  document.getElementById("launch-link").href = url;
  document.getElementById("launch-url").textContent = url;
  document.getElementById("fallback").style.display = "block";

  // Umami event: which image/mode actually got launched.
  //
  // The tracker loads with `defer` from <head>, but this script runs
  // synchronously at the end of <body> — i.e. *before* deferred
  // scripts execute — so `window.umami` is never there yet at this
  // point. (Tracking synchronously here meant zero launches were ever
  // recorded.) So: poll for the tracker briefly, send the event, give
  // the beacon a moment to leave (the tracker POSTs with
  // `keepalive: true`, so it survives the navigation once started),
  // then redirect. Analytics must never block the launch: a hard
  // deadline redirects regardless, e.g. when the tracker is blocked.
  const mode = file ? "file" : (repo ? "repo" : "bare");
  // Which frontend the repo launch actually resolves to (file wins
  // over repo, so a file launch is always "lab"). Mirrors the
  // urlpath ternary above.
  const dest = !file && repo && path
    ? (ui === "rise" ? "rise" : ui === "rise-classic" ? "rise-classic" : "lab")
    : "lab";
  const eventProps = { image, mode, ui: dest, notebook: (file || path || "") };

  const MIN_DELAY_MS = 400;   // let the user see the destination before the jump
  const POLL_MS = 50;         // how often to check for window.umami
  const MAX_WAIT_MS = 1500;   // give up on analytics after this long
  const BEACON_MS = 250;      // grace period after track() before navigating
  const started = Date.now();

  let redirected = false;
  const go = () => {
    if (redirected) return;
    redirected = true;
    location.replace(url);
  };
  // Hard deadline: the redirect happens no matter what analytics does.
  setTimeout(go, MAX_WAIT_MS + BEACON_MS);

  const goAfter = (ms) => {
    const wait = Math.max(ms, MIN_DELAY_MS - (Date.now() - started));
    setTimeout(go, wait);
  };

  const trackThenGo = () => {
    try {
      // Family taxonomy v2 (Fun-with-Quantum/family/EVENTS.md): `<Site>: <what happened>`.
      const p = window.umami.track("QuBins: notebook launch", eventProps);
      // umami.track returns a promise that settles once the POST is
      // done; navigate on whichever comes first — that or the grace period.
      if (p && typeof p.then === "function") {
        p.then(() => goAfter(0), () => goAfter(0));
      }
    } catch (_) { /* analytics is best-effort */ }
    goAfter(BEACON_MS);
  };

  const poll = () => {
    if (redirected) return;
    if (window.umami && typeof window.umami.track === "function") {
      trackThenGo();
    } else if (Date.now() - started < MAX_WAIT_MS) {
      setTimeout(poll, POLL_MS);
    } else {
      go(); // tracker never showed up (blocked / offline / wrong host)
    }
  };
  poll();
})();
