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
# Two in-image security upgrades, both for findings the base digest
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
#
# Remove each once the base image ships past the respective fix.
RUN pip install --no-cache-dir --no-compile -r /tmp/versions/${QISKIT_VERSION}/requirements.txt \
 && pip install --no-cache-dir --no-compile --upgrade 'jupyter-server>=2.20.0' 'msgpack>=1.2.1' \
 && rm -rf /tmp/versions \
 && fix-permissions "${CONDA_DIR}" \
 && fix-permissions "/home/${NB_USER}"

# Smoke test: catches wheels that resolve cleanly but break at import
# time (e.g. a python-version bump where pip picked a wheel that
# doesn't actually load). Runs at build time so the gate is the
# build itself.
RUN python -c 'import qiskit; from qiskit import QuantumCircuit; QuantumCircuit(2).measure_all()'

USER ${NB_UID}
WORKDIR /home/${NB_USER}
