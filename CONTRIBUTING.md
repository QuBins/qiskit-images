# Contributing to QuBins

Thanks for helping. Issues and pull requests are welcome, from a typo
fix to a new flavor. This page covers how the repo is laid out, how to
try a change locally, and what CI checks before anything is published.

Security problems: please follow [SECURITY.md](SECURITY.md) instead of
opening an issue.

## What lives where

| Path | What it is |
|---|---|
| `Dockerfile` | One recipe for every image, parameterised by `QISKIT_VERSION` (really a `<minor>-<flavor>` build target). |
| `versions/<minor>-<flavor>/requirements.txt` | The packages of one image. `versions/_xl-base.txt` is shared by the xl flavors. |
| `docker/` | Files the Dockerfile copies into the image. |
| `binder-stub/START-HERE.ipynb` | The welcome notebook in every Binder stub. It is not in the image. |
| `.github/workflows/build-matrix.yml` | Build, scan, publish, sign, and sync the Binder stubs. Its `ALL` list and `LATEST_QISKIT` are the source of truth for which targets exist. |
| `.github/scripts/` | Site data (`build-pages-data.py`, `build-badges.py`), the GHCR prune, the new-minor scaffolder, the upstream drift check. |
| `.github/ghcr-keep.txt` | Digests the prune must keep for a downstream pin, each with an expiry. |
| `.trivyignore` | Scanner suppressions, each with its reason. |
| `docs/` | The site, [qubins.org](https://qubins.org/). `versions.json` and `badges/` are generated at deploy time and not committed. |
| `tests/` | Stdlib `unittest` suite for the scripts and the security invariants. |

## Changing an image's packages

1. Edit `versions/<minor>-<flavor>/requirements.txt`. Explain any pin
   or cap in a comment next to it: why it is there and what would let
   us lift it. Most of the history of this repo lives in those
   comments.
2. Build that one target locally (Docker or Podman, about 5–15
   minutes for an xl):

   ```sh
   docker build --build-arg QISKIT_VERSION=2.5-xl -t qubins-test .
   ```

3. Run the same checks CI runs:

   ```sh
   # Smoke test: the canary notebook must execute.
   docker run --rm -v "$PWD/.github/canary:/tmp/canary:ro" qubins-test \
     jupyter nbconvert --to notebook --execute --output /tmp/out.ipynb \
     /tmp/canary/canary.ipynb

   # Scan: no HIGH/CRITICAL finding that has a fix.
   trivy image --severity HIGH,CRITICAL --ignore-unfixed \
     --skip-files 'opt/conda/lib/python3.13/site-packages/ray/jars/ray_dist.jar' \
     qubins-test
   ```

Only the target you changed gets rebuilt in CI, on both amd64 and
arm64. A change to the `Dockerfile` or the build workflow rebuilds all
of them.

## Adding a Qiskit minor

You usually don't need to. The `detect-new-qiskit` workflow notices a
new minor on PyPI and opens a `bot/qiskit-<X.Y>` pull request with the
small, xl and xxl targets, the matrix entries, the `LATEST_QISKIT` bump
and the Dependabot directories. The xl flavor often needs a hand
relaxing addon pins that don't support the new minor yet. To do it by
hand, run [`scaffold-new-qiskit.py`](.github/scripts/scaffold-new-qiskit.py),
the same script the workflow uses.

A new flavor (like `xl-rise`) needs its directory under `versions/`,
an entry in `ALL` in the build workflow, and the flavor name in the
regex and sort order in `build-pages-data.py`.

## Working on the site

```sh
python3 .github/scripts/build-pages-data.py   # docs/versions.json, from the live registry
python3 .github/scripts/build-badges.py       # docs/badges/
python3 -m http.server -d docs 8000           # http://localhost:8000/
```

`versions.json` is read by other projects (see
[the README](README.md#versionsjson-for-downstream-projects)). Only
ever add fields to it. Removing, renaming or redefining a field bumps
`schema_version`, and the README section must change with it.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

No network and no extra packages are needed. CI runs the same command.

## What CI does with your pull request

- Builds every affected target on both architectures, runs the smoke
  test, and scans it with Trivy. A fixable HIGH/CRITICAL finding fails
  the check.
- Nothing is published from a pull request or a branch. Only `main`
  pushes images, signs them and updates the Binder stubs.
- Pull requests are squash-merged.

## Pinning images downstream

If your project pins a QuBins image, pin a monthly snapshot tag
(`<minor>-<flavor>-YYYYMMDD`), not a nightly digest; see
[Pinning an image](README.md#pinning-an-image-downstream-projects). If
a release of yours already pins a nightly digest, open an issue and we
can add it to `.github/ghcr-keep.txt` for a limited time.
