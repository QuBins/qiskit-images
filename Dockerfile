# Pin to a digest so a re-tagged base can't silently change the
# build under us; Dependabot proposes digest bumps weekly and they
# go through the full Trivy + smoke gate like any other change.
# Tag retained in the comment for human readability — the digest is
# the source of truth.
FROM quay.io/jupyter/base-notebook:python-3.13@sha256:0b358e9ec57a1562f78ec63b13895e9a72f3fe245fb29ba59f1dc6005607ff7c

ARG QISKIT_VERSION
ENV QISKIT_VERSION=${QISKIT_VERSION}

USER root

# xl and xxl images bundle nbgitpuller (xxl pulls the xl set via
# `-r ../<minor>-xl/requirements.txt`), which shells out to `git` at
# runtime to clone the user's notebook repo into the running session.
# The Jupyter base-notebook image is intentionally minimal and ships
# without git, so without this step nbgitpuller raises FileNotFoundError
# on every git-pull URL. small images don't ship nbgitpuller and stay
# git-less to preserve the "small = small" property.
RUN if [[ "${QISKIT_VERSION}" == *-xl || "${QISKIT_VERSION}" == *-xxl ]]; then \
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
# jupyter-server upgrade patches CVE-2026-35397 / -40110 / -40934 that the
# base image still ships at 2.17.0; remove once the base bumps it.
RUN pip install --no-cache-dir --no-compile -r /tmp/versions/${QISKIT_VERSION}/requirements.txt \
 && pip install --no-cache-dir --no-compile --upgrade 'jupyter-server>=2.18.0' \
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
