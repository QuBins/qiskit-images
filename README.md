# QuBins

[![Build matrix](https://github.com/QuBins/qiskit-images/actions/workflows/build-matrix.yml/badge.svg)](https://github.com/QuBins/qiskit-images/actions/workflows/build-matrix.yml)
[![Qiskit Ecosystem](https://qisk.it/e-6c640264)](https://qisk.it/e)

**Prebuilt Qiskit environments.** Click a launch badge to run in your
browser via mybinder, or `docker pull` on your laptop. Pick the
Qiskit version you need; the image is signed, scanned, and rebuilt
daily.

> *QuBins* — the place for your QuBits: prebuilt quantum compartments,
> pick one, run your Qiskit notebook on (my)binder or as a container
> ("bin").

**Landing page & catalog:** [qubins.org](https://qubins.org/)

## Why trust this

- **cosign-signed** — every published manifest, keyless OIDC, verifiable
  identity scoped to this repo (see [Verifying images](#verifying-images)).
- **Trivy-scanned** — HIGH/CRITICAL findings with available fixes
  block the build.
- **Daily rebuilt** — a cron at 04:00 UTC absorbs upstream base-image
  CVE fixes within a day, even when no commit lands.
- **Multi-arch** — `linux/amd64` and `linux/arm64` (Apple Silicon,
  Graviton). Both arches must build for a release to publish.
- **SLSA provenance** — build attestations attached to every published
  multi-arch manifest by `docker/build-push-action`.
- **No accounts, no lock-in** — images live on GHCR (free, public);
  in-browser launches use the free public mybinder.org service.

## Quick start

In your browser:

[![launch QuBins latest-xl](https://qubins.org/badges/launch-qubins-latest-xl.svg)](https://qubins.org/launch/?image=latest-xl)

On your laptop:

```sh
docker run --rm -p 8888:8888 -v "$PWD:/home/jovyan/work" ghcr.io/qubins/images:latest-small
```

Open the `http://127.0.0.1:8888/lab?token=…` URL it prints. Save your
notebooks in `work/`, which is the folder you ran the command in:
everything else is deleted when the container stops. Podman, Windows
and port options are under [Run on your laptop](#run-on-your-laptop-docker).

The bare `:latest` tag (what Docker pulls when no tag is specified) is
`latest-small`; the alias `latest` follows the current Qiskit minor
(today: `2.5`).

## Versions

Three flavors:

- **`xl`** — for tutorials, documentation notebooks, addons, and the
  scientific stack. The usual pick. (Every Qiskit minor.)
- **`small`** — lean image with just core Qiskit (`qiskit` +
  `qiskit-aer` + `qiskit-ibm-runtime`). (Every Qiskit minor.)
- **`xxl`** — everything in `xl` plus
  `qiskit-ibm-transpiler[ai-local-mode]`, which pulls PyTorch and the
  full CUDA 13 wheelset (~4 GB download). Introduced at `2.4`. **For
  now only `2.4-xxl` has the transpiler:** it doesn't support Qiskit 2.5
  yet, so `2.5-xxl` (and `latest-xxl`) has the same content as `2.5-xl`
  until it does. The transpiler is amd64-only, so every xxl's arm64 build
  also equals xl. Use `xl` unless you specifically need the local AI
  transpiler.

Currently published: 15 multi-arch (amd64 + arm64) images — 6 Qiskit
minors × {small, xl}, plus `2.4-xxl` and `2.5-xxl`, plus the
special-purpose `2.1-xl-rise`. The
latter is a bridge flavor (`2.1-xl` + the classic Notebook frontend +
classic RISE) for slideshow notebooks whose interactive ipywidgets need
classic RISE to render; launch it with `&ui=rise-classic`. It retires
once [jupyterlab-rise renders ipywidgets](https://github.com/jupyterlab-contrib/rise/issues/119).
The xl flavor is based on the [Qiskit-documentation notebook
tester](https://github.com/Qiskit/documentation/tree/main/scripts/nb-tester);
notebooks from the Qiskit documentation site should run unmodified.

**Full catalog with badges and copyable docker tags:
[qubins.org](https://qubins.org/#catalog).**

<details>
<summary>small vs xl vs xxl — full comparison</summary>

| | **small** | **xl** | **xxl** |
| - | - | - | - |
| Use for | Lean image, fast pull, core Qiskit work | Tutorials, docs notebooks, addons, scientific stack *(the usual pick)* | Everything in xl plus the local AI transpiler (currently `2.4-xxl` only) |
| Approx. download | ~0.4 GB | ~0.9 GB | ~4 GB (amd64) |
| Includes | `qiskit` <br> `qiskit-aer` <br> `qiskit-ibm-runtime` | **Qiskit ecosystem:** `qiskit[all]`, all `qiskit-addon-*`, `qiskit-experiments`, `qiskit-serverless`, `qiskit-ibm-catalog` <br> **Scientific stack:** scipy, sklearn, pyscf, plotly, sympy, ffsim, pandas <br> **Notebook tooling:** `pylatexenc`, `nbgitpuller`, `jupyterlab-open-url-parameter` | Everything in **xl**, plus `qiskit-ibm-transpiler[ai-local-mode]` (pulls PyTorch + the full CUDA 13 wheelset) |
| Load a repo (nbgitpuller) or notebook URL (`?fromURL=`) | — (bare launch only) | ✓ | ✓ (inherits from xl) |
| arm64 caveats | none | `gem-suite` omitted (no aarch64 wheels) | the AI transpiler is amd64-only, so the arm64 build equals xl |

Qiskit-ecosystem packages are pinned in the xl flavor (xxl reuses
xl's pins via a pip `-r` include and adds the transpiler pin on top);
the scientific stack is unpinned and resolved by pip.

</details>

Qiskit 1.x is no longer published. `1.0`–`1.3` were dropped first:
they carried unfixable QPY-deserialisation CVEs (RCE in `< 1.4.2`,
DoS in `< 1.3.0`) and were holding the base image back to a
python-3.12 stream with a much larger CVE backlog. `1.4` followed
once Qiskit 1.x reached end-of-life and stopped receiving fixes,
including security fixes ([#162](https://github.com/QuBins/qiskit-images/issues/162)).
Already-published `1.4-*` tags stay pullable but are no longer rebuilt
or patched; use one of the 2.x tags.

## Launch your repo or notebook on QuBins

If you maintain a tutorial, course, or sample repo that needs a
specific Qiskit version, you can give readers a one-click Binder
launch link, and optionally a Markdown badge to embed in your README.
Readers land in a verified, daily-rebuilt Qiskit container on
[mybinder.org](https://mybinder.org) — no environment setup on the
reader's machine, no Qiskit-version drift between authoring and
reading.

> **Connecting to real IBM Quantum hardware from a Binder session?**
> mybinder is a shared, public environment — don't call
> `QiskitRuntimeService.save_account()` there. Follow IBM's
> [setup for an untrusted environment](https://quantum.cloud.ibm.com/docs/en/guides/cloud-setup-untrusted):
> pass your API key inline (or use a short-lived token) and rotate the
> key after use.

**The easiest way to build one** is the
[launch generator at qubins.org](https://qubins.org/#launch): paste
the repo or notebook URL, pick an image, copy the launch link (and the
badge Markdown, if you want one).

### What the badges look like

![launch on QuBins 2.4-xl](https://qubins.org/badges/launch-on-qubins-2.4-xl.svg)
&nbsp; — notebook launch (repo or single file)

![launch QuBins 2.4-xl](https://qubins.org/badges/launch-qubins-2.4-xl.svg)
&nbsp; — bare-image launch

The right half changes per image (`2.4-xl`, `latest-small`, etc.), or
use generic [`launch-on-qubins.svg`](https://qubins.org/badges/launch-on-qubins.svg)
/ [`launch-qubins.svg`](https://qubins.org/badges/launch-qubins.svg) if
you don't want to pin a version in the badge text.

### Markdown snippets

**Open a whole repo on QuBins** (nbgitpuller clones it on launch):

```markdown
[![launch on QuBins 2.4-xl](https://qubins.org/badges/launch-on-qubins-2.4-xl.svg)](https://qubins.org/launch/?image=2.4-xl&repo=https://github.com/YOU/YOUR-REPO)
```

Optional: `&branch=BRANCH`, `&path=path/to/notebook.ipynb`. With a
`path`, `&ui=rise` opens that notebook as a RISE slideshow instead of
in JupyterLab. For slides with interactive widgets, use
`image=2.1-xl-rise` with `&ui=rise-classic` (classic Notebook + classic
RISE).

**Open a single notebook on QuBins by raw URL** (xl images only):

```markdown
[![launch on QuBins 2.4-xl](https://qubins.org/badges/launch-on-qubins-2.4-xl.svg)](https://qubins.org/launch/?image=2.4-xl&file=https://raw.githubusercontent.com/YOU/YOUR-REPO/main/notebook.ipynb)
```

**Bare launch into the image** (no preloaded notebook):

```markdown
[![launch QuBins latest-xl](https://qubins.org/badges/launch-qubins-latest-xl.svg)](https://qubins.org/launch/?image=latest-xl)
```

### When to use which

- **Whole repo** — the notebook has sibling files (data, images,
  helper modules) or you want a working copy with `git pull` updates
  available from inside the session. xl and xxl images only (small has
  no git or nbgitpuller; `/launch/` upgrades a small tag to the same
  minor's xl). Cold-start cost: image pull + repo clone.
- **Single notebook by URL** — the notebook is self-contained (only
  standard imports, no relative `open()`). Faster cold start because
  only the `.ipynb` itself is fetched. xl only (needs the
  `jupyterlab-open-url-parameter` extension).
- **Bare launch** — drop the reader into a fresh Qiskit environment
  to experiment.

### Why the `/launch/?…` redirector?

Every badge points at `https://qubins.org/launch/?…`, a thin
client-side redirector that builds the actual mybinder URL on the
fly. Two reasons:

1. The mybinder URL form has subtle double-encoding rules that are
   easy to get wrong. The redirector keeps that logic in one place.
2. If the mybinder API or one of the underlying extensions changes
   its URL shape, only the redirector needs to update — every badge
   already published in the wild keeps working.
3. It checks the image tag first. A mistyped tag, a retired Qiskit
   minor or a snapshot that doesn't exist gets a short page offering
   a working image instead of a mybinder error.

The destination URL is always visible (rendered into the page before
the JS redirect fires), so the reader sees where they're about to be
sent.

## Run on your laptop (Docker)

Start any tag, mapping Jupyter's port and mounting the current folder
as `work/`:

```sh
docker run --rm -p 8888:8888 \
  -v "$PWD:/home/jovyan/work" \
  ghcr.io/qubins/images:latest-small
```

Jupyter prints a tokenised URL once ready:

```
http://127.0.0.1:8888/lab?token=<long-hex-string>
```

Open it; the token is required on first connect.

**Save your work in `work/`.** `--rm` deletes the container when it
stops, and with it everything outside the mounted folder. Without the
`-v` line, nothing you create survives.

- **Podman:** the same command with `podman` instead of `docker`.
- **Windows:** in PowerShell use `-v "${PWD}:/home/jovyan/work"`, in
  cmd.exe `-v "%cd%:/home/jovyan/work"`.
- **Port 8888 already in use:** `-p 8899:8888`, then open port 8899.
- **Linux file permissions:** Jupyter runs as `jovyan` (UID 1000).
  Either make the host directory readable/writable by that UID or pass
  `--user $(id -u):$(id -g)`.

Add `-d` for detached, `--name qubins` to allow `docker stop qubins`.

### Pinning an image (downstream projects)

Every tag above is rebuilt nightly to pick up security fixes. Each
rebuild produces a new digest, and old digests are garbage-collected a
few days later. **Don't pin a nightly digest**: it will stop pulling.

Instead, pin a **monthly snapshot**. The first nightly of each month
also publishes `<version>-YYYYMMDD`, dated by the day that nightly ran
(for example `2.5-xl-20261101`; the first set, made when snapshots
started, is `-20261008`).
That tag is never moved and is kept for 12 months, so the tag and its
digest both stay pullable for a year:

```sh
docker pull ghcr.io/qubins/images:2.5-xl-20261101
```

Snapshots launch on Binder too, so a course can pin the exact
environment its notebooks were tested against:
`https://qubins.org/launch/?image=2.5-xl-20261101` (add `repo=`,
`path=` or `file=` as for any other tag). Each snapshot has an
immutable git tag of the same name as its Binder stub, `FROM` the
snapshot's digest. Because that commit never changes, mybinder builds
it once and reuses that build, instead of rebuilding after every
nightly. mybinder.org is a free, shared service, so we don't pre-warm
snapshots: they cost it nothing until someone launches one.

To stay current, bump the pin when a new snapshot appears. The newest
snapshot for a version is the highest `<version>-YYYYMMDD` in the
registry's tag list (`/v2/qubins/images/tags/list`), or the first
entry of that image's `snapshots` in [`versions.json`](#versionsjson-for-downstream-projects).
Each snapshot is the same image, with the same signature, as that
night's `<version>` tag, so `cosign verify` (below) works on it too.

### versions.json (for downstream projects)

[`https://qubins.org/versions.json`](https://qubins.org/versions.json)
lists every published image with what a downstream project needs to
pick, pin or check one. It is regenerated after every nightly and
every publish. RasQberry, doQumentation and our own `/launch/`
redirector read it, so it is treated as an interface:

- Fields are only ever **added**. Removing or renaming a field, or
  changing what one means, bumps `schema_version`. Check it, and
  ignore fields you don't know.
- Registry-derived fields (everything from `digest` down) are
  best-effort: if GHCR can't be read during a deploy, they are omitted
  for that image rather than guessed. Treat each as optional.
- The site fetches it from the same origin. Cross-origin `fetch()`
  works too: GitHub Pages serves it with `Access-Control-Allow-Origin: *`.

```jsonc
{
  "schema_version": 1,
  "generated_at": "2026-10-10T05:15:42Z",
  "latest_qiskit": "2.5",              // the minor latest-<flavor> points at
  "images": [                          // newest minor first, then small, xl, xl-rise, xxl
    {
      "qiskit_minor": "2.5",
      "flavor": "xl",                  // small | xl | xl-rise | xxl
      "is_latest": true,               // qiskit_minor == latest_qiskit
      "binder_tag": "2.5-xl",          // the tag, also the Binder stub branch
      "docker_tag": "ghcr.io/qubins/images:2.5-xl",
      "notes": "…",                    // optional caveat, shown as a footnote
      "ai_transpiler": false,          // xxl only: has qiskit-ibm-transpiler
      "digest": "sha256:fad5d385…",    // tonight's multi-arch index; moves nightly
      "platforms": ["linux/amd64", "linux/arm64"],
      "size_mb": 902.7,                // compressed download, amd64
      "size_mb_arm64": 843.8,          // compressed download, arm64
      "updated_at": "2026-10-09T19:26:07Z",  // build time
      "qiskit_patch": "2.5.2",         // installed qiskit
      "qiskit_ibm_runtime": "0.49.0",  // installed qiskit-ibm-runtime
      "revision": "1391056…",          // commit of this repo that built it
      "snapshots": [                   // newest first; [] before the first one
        { "tag": "2.5-xl-20261008", "date": "2026-10-08",
          "digest": "sha256:dd8f4f72…" }
      ]
    }
  ]
}
```

Pin a snapshot's `tag` or `digest`, never the top-level `digest`: that
one is replaced by the next nightly and garbage-collected a few days
later. Different flavors of one minor can ship different
`qiskit_ibm_runtime` versions (2.5-small takes the newest; 2.5-xl is
held back by `qiskit-serverless`), so check that field if your
notebooks depend on a runtime API.

## Pull your own notebook repo (nbgitpuller)

The **xl** images bundle [nbgitpuller](https://github.com/jupyterhub/nbgitpuller),
which lets a Binder URL auto-clone a notebook repo into the running
session on first launch. Share it through the redirector, which builds
the double-encoded mybinder URL for you:

```
https://qubins.org/launch/?image=latest-xl&repo=https://github.com/YOU/YOUR-REPO&path=notebook.ipynb
```

The [launch generator at qubins.org](https://qubins.org/#launch)
builds this link and the matching badge Markdown.

## How it works

`Dockerfile` is parameterised by `QISKIT_VERSION` (which is really a
`<qiskit-minor>-<flavor>` build target) and installs the dependency
list at `versions/<target>/requirements.txt`. The `build-matrix.yml`
workflow has three stages:

1. **build + scan** — for each `<target>`, build an image per
   architecture on a native runner (`ubuntu-24.04` for amd64,
   `ubuntu-24.04-arm` for arm64), load the result into the local
   docker daemon, and run Trivy against it (HIGH/CRITICAL with
   available fixes block the run). A final `RUN python -c 'import
   qiskit; from qiskit import QuantumCircuit; QuantumCircuit(2).measure_all()'`
   smoke test catches wheels that resolve cleanly but break at import.
   The base image is force-pulled so security fixes flow through
   instead of riding on the GHA layer cache. This stage runs on every
   branch.
2. **publish to GHCR** (only on `main`, including manual dispatches started there) — re-run
   the build with `push: true` so `docker/build-push-action` produces
   the SLSA provenance attestation alongside
   `ghcr.io/.../images:<target>-<arch>`. All layers are cache hits
   from step 1, so this is fast.
3. **manifest + sign** (only on `main`, including manual dispatches started there) —
   combine the per-arch tags into a multi-arch
   `ghcr.io/.../images:<target>` with `docker buildx imagetools
   create`, sign the manifest with cosign keyless OIDC, then
   force-sync a per-target stub branch containing only
   `binder/Dockerfile` (a `FROM ghcr.io/...` reference) and the
   Binder welcome notebook `START-HERE.ipynb` (from `binder-stub/`),
   which bare launches open.
   Targets matching the `LATEST_QISKIT` env var also get a
   `latest-<flavor>` tag and stub branch. The first scheduled run of
   each month also publishes a `<target>-YYYYMMDD` snapshot tag, and
   every run makes sure each snapshot in the registry has a matching
   immutable git tag as its Binder stub (and deletes the git tag once
   the snapshot is pruned).

mybinder consumes the stub branch and pulls the pre-built image
instead of rebuilding the dep tree from scratch (cold start ~30s).

### Staying current

- A daily cron reruns the full matrix on `main`, so upstream
  base-image CVE fixes flow into published images within a day even
  when no one pushes a commit.
- Dependabot watches three ecosystems: the docker base image, the GHA
  action versions, and the pip pins in the `LATEST_QISKIT` minor's
  `requirements.txt` files. Each Dependabot PR runs through the same
  Trivy + smoke gate.
- A detector workflow polls PyPI for the latest Qiskit version. When
  a new minor ships, it opens a `bot/qiskit-<X.Y>` PR with the
  small + xl + xxl scaffolding (xxl mirrors the previous minor's xxl,
  with its `-r ../<minor>-xl` include repointed), matrix entries,
  `LATEST_QISKIT` bump, and updated `dependabot.yml` directories.
  Review and merge — the xl
  flavor commonly needs a human nudge to relax addon pins that don't
  yet support the new minor.
  [`scaffold-new-qiskit.py`](.github/scripts/scaffold-new-qiskit.py)
  is the same script the workflow uses, if you need to scaffold by
  hand.

## Verifying images

Every multi-arch tag is signed via cosign keyless OIDC:

```sh
cosign verify ghcr.io/qubins/images:2.4-small \
  --certificate-identity-regexp='^https://github.com/QuBins/qiskit-images/' \
  --certificate-oidc-issuer=https://token.actions.githubusercontent.com
```

Build provenance attestations are produced automatically by
`docker/build-push-action`; see them via:

```sh
docker buildx imagetools inspect ghcr.io/qubins/images:<tag> \
  --format '{{ json .Provenance }}'
```

### Image labels

Every image says what it is, so you can check one you already have,
offline, with `docker inspect --format '{{ json .Config.Labels }}' <image>`:

| Label | Example | Meaning |
|---|---|---|
| `org.qubins.tag` | `2.5-xl` | build target (minor + flavor) |
| `org.qubins.qiskit.patch` | `2.5.2` | installed qiskit |
| `org.qubins.qiskit-ibm-runtime` | `0.49.0` | installed qiskit-ibm-runtime (empty if none) |
| `org.opencontainers.image.version` | `2.5.2` | same as `qiskit.patch` |
| `org.opencontainers.image.revision` | `1391056…` | commit of this repo that built it |
| `org.opencontainers.image.created` | `2026-10-09T19:26:07Z` | build time |
| `org.opencontainers.image.base.name` | `quay.io/jupyter/base-notebook:python-3.13` | base image |
| `org.opencontainers.image.base.digest` | `sha256:4ef9cfd5…` | base image digest |
| `org.opencontainers.image.source` | `https://github.com/QuBins/qiskit-images` | this repo |
| `org.opencontainers.image.licenses` | `Apache-2.0` | license of this repo's build recipe |

The image config's own `Created` field is not the build time: builds
pin `SOURCE_DATE_EPOCH` to the last commit that touched an image input,
so that unchanged layers keep their digests from night to night. Use
the `image.created` label instead. A snapshot carries the labels of
the nightly it was taken from; its date is in its tag.
`org.qubins.tag`, the runtime label, `revision`, `licenses` and
`base.*` exist on images built from 2026-10-10 on.

To report a vulnerability, see [SECURITY.md](SECURITY.md). To add a
version, change a flavor or work on the site, see
[CONTRIBUTING.md](CONTRIBUTING.md).

## License & acknowledgements

QuBins is an independent open-source project (Apache-2.0; see
[LICENSE](LICENSE)). It packages the open-source Qiskit distributions
for convenient consumption. The images are hosted free on GHCR;
in-browser launches use the free public
[mybinder.org](https://mybinder.org) service. No account or sign-up
is required to use anything here.

[mybinder.org](https://mybinder.org) is provided by the
[Binder project](https://jupyter.org/binder) (part of Project
Jupyter), with federation backends operated by
[GESIS](https://www.gesis.org), [2i2c](https://2i2c.org), and
partners; please be patient on cold starts and don't hammer the
service. QuBins is just curated container images they pull.

Qiskit is a trademark of IBM. QuBins is independent and not
affiliated with IBM.

---

<!-- FWQ-FAMILY:START format=list — generated from family.json in JanLahmann/Fun-with-Quantum, do not edit by hand -->
## Part of the Fun with Quantum family

This project is part of [**Fun with Quantum**](https://fun-with-quantum.org), a family of open-source quantum outreach projects: [Fun with Quantum](https://fun-with-quantum.org) · [RasQberry Two](https://rasqberry.org) · [RasQberry One](https://rasqberry.one) · [Quantego](https://quantego.org) · [Qutie](https://qutie.org) · [Qoffee-Maker](https://qoffee-maker.org) · [Entangible](https://entangible.org) · [CertiQ](https://certiq.dev) · [doQumentation](https://doqumentation.org) · [QAMPoser](https://qamposer.org).

*God does play dice. Come play, build, learn.*
<!-- FWQ-FAMILY:END -->
