# Locked bridge image: dependency resolution happens only at build time,
# against the checked uv.lock and workflow_edit/package-lock.json. The
# container's entrypoint never installs or resolves dependencies: it starts
# the bridge directly against the environment this image already froze.
#
# All three upstream images are pinned by digest, not just by tag: Node,
# Python, and astral-sh/uv tags are mutable pointers that can resolve to
# different bytes on a later build. Re-pin deliberately; don't drop the digests.
FROM node:22.21.1-slim@sha256:25b3eb23a00590b7499f2a2ce939322727fcce1b15fdd69754fcd09536a3ae2c AS node_toolchain

COPY workflow_edit/package.json workflow_edit/package-lock.json /opt/workflow_edit/
RUN npm ci --prefix /opt/workflow_edit --ignore-scripts --no-audit --no-fund \
    && node --version \
    && node /opt/workflow_edit/node_modules/typescript/bin/tsc --version

FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285 AS base

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin trial \
    && apt-get update \
    && apt-get install --no-install-recommends -y git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.10.2@sha256:94a23af2d50e97b87b522d3cea24aaf8a1faedec1344c952767434f69585cbf9 /uv /usr/local/bin/uv
COPY --from=node_toolchain /usr/local/bin/node /usr/local/bin/node
COPY --from=node_toolchain /opt/workflow_edit /opt/workflow_edit
RUN ln -s /opt/workflow_edit/node_modules/typescript/bin/tsc /usr/local/bin/tsc \
    && test "$(node --version)" = "v22.21.1" \
    && test "$(tsc --version)" = "Version 5.9.2"

WORKDIR /bridge
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY README.md ./
COPY src ./src
COPY config ./config
RUN uv sync --frozen --no-dev

ENV PATH="/bridge/.venv/bin:${PATH}" \
    NODE_PATH=/opt/workflow_edit/node_modules \
    UV_NO_SYNC=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /submission /scratch && chown trial:trial /submission /scratch
USER trial

WORKDIR /workspace
ENTRYPOINT ["python", "-m", "assay_pier_bridge"]
