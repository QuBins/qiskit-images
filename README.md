# QuBins

[![Build matrix](https://github.com/QuBins/qiskit-images/actions/workflows/build-matrix.yml/badge.svg)](https://github.com/QuBins/qiskit-images/actions/workflows/build-matrix.yml)

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
docker run --rm -p 8888:8888 ghcr.io/qubins/images:latest-small
```

Watch stdout for `http://127.0.0.1:8888/lab?token=…`. Add
`-v "$PWD:/home/jovyan/work"` to mount your notebooks.

The bare `:latest` tag (what Docker pulls when no tag is specified) is
`latest-small`; the alias `latest` follows the current Qiskit minor
(today: `2.4`).

## Versions

Three flavors:

- **`xl`** — for tutorials, documentation notebooks, addons, and the
  scientific stack. The usual pick. (Every Qiskit minor.)
- **`small`** — lean image with just core Qiskit (`qiskit` +
  `qiskit-aer` + `qiskit-ibm-runtime`). (Every Qiskit minor.)
- **`xxl`** — everything in `xl` plus
  `qiskit-ibm-transpiler[ai-local-mode]`, which pulls PyTorch and the
  full CUDA 13 wheelset (~3.4 GB, amd64-only). Only where the AI
  transpiler is applicable — introduced at `2.4`. Use `xl` unless you
  specifically need the local AI transpiler.

Currently published: 12 multi-arch (amd64 + arm64) images — 6 Qiskit
minors × {small, xl} — plus 1 amd64-only `xxl` image, for 13 total.
The xl flavor is based on the [Qiskit-documentation notebook
tester](https://github.com/Qiskit/documentation/tree/main/scripts/nb-tester);
notebooks from the Qiskit documentation site should run unmodified.

**Full catalog with badges and copyable docker tags:
[qubins.org](https://qubins.org/#catalog).**

<details>
<summary>small vs xl vs xxl — full comparison</summary>

| | **small** | **xl** | **xxl** |
| - | - | - | - |
| Use for | Lean image, fast pull, core Qiskit work | Tutorials, docs notebooks, addons, scientific stack *(the usual pick)* | Everything in xl plus the local AI transpiler |
| Approx. size | ~250 MB | ~1 GB | ~3.4 GB |
| Includes | `qiskit` <br> `qiskit-aer` <br> `qiskit-ibm-runtime` | **Qiskit ecosystem:** `qiskit[all]`, all `qiskit-addon-*`, `qiskit-experiments`, `qiskit-serverless`, `qiskit-ibm-catalog` <br> **Scientific stack:** scipy, sklearn, pyscf, plotly, sympy, ffsim, pandas <br> **Notebook tooling:** `pylatexenc`, `nbgitpuller`, `jupyterlab-open-url-parameter` | Everything in **xl**, plus `qiskit-ibm-transpiler[ai-local-mode]` (pulls PyTorch + the full CUDA 13 wheelset) |
| Single-notebook `?fromURL=` | — | ✓ | ✓ (inherits from xl) |
| arm64 caveats | none | `gem-suite` omitted (no aarch64 wheels) | amd64-only — the AI transpiler chain has no aarch64 wheels |

Qiskit-ecosystem packages are pinned in the xl flavor (xxl reuses
xl's pins via a pip `-r` include and adds the transpiler pin on top);
the scientific stack is unpinned and resolved by pip.

</details>

Older Qiskit minors `1.0`/`1.1`/`1.2`/`1.3` are no longer published.
They carried unfixable QPY-deserialisation CVEs (RCE in `< 1.4.2`,
DoS in `< 1.3.0`) and were holding the base image back to a
python-3.12 stream with a much larger CVE backlog. Use `1.4` if you
need a 1.x environment, or one of the 2.x tags for any new work.

`1.4-xl` is a reduced set: `qiskit-addon-*`, `qiskit-serverless`,
`qiskit-ibm-catalog`, and `qiskit-ibm-transpiler` are 2.x-only and not
included.

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
the repo or notebook URL, pick an image, copy the Binder URL (and the
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

Optional: `&branch=BRANCH`, `&path=path/to/notebook.ipynb`.

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
  available from inside the session. Works with any image. Cold-start
  cost: image pull + repo clone.
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

The destination URL is always visible (rendered into the page before
the JS redirect fires), so the reader sees where they're about to be
sent.

## Run on your laptop (Docker)

Pull and start any tag, mapping Jupyter's port:

```sh
docker run --rm -p 8888:8888 ghcr.io/qubins/images:latest-small
```

Jupyter prints a tokenised URL once ready:

```
http://127.0.0.1:8888/lab?token=<long-hex-string>
```

Open it; the token is required on first connect.

To work on notebooks already on your laptop, mount your folder:

```sh
docker run --rm -p 8888:8888 \
  -v "$PWD:/home/jovyan/work" \
  ghcr.io/qubins/images:latest-small
```

Jupyter runs as `jovyan` (UID 1000); on Linux, either make the host
directory readable/writable by that UID or pass
`--user $(id -u):$(id -g)`. Add `-d` for detached, `--name qubins` to
allow `docker stop qubins`.

## Pull your own notebook repo (nbgitpuller)

The **xl** images bundle [nbgitpuller](https://github.com/jupyterhub/nbgitpuller),
which lets a Binder URL auto-clone a notebook repo into the running
session on first launch. The URL shape:

```
https://mybinder.org/v2/gh/QuBins/qiskit-images/latest-xl?urlpath=git-pull%3Frepo%3Dhttps%253A%252F%252Fgithub.com%252FYOU%252FYOUR-REPO%26urlpath%3Dlab%252Ftree%252FYOUR-REPO%252Fnotebook.ipynb
```

The least painful way to build one is the
[badge generator at qubins.org](https://qubins.org/#launch) — it
produces both the raw mybinder URL and the badge markdown.

## How it works

`Dockerfile` is parameterised by `QISKIT_VERSION` (which is really a
`<qiskit-minor>-<flavor>` build target) and installs the dependency
list at `versions/<target>/requirements.txt`. The `build-matrix.yml`
workflow has three stages:

1. **build + scan** — for each `<target>`, build an image per
   architecture on a native runner (`ubuntu-latest` for amd64,
   `ubuntu-24.04-arm` for arm64), load the result into the local
   docker daemon, and run Trivy against it (HIGH/CRITICAL with
   available fixes block the run). A final `RUN python -c 'import
   qiskit; from qiskit import QuantumCircuit; QuantumCircuit(2).measure_all()'`
   smoke test catches wheels that resolve cleanly but break at import.
   The base image is force-pulled so security fixes flow through
   instead of riding on the GHA layer cache. This stage runs on every
   branch.
2. **publish to GHCR** (only on `main` / `workflow_dispatch`) — re-run
   the build with `push: true` so `docker/build-push-action` produces
   the SLSA provenance attestation alongside
   `ghcr.io/.../images:<target>-<arch>`. All layers are cache hits
   from step 1, so this is fast.
3. **manifest + sign** (only on `main` / `workflow_dispatch`) —
   combine the per-arch tags into a multi-arch
   `ghcr.io/.../images:<target>` with `docker buildx imagetools
   create`, sign the manifest with cosign keyless OIDC, then
   force-sync a per-target stub branch containing only
   `binder/Dockerfile` (a one-line `FROM ghcr.io/...` reference).
   Targets matching the `LATEST_QISKIT` env var also get a
   `latest-<flavor>` tag and stub branch.

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
