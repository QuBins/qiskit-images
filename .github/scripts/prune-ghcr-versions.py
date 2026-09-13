#!/usr/bin/env python3
"""Prune unreferenced GHCR container versions for ghcr.io/qubins/images.

WHY THIS EXISTS
---------------
Every nightly Build matrix run republishes all 17 flavors, and each
publish mints brand-new GHCR "versions":

  * 34 per-arch pushes (17 flavors x 2 arches). Provenance attestation
    is enabled, so `docker/build-push-action` pushes an OCI *index*
    rather than a plain manifest: the index carries the
    `<version>-<arch>` tag and points at two UNTAGGED children -- the
    image manifest and the provenance attestation manifest. That is
    3 versions per push, so 102.
  *      17 parent multi-arch manifests (`imagetools create`).
  *       4 `latest-*` alias indexes (latest-small/-xl/-xxl + latest).
  *      21 cosign `.sig` tags, one per published tag.

~144 new versions per night. They are new every night even when no
layer changed, because the provenance attestation embeds build
timestamps -- a different attestation digest means a different index
digest means a new version.

Nothing has ever pruned them. At ~144/night the package sails past
5000 versions in about five weeks, which is why
build-admin-stats.py's paging guard ("GHCR versions paging runaway")
has been firing on every Pages deploy in living memory, silently
dropping the GHCR half of the admin page.

WHY NOT JUST "DELETE UNTAGGED"
------------------------------
Because that would delete live images. The standard recipe --
`actions/delete-package-versions` with `delete-only-untagged-versions`
-- assumes untagged means unreferenced. Here it does not: the image
manifest and provenance manifest inside *today's* `2.5-xl-amd64`
index are both untagged, and deleting them breaks the tag that points
at them.

So this script does not reason about tags alone. It walks the
registry: for every tag that exists today it fetches the manifest and
follows every digest reference (index -> child manifests -> subject/
attestation references), building the set of digests that are
genuinely reachable. Anything reachable is kept no matter what its tag
state looks like. Only versions that nothing points at are candidates.

SAFETY RAILS (in order of application)
--------------------------------------
 1. Reachability. A digest referenced by any live tag is never a
    candidate, tagged or not.
 2. Tagged versions are never candidates, even if unreachable -- a
    stray tag is a human signal, not garbage. (Except orphaned cosign
    `.sig` tags, see 3.)
 3. Cosign signatures. `sha256-<digest>.sig` is a tag, so rule 2 would
    pin every signature forever. A signature whose subject digest is
    gone is dead weight, so it becomes a candidate once its subject is
    no longer present. A signature whose subject is still live is
    always kept.
 4. Grace period. Nothing younger than --grace-days is ever deleted,
    so an in-flight publish (children pushed, index not yet created)
    cannot be collected mid-run. Default 3 days: a publish takes ~20
    minutes, so this is a ~200x margin for that job. The window is
    also, in practice, the rollback horizon for anyone pinning an
    UNREFERENCED digest -- live tags are protected by reachability
    regardless of age, so this only bounds how far back a digest that
    nothing points at stays resolvable. It is what sets the package's
    steady-state size: ~144 new versions a night means roughly
    grace_days x 144 versions retained on top of the live set.
 5. Floor. Refuse to run if it would delete more than --max-delete
    versions in one pass, so a bug in reachability cannot cascade.
 6. Dry run by default. --apply is required to delete anything.

Exit codes: 0 ok, 1 error, 2 refused (floor tripped).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

GH_ORG = "QuBins"
GH_PACKAGE = "images"  # ghcr.io/qubins/images
REGISTRY_REPO = "qubins/images"

GH_API = "https://api.github.com"
REGISTRY = "https://ghcr.io"

# Media types whose bodies carry further digest references.
INDEX_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
MANIFEST_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}
ACCEPT = ", ".join(sorted(INDEX_TYPES | MANIFEST_TYPES))


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler that does not leak the API token.

    Same rationale as build-admin-stats.py: the stdlib default copies
    a caller-set ``Authorization`` header across a host change. We
    strip it on a cross-host hop and refuse to follow a downgrade to
    plain HTTP.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        if urlsplit(newurl).scheme != "https":
            return None
        if urlsplit(newurl).hostname != urlsplit(req.full_url).hostname:
            new.remove_header("Authorization")
        return new


_OPENER = urllib.request.build_opener(_SafeRedirectHandler)


def _get(url: str, headers: dict[str, str], *, tries: int = 3) -> tuple[bytes, dict]:
    """GET with linear backoff on 5xx / transport errors.

    A 404 is returned to the caller as None-ish via HTTPError so the
    reachability walk can treat a missing manifest as "nothing further
    to follow" rather than aborting the whole run.
    """
    last: Exception | None = None
    for attempt in range(1, tries + 1):
        req = urllib.request.Request(url, headers=headers)
        try:
            with _OPENER.open(req, timeout=30) as resp:
                # Lowercase the keys. HTTP header names are
                # case-insensitive and `resp.headers` (an
                # email.message.Message) honours that, but
                # `dict(resp.headers)` does NOT -- it freezes whatever
                # case the server happened to send. GHCR sends
                # `docker-content-digest` in lower case, so a lookup
                # for the conventional `Docker-Content-Digest` silently
                # returned None and every digest went unrecorded.
                return resp.read(), {k.lower(): v for k, v in resp.headers.items()}
        except urllib.error.HTTPError as e:
            if e.code == 404 or 400 <= e.code < 500:
                raise
            last = e
        except Exception as e:  # transport-level
            last = e
        if attempt < tries:
            time.sleep(attempt * 2)
    raise RuntimeError(f"GET {url} failed after {tries} attempts: {last}")


# ------------------------------------------------------------ GitHub API


def gh_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "qubins-ghcr-prune",
    }


def list_versions(token: str) -> list[dict]:
    """Every version of the package, newest first.

    Deliberately has no low page ceiling: the whole point is that this
    package has more versions than the admin-stats guard allowed for.
    The bound here is a sanity limit far above any plausible real
    count, so a paging bug still cannot spin forever.
    """
    out: list[dict] = []
    page = 1
    while True:
        url = (
            f"{GH_API}/orgs/{GH_ORG}/packages/container/{GH_PACKAGE}"
            f"/versions?per_page=100&page={page}"
        )
        body, _ = _get(url, gh_headers(token))
        data = json.loads(body)
        if not data:
            break
        out.extend(data)
        if len(data) < 100:
            break
        page += 1
        if page > 1000:  # 100k versions; a real runaway, not growth
            raise RuntimeError("GHCR paging exceeded 100k versions")
    return out


class RateLimited(Exception):
    """Raised when the API is refusing writes and waiting is not worth it."""


def delete_version(token: str, version_id: int, *, budget: list[float]) -> None:
    """Delete one version, waiting out a rate limit if it is short.

    GitHub answers a secondary rate limit with **403**, not 429, and
    without a Retry-After in some cases -- so a 403 here is usually
    "slow down", not "forbidden". On the first full pass (2026-09-13,
    run 34742398684) 7058 deletions succeeded and then 7076 straight
    403s followed for 11 minutes, and because every failure was merely
    logged the run still exited 0 reporting "Deleted 7058/14134". A
    scheduled prune must not look successful after doing half its job.

    `budget` is a single-element list holding the seconds of waiting
    still allowed across the whole run, so one stalled pass cannot sit
    burning a 6h job slot. When it runs out we raise RateLimited and
    main() stops deleting and exits non-zero with the remainder
    reported -- the next run picks up where this one left off, since
    the candidate set is recomputed from scratch every time.
    """
    url = (
        f"{GH_API}/orgs/{GH_ORG}/packages/container/{GH_PACKAGE}"
        f"/versions/{version_id}"
    )
    for attempt in range(1, 5):
        req = urllib.request.Request(url, headers=gh_headers(token), method="DELETE")
        try:
            with _OPENER.open(req, timeout=30) as resp:
                resp.read()
            return
        except urllib.error.HTTPError as e:
            if e.code not in (403, 429):
                raise
            hdrs = {k.lower(): v for k, v in (e.headers or {}).items()}
            wait = 0.0
            if hdrs.get("retry-after"):
                try:
                    wait = float(hdrs["retry-after"])
                except ValueError:
                    wait = 60.0
            elif hdrs.get("x-ratelimit-remaining") == "0" and hdrs.get("x-ratelimit-reset"):
                try:
                    wait = max(0.0, float(hdrs["x-ratelimit-reset"]) - time.time())
                except ValueError:
                    wait = 60.0
            else:
                wait = 30.0 * attempt
            if wait > budget[0]:
                raise RateLimited(
                    f"rate limited; next wait {wait:.0f}s exceeds remaining "
                    f"budget {budget[0]:.0f}s"
                )
            print(f"  rate limited, waiting {wait:.0f}s ...", flush=True)
            time.sleep(wait)
            budget[0] -= wait
    raise RateLimited("still rate limited after 4 attempts")


# -------------------------------------------------------------- registry


def registry_token() -> str:
    """Anonymous pull token. The package is public, so no credential
    is needed to read manifests -- and using an anonymous token here
    keeps GITHUB_TOKEN off the registry hop entirely."""
    url = f"{REGISTRY}/token?scope=repository:{REGISTRY_REPO}:pull&service=ghcr.io"
    body, _ = _get(url, {"User-Agent": "qubins-ghcr-prune"})
    tok = json.loads(body).get("token")
    if not tok:
        raise RuntimeError("could not obtain anonymous ghcr.io pull token")
    return tok


def fetch_manifest(tok: str, ref: str) -> tuple[dict | None, str | None]:
    """Fetch a manifest by tag or digest. Returns (body, digest).

    A 404 yields (None, None): the reference vanished between listing
    and walking, which is normal on a live registry and simply means
    there is nothing further to follow.
    """
    url = f"{REGISTRY}/v2/{REGISTRY_REPO}/manifests/{ref}"
    headers = {
        "Accept": ACCEPT,
        "Authorization": f"Bearer {tok}",
        "User-Agent": "qubins-ghcr-prune",
    }
    try:
        body, hdrs = _get(url, headers)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, None
        raise
    # A manifest's digest is by definition sha256 over its exact
    # bytes, so compute it rather than trusting the header to be
    # present. The header is used when offered and verified against
    # the computed value; a mismatch means we are not looking at what
    # we think we are, and a GC must not act on that.
    computed = "sha256:" + hashlib.sha256(body).hexdigest()
    advertised = hdrs.get("docker-content-digest")
    if advertised and advertised != computed:
        raise RuntimeError(
            f"digest mismatch for {ref}: header {advertised} != computed {computed}"
        )
    return json.loads(body), computed


def walk_reachable(tok: str, tags: list[str]) -> tuple[set[str], list[str]]:
    """Every digest reachable from the given tags.

    Follows index -> manifests, plus the `subject` back-reference used
    by attestation/referrers manifests. Config and layer blobs are not
    GHCR "versions" so they are not collected; only manifest-level
    digests matter here.
    """
    seen: set[str] = set()
    unresolved: list[str] = []
    top = set(tags)
    queue: list[str] = list(tags)
    while queue:
        ref = queue.pop()
        doc, digest = fetch_manifest(tok, ref)
        if doc is None:
            # A top-level tag that will not resolve means our picture
            # of what is live is incomplete. Record it; main() refuses
            # to delete on an incomplete picture.
            if ref in top:
                unresolved.append(ref)
            continue
        if digest:
            if digest in seen:
                continue
            seen.add(digest)
        for child in doc.get("manifests", []) or []:
            d = child.get("digest")
            if d and d not in seen:
                queue.append(d)
        subj = (doc.get("subject") or {}).get("digest")
        if subj and subj not in seen:
            queue.append(subj)
    return seen, unresolved


# ------------------------------------------------------------------ main


def iso_age_days(ts: str | None, now: float) -> float:
    if not ts:
        return 0.0  # unknown age -> treat as brand new, i.e. protected
    try:
        t = time.strptime(ts.replace("Z", "UTC"), "%Y-%m-%dT%H:%M:%S%Z")
    except ValueError:
        return 0.0
    return (now - time.mktime(t) + time.timezone) / 86400.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="actually delete; default is a dry run")
    ap.add_argument("--grace-days", type=float, default=3.0,
                    help="never delete anything younger than this")
    ap.add_argument("--max-delete", type=int, default=20000,
                    help="refuse the run if more than this many would go")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap deletions this pass (0 = no cap)")
    ap.add_argument("--wait-budget", type=float, default=600.0,
                    help="total seconds this run may spend waiting out "
                         "rate limits before stopping and reporting")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("GITHUB_TOKEN not set", file=sys.stderr)
        return 1

    now = time.time()

    print("Listing package versions ...")
    versions = list_versions(token)
    print(f"  {len(versions)} versions total")

    # Tag inventory. `.sig` tags are handled separately below.
    tags_by_digest: dict[str, list[str]] = {}
    live_tags: list[str] = []
    for v in versions:
        name = v.get("name") or ""  # the digest, sha256:...
        tl = (v.get("metadata", {}).get("container", {}) or {}).get("tags") or []
        tags_by_digest[name] = tl
        live_tags.extend(tl)
    sig_tags = [t for t in live_tags if t.startswith("sha256-") and t.endswith(".sig")]
    real_tags = [t for t in live_tags if t not in set(sig_tags)]
    print(f"  {len(real_tags)} real tags, {len(sig_tags)} cosign signature tags")

    print("Walking reachability from live tags ...")
    reachable, unresolved = walk_reachable(registry_token(), real_tags)
    print(f"  {len(reachable)} digests reachable from live tags")

    # Coherence gate. Reachability is the rail that keeps this from
    # behaving like "delete every untagged version", which here would
    # delete the live children of every per-arch index. If the walk
    # did not actually work, we must not fall through to deleting on
    # a degraded picture -- which is exactly what happened on the
    # first dry run (2026-09-12, run 34713900112): a case-sensitive
    # header lookup meant 0 digests were recorded from 55 live tags,
    # and 13131 versions were listed as candidates with the rail
    # silently dead. Refuse instead.
    if real_tags and not reachable:
        print("\nREFUSING: walked ${n} live tags and found 0 reachable digests."
              .replace("${n}", str(len(real_tags))), file=sys.stderr)
        print("The reachability walk is not working; deleting now would "
              "treat live images as garbage.", file=sys.stderr)
        return 2
    if unresolved:
        print(f"\nREFUSING: {len(unresolved)} live tag(s) did not resolve, so the "
              f"set of reachable digests is incomplete:", file=sys.stderr)
        for t in unresolved[:10]:
            print(f"  {t}", file=sys.stderr)
        print("A GC must not delete on an incomplete picture. Re-run once the "
              "registry answers for every tag.", file=sys.stderr)
        return 2

    # A cosign signature's subject is encoded in its tag:
    #   sha256-<hex>.sig  ->  sha256:<hex>
    live_digests = set(tags_by_digest)
    def sig_subject(tag: str) -> str:
        return "sha256:" + tag[len("sha256-"):-len(".sig")]
    orphan_sig_tags = {
        t for t in sig_tags
        if sig_subject(t) not in reachable and sig_subject(t) not in live_digests
    }
    print(f"  {len(orphan_sig_tags)} signature tags whose subject is gone")

    keep, candidates = [], []
    for v in versions:
        digest = v.get("name") or ""
        tl = tags_by_digest.get(digest) or []
        age = iso_age_days(v.get("updated_at") or v.get("created_at"), now)

        if digest in reachable:
            keep.append((v, "reachable"))
        elif age < args.grace_days:
            keep.append((v, "within grace"))
        elif tl and not set(tl) <= orphan_sig_tags:
            keep.append((v, "tagged"))
        else:
            candidates.append((v, tl, age))

    # Break the keep set down by rule. A dry run exists to be
    # reviewed, and "KEEP 3895" on its own does not let anyone judge
    # whether the split is sensible -- the interesting question is
    # always which rail is holding what, e.g. how much is live vs
    # merely inside the grace window vs pinned by a tag.
    reasons: dict[str, int] = {}
    sig_kept = 0
    for v, why in keep:
        reasons[why] = reasons.get(why, 0) + 1
        tl = tags_by_digest.get(v.get("name") or "") or []
        if any(t.startswith("sha256-") and t.endswith(".sig") for t in tl):
            sig_kept += 1

    print()
    print(f"KEEP      {len(keep)}")
    for why in ("reachable", "within grace", "tagged"):
        if reasons.get(why):
            print(f"  {reasons[why]:6d}  {why}")
    print(f"  ({sig_kept} of the kept versions are cosign .sig tags)")
    print(f"CANDIDATE {len(candidates)}  (unreachable, untagged-or-orphan-sig, "
          f"older than {args.grace_days:g}d)")

    if candidates:
        ages = sorted(a for _, _, a in candidates)
        print(f"  age range: {ages[0]:.1f}d .. {ages[-1]:.1f}d")
        print("  sample (first 10):")
        for v, tl, age in candidates[:10]:
            print(f"    {v.get('name','')[:23]}…  age={age:6.1f}d  tags={tl or '-'}")

    if len(candidates) > args.max_delete:
        print(f"\nREFUSING: {len(candidates)} candidates exceeds "
              f"--max-delete {args.max_delete}.", file=sys.stderr)
        return 2

    if not args.apply:
        print("\nDry run — nothing deleted. Re-run with --apply to delete.")
        return 0

    batch = candidates if args.limit <= 0 else candidates[: args.limit]
    print(f"\nDeleting {len(batch)} versions ...", flush=True)
    budget = [float(args.wait_budget)]
    done = 0
    failed = 0
    stopped = ""
    for v, _tl, _age in batch:
        try:
            delete_version(token, int(v["id"]), budget=budget)
            done += 1
        except RateLimited as e:
            stopped = str(e)
            break
        except Exception as e:  # unexpected: report and keep going
            failed += 1
            if failed <= 20:
                print(f"  failed id={v.get('id')}: {e}", file=sys.stderr)
    remaining = len(batch) - done
    print(f"Deleted {done}/{len(batch)}.")
    if stopped:
        print(f"Stopped early: {stopped}", file=sys.stderr)
    if remaining:
        # Non-zero so a scheduled run does not read as fully successful
        # while leaving thousands of candidates behind. Re-running
        # resumes: the candidate set is recomputed each time.
        print(f"{remaining} candidate(s) not deleted; re-run to continue.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
