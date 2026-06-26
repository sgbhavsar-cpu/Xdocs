# Xdocs Test Host (+ mock IdP)

A minimal demo **host application** that embeds the `<xdocs-viewer>` control and
emulates the host's identity provider, so the full **host-issued-token** flow is
exercised end to end (design §17).

> For local testing/demo only — **never** use the mock IdP in production.

## What it does

- Serves `public/index.html`, which embeds `<xdocs-viewer>` and loads the built
  bundle from `/dist/xdocs.js`.
- **Mock IdP endpoints:**
  - `GET /.well-known/jwks.json` — public signing keys; the backend is pointed at
    this URL via `JWKS_URL` and validates tokens against it.
  - `GET /auth/token?role=reader|editor|admin` — returns a short-lived demo JWT
    with the matching roles/scopes (API Spec §3).
- A **role switcher** re-issues the token so you can see ACL-gated behavior, and a
  **theme switcher** drives the control's `theme` attribute.

## Run

### Via the dev stack (recommended)
From the repo root:
```bash
docker compose up --build       # starts api, postgres, redis, minio, test-host
# build the frontend bundle so /dist/xdocs.js exists (mounted into the test host):
make fe-build
open http://localhost:8080
```

### Standalone (host only)
```bash
cd examples/test-host
npm install
# ensure ../../frontend/dist is built and available at public/dist (symlink or copy)
TEST_HOST_PORT=8080 npm start
```

## Configuration (env)

| Var | Default | Meaning |
|---|---|---|
| `TEST_HOST_PORT` | `8080` | Port to serve on |
| `MOCK_IDP_ISSUER` | `https://mock-idp.local` | `iss` claim (must match backend `JWT_ISSUER`) |
| `MOCK_IDP_AUDIENCE` | `xdocs` | `aud` claim (must match backend `JWT_AUDIENCE`) |

The backend must set `JWKS_URL` to this host's `/.well-known/jwks.json`,
`JWT_ISSUER` to `MOCK_IDP_ISSUER`, and `JWT_AUDIENCE` to `MOCK_IDP_AUDIENCE`.
