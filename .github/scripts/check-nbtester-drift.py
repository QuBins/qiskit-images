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

It also watches the runtime pin's real blocker: when a newer
qiskit-ibm-runtime becomes installable alongside the serverless and
catalog releases that cap it, that is reported (and counts as drift)
even if upstream has not moved yet. See runtime_unblock().

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


# --- runtime unblock watch ---------------------------------------------
#
# The runtime pin is held back by the serverless/catalog trio, not by
# upstream: qiskit-serverless caps qiskit-ibm-runtime, and
# qiskit-ibm-catalog pins serverless. In Oct 2026 the docs notebooks
# already used runtime 0.50 APIs (16 notebooks, QuBins#148) while
# serverless 0.36 still required runtime <0.50. Dependabot does not
# catch the moment that clears -- bumping serverless alone does not
# resolve while runtime stays pinned -- so this walks the chain on PyPI
# and reports when a newer runtime becomes installable alongside
# serverless and catalog.
#
# Deliberately stdlib-only (no `packaging`), like the rest of this
# script, so the workflow needs no install step. The specifier subset
# below covers what these three packages actually publish.

RUNTIME, SERVERLESS, CATALOG = "qiskit-ibm-runtime", "qiskit-serverless", "qiskit-ibm-catalog"


def parse_version(s: str) -> tuple[int, ...] | None:
    """Final releases only: '0.50.0' -> (0, 50, 0); '0.50.0rc1' -> None."""
    parts = s.strip().split(".")
    if not parts or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def _cmp(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    n = max(len(a), len(b))
    a, b = a + (0,) * (n - len(a)), b + (0,) * (n - len(b))
    return (a > b) - (a < b)


def spec_contains(spec: str, version: str) -> bool:
    """Does `version` satisfy a PEP 440 specifier like '~=0.49.0' or
    '<0.50.0,>=0.49.0'? An empty spec admits everything."""
    v = parse_version(version)
    if v is None:
        return False
    for clause in filter(None, (c.strip() for c in spec.replace(" ", "").split(","))):
        m = re.match(r"^(~=|==|!=|>=|<=|>|<)(.+)$", clause)
        if not m:
            return False
        op, target = m.groups()
        if op in ("==", "!=") and target.endswith(".*"):
            prefix = parse_version(target[:-2])
            hit = prefix is not None and v[:len(prefix)] == prefix
            if hit != (op == "=="):
                return False
            continue
        t = parse_version(target)
        if t is None:
            return False
        c = _cmp(v, t)
        if op == "~=":
            # ~=X.Y.Z means >=X.Y.Z and ==X.Y.*
            if c < 0 or len(t) < 2 or v[:len(t) - 1] != t[:-1]:
                return False
        elif not {"==": c == 0, "!=": c != 0, ">=": c >= 0,
                  "<=": c <= 0, ">": c > 0, "<": c < 0}[op]:
            return False
    return True


def requirement_spec(requires_dist: list[str] | None, name: str) -> str | None:
    """The specifier a package's metadata puts on `name`, ignoring
    extras-only entries. None if it does not depend on it at all."""
    for entry in requires_dist or []:
        req, _, marker = entry.partition(";")
        if "extra" in marker:
            continue
        m = re.match(r"^\s*([A-Za-z0-9._-]+)\s*(\[[^\]]*\])?\s*\(?([^)]*)\)?\s*$", req)
        if m and canon(m.group(1)) == canon(name):
            return m.group(3).replace(" ", "")
    return None


def latest_final(pypi_json: dict) -> str | None:
    """Newest final, non-yanked release in a PyPI project JSON."""
    best = None
    for ver, files in (pypi_json.get("releases") or {}).items():
        pv = parse_version(ver)
        if pv is None or not files or all(f.get("yanked") for f in files):
            continue
        if best is None or _cmp(pv, parse_version(best)) > 0:
            best = ver
    return best


def fetch_pypi(name: str, version: str | None = None) -> dict:
    path = f"{name}/{version}/json" if version else f"{name}/json"
    req = urllib.request.Request(f"https://pypi.org/pypi/{path}",
                                 headers={"User-Agent": "qubins-drift-check"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def runtime_unblock(ours: dict[str, str], pypi=fetch_pypi) -> dict:
    """Is a runtime newer than our pin now installable with serverless
    and catalog? Returns {"status": ..., "message": ..., "pins": {...}}.

    status: "current"   our pin already admits the latest runtime
            "unblocked" catalog -> serverless -> runtime chain admits it
            "blocked"   still capped; message says by which package
    """
    ours_rt = ours.get(RUNTIME)
    rt_proj = pypi(RUNTIME)
    latest_rt = latest_final(rt_proj)
    if not ours_rt or not latest_rt or spec_contains(ours_rt, latest_rt):
        return {"status": "current", "latest": latest_rt,
                "message": f"`{RUNTIME}{ours_rt or ''}` admits the latest release ({latest_rt})."}

    # Newest serverless that the newest catalog accepts (or the newest
    # serverless outright if we do not ship catalog).
    srv_proj = pypi(SERVERLESS)
    srv_versions = sorted((v for v in (srv_proj.get("releases") or {})
                           if parse_version(v) and srv_proj["releases"][v]),
                          key=parse_version, reverse=True)
    latest_srv = srv_versions[0] if srv_versions else None
    cat_ver, cat_srv_spec = None, ""
    if CATALOG in ours:
        cat_ver = latest_final(pypi(CATALOG))
        cat_srv_spec = requirement_spec(pypi(CATALOG, cat_ver)["info"].get("requires_dist"),
                                        SERVERLESS) or ""
    srv_ver = next((v for v in srv_versions if spec_contains(cat_srv_spec, v)), None)

    def runtime_spec_of(ver):
        return requirement_spec(pypi(SERVERLESS, ver)["info"].get("requires_dist"), RUNTIME) or ""

    if srv_ver and spec_contains(runtime_spec_of(srv_ver), latest_rt):
        rt_minor = ".".join(latest_rt.split(".")[:2]) + ".0"
        pins = {RUNTIME: f"~={rt_minor}", SERVERLESS: f"~={srv_ver}"}
        if cat_ver:
            pins[CATALOG] = f"~={cat_ver}"
        return {"status": "unblocked", "latest": latest_rt, "pins": pins,
                "message": (f"`{RUNTIME}` {latest_rt} is now installable alongside "
                            + ", ".join(f"`{k}{v}`" for k, v in pins.items() if k != RUNTIME)
                            + f". Our pin is `{ours_rt}`; bump the three together.")}

    # Still blocked: name the package doing the blocking.
    if latest_srv and spec_contains(runtime_spec_of(latest_srv), latest_rt) and cat_ver:
        why = (f"`{SERVERLESS}` {latest_srv} allows it, but the newest "
               f"`{CATALOG}` ({cat_ver}) still pins `{SERVERLESS}{cat_srv_spec}`")
    else:
        why = (f"newest `{SERVERLESS}` ({latest_srv}) requires "
               f"`{RUNTIME}{runtime_spec_of(latest_srv) if latest_srv else '?'}`")
    return {"status": "blocked", "latest": latest_rt,
            "message": f"`{RUNTIME}` {latest_rt} is out but not installable yet: {why}."}


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
    unblock = result.get("unblock")
    if unblock and unblock["status"] == "unblocked":
        lines += ["### Runtime pin can move", "", unblock["message"], "",
                  "```", *[f"{k}{v}" for k, v in unblock["pins"].items()], "```", ""]
    if result["unpinned"]:
        lines += ["<details><summary>Upstream pins these; we leave them to pip "
                  f"({len(result['unpinned'])})</summary>", "",
                  "| package | upstream |", "|---|---|"]
        lines += [f"| `{n}` | `{s}` |" for n, s in result["unpinned"]]
        lines += ["", "Policy, per `versions/_xl-base.txt`: scientific-stack "
                  "packages stay unpinned.", "</details>", ""]
    if unblock and unblock["status"] == "blocked":
        lines += ["### Runtime blocker watch", "", unblock["message"], ""]
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
    ap.add_argument("--no-unblock-check", action="store_true",
                    help="skip the PyPI runtime/serverless/catalog unblock check")
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
    if not args.no_unblock_check:
        try:
            result["unblock"] = runtime_unblock(ours)
        except Exception as e:
            # PyPI being down must not hide real nb-tester drift, nor
            # fail the job: note it and carry on.
            result["unblock"] = {"status": "error",
                                 "message": f"unblock check failed: {e}"}
            print(f"warning: {result['unblock']['message']}", file=sys.stderr)
    # An unblocked runtime is actionable, so it opens the issue like
    # drift does; "blocked" is context only and never does.
    drift = (any(result[k] for k in ("differing", "missing", "extra"))
             or result.get("unblock", {}).get("status") == "unblocked")

    if args.json:
        print(json.dumps({"minor": args.minor, "drift": drift, **result}, indent=2))
    else:
        if drift:
            print(render(args.minor, result))
        else:
            print(f"No drift: {args.minor}-xl matches upstream nb-tester "
                  f"(excluding {len(EXCEPTIONS)} documented exceptions).")
            unblock = result.get("unblock")
            if unblock:
                print(f"\nRuntime blocker watch: {unblock['message']}")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
