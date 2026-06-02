#!/usr/bin/env python3
"""Generate docs/admin/stats.json from public usage data.

Two sources:

1. GHCR publish freshness for ghcr.io/qubins/images. Uses the
   GitHub Packages API (`GET /orgs/QuBins/packages/container/images/
   versions`) authenticated with GITHUB_TOKEN to list every published
   container version and its tag list + push timestamp.
   (Historical note: GHCR's `download_count` is exposed by the API
   but is *not* populated for container packages — it returns 0
   regardless of real pull traffic. Reporting "0 total pulls" as
   the headline metric was misleading rather than useful, so the
   admin page surfaces *publish freshness* instead: how many tags
   exist, when each was last refreshed, when the most recent
   publish landed. This is real operational signal — "all 13 tags
   refreshed in the last 24 h" tells you the daily cron is healthy;
   a tag with a stale `updated_at` flags a publish regression.)
   The mybinder section below carries the actual *usage* signal.

2. mybinder launch counts from the public events archive at
   https://archive.analytics.mybinder.org/. Each day has a
   `events-YYYY-MM-DD.jsonl` file. We pull the last 30 days and count
   rows whose spec is `gh/qubins/qiskit-images/<branch>`.

Output schema:

    {
      "generated_at": "2026-05-16T07:33:21Z",
      "ghcr": {
        "total_tags":   13,
        "latest_publish": "2026-05-16T04:23:11Z",
        "by_tag": [
          {"tag": "2.4-xl",       "updated_at": "2026-05-16T04:23:11Z"},
          {"tag": "latest-small", "updated_at": "2026-05-16T04:22:48Z"},
          ...
        ],
        "raw_versions": [
          {"id": 12345, "tags": ["2.4-small"], "updated_at": "..."},
          ...
        ]
      },
      "mybinder": {
        "window_days": 30,
        "window_start": "2026-04-16",
        "window_end":   "2026-05-15",
        "total_launches": 87,
        "by_branch": [
          {"branch": "latest-xl", "launches": 42},
          {"branch": "2.4-xl",    "launches": 19},
          ...
        ],
        "by_day": [
          {"date": "2026-05-15", "launches": 3},
          ...
        ],
        "days_missing": []
      }
    }

The admin page renders this directly. Best-effort: if a data source
fails (rate limited, archive day missing, etc.) we still write the
partial JSON and surface the failure in a `errors` array, so the
page shows what we got.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler that does not leak GITHUB_TOKEN.

    CPython's default HTTPRedirectHandler copies a caller-set
    ``Authorization`` header onto the redirected request verbatim,
    including across a host change. The GHCR/GitHub API call here
    carries a privileged ``GITHUB_TOKEN``; if any response 302s to a
    different host we strip the credential before following, and we
    refuse to follow a downgrade to a non-HTTPS target. (The default
    stdlib handler does NOT do either of these.)
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


# Default handlers minus the stock redirect handler, plus our
# credential-stripping one. Used for every request in this script.
_OPENER = urllib.request.build_opener(_SafeRedirectHandler)

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = REPO_ROOT / "docs" / "admin" / "stats.json"

GH_ORG = "QuBins"
GH_PACKAGE = "images"  # ghcr.io/qubins/images
MYBINDER_REPO_SLUG = "qubins/qiskit-images"  # mybinder lowercases owner/repo
MYBINDER_WINDOW_DAYS = 30
MYBINDER_ARCHIVE = "https://archive.analytics.mybinder.org/events-{date}.jsonl"


def utcnow_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------- GHCR


def fetch_ghcr_versions(token: str) -> list[dict]:
    """Fetch all versions of the GHCR package, paginated."""
    out: list[dict] = []
    page = 1
    while True:
        url = (
            f"https://api.github.com/orgs/{GH_ORG}/packages/container/"
            f"{GH_PACKAGE}/versions?per_page=100&page={page}"
        )
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "qubins-admin-stats",
            },
        )
        with _OPENER.open(req, timeout=30) as resp:
            data = json.loads(resp.read())
        if not data:
            break
        out.extend(data)
        if len(data) < 100:
            break
        page += 1
        if page > 50:
            raise RuntimeError("GHCR versions paging runaway (>5000 versions?)")
    return out


def summarize_ghcr(versions: list[dict]) -> dict:
    """Collapse the version list into a per-tag publish-freshness view.

    GHCR publishes each multi-arch manifest as one "version" with the
    parent tag (e.g. `2.4-small`), plus separate versions for each
    per-arch child manifest (`2.4-small-amd64`, `…-arm64`) and the
    cosign signature (`sha256-….sig`). Only the parent tags
    correspond to user-facing image tags, so we drop the per-arch
    suffixes and signature blobs.

    For each surviving parent tag we record the most recent
    `updated_at` across versions that carry it (a tag can move
    between versions, so the latest is what counts). We deliberately
    do NOT emit `download_count`/`total_pulls`: GHCR returns these
    as 0 for container packages, and showing a meaningless 0 on the
    admin page was misleading.
    """
    raw: list[dict] = []
    by_tag: dict[str, str] = {}
    for v in versions:
        tags = v.get("metadata", {}).get("container", {}).get("tags") or []
        updated_at = v.get("updated_at")
        raw.append({
            "id": v.get("id"),
            "tags": tags,
            "updated_at": updated_at,
        })
        if not updated_at:
            continue
        for tag in tags:
            if tag.endswith("-amd64") or tag.endswith("-arm64"):
                continue
            if tag.startswith("sha256-") or tag.endswith(".sig"):
                continue
            # ISO-8601 UTC strings sort lexicographically; keep the
            # newest publish for each tag.
            prev = by_tag.get(tag)
            if prev is None or updated_at > prev:
                by_tag[tag] = updated_at

    # Newest first; ties broken by tag name for stable output.
    sorted_tags = sorted(
        ({"tag": t, "updated_at": ts} for t, ts in by_tag.items()),
        key=lambda x: (x["updated_at"], x["tag"]),
        reverse=True,
    )
    latest_publish = sorted_tags[0]["updated_at"] if sorted_tags else None
    return {
        "total_tags": len(sorted_tags),
        "latest_publish": latest_publish,
        "by_tag": sorted_tags,
        "raw_versions": raw,
    }


# ------------------------------------------------------------- mybinder


def fetch_mybinder_day(date: dt.date) -> list[dict] | None:
    """Fetch one day's launch events. Returns None if the day file is
    missing (e.g. archive lag for the most recent day)."""
    url = MYBINDER_ARCHIVE.format(date=date.isoformat())
    try:
        with _OPENER.open(url, timeout=30) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    # The archive serves either gzipped or plain JSONL depending on the
    # day; sniff the magic header.
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    out: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def summarize_mybinder(window_days: int) -> dict:
    today = dt.datetime.now(dt.timezone.utc).date()
    # The most recent day is often not yet published (the archive lags
    # by a day or two). We sweep [today-window_days .. today] and let
    # missing days report cleanly.
    days = [today - dt.timedelta(days=i) for i in range(window_days, -1, -1)]

    by_branch: Counter[str] = Counter()
    by_day: dict[str, int] = defaultdict(int)
    missing: list[str] = []
    # Archive entries have the shape `<owner>/<repo>/<ref>` directly
    # (provider is recorded in a separate field). Owner/repo case is
    # preserved by some submitters, lowercased by others, so match
    # case-insensitively. We only count rows where provider is GitHub.
    matched_spec_prefix = f"{MYBINDER_REPO_SLUG}/".lower()

    for d in days:
        rows = fetch_mybinder_day(d)
        if rows is None:
            missing.append(d.isoformat())
            continue
        day_count = 0
        for row in rows:
            if (row.get("provider") or "").lower() != "github":
                continue
            spec = (row.get("spec") or "").lower()
            if not spec.startswith(matched_spec_prefix):
                continue
            branch = spec[len(matched_spec_prefix):]
            by_branch[branch] += 1
            day_count += 1
        by_day[d.isoformat()] = day_count

    by_branch_sorted = sorted(
        ({"branch": b, "launches": n} for b, n in by_branch.items()),
        key=lambda x: (-x["launches"], x["branch"]),
    )
    by_day_sorted = [
        {"date": d, "launches": by_day[d]}
        for d in sorted(by_day.keys())
    ]
    return {
        "window_days": window_days,
        "window_start": days[0].isoformat(),
        "window_end":   days[-1].isoformat(),
        "total_launches": sum(by_branch.values()),
        "by_branch": by_branch_sorted,
        "by_day":    by_day_sorted,
        "days_missing": missing,
    }


# ------------------------------------------------------------------ main


def main() -> None:
    out: dict = {"generated_at": utcnow_iso(), "errors": []}

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        out["errors"].append("GITHUB_TOKEN not set; GHCR section skipped.")
        out["ghcr"] = None
    else:
        try:
            versions = fetch_ghcr_versions(token)
            out["ghcr"] = summarize_ghcr(versions)
            print(
                f"GHCR: {len(versions)} versions, "
                f"{out['ghcr']['total_tags']} user-facing tags, "
                f"latest publish {out['ghcr']['latest_publish']}."
            )
        except Exception as e:  # noqa: BLE001 — best-effort
            out["errors"].append(f"GHCR fetch failed: {e}")
            out["ghcr"] = None

    try:
        out["mybinder"] = summarize_mybinder(MYBINDER_WINDOW_DAYS)
        print(
            f"mybinder: {out['mybinder']['total_launches']} launches "
            f"in window {out['mybinder']['window_start']}..{out['mybinder']['window_end']}, "
            f"{len(out['mybinder']['days_missing'])} days missing."
        )
    except Exception as e:  # noqa: BLE001 — best-effort
        out["errors"].append(f"mybinder fetch failed: {e}")
        out["mybinder"] = None

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2) + "\n")
    print(f"Wrote {OUT_PATH.relative_to(REPO_ROOT)}")

    if out["errors"]:
        print("Non-fatal issues:", file=sys.stderr)
        for err in out["errors"]:
            print(f"  - {err}", file=sys.stderr)


if __name__ == "__main__":
    main()
