# Security Operations Checklist

## Authentication

- [ ] JWT secret configured and not printed
- [ ] JWT minimum 32 characters for production
- [ ] Login rate limits remain enabled
- [ ] Invalid login responses remain generic
- [ ] Revoked-token behavior remains tested

## Authorization

- [ ] Backend database role remains authoritative
- [ ] Admin actions require backend admin role
- [ ] API keys validate lifecycle and expiry
- [ ] Revoked API keys fail closed
- [ ] Browser values never grant authorization

## Network

- [ ] CORS exact origins; no production wildcard
- [ ] Trusted proxies limited to exact network allowlist
- [ ] Security headers enabled
- [ ] HSTS enabled behind HTTPS in production
- [ ] Unnecessary ports remain closed

## Secrets and dependencies

- [ ] `.env` is untracked and never printed
- [ ] image layers contain no credentials
- [ ] dependencies checked by existing CI tooling
- [ ] container runs as non-root
- [ ] production DB target is separately validated
