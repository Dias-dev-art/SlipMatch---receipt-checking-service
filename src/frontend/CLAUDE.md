# Frontend — Next.js owner dashboard

Read `../CLAUDE.md` and `../API.md` first.

## Setup (first task)

```bash
npx create-next-app@latest frontend --typescript --tailwind --eslint --app --src-dir --import-alias "@/*"
cd frontend
npx shadcn@latest init
npx shadcn@latest add button card input label table badge dialog dropdown-menu tabs textarea switch sonner sheet separator skeleton avatar form select
```

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
| `/orders` (home) | Live order board: columns or tabs **Check payment** (with countdown + sound), **Awaiting payment**, **Approved**, **Cancelled**. Card shows code, total, items, order type, address, payment screenshot if any. Buttons: Approve, Not received, Restore |
| `/menu` | Table of items, add/edit dialog (name, price, description, tags, category), sold-out switch inline |
| `/inbox` | Conversations flagged `needs_owner`: read history, reply manually, "Resume AI" |
| `/test-chat` | Dev simulator: WhatsApp-like chat box calling `POST /dev/simulate`, shows current order state beside it |
| `/settings` | Business info, delivery fee, pickup/delivery toggles, payment QR upload, payment instructions, timeout, exclusion list, WhatsApp number connection |

## Structure

```
src/
├── app/
│   ├── (auth)/login, register
│   └── (dashboard)/layout.tsx, orders, menu, inbox, test-chat, settings
├── components/        # app components (OrderCard, MenuItemDialog, ...); shadcn in components/ui
├── lib/
│   ├── api.ts         # fetch wrapper: base URL, bearer token, error → toast, 401 → /login
│   ├── api-types.ts   # generated
│   ├── auth.ts        # token storage + useAuth hook
│   └── events.ts      # useOrderEvents(): EventSource on /api/v1/events
└── hooks/
```

## Rules

- Never compute prices or totals in the frontend; display what the API returns.
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
