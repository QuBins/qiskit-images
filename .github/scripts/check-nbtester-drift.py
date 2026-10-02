#!/usr/bin/env python3
"""Report where versions/<minor>-xl/requirements.txt has drifted from
Qiskit/documentation's nb-tester requirements.

WHY
---
The xl set deliberately tracks upstream's nb-tester requirements --
that is the environment the Qiskit docs notebooks are actually tested
in, and doQumentation builds its Binder and Code Engine images from
2.5-xl, so the two drifting apart shows up as notebooks failing for
users (QuBins#148, QuBins#157).

Nothing noticed when upstream moved: the runtime pin sat two minors
behind for a week before anyone spotted it by hand.

REPORT ONLY, deliberately. The differences need judgement -- several
are intentional and permanent (see EXCEPTIONS), and an auto-PR would
either fight them every week or have to encode the judgement anyway.

Exit codes: 0 = no drift, 1 = drift found (report on stdout),
2 = could not compare (upstream unreachable, file missing).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

UPSTREAM = (
    "https://raw.githubusercontent.com/Qiskit/documentation/main/"
    "scripts/nb-tester/requirements.txt"
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Packages where a difference from upstream is intentional. Each entry
# says WHY, because an unexplained exception here silently becomes a
# place drift can hide.
EXCEPTIONS: dict[str, str] = {
    # Only cp39-cp312 wheels and no abi3 wheel in any release; the
    # image is Python 3.13, so pip falls back to an sdist that needs a
    # C++ toolchain the image does not carry. Tracked in QuBins#157.
    "mthree": "no cp313/abi3 wheel; would build from sdist and fail",
    # 0.18 imports qiskit.synthesis.linear.linear_matrix_utils, removed
    # in qiskit 2.5, and requires serverless ~=0.30 which conflicts
    # with the trio. Upstream has it commented out for the same reason.
    "qiskit-ibm-transpiler": "broken on qiskit 2.5; upstream also disables it",
    # We are deliberately a patch ahead.
    "qiskit-experiments": "we track a newer patch than upstream",
    # Installed from a git URL at a pinned commit, not a PyPI version,
    # so there is no version to compare.
    "qiskit-device-benchmarking": "git URL pin; no comparable version",
}

# Packages upstream lists that this image deliberately does not ship.
# Absent-but-expected is not drift.
NOT_SHIPPED: dict[str, str] = {}

# Packages this image ships that upstream does not. All are notebook
# authoring/distribution tooling or a security floor, documented in
# versions/_xl-base.txt and versions/<minor>-xl/requirements.txt.
# Permanent, so reporting them weekly would be pure noise.
OURS_ONLY: dict[str, str] = {
    "nbgitpuller": "notebook distribution; powers the launch links",
    "pylatexenc": "notebook rendering",
    "pandas": "notebook authoring convenience",
    "jupyterlab-rise": "the -rise flavor's slideshow UI",
    "jupyterlab-open-url-parameter": "launch-by-URL support",
    "aiohttp": "security floor (CVE-2026-69244), not an upstream pin",
}


def parse_requirements(text: str, base: Path | None = None) -> dict[str, str]:
    """name -> specifier, for the shapes these two files actually use.

    Handles `name~=1.2.3`, `name[extra]~=1.2`, trailing `; marker`,
    and `name @ git+url`.

    `-r` includes ARE followed, relative to the including file, which
    is how pip resolves them. That matters: the xl set keeps its
    shared scientific stack (scipy, scikit-learn, pyscf, plotly,
    sympy, ffsim, python-sat) in ../_xl-base.txt, and upstream pins
    those same packages directly. Not following the include reported
    every one of them as "upstream has, we do not" -- seven false
    positives that would have buried the two real ones.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r") or line.startswith("--requirement"):
            if base is None:
                continue
            target = line.split(None, 1)[1].strip() if " " in line else line[2:].strip()
            inc = (base.parent / target).resolve()
            if inc.is_file():
                out.update(parse_requirements(inc.read_text(encoding="utf-8"), inc))
            continue
        if line.startswith("-"):
            continue
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        # strip an environment marker
        line = line.split(";", 1)[0].strip()
        if "@" in line:  # PEP 508 direct reference
            name = line.split("@", 1)[0].strip()
            out[canon(name)] = "@url"
            continue
        m = re.match(r"^([A-Za-z0-9._-]+)\s*(\[[^\]]*\])?\s*(.*)$", line)
        if not m:
            continue
        out[canon(m.group(1))] = (m.group(3) or "").replace(" ", "")
    return out


def canon(name: str) -> str:
    """PEP 503 normalisation, so qiskit_addon_slc == qiskit-addon-slc."""
    return re.sub(r"[-_.]+", "-", name).lower()


def fetch_upstream(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "qubins-drift-check"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def compare(ours: dict[str, str], theirs: dict[str, str]) -> dict[str, list]:
    differing, missing, extra, unpinned = [], [], [], []
    for name, spec in sorted(theirs.items()):
        if name in EXCEPTIONS or name in NOT_SHIPPED:
            continue
        if name not in ours:
            missing.append((name, spec))
        elif not ours[name]:
            # We ship it unpinned on purpose: _xl-base.txt states that
            # scientific-stack packages stay unpinned and are resolved
            # by pip. Upstream pinning them is not drift on our side,
            # but it is worth seeing, so it gets its own bucket rather
            # than being silently dropped.
            unpinned.append((name, spec))
        elif ours[name] != spec:
            differing.append((name, ours[name], spec))
    for name, spec in sorted(ours.items()):
        if name in EXCEPTIONS or name in OURS_ONLY or name in theirs:
            continue
        extra.append((name, spec))
    return {"differing": differing, "missing": missing,
            "extra": extra, "unpinned": unpinned}


def render(minor: str, result: dict[str, list]) -> str:
    lines = [
        f"Comparing `versions/{minor}-xl/requirements.txt` against upstream",
        f"[nb-tester requirements]({UPSTREAM}).",
        "",
    ]
    if result["differing"]:
        lines += ["### Pins that differ", "", "| package | ours | upstream |", "|---|---|---|"]
        lines += [f"| `{n}` | `{o}` | `{t}` |" for n, o, t in result["differing"]]
        lines.append("")
    if result["missing"]:
        lines += ["### Upstream has, we do not", "", "| package | upstream |", "|---|---|"]
        lines += [f"| `{n}` | `{s}` |" for n, s in result["missing"]]
        lines.append("")
    if result["extra"]:
        lines += ["### We have, upstream does not", "", "| package | ours |", "|---|---|"]
        lines += [f"| `{n}` | `{s}` |" for n, s in result["extra"]]
        lines.append("")
    if result["unpinned"]:
        lines += ["<details><summary>Upstream pins these; we leave them to pip "
                  f"({len(result['unpinned'])})</summary>", "",
                  "| package | upstream |", "|---|---|"]
        lines += [f"| `{n}` | `{s}` |" for n, s in result["unpinned"]]
        lines += ["", "Policy, per `versions/_xl-base.txt`: scientific-stack "
                  "packages stay unpinned.", "</details>", ""]
    lines += [
        "### Deliberate exceptions (not compared)",
        "",
        *[f"- `{k}` — {v}" for k, v in sorted(EXCEPTIONS.items())],
        "",
        "Report only: these need judgement, so nothing is changed automatically.",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--minor", required=True, help="e.g. 2.5")
    ap.add_argument("--upstream-url", default=UPSTREAM)
    ap.add_argument("--upstream-file", help="read upstream from a local file instead")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    args = ap.parse_args()

    ours_path = REPO_ROOT / "versions" / f"{args.minor}-xl" / "requirements.txt"
    if not ours_path.is_file():
        print(f"no such file: {ours_path}", file=sys.stderr)
        return 2
    try:
        up_text = (
            Path(args.upstream_file).read_text(encoding="utf-8")
            if args.upstream_file
            else fetch_upstream(args.upstream_url)
        )
    except Exception as e:
        print(f"could not fetch upstream: {e}", file=sys.stderr)
        return 2

    ours = parse_requirements(ours_path.read_text(encoding="utf-8"), ours_path)
    theirs = parse_requirements(up_text)
    result = compare(ours, theirs)
    drift = any(result[k] for k in ("differing", "missing", "extra"))

    if args.json:
        print(json.dumps({"minor": args.minor, "drift": drift, **result}, indent=2))
    else:
        print(render(args.minor, result) if drift
              else f"No drift: {args.minor}-xl matches upstream nb-tester "
                   f"(excluding {len(EXCEPTIONS)} documented exceptions).")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
