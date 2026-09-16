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
FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285 AS base

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin trial \
    && apt-get update \
    && apt-get install --no-install-recommends -y git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.10.2@sha256:94a23af2d50e97b87b522d3cea24aaf8a1faedec1344c952767434f69585cbf9 /uv /usr/local/bin/uv

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
