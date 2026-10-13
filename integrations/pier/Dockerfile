# Locked bridge image: dependency resolution happens only at build time,
# against the checked uv.lock. The container's entrypoint never installs,
# resolves, or mutates a pricing map — it starts the bridge directly against
# the environment this image already froze.
#
# Both base images are pinned by digest, not just by tag: "python:3.13-slim"
# and an astral-sh/uv release tag are both mutable pointers that can resolve
# to different bytes on a later build even with an unchanged uv.lock. The
# digests below are what "python:3.13-slim" / "ghcr.io/astral-sh/uv:0.10.2"
# resolved to as of 2026-09-16; re-pin deliberately, don't drop the digest.
FROM node:22.21.1-slim@sha256:25b3eb23a00590b7499f2a2ce939322727fcce1b15fdd69754fcd09536a3ae2c AS node_toolchain

# TypeScript 5.9.2 and its tarball integrity are recorded in web/bun.lock.
# Keep the same integrity here until the workflow fixture has its own lock.
RUN mkdir -p /opt/toolchain \
    && printf '%s\n' '{"name":"bridge-toolchain","version":"1.0.0","private":true,"dependencies":{"typescript":"5.9.2"}}' > /opt/toolchain/package.json \
    && printf '%s\n' '{"name":"bridge-toolchain","version":"1.0.0","lockfileVersion":3,"requires":true,"packages":{"":{"name":"bridge-toolchain","version":"1.0.0","dependencies":{"typescript":"5.9.2"}},"node_modules/typescript":{"version":"5.9.2","resolved":"https://registry.npmjs.org/typescript/-/typescript-5.9.2.tgz","integrity":"sha512-CWBzXQrc/qOkhidw1OzBTQuYRbfyxDXJMVJ1XNwUHGROVmuaeiEm3OslpZ1RV96d7SKKjZKrSJu3+t/xlw3R9A==","bin":{"tsc":"bin/tsc","tsserver":"bin/tsserver"}}}}' > /opt/toolchain/package-lock.json \
    && npm ci --prefix /opt/toolchain --ignore-scripts --no-audit --no-fund \
    && node --version \
    && node /opt/toolchain/node_modules/typescript/bin/tsc --version

FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285 AS base

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin trial \
    && apt-get update \
    && apt-get install --no-install-recommends -y git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.10.2@sha256:94a23af2d50e97b87b522d3cea24aaf8a1faedec1344c952767434f69585cbf9 /uv /usr/local/bin/uv
COPY --from=node_toolchain /usr/local/bin/node /usr/local/bin/node
COPY --from=node_toolchain /opt/toolchain/node_modules/typescript /opt/typescript
RUN ln -s /opt/typescript/bin/tsc /usr/local/bin/tsc \
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
    UV_NO_SYNC=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /submission /scratch && chown trial:trial /submission /scratch
USER trial

WORKDIR /workspace
ENTRYPOINT ["python", "-m", "assay_pier_bridge"]
