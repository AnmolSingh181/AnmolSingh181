# Frontend

Next.js 16 App Router + TypeScript + Tailwind CSS 4. UI primitives in `src/components/ui` follow shadcn/ui conventions
(Radix + class-variance-authority + tailwind-merge).

- All API calls go to `/api/*`, which `next.config.ts` rewrites to `BACKEND_URL` (default `http://localhost:8000`).
  No API keys or secrets exist in frontend code.
- `BACKEND_URL` is read at build time; rebuild after changing it.
- Pages: `/` dashboard · `/companies` discovery · `/companies/[id]` profile · `/search` AI search · `/contacts` ·
  `/trade` · `/leads` CRM · `/sources` admin · `/quality` acceptance metrics, review sample and duplicates ·
  `/settings` · `/login` · `/privacy` (public data-subject request form).

```bash
npm install && npm run dev
```
