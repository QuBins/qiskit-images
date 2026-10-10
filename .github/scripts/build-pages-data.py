#!/usr/bin/env python3
"""Generate docs/versions.json from the versions/ directory.

Walks versions/<minor>-<flavor>/ and emits an ordered list (newest minor
first, matching the build-matrix planner convention). The page JS
consumes this at runtime to render the catalog table and to populate
the URL generator's image dropdown.

The file is a public interface: RasQberry, doQumentation and the
/launch/ redirector read it. Its shape is documented for consumers in
the README ("versions.json"); keep that section, SCHEMA_VERSION and
this docstring in step. Fields are only ever added; removing or
renaming one, or changing its meaning, bumps SCHEMA_VERSION.

Top level:

    {
      "schema_version": 1,
      "generated_at":   "2026-10-10T05:15:42Z",
      "latest_qiskit":  "2.5",
      "images":         [ ... ]
    }

One entry per published image:

    {
      "qiskit_minor": "2.4",
      "flavor":       "small" | "xl" | "xxl" | "xl-rise",
      "is_latest":    true,      # current LATEST_QISKIT minor
      "binder_tag":   "2.4-small",
      "docker_tag":   "ghcr.io/qubins/images:2.4-small",
      "notes":        "reduced set: ...",     # optional
      "ai_transpiler": false,                 # xxl only
      "digest":       "sha256:...",           # multi-arch index, tonight's
      "platforms":    ["linux/amd64", "linux/arm64"],
      "size_mb":      812.5,                  # download, amd64 child
      "size_mb_arm64": 790.1,                 # same, arm64 child
      "updated_at":   "2026-05-15T04:34:21Z", # image.created label
      "qiskit_patch": "2.4.1",                # org.qubins.qiskit.patch
      "qiskit_ibm_runtime": "0.45.1",         # org.qubins.qiskit-ibm-runtime
      "revision":     "1391056...",           # image.revision (git SHA)
      "snapshots": [                          # newest first; may be []
        {"tag": "2.4-small-20261008", "date": "2026-10-08",
         "digest": "sha256:..."}
      ]
    }

LATEST_QISKIT is read from build-matrix.yml's env block so we don't
need a second source of truth.

`notes` overrides live in NOTES below; keep that in sync with the
README footnotes when a flavor changes.

Everything from `digest` down is best-effort enrichment from the public
GHCR registry. Anonymous reads work for the public package; if the
fetch fails for any reason the fields are simply omitted from that
image's record so the page still renders.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler that does not leak the bearer token.

    CPython's default HTTPRedirectHandler copies a caller-set
    ``Authorization`` header (added via ``Request(headers=...)``) onto
    the redirected request verbatim — including across a host change.
    GHCR legitimately 302s blob/manifest fetches to a separate CDN
    host, so following with the registry bearer attached would send
    that credential off-host. (An earlier comment here claimed urllib
    "does the right thing"; it does not.) We strip ``Authorization``
    whenever the redirect target's host differs from the original, and
    refuse to follow a downgrade to a non-HTTPS scheme. The GHCR CDN
    does not need the bearer (its URL carries a signed query string),
    so stripping is both safe and correct.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        if urlsplit(newurl).scheme != "https":
            return None  # never downgrade a credentialed request
        if urlsplit(newurl).hostname != urlsplit(req.full_url).hostname:
            new.remove_header("Authorization")
        return new


# Module-level opener: default handlers minus the stock redirect
# handler, plus our credential-stripping one.
_OPENER = urllib.request.build_opener(_SafeRedirectHandler)

# Hand-maintained notes per image (mirrors the README footnotes).
# Empty if no special note applies.
NOTES: dict[tuple[str, str], str] = {
    ("2.4", "xxl"): (
        "Everything in xl plus qiskit-ibm-transpiler[ai-local-mode], "
        "which pulls PyTorch + the full CUDA 13 wheelset (~4 GB "
        "download). The AI transpiler is amd64-only (no aarch64 "
        "wheels): the arm64 build of this tag has the same content as "
        "xl. Use xl unless you need the local AI transpiler."
    ),
    ("2.1", "xl-rise"): (
        "xl plus the classic Notebook frontend with classic RISE, so "
        "slideshows can show interactive widgets. Launch a notebook "
        "with ui=rise-classic; the Quantum Coin Game uses it."
    ),
}

# An xxl whose requirements file has the transpiler line commented out
# (2.5: the transpiler can't import on that Qiskit minor) has the same
# content as its xl. Detect that from the file rather than a hand note,
# so the site stops advertising it the moment the line is restored.
TRANSPILER_RE = re.compile(r"^\s*qiskit-ibm-transpiler\b", re.MULTILINE)


def has_ai_transpiler(minor: str, flavor: str) -> bool:
    if flavor != "xxl":
        return False
    req = VERSIONS_DIR / f"{minor}-{flavor}" / "requirements.txt"
    return bool(TRANSPILER_RE.search(req.read_text()))


def xxl_without_transpiler_note(minor: str, fallback: str | None) -> str:
    note = (
        f"Currently the same content as {minor}-xl: the local AI "
        f"transpiler does not support Qiskit {minor} yet."
    )
    if fallback:
        note += f" For the AI transpiler use {fallback}-xxl (amd64)."
    return note

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS_DIR = REPO_ROOT / "versions"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "build-matrix.yml"
DOCKER_PREFIX = "ghcr.io/qubins/images"
GHCR_HOST = "ghcr.io"
GHCR_REPO = "qubins/images"  # lowercase to match GHCR canonicalisation
SCHEMA_VERSION = 1


def latest_qiskit() -> str:
    text = WORKFLOW_PATH.read_text()
    m = re.search(r"LATEST_QISKIT:\s*'([0-9.]+)'", text)
    if not m:
        sys.exit("LATEST_QISKIT not found in build-matrix.yml")
    return m.group(1)


def discover_versions() -> list[dict]:
    pattern = re.compile(r"^(\d+\.\d+)-(small|xl|xxl|xl-rise)$")
    flavor_rank = {"small": 0, "xl": 1, "xl-rise": 2, "xxl": 3}
    entries: list[tuple[tuple[int, int], str, str]] = []
    for child in VERSIONS_DIR.iterdir():
        if not child.is_dir():
            continue
        m = pattern.match(child.name)
        if not m:
            continue
        minor, flavor = m.group(1), m.group(2)
        sort_key = tuple(int(p) for p in minor.split("."))
        entries.append((sort_key, minor, flavor))
    # newest minor first, then small -> xl -> xl-rise -> xxl within a minor
    entries.sort(key=lambda x: (-x[0][0], -x[0][1], flavor_rank.get(x[2], 99)))
    return [
        {"qiskit_minor": minor, "flavor": flavor}
        for _, minor, flavor in entries
    ]


# --------------------------------------------------------------- GHCR enrichment
#
# Best-effort fetch of per-tag size + push timestamp from the public
# GHCR registry. Anonymous reads work; we fetch a token, then the
# multi-arch index, then both child manifests to sum layer sizes.
#
# If anything fails — package not yet published, registry blip, network
# missing in a local run — we silently omit the fields rather than
# fail the deploy.


_REGISTRY_TOKEN: str | None = None


def _registry_token() -> str | None:
    """Anonymous bearer for ghcr.io pull. Cached per process."""
    global _REGISTRY_TOKEN
    if _REGISTRY_TOKEN is not None:
        return _REGISTRY_TOKEN
    url = f"https://{GHCR_HOST}/token?scope=repository:{GHCR_REPO}:pull&service={GHCR_HOST}"
    try:
        with _OPENER.open(url, timeout=15) as r:
            _REGISTRY_TOKEN = json.loads(r.read())["token"]
            return _REGISTRY_TOKEN
    except Exception:  # noqa: BLE001 — best-effort
        return None


def _ghcr_get(path: str, accept: str, raw: bool = False):
    """GET /v2/<repo>/<path>. Follows redirects via _OPENER, which
    strips the Authorization header on any host change (GHCR 302s
    blob/manifest fetches to a separate CDN host) and refuses non-HTTPS
    redirect targets, so the registry bearer never leaves ghcr.io.
    """
    token = _registry_token()
    if not token:
        return None
    url = f"https://{GHCR_HOST}/v2/{GHCR_REPO}/{path}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": accept},
    )
    try:
        with _OPENER.open(req, timeout=20) as r:
            body = r.read()
            return body if raw else json.loads(body)
    except urllib.error.HTTPError:
        return None
    except Exception:  # noqa: BLE001 — best-effort
        return None


MANIFEST_ACCEPT = (
    "application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.docker.distribution.manifest.v2+json"
)


def _manifest_size(manifest: dict) -> int:
    """Download size of one platform's image: config + all layers."""
    total = (manifest.get("config") or {}).get("size") or 0
    for layer in manifest.get("layers") or []:
        total += layer.get("size") or 0
    return total


INDEX_ACCEPT = (
    "application/vnd.oci.image.index.v1+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json"
)


def _index(tag: str) -> tuple[dict, str] | None:
    """The multi-arch index for a tag and its digest. The digest is
    the sha256 of the exact bytes the registry serves, which is what
    `docker pull ...@sha256:` checks against."""
    body = _ghcr_get(f"manifests/{tag}", INDEX_ACCEPT, raw=True)
    if not body:
        return None
    try:
        index = json.loads(body)
    except ValueError:
        return None
    if not isinstance(index.get("manifests"), list):
        return None
    return index, "sha256:" + hashlib.sha256(body).hexdigest()


_TAGS: list[str] | None = None


def registry_tags() -> list[str]:
    """Every tag in the package (GHCR serves them in one page)."""
    global _TAGS
    if _TAGS is None:
        listing = _ghcr_get("tags/list?n=10000", "application/json")
        _TAGS = (listing or {}).get("tags") or []
    return _TAGS


def fetch_snapshots(tag: str) -> list[dict] | None:
    """Monthly snapshots of a tag, newest first, or None if the tag
    list could not be read (so the field is omitted, not wrongly [])."""
    tags = registry_tags()
    if not tags:
        return None
    pat = re.compile(rf"^{re.escape(tag)}-(\d{{4}})(\d{{2}})(\d{{2}})$")
    snaps = []
    for t in sorted(tags, reverse=True):
        m = pat.match(t)
        if not m:
            continue
        snap = {"tag": t, "date": "-".join(m.groups())}
        idx = _index(t)
        if idx:
            snap["digest"] = idx[1]
        snaps.append(snap)
    return snaps


def fetch_image_meta(tag: str) -> dict:
    """Returns {size_mb, size_mb_arm64, updated_at, qiskit_patch} for
    the given tag, or {}.

    Strategy:
      1. Multi-arch index → pick the amd64 and arm64 child digests.
      2. Each child manifest → sum config.size + layers[].size.
      3. amd64 config blob → read the build time and labels.

    If any step fails (package not yet published, registry blip,
    network missing on a local run), we return whatever we managed
    to collect — a partial result is still useful and the page
    renders cleanly with omitted fields.
    """
    idx = _index(tag)
    if not idx:
        return {}
    index, index_digest = idx
    digests: dict[str, str] = {}
    for m in index["manifests"]:
        p = m.get("platform") or {}
        if p.get("os") == "linux" and p.get("architecture") in ("amd64", "arm64"):
            digests.setdefault(p["architecture"], m.get("digest"))
    if not digests.get("amd64"):
        return {}
    out: dict = {
        "digest": index_digest,
        "platforms": [f"linux/{a}" for a in ("amd64", "arm64") if a in digests],
    }
    manifest = _ghcr_get(f"manifests/{digests['amd64']}", MANIFEST_ACCEPT)
    if not manifest:
        return out
    total = _manifest_size(manifest)
    if total > 0:
        out["size_mb"] = round(total / (1024 * 1024), 1)
    # arm64 differs where wheels are missing (gem-suite; the whole AI
    # transpiler stack on xxl), so the page shows it when it differs.
    arm = _ghcr_get(f"manifests/{digests['arm64']}", MANIFEST_ACCEPT) if digests.get("arm64") else None
    arm_total = _manifest_size(arm) if arm else 0
    if arm_total > 0:
        out["size_mb_arm64"] = round(arm_total / (1024 * 1024), 1)
    # Push time + OCI labels live on the config blob, not on the
    # manifest. Fetch the blob and read them out. The
    # `org.qubins.qiskit.patch` label is populated by the build-matrix
    # workflow with the actual installed qiskit patch (e.g. "2.4.1");
    # for images built before that step landed, the label is absent
    # and we just omit qiskit_patch.
    #
    # We read `org.qubins.qiskit.patch` rather than
    # `org.opencontainers.image.version`. Both now carry the qiskit
    # patch -- the build-matrix workflow sets image.version explicitly
    # so Artifact Hub shows something meaningful -- but only images
    # built after that change do. Older published images still have
    # the inherited base value there (the Ubuntu release, "24.04"),
    # so reading image.version would surface "24.04" as the qiskit
    # version for anything older. The namespaced key has never meant
    # anything else, so it stays the one we trust.
    config_digest = (manifest.get("config") or {}).get("digest")
    if config_digest:
        config = _ghcr_get(f"blobs/{config_digest}", "application/json")
        if config:
            labels = (config.get("config") or {}).get("Labels") or {}
            # Build time: the image.created label. The config's own
            # `created` is the reproducible-layer epoch (last commit to
            # an image input) since builds pin SOURCE_DATE_EPOCH; it is
            # only the fallback, for images built before the label.
            created = labels.get("org.opencontainers.image.created") or config.get("created")
            if created:
                out["updated_at"] = created
            patch = labels.get("org.qubins.qiskit.patch")
            if patch:
                out["qiskit_patch"] = patch
            # Both absent on images built before the labels existed.
            runtime = labels.get("org.qubins.qiskit-ibm-runtime")
            if runtime:
                out["qiskit_ibm_runtime"] = runtime
            revision = labels.get("org.opencontainers.image.revision")
            if revision:
                out["revision"] = revision
    return out


def main() -> None:
    latest = latest_qiskit()
    entries = discover_versions()
    # Newest minor whose xxl really carries the transpiler (entries are
    # newest-first), for the pointer in the no-transpiler note.
    transpiler_minor = next(
        (e["qiskit_minor"] for e in entries
         if has_ai_transpiler(e["qiskit_minor"], e["flavor"])),
        None,
    )
    out: list[dict] = []
    enriched = 0
    for entry in entries:
        minor = entry["qiskit_minor"]
        flavor = entry["flavor"]
        tag = f"{minor}-{flavor}"
        item = {
            "qiskit_minor": minor,
            "flavor": flavor,
            "is_latest": minor == latest,
            "binder_tag": tag,
            "docker_tag": f"{DOCKER_PREFIX}:{tag}",
        }
        note = NOTES.get((minor, flavor))
        if flavor == "xxl":
            item["ai_transpiler"] = has_ai_transpiler(minor, flavor)
            if not item["ai_transpiler"]:
                note = xxl_without_transpiler_note(minor, transpiler_minor)
        if note:
            item["notes"] = note
        meta = fetch_image_meta(tag)
        if meta:
            item.update(meta)
            enriched += 1
        snaps = fetch_snapshots(tag)
        if snaps is not None:
            item["snapshots"] = snaps
        out.append(item)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "latest_qiskit": latest,
        "images": out,
    }
    target = REPO_ROOT / "docs" / "versions.json"
    target.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        f"Wrote {target.relative_to(REPO_ROOT)} ({len(out)} images, "
        f"latest={latest}, enriched={enriched}/{len(out)})"
    )


if __name__ == "__main__":
    main()
