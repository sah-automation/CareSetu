# Edge - staging TLS boundary

`deploy/edge/` is the **edge**: the reverse-proxy boundary at the staging VM
perimeter that terminates TLS. It is deliberately separate from the in-app
**gateway** (`apps/backend/app/gateway/` - FastAPI middleware that establishes
caller identity, JWT-verify and rate-limit stubs). See the `CONTEXT.md`
glossary for the two terms:

- **edge** - the reverse proxy (Caddy) that terminates TLS at the VM perimeter.
- **gateway** - the in-app FastAPI middleware stack in front of every route.

## What this scaffold is

A single `Caddyfile` that fronts both apps on one host:

| Route           | Backend                                          | Port             |
| :-------------- | :----------------------------------------------- | :--------------- |
| `/api/*`        | FastAPI backend (`apps/backend`, uvicorn)        | `127.0.0.1:8000` |
| everything else | Next.js frontend (`apps/frontend`, `next start`) | `127.0.0.1:3000` |

TLS is terminated here (auto-provisioned via Caddy ACME, HSTS header set).
The scaffold has no business logic; it exists so the deployment boundary is
real before traffic exists (PHASE-1 T8a, #31).

## Configuring the staging VM

The site address is environment-substituted so no real hostname is committed:

```sh
STAGING_DOMAIN=staging.caresetu.in caddy run --config deploy/edge/Caddyfile
```

If `STAGING_DOMAIN` is unset, the `staging.caresetu.example` default (RFC-2606
reserved TLD) is used. That default exists so the committed file lints; a live
`caddy run` still requires a real `STAGING_DOMAIN`, or Caddy cannot obtain a
certificate for the site.

## Validating

The `caddy` binary is not required for the repo gate; a deterministic lint pass
parses the Caddyfile structurally and asserts the boundary contract:

```sh
npm run check:edge
```

It fails when the site block is missing, the site address is not the
`{$STAGING_DOMAIN:...}` environment substitution (a committed literal
hostname), either `reverse_proxy` target is wrong, the HSTS header is absent,
the braces are unbalanced, or an unsubstituted placeholder (`CHANGE_ME`,
`example.com`, ...) is left in the file. The same gate runs in `npm run lint`
(pre-commit hook) and in CI.

If the `caddy` binary is available, an additional real syntax check is:

```sh
caddy validate --config deploy/edge/Caddyfile
```
