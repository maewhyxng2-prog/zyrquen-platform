# ZYRQUEN web workspace

Next.js App Router frontend for the existing FastAPI service.

The product is under development. Native inference requires a compatible local
model artifact, which is not bundled with the repository.

## Run locally

```bash
cp .env.example .env.local
npm install
npm run dev
```

Set `ZYRQUEN_API_BASE_URL` in `.env.local` to the FastAPI origin. The browser calls a same-origin Next.js proxy, so the backend does not need a browser CORS configuration for this application.

## Routes and backend
 integration

- `/` dashboard: reads `GET /health` and `GET /v1/native-ai/health`.
- `/login`: uses `POST /auth/register` and `POST /auth/login`; access tokens are stored in an HTTP-only cookie and forwarded only by the server proxy.
- `/workspace`: posts authenticated inference requests to `POST /v1/native-ai/infer` and uses the authenticated conversation API for saved history. Inference remains unavailable without the local model artifact.
- `/training`: documents the dataset and training core modules. It does not start or monitor training jobs; privileged training API routes exist separately.
- `/system`: reads actual API/runtime health and labels unexposed database, storage, and infrastructure checks unavailable.
- `/settings`: shows server environment configuration and provides an actual local-history clearing control.

The backend proxy allowlist is intentionally limited to the routes above and does not provide arbitrary upstream access.

## Branding

The shared symbol is served from `public/zyrquen-icon.svg` in the dashboard,
login header, and browser tab. The root README previews the animated lockup.
Color and monochrome SVG variants are available in `public/`; animated assets
respect `prefers-reduced-motion`.

## Checks

```bash
npm run test
npx playwright install chromium
npm run test:e2e
npm run lint
npm run typecheck
npm run build
```
