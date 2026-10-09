# Pin to a digest so a re-tagged base can't silently change the
# build under us; Dependabot proposes digest bumps weekly and they
# go through the full Trivy + smoke gate like any other change.
# Tag retained in the comment for human readability — the digest is
# the source of truth.
FROM quay.io/jupyter/base-notebook:python-3.13@sha256:4ef9cfd552d265799bd9e959a87fb674da8cea738145ce49e7d286cb967ad1d7

ARG QISKIT_VERSION
ENV QISKIT_VERSION=${QISKIT_VERSION}

USER root

# OpenSSL security upgrade, for EVERY flavor.
#
# CVE-2026-84782 (HIGH) hits libssl3t64 / openssl /
# openssl-provider-legacy. Base digest 4ef9cfd5 ships
# 3.5.5-1ubuntu3.5; the fix is 3.5.5-1ubuntu3.6 and Ubuntu 26.04's
# archive already carries 3.5.5-1ubuntu3.7, so a targeted upgrade
# genuinely resolves it rather than suppressing it.
#
# This is an OS package, so unlike a Python finding there is no pip
# floor that could reach it, and no newer base exists -- the
# 2026-09-29 rebuild is the current one. Ungated on purpose: the CVE
# is in the base layer, so -small is affected exactly like xl.
#
# The trailing rm of logs and caches (here and in the next apt step)
# keeps the layer byte-identical when the same packages are installed:
# apt/dpkg logs, the *-old backups and ldconfig's aux-cache carry
# timestamps or inode data, so without it every rebuild produced a new
# layer digest and invalidated everything above it. See "Reproducible
# layers" in build-matrix.yml.
RUN apt-get update \
 && apt-get install -y --no-install-recommends --only-upgrade \
      libssl3t64 openssl openssl-provider-legacy \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* /var/log/apt /var/log/dpkg.log \
      /var/cache/ldconfig/aux-cache /var/lib/dpkg/*-old /var/cache/debconf/*-old

# Two apt packages for the xl/xxl/rise flavors:
#
#  - git: these images bundle nbgitpuller (xxl and rise both pull the xl
#    set via `-r ../<minor>-xl/requirements.txt`), which shells out to
#    `git` at runtime to clone the user's notebook repo into the running
#    session. The Jupyter base-notebook image is intentionally minimal
#    and ships without git, so without this nbgitpuller raises
#    FileNotFoundError on every git-pull URL.
#  - graphviz: qiskit's `plot_coupling_map`, `plot_gate_map`,
#    `dag_drawer` and `pass_manager_drawer` shell out to the graphviz
#    *binaries*; the python bindings alone are not enough. Without them
#    they raise `MissingOptionalLibraryError: The 'Graphviz' library is
#    required`, and rustworkx's own drawers raise "Graphviz could not be
#    found or run". QuBins#148 measured this against the 283 current
#    Qiskit docs notebooks run in 2.5-xl: ~16 notebooks hit it, and
#    adding the binaries fixed 6 outright (the other 10 then failed for
#    unrelated reasons). ~10 MB, and it is a pure runtime dependency of
#    code qiskit already ships.
#  - libgvplugin-neato-layout8: from Ubuntu 26.04 (graphviz 14) the
#    `graphviz` package ships only the `dot` layout engine; neato, fdp,
#    sfdp, circo, twopi and osage moved to this split-out plugin, and
#    --no-install-recommends does not pull it. Without it
#    `plot_gate_map`/`plot_coupling_map` (neato) and the addon drawers
#    (circo) fail with "There is no layout engine support for neato".
#    The base bump in #156 regressed 13 docs notebooks this way; the
#    trailing render check makes the next such split fail the build
#    instead of the notebooks. The `8` is the plugin ABI suffix and will
#    change with a future graphviz soname bump.
#
# small images don't ship nbgitpuller and stay git-less to preserve the
# "small = small" property, so they get neither. The rise flavor's name
# ends in `-rise` (not `-xl`), so it needs its own glob here — otherwise
# it would ship without both and break nbgitpuller.
RUN if [[ "${QISKIT_VERSION}" == *-xl || "${QISKIT_VERSION}" == *-xxl || "${QISKIT_VERSION}" == *-rise ]]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends git graphviz libgvplugin-neato-layout8 \
      && echo 'graph{a--b}' | neato -Tpng >/dev/null \
      && echo 'graph{a--b}' | circo -Tpng >/dev/null \
      && apt-get clean \
      && rm -rf /var/lib/apt/lists/* /var/log/apt /var/log/dpkg.log \
           /var/cache/ldconfig/aux-cache /var/lib/dpkg/*-old /var/cache/debconf/*-old \
           /var/cache/fontconfig/* /root/.cache ; \
    fi

# Copy the whole versions/ tree so pip can resolve the relative
# `-r ../_xl-base.txt` reference inside each xl requirements file.
# small flavors don't reference _xl-base.txt; copying it is harmless
# (a single ~250-byte text file) and the layer cache gets keyed on
# ${QISKIT_VERSION} via the next RUN anyway.
COPY versions /tmp/versions
# Three post-install repair floors.
#
# Base digest 4ef9cfd5 (Ubuntu 26.04.1) is clean for all of these --
# it ships msgpack 1.2.2, urllib3 2.8.0 and setuptools 84.0.0. The
# problem is that OUR OWN requirements install, which runs after it,
# drags them back down: the (since retired) 1.4-small image came out with msgpack
# 1.1.2, urllib3 2.7.0 and setuptools 70.3.0, all flagged by Trivy.
#
# That is why this step runs AFTER the requirements install rather
# than being a base-image workaround. The distinction matters: the
# seven floors this file used to carry were compensating for an old
# base and are genuinely gone now (base ships jupyter-server 2.21.1,
# mistune 3.3.4, jupyterlab 4.6.4, cryptography 50.0.1, tornado
# 6.5.10, anyio 4.15.1 -- all past their old floors). These three are
# a different thing and have to stay until the pins that pull them
# down are tracked to their source.
#
# jupyterlab is deliberately NOT floored here any more. It used to be
# pinned `>=4.5.10,<4.6` to hold the 4.5 line; the new base ships
# 4.6.4, so that cap would now downgrade the base rather than protect
# anything.
#
# The install goes through a retry wrapper. The xl/xxl wheelsets pull
# several 40-80 MB binary wheels (ray, symengine, pyarrow, torch); when
# the PyPI CDN drops one mid-body, pip aborts with
#   ProtocolError: ('Connection broken: IncompleteRead(...)')
# which pip's own --retries does NOT cover — that governs connection
# setup and retryable HTTP statuses, not a truncated response body. On
# 2026-08-15 (run 31864090452) a truncated symengine download failed the
# 2.4-xxl arm64 build; the whole day's matrix was otherwise green.
# Three attempts with linear backoff; the last one's output is the
# error the build log shows.
RUN pip_retry() { \
      local attempt; \
      for attempt in 1 2 3; do \
        if pip install --no-cache-dir --no-compile "$@"; then return 0; fi; \
        if [ "${attempt}" -lt 3 ]; then \
          echo "pip attempt ${attempt} failed; retrying in $((attempt * 10))s" >&2; \
          sleep $((attempt * 10)); \
        fi; \
      done; \
      echo "pip failed after 3 attempts" >&2; \
      return 1; \
    }; \
    pip_retry -r /tmp/versions/${QISKIT_VERSION}/requirements.txt \
 && pip_retry --upgrade 'msgpack>=1.2.1' 'urllib3>=2.8.0' 'setuptools>=78.1.1' \
 && rm -rf /tmp/versions \
 && fix-permissions "${CONDA_DIR}" \
 && fix-permissions "/home/${NB_USER}"

# CVE-2026-27601 (HIGH): the base image's legacy nbclassic classic-notebook
# UI vendors a static copy of underscore.js 1.13.7 (DoS via flatten on
# recursively nested input; fixed upstream in underscore 1.13.8) at
#   nbclassic/static/components/underscore/{underscore-min.js,package.json}
# No nbclassic release carries the fix — 1.3.3 is the latest and still
# bundles 1.13.7 — so there is nothing to pip-upgrade to. We CANNOT just
# uninstall nbclassic: the `rise-classic` launch mode (used by the featured
# Quantum Coin Game) serves the classic Notebook frontend + classic RISE at
# the `/nbclassic/` URL prefix, which the nbclassic server extension itself
# provides — removing it 404s that UI. So instead patch the vendored copy in
# place to the upstream-fixed 1.13.8 build (a drop-in patch release): swap
# the loaded underscore-min.js and bump the two version manifests Trivy
# reads. This ships genuinely fixed code, not a relabel. Applied wherever
# nbclassic exists (every flavor derives from the same base); the guard
# no-ops if a future base drops the package. Drop this whole step once the
# base/nbclassic ships underscore >= 1.13.8.
COPY docker/underscore-1.13.8 /tmp/underscore-1.13.8
RUN us_dir="$(python3 -B -c 'import os, nbclassic; print(os.path.join(os.path.dirname(nbclassic.__file__), "static/components/underscore"))' 2>/dev/null || true)" \
 && if [ -n "${us_dir}" ] && [ -d "${us_dir}" ]; then \
      cp /tmp/underscore-1.13.8/underscore-min.js     "${us_dir}/underscore-min.js" \
      && cp /tmp/underscore-1.13.8/package.json         "${us_dir}/package.json" \
      && cp /tmp/underscore-1.13.8/modules/package.json "${us_dir}/modules/package.json" ; \
    fi \
 && rm -rf /tmp/underscore-1.13.8

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
# build itself. -B: don't leave .pyc files in this layer (they embed
# source mtimes, so the layer would differ on every rebuild).
RUN python -B -c 'import qiskit; from qiskit import QuantumCircuit; QuantumCircuit(2).measure_all()'

USER ${NB_UID}
WORKDIR /home/${NB_USER}
