# Pin to a digest so a re-tagged base can't silently change the
# build under us; Dependabot proposes digest bumps weekly and they
# go through the full Trivy + smoke gate like any other change.
# Tag retained in the comment for human readability — the digest is
# the source of truth.
FROM quay.io/jupyter/base-notebook:python-3.13@sha256:9388739dcd18bb191fac32b77aeef93d5babd981a38dca76a69abd015ce3bf87

ARG QISKIT_VERSION
ENV QISKIT_VERSION=${QISKIT_VERSION}

USER root

# xl, xxl, and rise images bundle nbgitpuller (xxl and rise both pull
# the xl set via `-r ../<minor>-xl/requirements.txt`), which shells out
# to `git` at runtime to clone the user's notebook repo into the running
# session. The Jupyter base-notebook image is intentionally minimal and
# ships without git, so without this step nbgitpuller raises
# FileNotFoundError on every git-pull URL. small images don't ship
# nbgitpuller and stay git-less to preserve the "small = small" property.
# The rise flavor's name ends in `-rise` (not `-xl`), so it needs its own
# glob here — otherwise it would ship git-less and break nbgitpuller.
RUN if [[ "${QISKIT_VERSION}" == *-xl || "${QISKIT_VERSION}" == *-xxl || "${QISKIT_VERSION}" == *-rise ]]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends git \
      && apt-get clean \
      && rm -rf /var/lib/apt/lists/* ; \
    fi

# Copy the whole versions/ tree so pip can resolve the relative
# `-r ../_xl-base.txt` reference inside each xl requirements file.
# small flavors don't reference _xl-base.txt; copying it is harmless
# (a single ~250-byte text file) and the layer cache gets keyed on
# ${QISKIT_VERSION} via the next RUN anyway.
COPY versions /tmp/versions
# Three in-image security upgrades, all for findings the base digest
# 9388739d still ships and that have an available fix (so Trivy's
# --ignore-unfixed gate flags them on every flavor):
#
#  - jupyter-server: CVE-2026-44727 (CRITICAL stored XSS in
#    NbconvertFileHandler), base ships 2.19.0, fixed in 2.20.0. (An
#    earlier 2.18.0 floor for a different CVE set was dropped in #91 when
#    the base caught up — this re-introduces the floor for the new
#    finding.)
#  - msgpack: GHSA-6v7p-g79w-8964 (HIGH out-of-bounds read / crash in
#    MessagePack for Python), base conda env ships 1.1.2, fixed in 1.2.1.
#    msgpack is a base/transitive package (no requirements.txt pin); the
#    1.1.2 -> 1.2.1 minor bump satisfies the loose `msgpack<2` caps its
#    downstream consumers (ray / qiskit-serverless) use.
#  - mistune: CVE-2026-49851 (HIGH denial of service via crafted
#    Markdown), base ships 3.2.1, fixed in 3.3.0. mistune is a transitive
#    nbconvert dependency (no requirements.txt pin); nbconvert caps it at
#    `mistune<4,>=2.0.3`, so the >=3.3.0 floor stays in range.
#
# Remove each once the base image ships past the respective fix.
#
# 2026-07-12: also uninstall nbclassic to clear CVE-2026-27601 (HIGH,
# underscore.js DoS via flatten on recursive structures). The base image
# ships the legacy nbclassic classic-notebook UI, which vendors a static
# copy of underscore.js 1.13.7 at
#   nbclassic/static/components/underscore/package.json
# (fixed upstream in underscore 1.13.8). No nbclassic release carries the
# fix — 1.3.3 is the latest and still bundles 1.13.7 — so there is nothing
# to pip-upgrade to. nbclassic is a deprecated, self-contained server
# extension that nothing in these images requires (Required-by: none;
# the served UIs are JupyterLab + notebook 7, neither of which depends on
# it), so uninstalling it removes the only vulnerable copy without touching
# the notebook experience. This must be a file-level removal, not a
# .trivyignore suppression: a repo-level .trivyignore does not propagate to
# downstream image consumers (e.g. traQmania's release gate re-scans the
# published image and re-flags it), so the vulnerable file has to actually
# leave the image. `pip uninstall -y` exits 0 if the package is already
# absent, so this stays safe once a future base drops nbclassic.
# Remove this step once the base image no longer ships nbclassic (or ships
# one whose bundled underscore is >= 1.13.8).
RUN pip install --no-cache-dir --no-compile -r /tmp/versions/${QISKIT_VERSION}/requirements.txt \
 && pip install --no-cache-dir --no-compile --upgrade 'jupyter-server>=2.20.0' 'msgpack>=1.2.1' 'mistune>=3.3.0' \
 && pip uninstall -y nbclassic \
 && rm -rf /tmp/versions \
 && fix-permissions "${CONDA_DIR}" \
 && fix-permissions "/home/${NB_USER}"

# rise flavor: auto-start the RISE slideshow on launch. RISE layers its
# `autolaunch` setting (lowest -> highest priority) as: hardwired default
# (off) -> this system nbconfig -> the notebook's own rise/livereveal
# metadata. So this makes autostart the image default while any notebook
# can still override it (e.g. autolaunch:false). RISE's is_slideshow()
# guard means only notebooks that actually carry slide metadata
# auto-present, so ordinary notebooks opened here are unaffected. This
# fixes slideshow notebooks whose .ipynb omits the flag (e.g. GHZ-Game)
# without a per-notebook edit. Config filename must be `rise.json` — the
# name of the RISE nbconfig ConfigSection.
RUN if [[ "${QISKIT_VERSION}" == *-rise ]]; then \
      mkdir -p "${CONDA_DIR}/etc/jupyter/nbconfig" \
      && printf '%s\n' '{"autolaunch": true}' > "${CONDA_DIR}/etc/jupyter/nbconfig/rise.json" ; \
    fi

# rise flavor: cold-cache autolaunch watchdog (QuBins#108). RISE's
# autolaunch is a one-shot chain (main.js ~L1353) that races cold asset
# loads and misses on the *first* page load, but works on every reload.
# Ship a tiny nbextension — installed + enabled exactly the way RISE
# enables itself (share/jupyter/nbextensions/<name>/main.js +
# etc/jupyter/nbconfig/notebook.d/<name>.json) — that re-enters the
# slideshow a beat after load iff RISE itself would have and we're not
# already presenting. Full rationale in docker/rise-autolaunch/main.js.
# The JS is added to the build context for every flavor (a ~3 KB file)
# but only installed + enabled for *-rise images.
COPY docker/rise-autolaunch/main.js /tmp/rise-autolaunch-main.js
RUN if [[ "${QISKIT_VERSION}" == *-rise ]]; then \
      mkdir -p "${CONDA_DIR}/share/jupyter/nbextensions/rise-autolaunch" \
               "${CONDA_DIR}/etc/jupyter/nbconfig/notebook.d" \
      && cp /tmp/rise-autolaunch-main.js \
            "${CONDA_DIR}/share/jupyter/nbextensions/rise-autolaunch/main.js" \
      && printf '%s\n' '{"load_extensions": {"rise-autolaunch/main": true}}' \
            > "${CONDA_DIR}/etc/jupyter/nbconfig/notebook.d/rise-autolaunch.json" ; \
    fi \
 && rm -f /tmp/rise-autolaunch-main.js

# Smoke test: catches wheels that resolve cleanly but break at import
# time (e.g. a python-version bump where pip picked a wheel that
# doesn't actually load). Runs at build time so the gate is the
# build itself.
RUN python -c 'import qiskit; from qiskit import QuantumCircuit; QuantumCircuit(2).measure_all()'

USER ${NB_UID}
WORKDIR /home/${NB_USER}
