#!/usr/bin/env python3
"""Plan and clean up the Qiskit pre-release canary images (rc-canary.yml).

The canaries are test-only xl images with a Qiskit pre-release swapped in,
for doQumentation's notebook sweep. Two tags per build:

    X.Y.ZrcN-xl   one per pre-release (also bN for betas)
    X.Y-rc-xl     moving: the newest pre-release of minor X.Y

Subcommands:

  plan     Pick the pre-release to build and write GitHub step outputs:
             rc       the Qiskit version to install ('' = nothing to build)
             tags     space-separated tags for it
           With --qiskit, that version is used as is (manual dispatch).
           Otherwise: the newest pre-release on PyPI whose final release
           does not exist yet; with --fallback-newest (PR test builds),
           the newest pre-release ever if none is live.

  cleanup  Delete the GHCR package versions of stale canaries: a
           pre-release whose final (X.Y.Z) is on PyPI. Jan gave a standing
           OK for exactly this on 2026-10-27. A version is deleted only if
           EVERY tag on it is a stale canary tag, so a tag that is still
           live, or any non-canary tag, protects it. The per-arch manifests
           it leaves untagged are removed later by prune-ghcr.yml.
           Dry run unless --apply.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request

PRE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(b|rc)(\d+)$")
SPECIFIC_TAG = re.compile(r"^(\d+\.\d+\.\d+(?:b|rc)\d+)-xl$")
MOVING_TAG = re.compile(r"^(\d+\.\d+)-rc-xl$")


def pypi_releases():
    with urllib.request.urlopen("https://pypi.org/pypi/qiskit/json", timeout=30) as r:
        data = json.load(r)
    # Only releases that still have non-yanked files count.
    return {
        v for v, files in data["releases"].items()
        if any(not f.get("yanked") for f in files)
    }


def pre_key(v):
    m = PRE.match(v)
    major, minor, patch, kind, n = m.groups()
    return (int(major), int(minor), int(patch), 0 if kind == "b" else 1, int(n))


def live_pres(releases):
    """Pre-releases whose final release has not shipped yet."""
    out = []
    for v in releases:
        m = PRE.match(v)
        if m and ".".join(m.groups()[:3]) not in releases:
            out.append(v)
    return sorted(out, key=pre_key)


def tags_for(rc):
    m = PRE.match(rc)
    return [f"{rc}-xl", f"{m.group(1)}.{m.group(2)}-rc-xl"]


def write_outputs(**kv):
    path = os.environ.get("GITHUB_OUTPUT")
    lines = "".join(f"{k}={v}\n" for k, v in kv.items())
    if path:
        with open(path, "a") as f:
            f.write(lines)
    sys.stdout.write(lines)


def cmd_plan(args):
    if args.qiskit:
        if not PRE.match(args.qiskit):
            sys.exit(f"Not a Qiskit pre-release version: {args.qiskit!r}")
        rc = args.qiskit
    else:
        releases = pypi_releases()
        live = live_pres(releases)
        print(f"Live pre-releases on PyPI: {live or 'none'}")
        rc = live[-1] if live else ""
        if not rc and args.fallback_newest:
            rc = max((v for v in releases if PRE.match(v)), key=pre_key)
            print(f"None live; test build with the newest pre-release ever: {rc}")
    write_outputs(rc=rc, tags=" ".join(tags_for(rc)) if rc else "")


def gh_api(*args):
    out = subprocess.run(["gh", "api", *args], check=True, capture_output=True, text=True).stdout
    return out


def is_stale(tag, releases):
    """A canary tag whose pre-release(s) all have a final release."""
    m = SPECIFIC_TAG.match(tag)
    if m:
        pm = PRE.match(m.group(1))
        return ".".join(pm.groups()[:3]) in releases
    m = MOVING_TAG.match(tag)
    if m:
        # The moving tag is stale once no pre-release of that minor is live.
        minor = m.group(1)
        return not any(v.startswith(minor + ".") for v in live_pres(releases))
    return False


def cmd_cleanup(args):
    releases = pypi_releases()
    base = f"/orgs/{args.owner}/packages/container/{args.package}/versions"
    pages = gh_api("--paginate", "--slurp", f"{base}?per_page=100")
    versions = [v for page in json.loads(pages) for v in page]
    doomed = []
    for v in versions:
        tags = v.get("metadata", {}).get("container", {}).get("tags", [])
        canary = [t for t in tags if SPECIFIC_TAG.match(t) or MOVING_TAG.match(t)]
        if not canary:
            continue
        if len(canary) == len(tags) and all(is_stale(t, releases) for t in tags):
            doomed.append((v["id"], tags))
        else:
            print(f"keep {v['id']}: {tags}")
    if not doomed:
        print("No stale canary versions.")
    for vid, tags in doomed:
        if args.apply:
            gh_api("-X", "DELETE", f"{base}/{vid}")
            print(f"deleted {vid}: {tags}")
        else:
            print(f"would delete {vid}: {tags} (dry run)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("plan")
    pp.add_argument("--qiskit", default="")
    pp.add_argument("--fallback-newest", action="store_true")
    pc = sub.add_parser("cleanup")
    pc.add_argument("--owner", required=True)
    pc.add_argument("--package", default="images")
    pc.add_argument("--apply", action="store_true")
    args = p.parse_args()
    {"plan": cmd_plan, "cleanup": cmd_cleanup}[args.cmd](args)


if __name__ == "__main__":
    main()
