# Frontend — Waitly owner dashboard (Next.js)

The app is called **Waitly**. Read `../CLAUDE.md` and `../API.md` first, and `AGENTS.md` before touching Next.js APIs: this is Next.js 16, so check `node_modules/next/dist/docs/` instead of relying on older Next.js knowledge.

## Setup (done)

Scaffolded with `create-next-app` and `shadcn init --base radix`. Notes:

- shadcn no longer ships a `form` component; forms use `field` (`Field`, `FieldLabel`, `FieldError`…) with `react-hook-form`. `components/form-row.tsx` wires one field.
- `.npmrc` sets `legacy-peer-deps=true`: `@hookform/resolvers` pulls optional peers (`@typeschema/*`) that conflict with zod 4. Keep `@hookform/resolvers@^5`.
- `npm install` then `npm run dev`. Demo login: `demo@demo.my` / `demo1234`.

UI/UX: use shadcn/ui components as they come; no custom design system for now. Keep it clean, mobile-friendly (owners will often use a phone), and fast to scan.

## Stack

- Next.js App Router, React, TypeScript (strict)
- Tailwind + shadcn/ui, `lucide-react` icons, `sonner` toasts
- Data fetching: TanStack Query
- Forms: `react-hook-form` + `zod`
- API types: generate from FastAPI OpenAPI with `openapi-typescript` (`npm run gen:api` → `src/lib/api-types.ts`)

## Pages

| Route | Purpose |
| --- | --- |
| `/login`, `/register` | Auth (register also creates the business) |
| `/orders` (home) | **Phone:** status switcher (Check · Awaiting · Approved · Cancelled) + one card per order. **Desktop (≥1024px):** Shopify-style table with status tabs + counts (All, Check payment, Awaiting payment, Approved, Cancelled), Sort menu (Status / Newest / Oldest), one row per order (code, date, customer, type, items, total, status, timer), Approve / Not received / Restore in the row, click a row to expand items, totals, address and payment screenshot. Countdown + sound on Check payment |
| `/menu` | Table of items (cards on phone), add/edit dialog (name, price, description, tags, category), sold-out switch inline |
| `/settings` | Business info, delivery fee, pickup/delivery toggles, payment QR upload, payment instructions, timeout, exclusion list, WhatsApp number connection |

## Structure

```
src/
├── app/
│   ├── (auth)/login, register
│   └── (dashboard)/layout.tsx, orders, menu, settings
├── components/        # app components (OrderCard, MenuItemDialog, ...); shadcn in components/ui
├── lib/
│   ├── api.ts         # the backend: fetch wrapper (base URL, bearer token, 401 → /login) + SSE
│   ├── api-types.ts   # (todo) generated
│   ├── mock-api.ts    # in-memory backend stand-in, same exports as api.ts (see "Mock data")
│   ├── strings.ts     # all UI text
│   ├── format.ts      # formatMYR, times, phones
│   └── auth.ts        # token in memory + localStorage, useToken()
└── hooks/             # use-orders, use-menu, use-business, use-auth, use-server-events, use-media-query…
```

No Inbox or Test chat page: when the AI hands a chat off (`handoff_to_owner`), the owner replies from the WhatsApp Business app. Test the agent through the backend's `/dev/simulate` directly.

## Theme

- Palette: `#0d1321` ink · `#1d2d44` navy · `#3e5c76` slate · `#748cab` steel · `#f0ebd8` cream. Defined once in `src/app/globals.css` (`:root` = light, `.dark` = dark) and mapped to the shadcn tokens. Light: cream page, navy sidebar and primary. Dark: ink page, navy cards, steel primary.
- Light / Dark / System via `next-themes` (`components/providers.tsx`); the picker is in the user menu.
- Signal colors are tokens too: `status-check` (amber), `status-awaiting`, `status-approved` (green), `status-cancelled`, `danger` (red), each with a `-soft` background. Status → classes map lives in `components/orders/status.ts`.
- Use tokens (`bg-primary`, `text-muted-foreground`, `bg-status-check-soft`…), never raw Tailwind colors like `bg-amber-500`. The only exception is the white behind the payment QR (QR codes need it to scan).

## Backend connection

- Hooks in `src/hooks/use-*.ts` (TanStack Query) import `* as api from "@/lib/api"`, which calls the FastAPI backend at `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`; set it in `src/frontend/.env.local` if different). The backend must allow this origin: `FRONTEND_URL` in the repo `.env`.
- `subscribeEvents` in `lib/api.ts` is an `EventSource` on `/api/v1/events?token=…` (reconnects when the stream closes). `use-server-events.ts` handles `order.*`, `payment.check_requested` (sound + toast) and `conversation.needs_owner` (toast with **Resume AI** → `POST /api/v1/conversations/{id}/resume-ai`).
- `src/lib/types.ts` hand-writes the API shapes; replace with the generated `api-types.ts`. Money and coordinates are decimal strings from the API. Order items: `{id, menu_item_id, slug, name, unit_price, qty, note}` (name/price are snapshots).
- Test orders without WhatsApp: `POST /dev/simulate` on the backend (`/docs`), the board updates live.
- Production is a static export (`output: "export"` in `next.config.ts`, so no server features: no server actions, route handlers, rewrites or `cacheComponents`). `NEXT_PUBLIC_API_URL= npm run build` writes `out/`, which the FastAPI backend serves at `/`; the empty API URL makes every call same-origin.

## Mock data (offline design)

- `src/lib/mock-api.ts` has the same exports as `lib/api.ts`, backed by memory and seeded from `src/lib/mock-data.ts` (Kak Ani Kitchen). State resets on reload. It also emits the order events and runs the expiry timer. Point the hooks' `* as api` import at it to design without a backend.
- Queries only run when a token exists (`enabled` default in `components/providers.tsx`). The dashboard layout always renders the shell and page (loading state) on the server; it redirects to `/login` only once the browser confirms there is no token.

## Rules

- Never compute prices or totals in the frontend; display what the API returns.
- Don't render the same list twice for mobile and desktop (it duplicates ids, timers and mutation state). Use one DOM with responsive classes, or `useMediaQuery` for content that only renders after client data loads.
- Approve/Not received buttons: disable while pending, handle 409 by refetching (someone else or the timer already changed it).
- On SSE `payment.check_requested`: play a short sound, show a toast, invalidate the orders query. Reconnect EventSource on error.
- Countdown uses `expires_at` from the API.
- Money format: `RM 10.00` via `Intl.NumberFormat('en-MY', { style: 'currency', currency: 'MYR' })`.
- Store the JWT in memory + `localStorage` for the hackathon (same as the Full Stack FastAPI Template); protect dashboard routes in the layout.
- English UI text for now; keep strings in one place so Malay can be added later.

## Commands

```bash
npm run dev        # http://localhost:3000
npm run lint
npm run build
npm run gen:api    # needs backend running
```
