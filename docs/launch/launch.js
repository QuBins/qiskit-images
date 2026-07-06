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
  const ui     = params.get("ui");

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
    // The rise presenter needs a concrete notebook; without a path,
    // fall back to the Lab file browser as before.
    inner.set("urlpath",
      ui === "rise" && path ? `rise/${repoName}/${path}`
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
  document.getElementById("launch-link").href = url;
  document.getElementById("launch-url").textContent = url;
  document.getElementById("fallback").style.display = "block";

  // Fire-and-forget Umami event: which image/mode actually got
  // launched. Best-effort — guard for the script not loading.
  try {
    if (window.umami && typeof window.umami.track === "function") {
      const mode = file ? "file" : (repo ? "repo" : "bare");
      const dest = ui === "rise" && repo && path ? "rise" : "lab";
      window.umami.track("launch-redirect", { image, mode, ui: dest });
    }
  } catch (_) { /* analytics is best-effort */ }

  // Brief delay so the user can see the destination before the jump.
  setTimeout(() => { location.replace(url); }, 400);
})();
