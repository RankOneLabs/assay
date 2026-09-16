# Locked bridge image: dependency resolution happens only at build time,
# against the checked uv.lock. The container's entrypoint never installs,
# resolves, or mutates a pricing map — it starts the bridge directly against
# the environment this image already froze.
FROM python:3.13-slim AS base

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin trial \
    && apt-get update \
    && apt-get install --no-install-recommends -y git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.10.2 /uv /usr/local/bin/uv

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
