# The self-trust sandbox, plus Hono for the resume146 fixture.
#
# The base is the pier bridge image every earlier self-trust cell ran in,
# built from d560099 (`sha256:4fadd5ab...`). A build cannot name a local
# image by ID, so it is named by its local tag; check that the tag still
# resolves to that ID before rebuilding. kbbl's
# server, which #146 changes, imports Hono; that image carries only zod and
# the TypeScript toolchain. This adds Hono, at the version kbbl ran with,
# into the same image-owned node_modules, so a workspace still never carries
# its own. Nothing else changes.
#
#   docker build -t self-trust-sandbox:hono experiments/verification_pilot/self_trust/image
FROM node:22.21.1-slim@sha256:25b3eb23a00590b7499f2a2ce939322727fcce1b15fdd69754fcd09536a3ae2c AS extras
COPY package.json package-lock.json /opt/extras/
RUN npm ci --prefix /opt/extras --ignore-scripts --no-audit --no-fund

FROM assay-pier-bridge:vp-screen-d560099
COPY --from=extras /opt/extras/node_modules/hono /opt/workflow_edit/node_modules/hono
