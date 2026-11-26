# ZYRQUEN Cloudflare API Gateway

This Worker is an isolated HTTPS reverse-proxy edge layer for the existing Python
FastAPI service in `apps/api`. It does not contain, load, train, or infer with a
model. Native Runtime, datasets, checkpoints, model registry, and training
infrastructure remain outside this Worker.

## Request flow

```
Client
  -> Cloudflare Worker (this directory)
  -> configured HTTPS ZYRQUEN FastAPI origin
  -> existing API authentication and authorization
  -> ZYRQUEN Native Runtime / services
```

The Worker forwards API paths and query strings to one fixed HTTPS origin.
It preserves the caller's Authorization header, adds a bounded correlation ID,
disables caching, rejects unsupported methods, and fails closed when the origin
is absent or invalid. It does not implement authentication itself; the FastAPI
service remains the authorization authority.

## Configuration

- Wrangler config: `wrangler.jsonc`
- Entrypoint: `src/index.mjs`
- Required encrypted binding: `ZYRQUEN_API_ORIGIN`
- The origin must be a public, reachable HTTPS origin with no path, query, or
  credentials in the URL.
- Never commit origin credentials, API keys, bearer tokens, or other secrets.
- Do not use this Worker as a substitute for the Python runtime or database.

The required secret is deliberately not populated in this repository. Do not
create or upload it until a separately approved deployment plan exists. Cloudflare
secret changes and deployment commands can create a deployed Worker version.

## Cloudflare project setup

If configuring the Cloudflare dashboard before deployment:
- Repository: `maewhyxng2-prog/zyrquen-platform`
- Root directory: `infra/cloudflare/api-gateway`
- Build command: leave empty
- Deploy command: do not run until deployment is separately approved
- Preview builds: disabled
- Access protection: configure only after the intended identity/access policy
  and backend authentication model have been reviewed.

The Wrangler config sets `workers_dev = false` and declares no route, so this
change does not configure a public Worker URL or production route.

## Local test

Run from this directory:

```sh
npm test
```

Tests use Node's built-in test runner and do not install dependencies, contact
Cloudflare, contact the API origin, run inference, or start training.

## Current authorization boundary

This PR authorizes source/configuration and documentation changes only. It does
not authorize GitHub merge, Cloudflare deployment, secret creation, origin
provisioning, database migration, training, model activation, or production
traffic routing.
