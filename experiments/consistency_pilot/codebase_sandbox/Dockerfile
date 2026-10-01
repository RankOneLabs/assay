# Correctness sandbox for the DRY tasks set in snapshots of our codebases
# (jig and scout), which import httpx, aiosqlite and pydantic. The harness
# runs `python -I -S`, so site-packages is never on sys.path; the packages go
# into the standard library directory instead.
#
#   docker build -t assay-codebase-sandbox experiments/consistency_pilot/codebase_sandbox
#
# The resulting image ID is pinned as CODEBASE_PYTHON_IMAGE in
# assay.investigations.correctness. Rebuilding produces a new ID.
FROM python@sha256:2be5d3cb08aa616c6e38d922bd7072975166b2de772004f79ee1bae59fe983dc
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --no-deps --require-hashes \
        --target /usr/local/lib/python3.13 -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt
